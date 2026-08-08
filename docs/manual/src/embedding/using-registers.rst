Using registers to connect to logic
-----------------------------------

Once we have gained the capability to dynamically generate digital logic for
Glasgow, the rest of the power of Glasgow lies in its easy integration with
software running on the host computer.

In addition to user logic, the Glasgow ``Assembly`` system automatically
instantiates a communications framework to glue your logic to objects that
are plumbed through to Python code.  The simplest form of communication is
through **registers**: signals that are mirrored unidirectionally (either
from logic into the host, or from the host into logic).  When you
instantiate registers into your design, you can access them through Python
``get`` and ``set`` functions, and the accessors behave just as any other
``asyncio``-compatible ``async`` functions would; as a result, you can
access them anywhere else in your program once your Glasgow code is running
on the hardware.

In our previous example, we controlled Glasgow's LEDs with a pattern
generated entirely within the Glasgow hardware's programmable logic.  To
demonstrate the connectivity between Glasgow hardware and host software,
we will augment it with a host-to-logic register that is wired into the
output buffers for the LEDs.

In this example, we also demonstrate using the ``wiring.Component``
interface to define logic.  Because the previous example kept all of its
signals internal to the generated module, it had no interface to expose --
and, as a result, you may recall that we implemented it as a raw
``Elaboratable``, rather than a ``Component``.  A Component builds on
the concept of an Elaboratable, but adds a "signature" of what signals
it exports to the outside world, using properties with specially-defined
Python types.  This example adds a property ``led_data`` that the ``wiring``
subsystem will automatically fill in as a 5-bit-wide signal; the type hint
``In(5)`` suggests that the Component that we generate expects the signal to
be externally assigned.  (For more information on this, `reference the
amaranth.lib.wiring documentation
<https://amaranth-lang.org/docs/amaranth/latest/stdlib/wiring.html#module-amaranth.lib.wiring>`_!)
You should use the Component interface for nearly all Glasgow and Amaranth
modules that you write.

This example also provides further documentation within its comments.  To
solidify your understanding further, you may wish to consider the following
exercises:

* What happens to the LEDs this time when you press Ctrl-C to exit the
  Glasgow runtime?  Why?
* Why does the "FX3" LED blink in this example, but not the previous one?
* Try using the ``add_ro_register`` API to read data back from user logic. 
  (For instance, you might add a second register that inverts the data
  that was written to user logic, and read it back to prove that data is
  correctly being written.)

`Below, we give a program <../_static/examples/using-registers.py>`_ that
implements a similar binary counter on the LEDs, but with the computation
running on the host.  You do not need any external connections other than
the Glasgow hardware itself to run this program.

.. literalinclude:: ../_static/examples/using-registers.py
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
    INFO:glasgow.hardware.device:device already has bitstream ID df1012881231733da1317da8cf077ff6
    INFO:root:assembly has started
