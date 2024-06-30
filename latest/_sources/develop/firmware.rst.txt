.. _firmware:

Firmware
========


Introduction
------------

All revisions of the Glasgow hardware include a single ASIC with a CPU that runs firmware: the `Infineon/Cypress CY7C68013A <FX2LP_>`__ chip, also known as "FX2LP" or just "FX2" (which is how it is called in this documentation). It is the de-facto standard ASIC for adding a relatively high-performance (~300 Mbps) USB interface to an FPGA-based system at low cost and without much increase in complexity. This ASIC implements a configurable USB to parallel bus bridge that functions autonomously once configured, and includes an `Intel MCS8051`_ compatible CPU core for configuration and ancillary functions that executes a firmware residing in the internal RAM. The firmware can be loaded from an external I²C EEPROM after power-on reset, or be reloaded by the host PC using a vendor-specific USB request at any time.

The Glasgow hardware relies on this CPU core to perform all of the board management functions, such as loading the FPGA bitstream, configuring the port I/O standard, sensing port voltage and current, configuring pull resistors, and so on. The FPGA solely concerns itself with data processing. Because of its central (and safety-critical) function in the device, the FX2 firmware is of paramount importance, and the way it is managed reflects this fact.

.. _FX2LP: https://www.infineon.com/cms/en/product/universal-serial-bus/usb-2.0-peripheral-controllers/ez-usb-fx2lp-fx2g2-usb-2.0-peripheral-controller/
.. _Intel MCS8051: https://en.wikipedia.org/wiki/Intel_8051


Firmware management
-------------------

The FX2 firmware is considered an integral component of the Glasgow software/hardware stack: it is not end user modifiable or replaceable, does not have an interface that is stable or suitable for use in third-party tools, and is reloaded by the host software without prior consent whenever necessary.

.. note::

    Being open software and open hardware, nothing prevents an end user from modifying, replacing, or interfacing with the firmware. However, the Glasgow project will not in general provide support for running modified firmware, and interfacing third party tools with the firmware directly (by means other than the Python-based software stack) is strongly discouraged at the moment.

The Glasgow hardware includes an EEPROM labelled "FX2_MEM" that stores the factory provisioning information (revision, serial number, etc) as well as the FX2 firmware. In most cases, this EEPROM would have a firmware stored in it at all times (as done by the ``glasgow flash`` command, unless requested otherwise), but this is only an optimization: if the software stack discovers a device plugged in without firmware it will automatically load the firwmare, and if it discovers that the firmware is too old (or too new) to be compatible, it will reload a compatible version of the firmware to RAM (without affecting the stored version).

To ensure that a compatible version of the firmware is available at all times, a built artifact (an Intel HEX file) is checked into the repository as ``software/glasgow/device/firmware.ihex`` and included in the built artifacts (Python wheels) of the Glasgow software. Whenever necessary, this data file is requested via :mod:`importlib.resources` and loaded or flashed. At the moment, whenever the firmware source code is changed, this file is manually built on a developer's machine and committed to the repository.

Currently, the firmware is written to be compatible with every version of the Glasgow hardware ever designed. This simplifies firmware management and to some extent development, eliminating the need for conditional compilation. It is possible that, as functionality is added, this approach will become infeasible and several versions of the firmware will be concurrently built.


Firmware interface
------------------

The interface of the FX2 firmware that is exposed over USB is a critical implementation detail, and it is necessary to ensure that the firmware and the software agree on the exact interface used at all times. This is a common situation, and many FX2-based devices opt to ensure this by (re)loading the firmware each time the driver opens the device. (This also allows them to use the smallest, and cheapest, I²C EEPROM available, only large enough to store the unique USB VID/PID pair.) However, this is not an option for the Glasgow firmware, for two core reasons:

1. It is not possible for a USB device to indicate that its descriptors have changed, so reloading the firmware, in general, requires the device to logically disconnect itself from the USB bus and reconnect back. This adds a delay that can be as high as several seconds, and can interact poorly with virtualization (where manual action may be required to pass a USB device to the VM) or security features (where user consent may be required each time the device is opened).
2. Reloading the firmware, in general, requires the device to be reinitialized, since there is no way to be sure that the previously loaded firmware has left the device in a well-defined state. This will clear the FPGA configuration, disable Vio supply, and otherwise clear volatile state.

The Glasgow software encourages a granular workflow where the ``glasgow`` CLI tool is often invoked many times in quick succession; reloading the firmware on each invocation would be extremely disruptive. Because of this as well as the delivery optimization of having the firmware initially load from the FX2_MEM EEPROM, the firmware interface is versioned, enabling the software stack to reload the firmware only on version mismatch.

The version of the firmware interface is called an "API level", which is an integer (in range of 1 to 255 inclusive) with semantics roughly equivalent to the "major" version in `Semantic Versioning`_ terminology. That is, whenever an incompatible change is made to the firmware interface, the API level is increased by 1; if a backwards-compatible change (that could be as significant as support for a new hardware revision) is made, the API level does not change.

.. note::

    What counts as an "incompatible change" is left to the discretion of maintainers. The usable range of API levels is limited, making it infeasible to increment it every time the firmware is changed at all.

The API level is exposed to the software stack by being placed in the high byte of the ``bcdDevice`` field of the standard USB device descriptor. Since this descriptor is read by the OS during enumeration, it is possible for the software stack to discover the API level of any connected device without accessing it.

.. _Semantic Versioning: https://semver.org


Building firmware
-----------------

The firmware can only be built on a Unix-like system; to develop the firmware on Windows, use `WSL`_. You will need `GNU Make`_ and `sdcc`_ (version 4.0 or newer). To install these, run:

.. tab:: Debian

    .. code:: console

        $ sudo apt install -y --no-install-recommends make sdcc

.. tab:: Arch

    .. code:: console

        $ sudo pacman -Sy make sdcc

.. tab:: Fedora

    .. code:: console

        $ sudo dnf install -y make sdcc

The source code of the chip support library `libfx2`_ used by the firmware is included in the Glasgow repository as a `git submodule`_. Make sure it is checked out at the appropriate revision and compiled:

.. code:: console

    $ git submodule update --init
    $ make -C vendor/libfx2/firmware

Now, build the firmware itself:

.. code:: console

    $ make -C firmware

The freshly built firmware can be unconditionally loaded to a connected device as follows:

.. code:: console

    $ make -C firmware load

Provided the API level matches, the Glasgow software stack will use the device where the firmware was loaded in such a way as-is and not reload the firmware. In the unlikely case of an API level mismatch, the ``glasgow`` tool will print a diagnostic message at the ``WARN`` log level.

.. _WSL: https://learn.microsoft.com/en-us/windows/wsl/install
.. _GNU Make: https://www.gnu.org/software/make/
.. _sdcc: https://sdcc.sourceforge.net/
.. _libfx2: https://github.com/whitequark/libfx2
.. _git submodule: https://git-scm.com/book/en/v2/Git-Tools-Submodules


Deploying firmware
------------------

Building the firmware within the ``firmware/`` subtree does not affect the built firmware artifact used by the software stack, which resides within the ``software/`` subtree. Firmware development can be done in the same repository checkout that is being used for applet development or other everyday use of the device.

Whenever the modified firmware is ready for general use, it must be rebuilt in a reproducible environment (guaranteeing that every developer, as well as our continuous integration system, would produce a bit-for-bit identical binary artifact) and copied to its final location within the ``software/`` subtree. This process is called "deployment".

Deploying the firmware requires `Docker`_ and an internet connection. To deploy the firmware, run:

.. code:: console

    $ ./software/deploy-firmware.sh

Once a modified firmware is deployed, the Glasgow software stack will load this firmware whenever the usual conditions for doing so are met, and loading it manually (with ``make -C firmware load``) is no longer necessary.

.. important::

    When submitting a pull request that changes the firmware source code, be sure to update the built binary artifact, ``software/glasgow/device/firmware.ihex``, in a separate commit that is the very last one in your pull request. (The built binary artifact includes the git revision of the latest modification of the source code in the ``firmware/`` subtree, and it cannot be self-referential.)

    Our continuous integration system will rebuild the firmware from source code and prevent the pull request from being merged unless the freshly built firmware is bit-for-bit identical to the firmware checked into the repository. This automated process ensures that the checked-in binary artifact is trustworthy and reproducible.

.. _Docker: https://docs.docker.com/desktop/