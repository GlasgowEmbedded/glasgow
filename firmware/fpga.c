#include <fx2regs.h>
#include <fx2delay.h>
#include "glasgow.h"

void fpga_reset() {
  // disable FIFO bus
  IFCONFIG &= ~(_IFCFG1|_IFCFG0);

  // put FPGA in reset
  OED |=  (1<<PIND_CRESET_N);
  IOD &= ~(1<<PIND_CRESET_N);
  delay_us(1);

  // configure config pins while FPGA is in reset
  IOB |=  (1<<PINB_SCK);
  IOB &= ~(1<<PINB_SS_N);
  OEA &= ~(1<<PINA_CDONE);
  OEB |=  (1<<PINB_SCK)|(1<<PINB_SS_N)|(1<<PINB_SI);

  // release FPGA reset
  IOD |=  (1<<PIND_CRESET_N);
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
  // Use the 1st autopointer to automatically traverse the buffer
  mov  _AUTOPTRSETUP, #0b11 ; APTR1INC|APTREN
  mov  _AUTOPTRL1, _DPL0
  mov  _AUTOPTRH1, _DPH0
  mov  dptr, #_XAUTODAT1

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
  djnz _fpga_load_PARM_2, 00000$
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

  // tristate PORTB drivers as FPGA may drive them now
  OEB &= ~((1<<PINB_SCK)|(1<<PINB_SS_N)|(1<<PINB_SI));

  // enable FIFO bus with external master
  IFCONFIG |= _IFCFG1|_IFCFG0;

  return (IOA & (1 << PINA_CDONE));
}
