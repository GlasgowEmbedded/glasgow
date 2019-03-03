"""
The ``program`` taxon groups applets implementing interfaces to memory technology devices (volatile
and non-volatile) that are directly connected to programmable logic, such as a microcontroller or
a gate array.

Such memories may be included on the same die, in the same package, on the same  board, or in
the same assembly as the programmable logic; what is important is that the applet has both memory
functionality (i.e. read/write functions) and logic functionality (e.g. as simple as holding
the logic in reset while updating the memory, or as complex as encapsulating memory operations
in JTAG transactions).

Examples: flash macroblock embedded in an AVR microcontroller, SPI flash on an FPGA board that
requires coordinated reset.
Counterexamples: JTAG interface for an ARM microcontroller that may be used with an external tool
to update its flash (use taxon ``debug``).
"""
