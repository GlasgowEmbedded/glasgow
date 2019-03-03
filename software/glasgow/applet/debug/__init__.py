"""
The ``debug`` taxon groups applets implementing interfaces to microprocessor or microcontroller
debug functions, such as manipulating memory and core state, and pausing and resuming execution.
The differentiating characteristic for this taxon is manipulation of control flow.

These applets may provide a higher level interface that can be used with an external debugger,
like gdb, or any other appropriate interface. If the debug functions may be used for manipulating
non-volatile memories, a different applet would be provided for that under the ``program`` taxon.

The names of applets in this taxon start with the processor architecture they work with, and may
be differentiated further, by architecture variant and/or debug transport.

Examples: MIPS EJTAG, AVR debugWIRE.
Counterexamples: AVR SPI (use taxon ``program``).
"""
