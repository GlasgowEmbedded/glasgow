"""
The Microchip (Atmel) AVR family has 9 (nine) incompatible programming interfaces. The vendor
provides no overview, compatibility matrix, or (for most interfaces) documentation other than
descriptions in MCU datasheets, so this document has to fill in the blanks.

The table below contains the summary of all necessary information to understand and implement these
programming interfaces (with the exception of debugWIRE). The wire counts include all wires between
the programmer and the target, including ~RESET, but excluding power, ground, and xtal (if any).

  * "Low-voltage serial"; 4-wire.
    Described in AVR910 application note and e.g. ATmega8 datasheet.
    This is what is commonly called SPI programming interface.
  * "Parallel"; 16-wire; requires +12 V on ~RESET.
    Described in e.g. ATmega8 datasheet.
  * JTAG; 4-wire.
    Described in e.g. ATmega323 datasheet.
  * "High-voltage serial"; 5-wire; requires 12 V on ~RESET.
    Described in e.g. ATtiny11 datasheet.
  * debugWIRE; 1-wire.
    Completely undocumented, partially reverse-engineered.
  * TPI ("tiny programming interface"); 3-wire.
    Described in AVR918 application note and e.g. ATtiny4 datasheet.
  * PDI ("program/debug interface"); 2-wire.
    Described in AVR1612 application note and e.g. ATxmega32D4 datasheet.
    PDI command set is a non-strict superset of TPI command set. PDICLK is unified with ~RESET.
  * UPDI ("unified program/debug interface"); 1-wire.
    Described in e.g. ATtiny417 datasheet.
    UPDI command set is a non-strict subset of PDI command set. PDICLK and PDIDATA are unified
    with ~RESET.
  * aWire; 1-wire; AVR32 only.
    Described in e.g. AT32UC3L064 datasheet.
"""

from ... import *


class AVRError(GlasgowAppletError):
    pass
