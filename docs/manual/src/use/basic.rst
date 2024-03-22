Basic usage
===========

How do I use Glasgow?
---------------------

After :ref:`installing <initial-setup>` the Glasgow software, the ``glasgow`` utility should be operational:

.. code:: console

    $ glasgow --version

Glasgow has a number of commands, the most basic being ``safe`` and ``run``. At all times, the ``--help`` argument may be appended for more details.

.. important::

    Please be aware that a Glasgow device that is unable to establish a USB connection will slowly fade the `FX2` LED on and off to indicate a failure. This most commonly occurs if you use a power-only USB cable to connect the Glasgow device to your computer.


``glasgow safe``
################

.. note:: This command has the same effect as pressing the physical `E-STOP / RESET` button that is present on ``revC3`` and later hardware revisions.

Set all I/O to a `safe` state---disable voltage outputs, and set all I/O pins to a high impedance state.

.. code:: console

    $ glasgow safe


``glasgow run ...``
###################

Glasgow is based around the concept of `applets`, with each implementing a particular mode of operation or interface. For example, there are applets such as ``uart``, ``i2c`` and ``spi``---each implementing the gateware (which runs on the FPGA) and software (which runs on the host PC). The Glasgow framework coordinates building, caching, and operating these applets for you.

A common argument is ``-V ...``, which sets the I/O voltage, as well as the supply output voltage for the selected port(s). Be careful that you set the correct voltage for your connected devices.

The following command will run the ``uart`` applet, with an I/O voltage of 3.3 V, and will configure pin ``A0`` to be `Tx` (Glasgow transmitting), and pin ``A1`` to be `Rx` (Glasgow receiving):

.. code:: console

    $ glasgow run uart -V 3.3 --pin-tx 0 --pin-rx 1 tty

A list of available applets can be retrieved by running ``glasgow run --help``.


Command line format
-------------------

As you build up the Glasgow command line, the `context` changes---for example the output of the following ``--help`` are all different.

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


Ports and pin numbering
-----------------------

The ``revC`` hardware has two ports (A and B), each of which have 8× I/O pins. When running the ``glasgow`` utility, you will see reference to a ``--port`` argument, along with ``--pin-*``, as defined by each applet (e.g: ``--pin-tx`` for UART).

By default, the `port` will typically be set to ``AB``, which results in all 16× I/O pins being available for use, numbered 0 to 15... e.g: "`pin 0`" is ``A0``, "`pin 7`" is ``A7``, "`pin 8`" is ``B0``, and so on.

In some cases, you may want to use ``B3`` without using port A, which can be achieved using the following:

.. code:: console

    $ glasgow run uart -V 3.3 --port B --pin-tx 3 tty


Examples
--------


UART
####

The ``uart`` applet provides a basic full-duplex UART interface that can operate at virtually any reasonable baudrate, and also supports automatically detecting the baudrate based on frames sent by the remote device. The transmit and receive signals can also be easily inverted.

By running the applet using the ``tty`` mode, you will be delivered a direct pipe to the UART---characters you enter into the terminal will be transmitted by the Glasgow hardware, and characters received by the Glasgow hardware will appear in the terminal.

The baud rate can be set using ``-b 57600``, and automatic baud rate detection can be enabled with ``-a``. Although reliable and particularly convenient for devices that change their baud rate as they boot, this detection mechanism is not perfect, and sometimes you may have to set the baud rate manually.

Aside from the ``tty`` mode, others are available (``pty``, ``socket``), which are explained further by the help text.

.. code:: console

    $ glasgow run uart -V 3.3 --pin-tx 0 --pin-rx 1 -b 57600 tty


SPI Controller
##############

The ``spi-controller`` applet implements an SPI controller, allowing full-duplex transfer to an SPI device. The following command will assert `CS#`, send the five bytes ``03 01 23 5f f5``, and then de-assert `CS#`, before printing the received data to the console.

.. code:: console

    $ glasgow run spi-controller -V 3.3 --pin-sck 0 --pin-cs 1 --pin-copi 2 --pin-cipo 3 \
        '0301235ff5'


I²C Initiator
#############

The ``i2c-initiator`` applet implements an I²C initiator, which facilitates a simple bus scan from the command line, using the on-board pull-up resistors.

.. code:: console

    $ glasgow run i2c-initiator -V 3.3 --pulls scan

Using the :ref:`repl or script modes <repl-script>`, it's possible to easily communicate with devices, obeying clock stretching and other factors that are often ignored with bit-banged interfaces.
