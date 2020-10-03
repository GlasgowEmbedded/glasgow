Factory Flashing
================

"Factory flashing" refers to the process of assigning a brand new Glasgow board (that you probably just assembled) a serial number, as well as writing a few critical configuration options that will let the normal Glasgow CLI pick up this device. Barring severe and unusual EEPROM corruption, this process is performed only once for each board.

.. warning::

        If an un-flashed Glasgow board is plugged into a Windows machine, Windows will remember the fact that it has no
        WinUSB descriptor, even after it has been flashed, which will prevent it from working on that machine.

        For simplicity, it is more convenient to initially flash Glasgow using a non-Windows host.

As a prerequisite to factory flashing, make sure you have a working Glasgow CLI as described in the README.

Any board that is factory flashed must have a blank `FX2_MEM` EEPROM. If the `FX2_MEM` is not completely erased (all bytes set to `FF`), the factory flashing process may fail.

On Linux, you'll need to configure your system to allow unprivileged access (for anyone in the `plugdev` group) to any hardware that enumerates as the Cypress FX2 ROM bootloader::

    sudo cp config/99-cypress.rules /etc/udev/rules.d

Note that this udev rule will affect more devices than just Glasgow, since the Cypress VID:PID pair is shared.

Plug in the newly assembled device. At this point, `lsusb | grep 04b4:8613` should list one entry. Assuming you are factory flashing a board revision C1, run::

    glasgow factory --rev C1
    glasgow flash

Done! At this point, `lsusb | grep 20b7:9db1` should list one entry.
