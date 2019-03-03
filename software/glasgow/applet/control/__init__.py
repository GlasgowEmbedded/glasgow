"""
The ``control`` taxon groups applets implementing control interfaces, that is, interfaces for
changing the volatile or non-volatile state of a device.

This taxon is an exclusion taxon, i.e. if a more specific taxon exists, it should be used. For
example, ``memory`` and ``program`` applets also change volatile or non-volatile state of a device.

Examples: PLL frequency, DAC total level, USB PD I²C interface.
Counterexamples: DAC total level plus bitstream (use taxon ``stream``), AVR SPI flashing
(use taxon ``program``).
"""
