#include <fx2regs.h>
#include <fx2delay.h>
#include "glasgow.h"

void fifo_init() {
  // Use newest chip features.
  SYNCDELAY;
  REVCTL = _ENH_PKT|_DYN_OUT;

  // Disable all FIFOs and bus.
  // The FIFO clock must stay enabled for FIFO registers to work.
  SYNCDELAY;
  IFCONFIG = _IFCLKSRC;
  SYNCDELAY;
  FIFORESET = _NAKALL;

  // Configure strobes and flags.
  // All flags are configured as RDY; this means ~EF for OUT endpoints and ~FF for IN endpoints.
  // SLRD and SLWR *must* be configured as active low; otherwise, when the FPGA I/Os are
  // internally pulled up during reset, spurious reads and writes will happen.
  SYNCDELAY;
  FIFOPINPOLAR = 0;
  SYNCDELAY;
  PINFLAGSAB = 0b10011000; // FLAGA = EP2 ~EF, FLAGB = EP4 ~EF
  SYNCDELAY;
  PINFLAGSCD = 0b11111110; // FLAGC = EP6 ~FF, FLAGD = EP8 ~FF
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

  // Configure EP2.
  SYNCDELAY;
  EP2CFG = _VALID|_TYPE1|ep26buf; // OUT BULK 512B

  // Configure EP4.
  SYNCDELAY;
  EP4CFG = ep48valid|_TYPE1; // OUT BULK 512B

  // Configure EP6.
  SYNCDELAY;
  EP6CFG = _VALID|_DIR|_TYPE1|ep26buf; // IN BULK 512B

  // Configure EP8.
  SYNCDELAY;
  EP8CFG = ep48valid|_DIR|_TYPE1; // IN BULK 512B

  // Reset and configure endpoints.
  fifo_reset(two_ep, two_ep ? 0x1 : 0x3);

  // Enable FIFOs.
  SYNCDELAY;
  FIFORESET = 0;
}

void fifo_reset(bool two_ep, uint8_t interfaces) {
  // For the following code, note that for FIFORESET and OUTPKTEND to do anything,
  // the endpoints *must* be in manual mode (_AUTOIN/_AUTOOUT bits cleared).

  if(interfaces & (1 << 0)) {
    // Reset EP2OUT.
    SYNCDELAY;
    EP2FIFOCFG = 0;
    SYNCDELAY;
    FIFORESET |= 2;
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

    // Reset EP6IN.
    SYNCDELAY;
    EP6FIFOCFG = 0;
    SYNCDELAY;
    FIFORESET |= 6;
    SYNCDELAY;
    EP6FIFOCFG = _ZEROLENIN;
  }

  if(interfaces & (1 << 1)) {
    // Reset EP4OUT.
    SYNCDELAY;
    EP4FIFOCFG = 0;
    SYNCDELAY;
    FIFORESET |= 4;
    SYNCDELAY;
    OUTPKTEND = _SKIP|4;
    SYNCDELAY;
    OUTPKTEND = _SKIP|4;
    SYNCDELAY;
    EP4FIFOCFG = _AUTOOUT;

    // Reset EP8IN.
    SYNCDELAY;
    EP8FIFOCFG = 0;
    SYNCDELAY;
    FIFORESET |= 8;
    SYNCDELAY;
    EP8FIFOCFG = _ZEROLENIN;
  }
}
