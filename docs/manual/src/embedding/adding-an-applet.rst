Adding an applet to an Assembly
-------------------------------

The most common straightforward of an Assembly is to add `existing Glasgow
applets <../applets>`_ to it.  (Indeed, internally, the "new-style" Glasgow
``AppletV2`` subsystem is based on Assemblies.) Many Glasgow applets were
designed to be used with :ref:`the REPL <repl-script>`, and expose a
programmatic interface to be used interactively; you can also use these from
your own programs.  In this section, we will instantiate a pair of UARTs,
with the interface as described in :ref:`the UART REPL example <repl-uart>`.

.. note::

    Not all Glasgow applets have been ported to the "new-style" API yet. 
    (Applets that haven't instead derive from ``GlasgowApplet``.)  If
    you find one that hasn't yet been ported, the Glasgow project will
    gladly accept your help!

Most "new-style" applets include an ``Interface`` module that encapsulates
their digital logic, and host-side logic to act on it.  The UART is no
exception; it is implemented as
``glasgow.applet.interface.uart.UARTInterface``.  In this example, we
instantiate two ``UARTInterface``\s, and use them to talk to each other
through Glasgow's external I/O pins.  Most of the example is relatively
self-explanatory, but it is worth considering:

* Instantiating the ``Interface`` -- and, indeed, any module that adds logic
  into the Assembly -- must be done before the Assembly is started.  In our
  examples, as described above, the Assembly is started implicitly by the
  ``async with`` block, so we attach the ``UARTInterface`` to the Assembly
  before we enter that block.
* Conversely, interacting with the ``Interface`` can happen only after
  synthesis is complete and the gateware is running to Glasgow.  Many
  applets will implement configuration settings (in this example, setting
  the baud rate on the UART peripheral) as dynamic register writes; these
  qualify as interactions, for our purposes!  So we ``set_baud`` on each of
  the ``UARTInterface``\s inside of the ``async with`` block, after the
  Assembly has been started.
* In this example, we want to run the transmit and receive tasks in parallel
  (the Glasgow system has enough buffer for this trivial case, even if we do
  not, but it is educational to demonstrate how to do it!).  Many
  applications will want to operate in a "straight line" -- there is no
  inherent requirement that ``uart_b.read(...)`` must be wrapped in an
  ``asyncio.create_task``, and indeed, you could just as well do something
  like ``result = await uart_b.read(...)`` to immediately block on an
  interaction with an ``Interface``.  (This is also demonstrated in the
  ``.set_baud`` calls.)

`Below, we give a program <../_static/examples/assembly-applets.py>`_ that
instantiates two unidirectional UARTs, sets them each to 115200 baud, and
transmits some bytes from one to the other.  In order to run this program,
remember to connect a flying lead from pin A0 to pin B0!

.. literalinclude:: ../_static/examples/assembly-applets.py
   :language: python

Glasgow should respond:

.. code:: console

    DEBUG:asyncio:Using selector: EpollSelector
    DEBUG:glasgow.hardware.device:found revC3 device with serial C3-20240518T200308Z
    DEBUG:glasgow.hardware.assembly:setting port A voltage to 3.30 V
    DEBUG:glasgow.hardware.assembly:setting port B voltage to 3.30 V
    DEBUG:glasgow.hardware.assembly:assigning pin tx[0] to A0
    DEBUG:glasgow.hardware.assembly:assigning pin rx[0] to B0
    DEBUG:glasgow.hardware.assembly:pulling pin B0 high
    DEBUG:glasgow.hardware.toolchain:using toolchain 'builtin' (yosys 0.61.0.0.post1073, nextpnr-ice40 0.9.0.0.post686, icepack 0.9.0.0.post686)
    INFO:glasgow.hardware.device:device already has bitstream ID 083ca04cc3edb43de9ba63d35bec38fc
    INFO:glasgow.hardware.assembly:port A voltage set to 3.3 V
    INFO:glasgow.hardware.assembly:port B voltage set to 3.3 V
    INFO:root:assembly has started
    INFO:root:uart_a transmitted data, waiting for received data
    INFO:root:uart_b received data b'Hello, Glasgow!'
