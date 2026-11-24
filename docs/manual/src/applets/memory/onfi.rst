``memory-onfi``
===============

Read and program raw NAND Flash using the asynchronous, 8-bit ONFI-like interface. ONFI parameter pages provide the memory geometry automatically; non-ONFI devices can be used by specifying the page, spare, and block sizes explicitly.

Wiring
------

Connect I/O0 through I/O7 in order to ``--io``, and connect CLE, ALE, RE#, WE#, R/B#, and the target CE# pins to their corresponding options. Tie all R/B# pins together and provide an external pull-up. The applet also enables an internal pull-up on R/B#. Connect every CE# pin or pull unused CE# pins high to prevent bus contention. Up to four CE# signals are supported; ``--chip`` selects one, numbered from 1 in the order given to ``--ce``. All connected targets are reset during setup.

Supply the memory separately and set ``-V`` to its I/O voltage. WP# must be driven to the appropriate level externally; the applet does not control it.

Usage
-----

For example, with eight data pins on port A and control pins on port B::

    glasgow run memory-onfi -V 3.3 --io A0:7 --cle B0 --ale B1 \
        --re B2 --we B3 --r_b B4 --ce B5 identify

Using the same wiring options, read 64 pages starting at page 0::

    glasgow run memory-onfi -V 3.3 --io A0:7 --cle B0 --ale B1 \
        --re B2 --we B3 --r_b B4 --ce B5 read 0 64 data.bin spare.bin

With two output files, data and spare bytes are stored separately. With only one output file, each page's data bytes are immediately followed by its spare bytes. For non-ONFI devices, supply ``--page-size`` (data bytes per page), ``--spare-size`` (spare bytes per page), and ``--block-size`` (pages per erase block). Valid ONFI parameters take precedence over these options.

``program PAGE COUNT DATA-FILE SPARE-FILE`` programs separate data and spare files. ``erase PAGE [COUNT]`` erases entire blocks. Use block-aligned page ranges to erase a specific set of blocks.

.. warning::

    Operations access raw NAND contents. The applet does not generate or correct ECC, skip bad blocks, or enforce device-specific partial programming limits. Preserve spare data when making backups, and consult the device datasheet before programming. Programming requires erased pages and erasing destroys the contents of the whole block.

The interface uses two column address bytes and three row address bytes. Only 8-bit asynchronous devices compatible with the documented command sequence are supported; geometry detection does not adapt the address cycle count.

CLI reference
-------------

.. _applet.memory.onfi:

.. autoprogram:: glasgow.applet.memory.onfi:MemoryONFIApplet._get_argparser_for_sphinx("memory-onfi")
    :prog: glasgow run memory-onfi

API reference
-------------

.. autoclass:: glasgow.applet.memory.onfi.MemoryONFIPorts

.. autoclass:: glasgow.applet.memory.onfi.ONFIInterface
