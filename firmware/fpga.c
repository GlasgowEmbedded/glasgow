#include <fx2regs.h>
#include <fx2delay.h>
#include <fx2i2c.h>
#include "glasgow.h"

void fpga_reset() {
  // Disable FIFO bus.
  SYNCDELAY;
  IFCONFIG &= ~(_IFCFG1|_IFCFG0);

  // Put FPGA in reset.
  switch(glasgow_config.revision) {
    case 'A':
    case 'B':
      OED |=  (1<<PIND_CRESET_N_REVAB);
      IOD &= ~(1<<PIND_CRESET_N_REVAB);
      break;

    case 'C':
      OEA |=  (1<<PINA_CRESET_N_REVC);
      IOA &= ~(1<<PINA_CRESET_N_REVC);
      break;
  }
  delay_us(1);

  // Configure config pins while FPGA is in reset.
  OEA &= ~(1<<PINA_CDONE);
  OEB |=  (1<<PINB_SCK)|(1<<PINB_SS_N)|(1<<PINB_SI);
  IOB |=  (1<<PINB_SCK);
  IOB &= ~(1<<PINB_SS_N);

  // Release FPGA reset.
  switch(glasgow_config.revision) {
    case 'A':
    case 'B':
      IOD |=  (1<<PIND_CRESET_N_REVAB);
      break;

    case 'C':
      IOA |=  (1<<PINA_CRESET_N_REVC);
      break;
  }
  delay_us(1200); // 1200 us for HX8K, 800 us for others
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

void fpga_start() {
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
  IFCONFIG |= _IFCLKOE|_IFCFG0|_IFCFG1;
}

bool fpga_is_ready() {
  return (IOA & (1 << PINA_CDONE));
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
