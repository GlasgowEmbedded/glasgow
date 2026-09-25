Connecting to pins
------------------

Glasgow's interface between digital logic and host software is certainly
lovely, but let's face it -- if you only wanted to blink LEDs, you wouldn't
bother to buy hardware, and you'd just `cosimulate in the Amaranth
playground <https://amaranth-lang.org/play/>`_!  The core of what you want
to do with Glasgow is use the I/O pins to interface with other circuits.

We previously instantiated output buffers for the platform LEDs, and
connected those to a host-writable register.  In this example, we'll connect
the writable register to output buffers attached to physical pins, and we'll
also instantiate some input buffers associated with host-readable registers.

On Glasgow, you access the pins on the board by requesting them from the
``Assembly``.  One way to access pins is by requesting individual pins in
sequence (or a sequential bus of pins, as shown in this example): we use the
``assembly.get_port`` API for this, which returns an ``io.PortLike``
(similar to the LED pads that we requested in the previous example).  It can
be convenient to request many different pins all in one operation; to do so,
take a look at the ``assembly.get_port_group`` API.

The Glasgow ``Assembly`` mechanism abstracts the implementation details of
any given version of Glasgow's interface to its pads -- whether a device
uses the FPGA's internal output buffers for tristatable drivers, or whether
it (like Glasgow revC) uses external level shifters with their own output
enable pins, the ``PortLike`` API encapsulates these differences so that
your code will continue to work on any Glasgow-like device that has
appropriately labeled pins.  Similarly, instead of specifying FPGA pin
numbers, the Assembly maps ports to user-visible labeled pins; no matter
what the underlying FPGA is on a device, you can always specify pin ``"A0"``
to get the first pin in port A.

`Below, we give a program <../_static/examples/using-pins.py>`_ that inverts
a sequence of values as they are written to port A, and then receives them
on port B.  The host driver verifies that the received values are the
expected inverted written values.  In order to run this program, remember to
connect flying leads from pins A0 to B0, A1 to B1, A2 to B2, and A3 to B3!

.. literalinclude:: ../_static/examples/using-pins.py
   :language: python

Glasgow should respond:

.. code:: console

    DEBUG:asyncio:Using selector: EpollSelector
    DEBUG:glasgow.hardware.device:found revC3 device with serial C3-20240518T200308Z
    DEBUG:glasgow.hardware.assembly:setting port A voltage to 3.30 V
    DEBUG:glasgow.hardware.assembly:setting port B voltage to 3.30 V
    DEBUG:glasgow.hardware.assembly:assigning pin tx[0][0] to A0
    DEBUG:glasgow.hardware.assembly:assigning pin tx[1][0] to A1
    DEBUG:glasgow.hardware.assembly:assigning pin tx[2][0] to A2
    DEBUG:glasgow.hardware.assembly:assigning pin tx[3][0] to A3
    DEBUG:glasgow.hardware.assembly:assigning pin rx[0][0] to B0
    DEBUG:glasgow.hardware.assembly:assigning pin rx[1][0] to B1
    DEBUG:glasgow.hardware.assembly:assigning pin rx[2][0] to B2
    DEBUG:glasgow.hardware.assembly:assigning pin rx[3][0] to B3
    DEBUG:glasgow.hardware.toolchain:using toolchain 'builtin' (yosys 0.61.0.0.post1073, nextpnr-ice40 0.9.0.0.post686, icepack 0.9.0.0.post686)
    INFO:glasgow.hardware.device:device already has bitstream ID 152e59126139a752bf89f6c498eac037
    INFO:glasgow.hardware.assembly:port A voltage set to 3.3 V
    INFO:glasgow.hardware.assembly:port B voltage set to 3.3 V
    INFO:root:assembly has started
    INFO:root:transmitted 0, received f (expected f)
    INFO:root:transmitted 1, received e (expected e)
    INFO:root:transmitted 2, received d (expected d)
    INFO:root:transmitted 3, received c (expected c)
    INFO:root:transmitted 4, received b (expected b)
    INFO:root:transmitted 5, received a (expected a)
    INFO:root:transmitted 6, received 9 (expected 9)
    INFO:root:transmitted 7, received 8 (expected 8)
    INFO:root:transmitted 8, received 7 (expected 7)
    INFO:root:transmitted 9, received 6 (expected 6)
    INFO:root:transmitted a, received 5 (expected 5)
    INFO:root:transmitted b, received 4 (expected 4)
    INFO:root:transmitted c, received 3 (expected 3)
    INFO:root:transmitted d, received 2 (expected 2)
    INFO:root:transmitted e, received 1 (expected 1)
    INFO:root:transmitted f, received 0 (expected 0)
