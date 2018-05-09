#include <fx2regs.h>
#include <fx2delay.h>
#include "glasgow.h"

void fifo_init() {
  // Use newest chip features.
  SYNCDELAY;
  REVCTL = _ENH_PKT|_DYN_OUT;

  // Disable all FIFOs.
  SYNCDELAY;
  FIFORESET = _NAKALL;

  // Configure strobes and flags.
  SYNCDELAY;
  FIFOPINPOLAR = _PKTEND|_SLOE|_SLRD|_SLWR|_EF|_FF;
  SYNCDELAY;
  PINFLAGSAB = 0b10011000; // FLAGA = EP2 EF, FLAGB = EP4 EF
  SYNCDELAY;
  PINFLAGSCD = 0b11111110; // FLAGC = EP6 FF, FLAGD = EP8 FF
  SYNCDELAY;
  PORTACFG |= _FLAGD; // PA7 is FLAGD

  // Use 8-bit wide bus.
  SYNCDELAY;
  EP2FIFOCFG &= ~_WORDWIDE;
  SYNCDELAY;
  EP4FIFOCFG &= ~_WORDWIDE;
  SYNCDELAY;
  EP6FIFOCFG &= ~_WORDWIDE;
  SYNCDELAY;
  EP8FIFOCFG &= ~_WORDWIDE;

  // Drive 30 MHz IFCLK, sample on negative edge, use FIFO with external master
  SYNCDELAY;
  IFCONFIG = _IFCLKSRC|_IFCLKOE|_IFCLKPOL|_IFCFG1|_IFCFG0;
}

void fifo_configure(bool two_ep) {
  uint8_t ep26buf, ep48valid;
  if(two_ep) {
    ep26buf   = 0;      // quad buffered
    ep48valid = 0;      // invalid
  } else {
    ep26buf   = _BUF1;  // double buffered
    ep48valid = _VALID; // valid
  }

  // Disable all FIFOs.
  SYNCDELAY;
  FIFORESET = _NAKALL;

  // For the following code, note that for FIFORESET and OUTPKTEND to do anything,
  // the endpoints *must* be in manual mode (_AUTOIN/_AUTOOUT bits cleared).

  // Configure EP2.
  SYNCDELAY;
  EP2CFG = _VALID|_TYPE1|ep26buf; // OUT BULK 512B
  SYNCDELAY;
  EP2FIFOCFG = 0;
  SYNCDELAY;
  FIFORESET = _NAKALL|2;
  SYNCDELAY;
  OUTPKTEND = _SKIP|2;
  SYNCDELAY;
  OUTPKTEND = _SKIP|2;
  if(two_ep) {
    SYNCDELAY;
    OUTPKTEND = _SKIP|2;
    SYNCDELAY;
    OUTPKTEND = _SKIP|2;
  }
  SYNCDELAY;
  EP2FIFOCFG = _AUTOOUT;

  // Configure EP4.
  SYNCDELAY;
  EP4CFG = ep48valid|_TYPE1; // OUT BULK 512B
  SYNCDELAY;
  EP4FIFOCFG = 0;
  SYNCDELAY;
  FIFORESET = _NAKALL|4;
  SYNCDELAY;
  OUTPKTEND = _SKIP|4;
  SYNCDELAY;
  OUTPKTEND = _SKIP|4;
  SYNCDELAY;
  EP4FIFOCFG = _AUTOOUT;

  // Configure EP6.
  SYNCDELAY;
  EP6CFG = _VALID|_DIR|_TYPE1|ep26buf; // IN BULK 512B
  SYNCDELAY;
  EP6AUTOINLENH = 512 >> 8;
  SYNCDELAY;
  EP6AUTOINLENL = 0;
  SYNCDELAY;
  EP6FIFOCFG = 0;
  SYNCDELAY;
  FIFORESET = _NAKALL|6;
  SYNCDELAY;
  EP6FIFOCFG = _AUTOIN|_ZEROLENIN;

  // Configure EP8.
  SYNCDELAY;
  EP8CFG = ep48valid|_DIR|_TYPE1; // IN BULK 512B
  SYNCDELAY;
  EP8AUTOINLENH = 512 >> 8;
  SYNCDELAY;
  EP8AUTOINLENL = 0;
  SYNCDELAY;
  EP8FIFOCFG = 0;
  SYNCDELAY;
  FIFORESET = _NAKALL|8;
  SYNCDELAY;
  EP8FIFOCFG = _AUTOIN|_ZEROLENIN;

  // Enable FIFOs.
  SYNCDELAY;
  FIFORESET = 0;
}
