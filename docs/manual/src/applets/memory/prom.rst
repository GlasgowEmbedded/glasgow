``memory-prom``
===============

Read, verify, and rescue parallel EPROMs, EEPROMs, Flash memories, and other addressable read-only devices. Basic writes and an Atmel sector programming operation are also available; programming algorithms are device dependent.

Wiring and timing
-----------------

Connect ``--dq`` to the data bus, ordered from the least significant bit, and ``--a`` to the low address bits in the same order. Connect ``--oe``, ``--ce``, and, for writing, ``--we`` to the corresponding active-low control signals. Omitted control signals must be held at the appropriate level externally. Connect the grounds and arrange memory power separately. Select an I/O voltage compatible with the memory and any address shift registers.

For memories with more address lines than available pins, connect the high address bits through a serial-in, parallel-out shift register such as a chain of 74HC164 devices. Specify its clock and serial input with ``--a-clk`` and ``--a-si``, and the *total* address width with ``--a-bits``. High address bits are shifted most significant bit first. For registers with output latches, use ``--a-lat`` as well. Without ``--a-bits``, the address width is the number of direct address pins.

Set ``--read-cycle``, ``--write-cycle``, and ``--write-hold`` according to the memory datasheet; these values are in nanoseconds. ``--shift-freq`` is in MHz.

Reading and programming
-----------------------

For example, read a 64 Kiword, eight-bit memory with an external 16-bit address shift register::

    glasgow run memory-prom -V 5 --dq A0:7 --a-clk B0 --a-si B1 \
        --a-bits 16 --oe B2 --ce B3 read -f dump.bin

Addresses and lengths count **words**, including for buses wider than eight bits. Files store each word in ``ceil(data_width / 8)`` bytes, little endian by default; use ``--endian big`` for most significant byte first. ``read`` wraps around at the memory depth, and defaults to reading the entire memory. To compare a dump against the device, use ``verify -f dump.bin`` with the same wiring arguments.

``write`` buffers its complete command sequence before issuing write pulses, so host transfer delays do not interrupt page programming. The escaped command sequence must fit in the 1024-byte command buffer; large writes must be split. It does not poll for programming completion. ``atmel write --sector-size WORDS`` splits the input at sector boundaries and polls after each sector. It does not preserve unwritten bytes or issue an unlock sequence. Use it only with a device supporting that algorithm, and choose a power-of-two sector size from its datasheet. This applet does not provide the elevated programming voltage required by many EPROMs.

Assessing data retention
------------------------

``health check`` compares repeated reads in shuffled address order against an initial read. ``health scan`` continues until the requested number of consecutive reads finds no new unstable addresses, optionally recording them with ``-f``. These operations identify inconsistent reads; they cannot prove that stable data is correct.

``health sweep`` reduces the I/O supply voltage from the value selected with ``-V`` until its samples agree. Both ports must have the same explicit numeric starting voltage (for example, ``-V 5``). ``health popcount --sweep START:END results.json`` records the number of set bits over a voltage range. Both operations change Glasgow's A and B port voltages, so the memory supply must track that voltage for the measurement to reflect its supply dependence. Stay within the ratings of the memory and all connected logic. Display the collected population counts with::

    glasgow tool memory-prom popcount results.json

CLI reference
-------------

.. _applet.memory.prom:

.. autoprogram:: glasgow.applet.memory.prom:MemoryPROMApplet._get_argparser_for_sphinx("memory-prom")
    :prog: glasgow run memory-prom

.. _applet.memory.prom.tool:

.. autoprogram:: glasgow.applet.memory.prom:MemoryPROMAppletTool._get_argparser_for_sphinx("memory-prom")
    :prog: glasgow tool memory-prom

API reference
-------------

In REPL and script mode, ``prom_iface`` provides access to the configured memory. Timing parameters in the Python constructor use seconds and hertz.

.. autoclass:: glasgow.applet.memory.prom.MemoryPROMPorts

.. autoclass:: glasgow.applet.memory.prom.MemoryPROMInterface
