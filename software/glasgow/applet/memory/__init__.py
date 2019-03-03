"""
The ``memory`` taxon groups applets implementing interfaces to memory technology devices (volatile
and non-volatile) that include no functionality beyond manipulating data.

Examples: SPI flash, I²C EEPROM.
Counterexamples: SPI flash on an FPGA board that requires coordinated reset (use taxon
``program``), flash macroblock embedded in a microcontroller (use taxon ``program``).
"""
