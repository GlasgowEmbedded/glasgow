"""
The ``sensor`` taxon groups applets implementing interfaces to measurement devices.
The  differentiating characteristic for this taxon is explicit display of measured data in terms
of physical quantities.

Examples: I²C thermometer, Xilinx XADC.
Counterexamples: SPI ADC with bitstream output (use taxon ``stream``), integrated thermometer on
a e-ink display (use taxon ``display``).
"""
