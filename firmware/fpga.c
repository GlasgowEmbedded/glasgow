#include <fx2regs.h>
#include <fx2delay.h>
#include <fx2i2c.h>
#include "glasgow.h"

__xdata uint8_t fpga_reg_pipe_rst;

void fpga_init() {
  OED |=  (1<<PIND_LED_ICE);
  fpga_is_ready();
}

// Also sets the LED status, for code size reasons.
bool fpga_is_ready() {
  if(IO_CDONE) {
    if (!test_leds)
      IO_LED_ICE = 1;
    return true;
  } else {
    if (!test_leds)
      IO_LED_ICE = 0;
    return false;
  }
}

void fpga_reset() {
  switch(glasgow_config.revision) {
    case GLASGOW_REV_A:
    case GLASGOW_REV_B:
      // Reset the FPGA.
      OED |=  (1<<PIND_CRESET_N_REVAB);
      IO_CRESET_N_REVAB = 0;
      delay_us(1);
      IO_CRESET_N_REVAB = 1;
      break;

    case GLASGOW_REV_C0:
    case GLASGOW_REV_C1:
    case GLASGOW_REV_C2:
    case GLASGOW_REV_C3: {
      // Disable voltage output.
      // This is necessary because iCE40 FPGAs have pull-ups enabled by default (when unconfigured
      // and on unused pins), and on revC, a high logic level on the OE pin configures the respective
      // level shifter as an output.
      __xdata uint16_t millivolts = 0;
      iobuf_set_voltage(IO_BUF_ALL, &millivolts);

      // We don't have feedback from the Vio output to know when it has actually discharged.
      // The device itself has 6 µF of capacitance and a load of 1 kΩ(min), for a t_RC = 6 ms.
      // A reasonable starting point is 3×t_RC = 18 ms. However, external circuitry powered by
      // the device can and likely will add some bulk capacitance. 250 ms of delay would be safe
      // in the worst case of 5 V, 40 uF, no added load. It is also not long enough to become
      // an annoyance.
      delay_ms(250);

      // Reset the FPGA now that it's safe to do so.
      OEA |= (1<<PINA_CRESET_N_REVC);
      IO_CRESET_N_REVC = 0;
      delay_us(1);
      IO_CRESET_N_REVC = 1;
      break;
    }
  }

  // Disable FIFO bus. This must be done after resetting the FPGA, or the running applet may do
  // something weird in its dying gasp after receiving a phantom stream of zero bytes. The USB host
  // will receive some spurious data, but so it will during configuration anyway.
  SYNCDELAY;
  IFCONFIG &= ~(_IFCFG1|_IFCFG0);

  // Enable FPGA configuration interface.
  OEA &= ~(1<<PINA_CDONE);
  OEB |=  (1<<PINB_SCK)|(1<<PINB_SS_N)|(1<<PINB_SI);
  IO_SCK = 1;
  IO_SS_N = 0;

  // Wait for FPGA to initialize. This is specified as 800 us for the UP5K FPGA on revAB, and
  // 1200 us for the HX8K FPGA on revC.
  delay_us(1200);

  // Update FPGA status.
  fpga_is_ready();
}

void fpga_load(__xdata uint8_t *data, uint8_t len) {
  data;
  len;

  // 8c/bit -> 6 MHz SCLK @ 48 MHz CLKOUT
#define BIT(bit) \
  mov  c, acc+bit      /*2c*/ \
  clr  _IOB+PINB_SCK   /*2c*/ \
  mov  _IOB+PINB_SI, c /*2c*/ \
  setb _IOB+PINB_SCK   /*2c*/

__asm
  // Use the 1st autopointer to automatically traverse the buffer.
  mov  _AUTOPTRSETUP, #0b11 ; APTR1INC|APTREN
  mov  _AUTOPTRL1, _DPL0
  mov  _AUTOPTRH1, _DPH0
  mov  dptr, #_XAUTODAT1

#if defined(__SDCC_MODEL_SMALL)
  mov  r0, _fpga_load_PARM_2
#elif defined(__SDCC_MODEL_MEDIUM)
  mov  r0, #_fpga_load_PARM_2
  movx a, @r0
  mov  r0, a
#else
#error Unsupported memory model
#endif

00000$:
  movx a, @dptr
  BIT(7)
  BIT(6)
  BIT(5)
  BIT(4)
  BIT(3)
  BIT(2)
  BIT(1)
  BIT(0)
  djnz r0, 00000$
__endasm;
#undef  BIT
}

bool fpga_start() {
__asm
  mov  a, #49

00001$:
  // 8c/bit
  clr  _IOB+PINB_SCK   /*2c*/
  nop                  /*1c*/
  setb _IOB+PINB_SCK   /*2c*/
  djnz acc, 00001$     /*3c*/
__endasm;

  // Tristate PORTB drivers as FPGA may drive them now.
  OEB &= ~((1<<PINB_SCK)|(1<<PINB_SS_N)|(1<<PINB_SI));

  // Enable clock and FIFO bus.
  switch(glasgow_config.revision) {
    case GLASGOW_REV_A:
    case GLASGOW_REV_B:
      IFCONFIG |= _IFCLKOE|_IFCFG0|_IFCFG1;
      break;

    case GLASGOW_REV_C0:
    case GLASGOW_REV_C1:
    case GLASGOW_REV_C2:
    case GLASGOW_REV_C3:
      IFCONFIG |= _IFCLKOE|_3048MHZ|_IFCFG0|_IFCFG1;
      break;
  }

  // Synchronize pipe reset status.
  fpga_reg_pipe_rst = 0b1111;

  // Check FPGA status.
  return fpga_is_ready();
}

bool fpga_reg_select(uint8_t addr) {
  if(!i2c_start(I2C_ADDR_FPGA<<1))
    goto fail;
  if(!i2c_write(&addr, 1))
    goto fail;
  return true;

fail:
  i2c_stop();
  return false;
}

bool fpga_reg_read(__xdata uint8_t *value, uint8_t length) {
  if(!i2c_start((I2C_ADDR_FPGA<<1)|1))
    goto fail;
  if(!i2c_read(value, length))
    goto fail;
  return true;

fail:
  i2c_stop();
  return false;
}

bool fpga_reg_write(__xdata const uint8_t *value, uint8_t length) {
  if(!i2c_write(value, length))
    goto fail;
  if(!i2c_stop())
    return false;
  return true;

fail:
  i2c_stop();
  return false;
}

bool fpga_pipe_rst(uint8_t set, uint8_t clr) {
  if (set) {
    fpga_reg_pipe_rst |= set;
    if (!fpga_reg_select(FPGA_REG_PIPE_RST))
      return false;
    if (!fpga_reg_write(&fpga_reg_pipe_rst, 1))
      return false;
  }

  if (clr) {
    fpga_reg_pipe_rst &= ~clr;
    if (!fpga_reg_select(FPGA_REG_PIPE_RST))
      return false;
    if (!fpga_reg_write(&fpga_reg_pipe_rst, 1))
      return false;
  }

  return true;
}
