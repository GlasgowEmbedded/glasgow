Known Issues
============

Device Not Found
----------------

If Glasgow is connected to the system, appears in ``dmesg`` and ``/sys/bus/usb/...``, but is not listed when using ``glasgow list`` or ``lsusb``, you may have run into a bug in libusb v1.0.24, see `libusb#825 <https://github.com/libusb/libusb/issues/825>`_.
