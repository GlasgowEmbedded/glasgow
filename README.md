# Glasgow Debug Tool

**Want one? [Subscribe here](https://mailchi.mp/44980ff6f0ab/glasgow-announcements).**

**Let's chat! [Our IRC channel is #glasgow at freenode.net](https://webchat.freenode.net/?channels=glasgow).**

**Important note: if you are looking to assemble boards yourself, use only revC1.**

## What is Glasgow?

Glasgow is a tool for exploring digital interfaces, aimed at embedded developers, reverse engineers, digital archivists, electronics hobbyists, and everyone else who wants to communicate to a wide selection of digital devices with high reliability and minimum hassle. It can be attached to most devices without additional active or passive components, and includes extensive protection from unexpected conditions and operator error.

The Glasgow hardware can support many digital interfaces because it uses reconfigurable logic. Instead of only offering a small selection of standard hardware supported interfaces, it uses an FPGA to adapt on the fly to the task at hand without compromising on performance or reliability, even for unusual, custom or obsolete interfaces.

The Glasgow software is a set of building blocks designed to eliminate incidental complexity. Each interface is packaged into a self-contained *applet* that can be used directly from the command line, or reused as a part of a more complex system. Using Glasgow does not require any programming knowledge, although it becomes much more powerful if you know a bit of Python.

## What can I do with Glasgow?

Some of the tasks Glasgow can do well are:

  * communicate via UART,
    * automatically determine and follow the baud rate of device under test,
  * initiate transactions via SPI or I²C,
  * read and write 24-series EEPROMs,
  * read and write 25-series Flash memories,
    * determine memory parameters via SFDP,
  * read and write ONFI-compatible Flash memories,
    * determine memory parameters via ONFI parameter page,
  * program and verify AVR microcontrollers with SPI interface,
  * automatically determine unknown JTAG pinout,
  * play back JTAG SVF files,
  * debug ARC processors via JTAG,
  * debug some MIPS processors via EJTAG,
  * program and verify XC9500XL CPLDs via JTAG,
  * synthesize sound using a Yamaha OPL chip and play it in real time on a webpage,
  * read raw modulated data from 5.25"/3.5" floppy drives,
  * ... and more!

Everything above can be done with only a Glasgow revC board, some wires, and depending on the device under test, external power.

## How does using Glasgow look like?

Watch a typical command-line workflow in this screencast:

[![asciicast](https://asciinema.org/a/i9edqaUBVLLw7mRZCpdxe91Fu.svg)](https://asciinema.org/a/i9edqaUBVLLw7mRZCpdxe91Fu)

## What hardware does Glasgow use?

The Glasgow hardware evolves over time, with each major milestone called a "revision". Although all revisions are, and will always be supported with the same software, they vary significantly in their capabilities, and the chosen revision will limit the possible tasks.

Glasgow boards use a version in the `revXN` format, where `X` is a revision letter (increased on major design changes) and `N` is a stepping number (increased on any layout or component changes). For example, `revC0` is the first stepping of revision C.

### revA/revB

Revisions A and B have not been produced in significant amounts, contain major design issues, and are therefore mostly of historical interest. Nevertheless, everyone who has one of the revA/revB boards can keep using them—forever.

### revC

![Overview of the Glasgow PCB](hardware/boards/glasgow/3drender-readme.png)

Revision C is the latest revision and is being prepared for mass production. It provides 16 I/O pins with a maximum frequency of approx. 100 MHz\*, independent direction control and independent programmable pull-up/pull-down resistors. The I/O pins are grouped into two I/O ports that can use any voltage from 1.8 V to 5 V, sense and monitor I/O voltage of the device under test, as well as provide up to 150 mA of power. The board uses USB 2 for power, configuration, and communication, achieving up to 336 Mbps (42 MB/s) of sustained combined throughput.

<sub>\* Maximum frequency achievable in practice depends on many factors and will vary greatly with specific interface and applet design. 24 MHz non-DDR can be achieved for most interfaces with minimal effort.</sub>

## What software does Glasgow use?

Glasgow is written entirely in Python 3. The interface logic that runs on the FPGA is described using [Migen](https://m-labs.hk/migen/), which is a Python-based domain specific language. The supporting code that runs on the host PC is written in Python with [asyncio](https://docs.python.org/3/library/asyncio.html). This way, the logic on the FPGA can be assembled on demand for any requested configuration, keeping it as fast and compact as possible, and code can be shared between gateware and software, removing the need to add error-prone "glue" boilerplate.

Glasgow would not be possible without the [open-source iCE40 FPGA toolchain](http://www.clifford.at/icestorm/), which is not only very reliable but also extremely fast. It is so fast that FPGA bitstreams are not cached (beyond not rebuilding the bitstream already on the device), as it only takes a few seconds to build one from scratch for something like an UART. When developing a new applet it is rarely necessary to wait for the toolchain.

Implementing reliable, high-performance USB communication is not trivial—packetization, buffering, and USB quirks add up. Glasgow abstracts away USB: on the FPGA, the applet gateware writes to or reads from a FIFO, and on the host, applet software writes to or reads from a socket-like interface. Idiomatic Python code can communicate at maximum USB 2 bulk bandwidth on a modern PC without additional effort. Moreover, when a future Glasgow revision will use Ethernet in addition to USB, no changes to applet code will be required.

Debugging new applets can be hard, especially if bidirectional buses are involved. Glasgow provides a built-in cycle-accurate logic analyzer that can relate the I/O pin level and direction changes to commands and responses received and sent by the applet. The logic analyzer compresses waveforms and can pause the applet if its buffer is about to overflow.

## How do I use Glasgow?

### ... with Linux?

You will need Python 3.7 (or a newer version, in which case replace `3.7` with that version below) and sdcc. On a Debian or Ubuntu system these can be installed with:

    apt-get install python3.7 sdcc

Obtain the source code:

    git clone https://github.com/GlasgowEmbedded/Glasgow
    cd Glasgow

Configure your system to allow unprivileged access (for anyone in the `plugdev` group) to the Glasgow hardware:

    sudo cp config/99-glasgow.rules /etc/udev/rules.d

Install the dependencies and the binaries for the current user:

    cd software
    python3.7 setup.py develop --user

The binaries are placed in `$HOME/.local/bin`, so be sure to add that directory to the `PATH` environment variable; after this, you can run `glasgow` from a terminal. Instead of adjusting `PATH` it is also possible to use `python3.7 -m glasgow.cli`.

To update the source code, do:

    cd Glasgow
    git pull
    cd software
    python3.7 setup.py build_ext

### ... with Windows?

Although first-class Windows support is an important goal and Glasgow already works on Windows, the installation process is not yet ready.

## Who made Glasgow?

  * [@whitequark](https://github.com/whitequark) came up with the design, coordinates the project and implements most of gateware and software;
  * [@awygle](https://github.com/awygle) designed the power/analog port circuitry and helped with layout of revB;
  * [@marcan](https://github.com/marcan) improved almost every aspect of hardware for revC;
  * [@esden](https://github.com/esden) is handling batch manufacturing;
  * [@smunaut](https://github.com/smunaut) provided advice crucial for stability and performance of USB communication;
  * [@electronic_eel](https://github.com/electronic_eel) designed the test jig and advanced protection circuitry;
  * ... and many [other people](https://github.com/GlasgowEmbedded/Glasgow/graphs/contributors).

## License

Glasgow is distributed under the terms of both 0-clause BSD license as well as Apache 2.0 license.

See [LICENSE-0BSD](LICENSE-0BSD.txt) and [LICENSE-Apache-2.0.txt](LICENSE-Apache-2.0.txt) for details.
