# Glasgow Debug Tool

**Want one? The [Crowdsupply campaign](https://www.crowdsupply.com/1bitsquared/glasgow) is now live.**

**Let's chat! Our IRC channel is [#glasgow at libera.chat](https://web.libera.chat/#glasgow); our Discord channel is [#glasgow at 1BitSquared's Discord server](https://1bitsquared.com/pages/chat).**

**Important note: if you are looking to assemble boards yourself, use only revC2.**


## ⚠️⚠️⚠️ NEWCOMERS AND CROWDSUPPLY BUYERS: PLEASE READ THIS FIRST ⚠️⚠️⚠️

At the moment the project does not see much activity because the founder and primary maintainer, [Catherine @whitequark](https://github.com/whitequark), has spent several years struggling to survive due to disability, large scale social unrest, and other factors. She has now moved to the UK, got necessary healthcare, and is doing a lot better; the project's pace will pick up soon and more maintainers will be added to the current team of three in close future, but the timing of Crowdsupply orders being shipped doesn't match up to maintainer capacity a little bit.

Please stay patient and keep in mind that hardware is made by people who have limited capacity and sometimes need to recover from extreme events.

If you want to show appreciation or help with Catherine's living costs, she has a personal [Patreon](https://patreon.com/whitequark). These donations will not impact the progress of the project since the limiting factor is health first and time second, but they are very much appreciated.


## What is Glasgow?

Glasgow is a tool for exploring digital interfaces, aimed at embedded developers, reverse engineers, digital archivists, electronics hobbyists, and everyone else who wants to communicate to a wide selection of digital devices with high reliability and minimum hassle. It can be attached to most devices without additional active or passive components, and includes extensive protection from unexpected conditions and operator error.

The Glasgow hardware can support many digital interfaces because it uses reconfigurable logic. Instead of only offering a small selection of standard hardware supported interfaces, it uses an FPGA to adapt on the fly to the task at hand without compromising on performance or reliability, even for unusual, custom or obsolete interfaces.

The Glasgow software is a set of building blocks designed to eliminate incidental complexity. Each interface is packaged into a self-contained *applet* that can be used directly from the command line, or reused as a part of a more complex system. Using Glasgow does not require any programming knowledge, although it becomes much more powerful if you know a bit of Python.


## What can I do with Glasgow?

Some of the tasks Glasgow can do well are:

  * communicate via UART,
    * automatically determine and follow the baud rate of device under test,
  * initiate transactions via SPI or I²C,
  * read and write 24-series I²C EEPROMs,
  * read and write 25-series SPI Flash memories,
    * determine memory parameters via SFDP,
  * read and write ONFI-compatible Flash memories,
    * determine memory parameters via ONFI parameter page,
  * read and write parallel 27/28/29-series EPROMs, EEPROMs and Flash memories,
    * determine the extent of floating gate charge decay and rescue data,
  * program and verify AVR microcontrollers with SPI interface,
  * automatically determine unknown JTAG pinout,
  * play back JTAG SVF files,
  * debug ARC processors via JTAG,
  * debug some MIPS processors via EJTAG,
  * program and verify XC9500XL CPLDs via JTAG,
  * communicate using nRF24L01(+) radios,
  * program nRF24LE1 and nRF24LU1(+) microcontrollers,
  * synthesize sound using a Yamaha OPLx/OPM chip and play it in real time on a webpage,
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

Revision C is the latest revision and is being prepared for mass production. It provides 16 I/O pins with a data rate up to approx. 100 Mbps/pin (50 MHz)\*, independent direction control and independent programmable pull-up/pull-down resistors. The I/O pins are grouped into two I/O ports, each of which can use any voltage from 1.8 V to 5 V, sense and monitor I/O voltage of the device under test, as well as provide up to 150 mA of power. The board uses USB 2 for power, configuration, and communication, achieving up to 336 Mbps (42 MB/s) of sustained combined throughput.

<sub>\* Data rate achievable in practice depends on many factors and will vary greatly with specific interface and applet design. 12 Mbps/pin (6 MHz) can be achieved with minimal development effort; reaching higher data rates requires careful HDL coding and a good understanding of timing analysis.</sub>


## What software does Glasgow use?

Glasgow is written entirely in Python 3. The interface logic that runs on the FPGA is described using [Amaranth](https://github.com/amaranth-lang/amaranth/), which is a Python-based domain specific language. The supporting code that runs on the host PC is written in Python with [asyncio](https://docs.python.org/3/library/asyncio.html). This way, the logic on the FPGA can be assembled on demand for any requested configuration, keeping it as fast and compact as possible, and code can be shared between gateware and software, removing the need to add error-prone "glue" boilerplate.

Glasgow would not be possible without the [open-source iCE40 FPGA toolchain](http://bygone.clairexen.net/icestorm/), which is not only very reliable but also extremely fast. It is so fast that FPGA bitstreams are not cached (beyond not rebuilding the bitstream already on the device), as it only takes a few seconds to build one from scratch for something like an UART. When developing a new applet it is rarely necessary to wait for the toolchain.

Implementing reliable, high-performance USB communication is not trivial—packetization, buffering, and USB quirks add up. Glasgow abstracts away USB: on the FPGA, the applet gateware writes to or reads from a FIFO, and on the host, applet software writes to or reads from a socket-like interface. Idiomatic Python code can communicate at maximum USB 2 bulk bandwidth on a modern PC without additional effort. Moreover, when a future Glasgow revision will use Ethernet in addition to USB, no changes to applet code will be required.

Debugging new applets can be hard, especially if bidirectional buses are involved. Glasgow provides a built-in cycle-accurate logic analyzer that can relate the I/O pin level and direction changes to commands and responses received and sent by the applet. The logic analyzer compresses waveforms and can pause the applet if its buffer is about to overflow.


## How do I use Glasgow?

A lot of care and effort has been put into making the use of the software stack as seamless as possible. In particular, every dependency where it is possible is shipped via the [Python package index][pypi] (including the USB driver and the FPGA toolchains) to make installation and upgrades as seamless as they can be.

[pypi]: https://pypi.org/

**If these instructions don't work for you, please file it as a bug, so that the experience can be made smoother for everyone.**


### ... with Linux?

You will need to have git, Python, and pipx installed. To install these on an Ubuntu or Debian system, run:

```shell
sudo apt install --no-install-recommends git pipx
pipx ensurepath
```

The `pipx ensurepath` command may prompt you to reopen the terminal window; do so.

Navigate to a convenient working directory and download the source code:

```shell
git clone https://github.com/GlasgowEmbedded/glasgow
```

Configure your system to allow unprivileged access (for anyone in the `plugdev` group) to the Glasgow hardware:

```shell
sudo cp glasgow/config/99-glasgow.rules /etc/udev/rules.d
```

Install the Glasgow software for the current user:

```shell
pipx install -e 'glasgow/software[builtin-toolchain]'
```

To update the software to its newest revision, navigate to your working directory and run:

```shell
git -C glasgow pull
pipx reinstall glasgow
```


### ... with Windows?

You will need to have git, Python, and pipx installed. To install [git][git-win] and [Python][py-win], follow the instructions from their respective pages. To install pipx, run:

[git-win]: https://git-scm.com/download/win
[py-win]: https://www.python.org/downloads/windows/

```cmd
py -3 -m pip install --user pipx
py -3 -m pipx ensurepath
```

The `py -3 -m pipx ensurepath` command may prompt you to reopen the terminal window; do so.

Navigate to a convenient working directory (it is highly recommended to use a local directory, e.g. `%LOCALAPPDATA%`, since running Glasgow software from a network drive or a roaming profile causes significant slowdown) and download the source code:

```cmd
git clone https://github.com/GlasgowEmbedded/glasgow
```

Install the Glasgow software for the current user:

```cmd
pipx install -e glasgow/software[builtin-toolchain]
```

To update the software to its newest revision, navigate to your working directory and run:

```cmd
git -C glasgow pull
pipx reinstall glasgow
```


### ... with macOS?

You will need to have pipx installed. If you haven't already, install [Homebrew](https://brew.sh/). To install pipx, run:

```shell
brew install pipx
pipx ensurepath
```

The `pipx ensurepath` command may prompt you to reopen the terminal window; do so.

Navigate to a convenient working directory and download the source code:

```shell
git clone https://github.com/GlasgowEmbedded/glasgow
```

Install the Glasgow software for the current user:

```shell
pipx install -e 'glasgow/software[builtin-toolchain]'
```

To update the software to its newest revision, navigate to your working directory and run:

```shell
git -C glasgow pull
pipx reinstall glasgow
```


### Advanced topic: Using a native FPGA toolchain

The steps above install the [YoWASP][] FPGA toolchain, which is a good low-friction option, especially for people whose primary competence is not in software, since it does not require any additional steps besides those that are already necessary. However, the YoWASP toolchain is noticeably slower than the native one (usually by a factor of less than 2×). The YoWASP toolchain is also not available for all platforms and architectures; notably, 32-bit Raspberry Pi is not covered.

If you already have the required tools (`yosys`, `nextpnr-ice40`, `icepack`) installed or are willing to [install][oss-cad-suite] them, you can update your profile to set the environment variable `GLASGOW_TOOLCHAIN` to `system,builtin`, which prioritizes using the native tools over the YoWASP tools. The default value is `builtin,system`, which causes the native tools to be used only if the YoWASP tools are unusable.

[yowasp]: https://yowasp.org/
[oss-cad-suite]: https://github.com/YosysHQ/oss-cad-suite-build


### Advanced topic: Developing the Glasgow software

The steps above install the Glasgow software using `pipx install -e`, which performs an _editable install_: changes to the downloaded source code modify the behavior of the next invocation of the `glasgow` tool. Changes to `pyproject.toml`, most importantly to the dependencies or list of applet entrypoints, are not picked up until `pipx reinstall` is manually run.

If you want to have your global Glasgow installation be independent from the source code check-out, you can omit `-e` in the instructions above. You can use any way of managing virtual environments for your development workflow, but we use and recommend [PDM][].

[pdm]: https://pdm.fming.dev/


## How do I factory flash Glasgow?

"Factory flashing" refers to the process of assigning a brand new Glasgow board (that you probably just assembled) a serial number, as well as writing a few critical configuration options that will let the normal Glasgow CLI pick up this device. Barring severe and unusual EEPROM corruption, this process is performed only once for each board.

As a prerequisite to factory flashing, follow all steps from the "[How do I use Glasgow?](#how-do-i-use-glasgow)" section.

Any board that is factory flashed must have a blank FX2_MEM EEPROM. If the FX2_MEM EEPROM is not completely erased (all bytes set to `FF`), the factory flashing process may fail.


### ... with Linux?

Configure your system to allow unprivileged access (for anyone in the `plugdev` group) to any hardware that enumerates as the Cypress FX2 ROM bootloader:

    sudo cp config/99-cypress.rules /etc/udev/rules.d

Note that this udev rule will affect more devices than just Glasgow, since the Cypress VID:PID pair is shared.

Plug in the newly assembled device. At this point, `lsusb | grep 04b4:8613` should list one entry. Assuming you are factory flashing a board revision C2, run:

    glasgow factory --rev C2

Done! At this point, `lsusb | grep 20b7:9db1` should list one entry.


### ... with Windows?

The steps are similar to the steps for Linux above, but you will need to use Zadig to bind the WinUSB driver to the device, since this will not happen automatically with a device that hasn't been flashed yet.


## Who made Glasgow?

  * [@whitequark](https://github.com/whitequark) came up with the design, coordinates the project and implements most of gateware and software;
  * [@awygle](https://github.com/awygle) designed the power/analog port circuitry and helped with layout of revB;
  * [@marcan](https://github.com/marcan) improved almost every aspect of hardware for revC;
  * [@esden](https://github.com/esden) is handling batch manufacturing;
  * [@smunaut](https://github.com/smunaut) provided advice crucial for stability and performance of USB communication;
  * [@electronic_eel](https://github.com/electronic_eel) improved the hardware for revC2, designed the test jig and is working on advanced protection circuitry;
  * [@Attie](https://github.com/attie) improved and refactored many applets;
  * [@mwkmwkmwk](https://github.com/mwkmwkmwk) did important maintenance work to keep the codebase in good shape;
  * ... and many [other people](https://github.com/GlasgowEmbedded/Glasgow/graphs/contributors).


## License

Glasgow is distributed under the terms of both 0-clause BSD license as well as Apache 2.0 license.

See [LICENSE-0BSD](LICENSE-0BSD.txt) and [LICENSE-Apache-2.0.txt](LICENSE-Apache-2.0.txt) for details.
