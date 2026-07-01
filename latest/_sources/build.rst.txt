.. _build:

Building hardware
=================

Pre-assembled Glasgow devices and cases are :ref:`available for purchase <purchasing>`. Since Glasgow is open hardware, you also have the option of building a device yourself.

.. attention::

    If you manufacture your own devices from the design files in this repository, you must clearly distinguish the PCBs by modifying the silkscreen artwork such that the placeholder manufacturer name and/or logo are replaced with your own contact information.

    If you use the PCBA design files and the BOM that are included in this repository without modifications (other than the modifications required above), the Glasgow project will provide the same degree of support for your device as it does for the CrowdSupply orders (except for repairs under warranty).

    If you modify the design files (which the license allows you to do without restrictions), the Glasgow project will not in general provide support for such devices, and you must not call your modified devices "Glasgow". You must remove the name "Glasgow" from the PCB silkscreen artwork to ensure that the device is clearly identifiable as being modified from the original source files. You must run ``glasgow factory`` with the ``--using-modified-design-files=yes`` argument when preparing the device, which will appropriately mark the device and change the product name USB descriptor to not include "Glasgow".

    If you are modifying the BOM to replace passive components with equivalent parts from a different vendor (such as in response to shortages), you may call your modified device "Glasgow". In addition, exceptions to the rule above can be made after discussing your case with Catherine "whitequark" or Piotr Esden-Tempski.


.. _assembling:

Assembling a device
-------------------

.. todo::

    This section is not written yet.


.. _factory-flashing:

Factory flashing
----------------

"Factory flashing" refers to the process of assigning a brand new Glasgow board (that you probably just assembled) a serial number, as well as writing a few critical configuration options that will let the ``glasgow`` command use this device. Barring severe and unusual EEPROM corruption, this process is performed only once in the lifetime of a device.

To prepare for factory flashing, follow the :ref:`installation steps <initial-setup>`.

Any board that is being factory flashed must have a blank ``FX2_MEM`` EEPROM. If the ``FX2_MEM`` EEPROM is not completely erased (all bytes set to ``FF``), the factory flashing process may fail.

.. tab:: Linux

    Configure your system to allow unprivileged access for anyone logged in to the physical terminal to any hardware that enumerates as the Cypress FX2 ROM bootloader:

    .. code:: console

        $ sudo cp config/70-cypress.rules /etc/udev/rules.d
        $ sudo udevadm control --reload
        $ sudo udevadm trigger -v -c add -s usb -a idVendor=04b4 -a idProduct=8613

    Note that this rule will allow unprivileged access to any device based on the Cypress FX2 that has a blank EEPROM, and not just the Glasgow hardware specifically.

    Plug in the newly assembled device. At this point, ``lsusb -d 04b4:8613`` should list one entry. Note the revision of the board you are factory flashing. If the board has revision ``C3``, run:

    .. code:: console

        $ glasgow factory --rev C3 --using-modified-design-files=<yes|no>

    That's it! After running this command, the device will disconnect from USB and reconnect, and ``lsusb -d 20b7:9db1`` will list one entry.

.. tab:: Windows

    The steps are similar to the steps for Linux, but you will need to use Zadig to bind the WinUSB driver to the device, since this will not happen automatically with a device that hasn't been flashed yet.

    .. todo::

        Write a full explanation here.

.. tab:: macOS

    Plug in the newly assembled device. At this point, ``System Information.app`` should list the FX2 device with Vid ``04b4`` and Pid ``8613``. Note the revision of the board you are factory flashing. If the board has revision ``C3``, run:

    .. code:: console

        $ glasgow factory --rev C3 --using-modified-design-files=<yes|no>

    That's it! After running this command, the device will disconnect from USB and reconnect, and after refreshing (⌘R) the information in ``System Information.app`` you should see a new entry with Vid ``20b7`` and Pid ``9db1``.