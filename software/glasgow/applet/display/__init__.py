"""
The ``display`` taxon groups applets implementing display interfaces, that is, interfaces for
sending commands to a device that alters its transmittance and/or reflectance in response.

Although some devices may receive periodic commands that embed 2d arrays of samples, they are
still classified under the ``display`` taxon, unless that is the only possibe mode of operation,
in which case the ``video`` taxon is appropriate.

Examples: HD44780 character LCD, SPI raster LCD, SPI LCD with integrated microcontroller that can
draw geometric primitives.
Counterexamples: RGB TFT LCD (use taxon ``video``).
"""
