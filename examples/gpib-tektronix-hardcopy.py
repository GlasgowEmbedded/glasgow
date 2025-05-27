"""
An example script which can be used with run-script.

This script will request a screen capture from a Tektronix
oscilloscope.

    glasgow script gpib-tektronix-hardcopy.py gpib-controller -V5

"""

address = 10

# await iface.send_to(address, b"HARDCOPY:FORMAT EPSCOLOR")
# await iface.send_to(address, b"HARDCOPY:FORMAT BMPCOLOR")
await iface.send_to(address, b"HARDCOPY:FORMAT TIFF")

await iface.send_to(address, b"HARDCOPY:COMPRESSION 0")
await iface.send_to(address, b"HARDCOPY:LAYOUT LAND")
await iface.send_to(address, b"HARDCOPY:PORT GPIB")
await iface.send_to(address, b"HARDCOPY START")

with open('hardcopy.tiff', 'wb') as f:
    async for b in iface.iter_from(address):
        f.write(b)
