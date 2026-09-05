Putting your own logic into an Assembly
---------------------------------------

One of the most important parts of the Glasgow system is that it is built
off of programmable logic.  This means that even if none of the existing
Glasgow applets meet your needs, you can design digital logic to implement
protocols or analyzers that you find useful.  In this section, we will
build a simple binary counter that blinks Glasgow's LEDs.

The Glasgow system is based off of the `Amaranth hardware description
language <https://github.com/amaranth-lang/amaranth/>`_, which is a
domain-specific language embedded in Python.  This section provides a very
simple introduction to specifying extremely trivial hardware in Amaranth,
but experienced digital logic designers may find it useful to `read the
Amaranth language guide
<https://amaranth-lang.org/docs/amaranth/latest/guide.html>`_

In the previous example, the ``UARTInterface`` that was instantiated was
responsible for adding itself to the Assembly.  Internally, the
``UARTInterface`` created a Python object that `implemented the
Elaboratable abstract base class
<https://amaranth-lang.org/docs/amaranth/latest/guide.html#elaboration>`_, and then called the Assembly's
``add_submodule()`` method; in order to implement our own logic, we will
want to create our own ``Elaboratable`` object.

.. note::

    This is probably the only time you will ever directly instantiate an
    ``Elaboratable``!  In general, if you find yourself directly
    instantiating one, you are probably doing something very unusual. 
    Later, when we connect pins and registers to our logic, we'll switch to
    the more powerful ``wiring.Component`` -- itself a subclass of an
    ``Elaboratable`` -- which allows us to describe, roughly, "things that
    you can connect together", on top of the ``Elaboratable``'s abstraction
    of "things that contain logic".  But for now, since the logic we're
    about to describe keeps all of its I/Os internally, we won't quite
    concern ourselves with the ``wiring.Component`` yet.

All ``Elaboratable`` objects have a method, ``elaborate``, that instantiates
the logic inside of a module.  (Digital logic designers will recognize the
contents as being the RTL that they are used to writing!) This example
mostly documents itself within its comments, but to solidify your
understanding, you may wish to consider the following exercises:

* What happens to the LEDs when you press Ctrl-C to exit the Glasgow
  runtime, and why?  Should the ``asyncio.sleep`` loop actually be
  necessary?  Why, or why not?
* What if you wanted to make all five LEDs blink at the same time?  Normal
  Python control flow (i.e., ``if counter[23] == 0:``) will not behave as
  you might expect -- why not?  How many different ways can you come up with
  to express the behavior of making all five LEDs blink at the same time?

`Below, we give a program <../_static/examples/assembly-logic.py>`_ that
implements a binary counter on the LEDs.  You do not need any external
connections other than the Glasgow hardware itself to run this program.

.. literalinclude:: ../_static/examples/assembly-logic.py
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
    INFO:glasgow.hardware.device:device already has bitstream ID c85af25c02e4e3f0088bf92d4ce7310c
    INFO:root:assembly has started
