.. _repl-script:

REPL & script operation
=======================

What is "*REPL*"?
-----------------

If you've ever typed ``python3`` into a terminal, or found yourself looking at the three angle brackets (``>>>``), then you'll have some idea of what we're referring to. It stands for "`Read Eval Print Loop`", and is a fundamental way of interacting with many interpreted languages (including Bash and JavaScript, alongside Python).

By invoking ``glasgow repl ...`` you can gain interactive code-level access to the applet of your choice.

.. warning::
    As always, please make sure you select the correct I/O and supply voltage for whatever you have connected to your Glasgow.

.. code:: console

    $ glasgow repl i2c-controller -V 3.3
    I: glasgow.hardware.device: device already has bitstream ID 0484178a31cff82770362171c7bccf0a
    I: glasgow.hardware.assembly: port A voltage set to 3.3 V
    I: glasgow.hardware.assembly: port B voltage set to 3.3 V
    I: glasgow.cli: running handler for applet 'i2c-controller'
    I: glasgow.applet.interface.i2c_controller: dropping to REPL; use 'help(i2c_iface)' to see available APIs
    >>>

What happens now is entirely up to you --- ``glasgow script ...`` is given an identical environment, except that it will run the nominated script rather than present control to you.

The Glasgow framework provides us with access to the ``device`` and ``args`` variables, plus another variable that is named differently depending on the applet being used. For example, the I²C applet calls it ``i2c_iface``.

.. code:: console

    >>> locals().keys()
    dict_keys(['__name__', 'device', 'i2c_iface', 'args', '__builtins__'])

.. note::
    Some examples are maintained in the `examples <https://github.com/GlasgowEmbedded/glasgow/tree/main/examples>`_ directory.

One further note --- a lot of the Glasgow framework uses ``asyncio``, with the most apparent impact to users being that the ``await`` keyword must be used. You are provided with an async-capable environment, so no additional setup work is required on your part --- just use the ``await`` keyword... if you ever see a ``<coroutine object ....>``, try using ``await``.


How do I use this interface?
----------------------------

The exact usage will depend heavily on the applet you've requested, some examples are provided below with explanations.

As the startup prompt suggests, investigating ``help(applet_iface)`` and ``help(device)`` are good places to start... after that, have a look at the applet's code.

I²C
~~~

For this example, I will be using the `Sparkfun BMP085 <https://web.archive.org/web/20230206233109/https://www.sparkfun.com/products/retired/9694>`_ (a now-retired breakout for an I²C barometric pressure sensor), which supports 3.3v operation.

.. note::
    I²C busses are implemented using open-drain, meaning that pull-up resistors are `required`... Glasgow's onboard 10kΩ pull-ups are enabled by default --- while they will generally be enough, they may not suffice for fast or long busses. This particular breakout board has on-board pull-ups already, so it's not necessary to use them.

.. code:: console

    $ glasgow repl i2c-controller -V 3.3
    I: glasgow.hardware.device: device already has bitstream ID 0484178a31cff82770362171c7bccf0a
    I: glasgow.hardware.assembly: port A voltage set to 3.3 V
    I: glasgow.hardware.assembly: port B voltage set to 3.3 V
    I: glasgow.cli: running handler for applet 'i2c-controller'
    I: glasgow.applet.interface.i2c_controller: dropping to REPL; use 'help(i2c_iface)' to see available APIs
    >>>

Let's start with a bus scan:

.. code:: console

    >>> await i2c_iface.scan()
    {119}
    >>>

Address ``119`` has responded, which is ``0x77`` --- and this matches the datasheet!

This sensor isn't the easiest to operate directly (you need to read a number of calibration variables and perform long calculations), so this is a great example of when you might want to start writing a script instead of using the REPL interface... however, to prove the point, we're going to read a register and leave the rest as an exercise for the reader.

If you're familiar with I²C, you'll know that a common convention is for the target register address to be conveyed as the first portion of a write's payload, with a subsequent read accessing the data from that location, with addresses incrementing automatically. Here we read the ``AC1`` value, which is a 16-bit integer stored at addresses ``0xAA`` and ``0xAB`` --- first by writing the ``0xAA`` base address, and then performing a 2-byte read.

.. code:: console

    >>> await i2c_iface.write(119, [ 0xAA ])
    True
    >>> await i2c_iface.read(119, 2)
    b'\x1c\x04'

UART
~~~~

To demonstrate a simple UART loopback, I've connected pin 0 and 1 of Port A together... i.e: anything that we transmit, will be immediately received again by us.

.. code:: console

    $ glasgow repl uart -V 3.3
    I: glasgow.hardware.device: device already has bitstream ID f3838ff227839f106448c2ecf6913ee9
    I: glasgow.hardware.assembly: port A voltage set to 3.3 V
    I: glasgow.hardware.assembly: port B voltage set to 3.3 V
    I: glasgow.cli: running handler for applet 'uart'
    I: glasgow.applet.interface.uart: dropping to REPL; use 'help(uart_iface)' to see available APIs
    >>>

Again, we simply call the ``uart_iface.write()`` and ``uart_iface.read()`` functions to handle transmit and receive...

.. code:: console

    >>> await uart_iface.write(b'hello!')
    >>> await uart_iface.read()
    b'hello!'


WS2812
~~~~~~

I've got a `quarter of an Adafruit 60 LED ring <https://www.adafruit.com/product/1768>`_... that's 15x WS2812 RGB LEDs.

.. note::

    Due to some buffering artifacts, make sure you write a whole frame at once!

.. code:: console

    $ glasgow repl video-ws2812-output -V 5 -c 15 -b 1 -f RGB-xBRG --out A0
    I: glasgow.hardware.device: generating bitstream ID 0dfe27478be3932374f61610193f34f0
    I: glasgow.cli: running handler for applet 'video-ws2812-output'
    I: glasgow.applet.video.ws2812_output: port A voltage set to 5.0 V
    I: glasgow.applet.video.ws2812_output: port B voltage set to 5.0 V
    I: glasgow.applet.video.ws2812_output: dropping to REPL; use 'help(iface)' to see available APIs
    >>>

Next, we just write pixel data! Glasgow handles the pixel format mapping for us, and because we requested ``RGB-xBRG``, the conversion from RGB24 (three bytes per pixel) will be handled in hardware.
The ``xBRG`` indicates that we're giving a constand ``0`` for the White channel, followed by the required order of Red, Green, and Blue.

They're bright, so be careful of your eyes (I used ``1`` for a reason)... here's a strip of green pixels:

.. code:: console

    >>> await iface.write([ 0,1,0 ] * args.count)
    >>>

A 3-bit rainbow: (black, red, green, yellow, blue, magenta, cyan, white)

.. code:: console

    >>> from itertools import chain
    >>> pix = ( (n&1, n&2, n&4) for n in range(args.count) )    # counter to 3-bit colors
    >>> pix = chain.from_iterable(pix)                          # flatten to 1 dimension
    >>> pix = map(lambda v: 1 if v else 0, pix)                 # flatten to 0 or 1
    >>> pix = [ *pix ]                                          # make into a list for re-use
    >>> await iface.write(pix)                                  # display it
    >>>

And all off again, followed by a full power-down of the I/O:

.. code:: console

    >>> await iface.write([ 0,0,0 ] * args.count)
    >>> await device.set_voltage('AB', 0)
    >>>

Hopefully this example starts to show you the power you have available.


.. _script-usage:

How do I use a script?
----------------------

Scripts operate in exactly the same way as the REPL interface --- the only real difference is that instead of you typing (or copy/pasting) the code, it will be read from the nominated file.
This allows you to build up much more sophisticated things, harnessing the power of Glasgow without touching any applet code directly.

See the `PCF8574 <https://github.com/GlasgowEmbedded/glasgow/blob/main/examples/i2c-pcf8574.py>`_ example for a simple demo.


Can I use command line arguments?
---------------------------------

Yes! The ``args`` variable that is passed into the REPL and script environments contains all command line arguments that Glasgow sets up (including any defaults), along with a ``script_args`` member which contains anything after the first terminating ``--``.

Of course you're also able to setup ``argparse`` or do whatever argument parsing you need to do --- see the `script args <https://github.com/GlasgowEmbedded/glasgow/blob/main/examples/script_args.py>`_ example.

.. code:: console

    $ glasgow repl i2c-controller -V 3.3 -- test me
    I: glasgow.hardware.device: generating bitstream ID 0484178a31cff82770362171c7bccf0a
    I: glasgow.hardware.assembly: port A voltage set to 3.3 V
    I: glasgow.hardware.assembly: port B voltage set to 3.3 V
    I: glasgow.cli: running handler for applet 'i2c-controller'
    I: glasgow.applet.interface.i2c_controller: dropping to REPL; use 'help(i2c_iface)' to see available APIs
    >>> args
    Namespace(verbose=0, quiet=0, log_file=None, filter_log=None, no_shorten=False, show_statistics=False, serial=None, action='repl', override_required_revision=False, reload=False, prebuilt=False, prebuilt_at=None, applet='i2c-initiator', scl=PinArgument(number=0, invert=False), sda=PinArgument(number=1, invert=False), bit_rate=100, voltage=[VoltArgument(ports='AB', value=3.3, sense=None)], pulls=True, script_args=['test', 'me'])
    >>> args.script_args
    ['test', 'me']
    >>>
