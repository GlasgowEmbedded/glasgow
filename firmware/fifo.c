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
  // All flags are configured as RDY; this means ~EF for OUT endpoints
  // and ~FF for for IN endpoints. The actual flag is set as ~PF to allow
  // for more flexibility in exact timings.
  // SLRD and SLWR *must* be configured as active low; otherwise, glitches
  // on these lines during reset cause spurious data in FIFOs.
  SYNCDELAY;
  FIFOPINPOLAR = 0;
  SYNCDELAY;
  PINFLAGSAB = 0b01010100; // FLAGA = EP2 ~PF, FLAGB = EP4 ~PF
  SYNCDELAY;
  PINFLAGSCD = 0b01110110; // FLAGC = EP6 ~PF, FLAGD = EP8 ~PF
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

#define OUT_THRESHOLD 1U
#define IN_THRESHOLD  509U

void fifo_configure(bool two_ep) {
  uint8_t ep26buf, ep48valid, ep26pkts;
  if(two_ep) {
    ep26buf   = 0;         // quad buffered
    ep48valid = 0;         // invalid
    ep26pkts  = 0b011000;  // 512B ×3
  } else {
    ep26buf   = _BUF1;     // double buffered
    ep48valid = _VALID;    // valid
    ep26pkts  = 0b001000;  // 512B ×1
  }

  // Disable all FIFOs.
  SYNCDELAY;
  FIFORESET = _NAKALL;

  // Configure EP2.
  SYNCDELAY;
  EP2CFG = _VALID|_TYPE1|ep26buf; // OUT BULK 512B
  SYNCDELAY;
  EP2FIFOPFH = _DECIS|(OUT_THRESHOLD >> 8);
  SYNCDELAY;
  EP2FIFOPFL = OUT_THRESHOLD & 0xff;

  // Configure EP4.
  SYNCDELAY;
  EP4CFG = ep48valid|_TYPE1; // OUT BULK 512B
  SYNCDELAY;
  EP4FIFOPFH = _DECIS|(OUT_THRESHOLD >> 8);
  SYNCDELAY;
  EP4FIFOPFL = OUT_THRESHOLD & 0xff;

  // Configure EP6.
  SYNCDELAY;
  EP6CFG = _VALID|_DIR|_TYPE1|ep26buf; // IN BULK 512B ×2/×4
  SYNCDELAY;
  EP6AUTOINLENH = 512 >> 8;
  SYNCDELAY;
  EP6AUTOINLENL = 512 & 0xff;
  SYNCDELAY;
  EP6FIFOPFH = ep26pkts|(IN_THRESHOLD >> 8);
  SYNCDELAY;
  EP6FIFOPFL = IN_THRESHOLD & 0xff;

  // Configure EP8.
  SYNCDELAY;
  EP8CFG = ep48valid|_DIR|_TYPE1; // IN BULK 512B ×2
  SYNCDELAY;
  EP8AUTOINLENH = 512 >> 8;
  SYNCDELAY;
  EP8AUTOINLENL = 512 & 0xff;
  SYNCDELAY;
  EP8FIFOPFH = 0b001000|(IN_THRESHOLD >> 8);
  SYNCDELAY;
  EP8FIFOPFL = IN_THRESHOLD & 0xff;

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
    EP6FIFOCFG = _AUTOIN|_ZEROLENIN;
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
    EP8FIFOCFG = _AUTOIN|_ZEROLENIN;
  }
}
