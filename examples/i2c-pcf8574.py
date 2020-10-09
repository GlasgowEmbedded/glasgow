"""
An example of a script that can be used with the run-script mode.

This will read and write the pins of a PCF8574. Once connected, run:

    glasgow run-script i2c-pcf8574.py i2c-initiator -V 3.3
"""

# read pin values
print('I/O pin state: 0b{:08b}'.format((await iface.read(0x20, 1))[0]))

# write pin values
await iface.write(0x20, [ 0x55 ])

# power down the device after use
await device.set_voltage("AB", 0)
