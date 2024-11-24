Basic usage
===========


Getting started with Glasgow
----------------------------

After :ref:`installing <initial-setup>` the Glasgow software, the ``glasgow`` utility should be operational.  The ``glasgow`` utility is the most common (but not the only) way to interact with Glasgow hardware.  Test to see if ``glasgow`` is installed correctly with:

.. code:: console

    $ glasgow --version

``glasgow`` has a number of subcommands. At all times, the ``--help`` argument may be appended for more details.

.. note::

  As you build up the ``glasgow`` tool's command line, the `context` changes --- for example, the output of each of the following ``--help`` s are all different:

  .. code:: console

      $ glasgow --help
      $ glasgow run --help
      $ glasgow run uart --help

  The upshot of this is that different arguments need to be placed at different positions in the command line. The help section at each level should clarify where each argument should be placed. For example, the ``--serial`` parameter is recognized by the top-level ``glasgow`` command, and not by the third-level ``glasgow run uart`` command.

  .. code:: console

      ## this is valid:
      $ glasgow --serial ${my_serial} run uart -V 3.3 tty

      ## this is invalid!
      $ glasgow run uart --serial ${my_serial} -V 3.3 tty


Returning Glasgow to a safe state
#################################

To begin with, use the ``glasgow safe`` command to make sure that the ``glasgow`` utility can communicate with your Glasgow hardware.   The ``glasgow safe`` command sets all I/O to a `safe` state --- it disables voltage outputs, and sets all I/O pins to a high impedance state.  Try it with:

.. code:: console

    $ glasgow safe

.. note:: This command has the same effect as pressing the physical `E-STOP / RESET` button that is present on ``revC3`` and later hardware revisions.  You may prefer to get in the habit of using the physical button if you're sitting next to your Glasgow; the button gives tactile feedback that the device has entered a safe state, in a way that ``glasgow safe`` cannot!

You can use this command at any time to put your Glasgow hardware into a `safe` state; if it is successful, it will provide the output:

.. code:: console

    $ glasgow safe
    I: g.cli: all ports safe

.. tip::

    If the ``glasgow`` tool cannot detect your connected Glasgow hardware, look at the LEDs.  A Glasgow device that is unable to establish a USB connection will slowly fade the `FX2` LED on and off to indicate a failure. This most commonly occurs if you use a power-only USB cable to connect the Glasgow device to your computer.


Working with applets
--------------------

``glasgow`` is based around the concept of `applets`, with each implementing a particular mode of operation or interface. For example, there are applets such as ``uart``, ``i2c-initiator``, and ``spi-controller`` --- each implementing the gateware (which runs on the FPGA) and software (which runs on the host PC). The Glasgow software framework coordinates building, caching, and operating these applets for you.

A list of available applets [#applet_sources]_ can be shown by running ``glasgow run --help``.  You can interact with applets from the ``glasgow`` tool in one of four ways:

* **Running an applet**.  Most applets come with command line programs that perform a specific task related to the gateware that they interface with; ``glasgow run`` ning an applet allows you to invoke one or more of these applet-associated programs.  This usage is described below.

* **Using an applet from the REPL.**  Applets provide a Python programming interface.  ``glasgow repl`` launches a Python prompt (a "REPL") that you can use to interactively explore the gateware implemented by an applet, and hardware connected to it.  This is described in the :ref:`REPL & script operation <repl-script>` section.

* **Scripting an applet**.  It is often useful to use an applet's Python programming interface non-interactively, to run a stored set of operations using the Glasgow platform.  This is described in the :ref:`script usage <script-usage>` section.

* **Using an offline tool**.  Some applets come with offline tools that do not use the Glasgow hardware at all.  For instance, the ``memory-floppy`` applet has a tool to manipulate raw disk images that may have been captured by ``glasgow run`` ning the applet.  This is not currently described in this document, but can be accessed with the ``glasgow tool`` command.

In this basic usage, we describe only using ``glasgow run`` to run an applet.


Using ``glasgow run``
#####################

Applets that have ``run`` nable programs often have `subcommands` to specify what task you would like to accomplish.  For instance, the ``uart`` applet has three subcommands -- ``tty``, which attaches the UART to stdin; ``pty``, which creates a UNIX pseudoterminal; and ``socket``, which attaches the UART to either a UNIX or TCP socket.  You can get a list of an applet's subcommands by using the ``--help`` argument; each subcommand may also have arguments of its own:

.. code:: console

    $ glasgow run uart --help
    [...]
    positional arguments:
      OPERATION
        tty                     connect UART to stdin/stdout
        pty                     connect UART to a pseudo-terminal device file
        socket                  connect UART to a socket
    [...]
    $ glasgow run socket --help
    usage: glasgow run uart socket [-h] ENDPOINT
    
    positional arguments:
      ENDPOINT    listen at ENDPOINT, either unix:PATH or tcp:HOST:PORT
    [...]

Applets also can have `build arguments` that specify how the gateware is constructed, and `run arguments` that modify the behavior of the applet as a whole; these are also listed in the ``--help`` output.  A common run argument is ``-V ...``, which sets the I/O voltage, as well as setting the supply output voltage for the selected port(s). Be careful that you set the correct voltage for your connected devices!

Putting it together, the following command will run the ``uart`` applet, with an I/O voltage of 3.3 V, and will configure pin ``A0`` to be `Tx` (Glasgow transmitting), and pin ``A1`` to be `Rx` (Glasgow receiving).  It uses the ``socket`` subcommand to bridge the UART to a socket:

.. code:: console

    $ glasgow run uart -V 3.3 --pin-tx 0 --pin-rx 1 socket tcp:127.0.0.1:4321
    I: g.device.hardware: generating bitstream ID [...]
    I: g.cli: running handler for applet 'uart'
    I: g.applet.interface.uart: port(s) A, B voltage set to 3.3 V
    I: g.applet.interface.uart: port(s) A, B pull resistors configured
    I: g.applet.interface.uart: socket: listening at tcp:127.0.0.1:4321

As the applet's output suggests, you can connect to TCP port 4321 using a tool of your choice --- ``nc`` or PuTTY will both work.


Specifying port numbers
#######################

The ``revC`` hardware has two ports (A and B), each of which have 8× I/O pins. When running the ``glasgow`` utility, you will see reference to a ``--port`` argument, along with ``--pin-*``, as defined by each applet (e.g: ``--pin-tx`` for UART).

By default, the `port` will typically be set to ``AB``, which results in all 16× I/O pins being available for use, numbered 0 to 15... e.g: "`pin 0`" is ``A0``, "`pin 7`" is ``A7``, "`pin 8`" is ``B0``, and so on.

In some cases, you may want to use ``B3`` without using port A, which can be achieved using the following:

.. code:: console

    $ glasgow run uart -V 3.3 --port B --pin-tx 3 socket tcp:127.0.0.1:4321


Inverting pins
##############

Any pin can be inverted via the command-line interface using one of the following syntaxes:

* single pin: ``--pin-x 0#``
* pin range:  ``--pins-x 0:8#``      (inverts all of them)
* pin list:   ``--pins-x 0,1#,2#,3`` (inverts only specified pins)

Pull-ups configured for a pin with inversion get converted to pull-downs and vice versa.


Examples
--------


UART
####

The ``uart`` applet provides a basic full-duplex UART interface that can operate at virtually any reasonable baudrate, and also supports automatically detecting the baudrate based on frames sent by the remote device. The transmit and receive signals can also be easily inverted.

By running the applet using the ``tty`` mode, you will be delivered a direct pipe to the UART --- characters you enter into the terminal will be transmitted by the Glasgow hardware, and characters received by the Glasgow hardware will appear in the terminal.

The baud rate can be set using ``-b 57600``, and automatic baud rate detection can be enabled with ``-a``. Although reliable and particularly convenient for devices that change their baud rate as they boot, this detection mechanism is not perfect, and sometimes you may have to set the baud rate manually.

Aside from the ``tty`` mode, others are available (``pty``, ``socket``), which are explained further by the help text.

.. code:: console

    $ glasgow run uart -V 3.3 --pin-tx 0 --pin-rx 1 -b 57600 tty


SPI controller
##############

The ``spi-controller`` applet implements an SPI controller, allowing full-duplex transfer to an SPI device. The following command will assert `CS#`, send the five bytes ``03 01 23 5f f5``, and then de-assert `CS#`, before printing the received data to the console.

.. code:: console

    $ glasgow run spi-controller -V 3.3 --pin-sck 0 --pin-cs 1 --pin-copi 2 --pin-cipo 3 \
        '0301235ff5'


I²C initiator
#############

The ``i2c-initiator`` applet implements an I²C initiator, which facilitates a simple bus scan from the command line, using the on-board pull-up resistors.

.. code:: console

    $ glasgow run i2c-initiator -V 3.3 --pulls scan

Using the :ref:`repl or script modes <repl-script>`, it's possible to easily communicate with devices, obeying clock stretching and other factors that are often ignored with bit-banged interfaces.

.. [#applet_sources] In the current Glasgow software, all applets are packaged as part of the Glasgow software distribution; future versions of Glasgow :ref:`may support out-of-tree applets <applet>`.  For the curious, the list of applets is retrieved from the `installed package's metadata <https://packaging.python.org/en/latest/guides/creating-and-discovering-plugins/#using-package-metadata>`_; this list, in turn, comes from the |pyproject_toml|_ file's ``project.entry-points."glasgow.applet"`` section.

.. |pyproject_toml| replace:: ``glasgow`` package's ``pyproject.toml``
.. _pyproject_toml: https://github.com/GlasgowEmbedded/glasgow/blob/main/software/pyproject.toml
