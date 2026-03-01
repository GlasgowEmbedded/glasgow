Embedding Glasgow
=================

For some applications, it may be either inconvenient or inappropriate to use
the Glasgow applet interface.  For instance, you may wish to build a class
of interface for Glasgow that will not ever end up in Glasgow upstream (and
therefore should not be written inside of the Glasgow repository); you may
wish to control Glasgow in another program's main loop; or you may wish to
write a quick one-off experiment without the full infrastructure of Glasgow. 

Such applications may prefer to use Glasgow's embeddable APIs, which provide
access to directly find and instantiate Glasgow hardware, to build gateware
and host-side interfaces, and to load and run the generated programs on
Glasgow hardware.  The embeddable APIs are designed to provide a similar
level of abstraction as the Glasgow applet interface (the embeddable API is
responsible for generating and loading bitstreams, and providing physical
communications with Glasgow), but control flow is owned by the host
application; Glasgow's embeddable APIs run in an ordinary Python `asyncio`
framework.

.. caution::

    Glasgow's embeddable APIs are an implementation artifact of the existing
    applet architecture, which is the only committed interface for Glasgow. 
    All applets inside the Glasgow repository will be maintained and pushed
    forward when internal APIs change -- but if you develop against
    Glasgow's embeddable APIs, they may change underneath you in future
    versions of Glasgow!

Getting started with Assemblies
-------------------------------

The core concept of the Glasgow embeddable API is the Assembly, accessible
through the ``glasgow.hardware.assembly.HardwareAssembly`` class
[#other_assemblies]_.  An Assembly represents a configuration of gateware
for a specific Glasgow, including all gateware necessary to interface with
the host software, and including all pipes and registers that the gateware
has access to.

Because each Assembly object is associated with a specific Glasgow, in order
to begin working with an Assembly, you will need to instantiate it with
reference to an attached device; you can use
``HardwareAssembly.find_device()`` to locate a device, and build an Assembly
based on it.  An Assembly has ``.start()`` and ``.stop()`` methods to
synthesize it and download it to the device, but for convenience, it also
implements the async context manager protocol to connect to the device. 
`The following skeleton of a program
<../_static/examples/assembly-skeleton.py>`_ will search for a Glasgow,
create an empty Assembly targetted to it, and then download it to the
attached Glasgow:

.. literalinclude:: ../_static/examples/assembly-skeleton.py
   :language: python

.. note::

    Most users that have `followed the recommended installation instructions
    <initial-setup>`__ will have Glasgow already installed via ``pipx``. 
    Usually, this is an important part of making Glasgow easy-to-install --
    but ``pipx`` is designed for standalone packages that are not meant to
    be imported!  Installing Glasgow outside of ``pipx`` in your own
    environment is outside of the scope of this document, but to run these
    samples, you might consider running inside of the Glasgow venv that
    ``pipx`` already set up for you.  For many users, doing so will take the
    form:

    .. code:: console

        $ ~/.local/pipx/venvs/glasgow/bin/python3 assembly-skeleton.py

Glasgow should respond:

.. code:: console

    DEBUG:asyncio:Using selector: EpollSelector
    DEBUG:glasgow.hardware.device:found revC3 device with serial C3-20240518T200308Z
    DEBUG:glasgow.hardware.toolchain:using toolchain 'builtin' (yosys 0.61.0.0.post1073, nextpnr-ice40 0.9.0.0.post686, icepack 0.9.0.0.post686)
    INFO:glasgow.hardware.device:generating bitstream ID ae08e17ee60fe32bc1165e0c59410d57
    DEBUG:glasgow.hardware.build_plan:bitstream ID ae08e17ee60fe32bc1165e0c59410d57 is not cached, executing build
    INFO:root:Glasgow is alive!

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

Putting your own logic into an Assembly
---------------------------------------

Using registers to connect to logic
-----------------------------------

Connecting to pins
------------------

Using pipes to transfer data
----------------------------

.. [#other_assemblies]

    There are other Assemblies in Glasgow; for instance, if you
    wish to develop gateware without hardware on your desk at all, you might
    consider a ``SimulationAssembly``.  All Assemblies derive from the
    ``AbstractAssembly`` base class, which is the type that you will most
    commonly find passed around in Glasgow's internals.  These types of
    Assemblies are out of scope for this document!
