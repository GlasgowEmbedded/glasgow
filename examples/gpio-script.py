from asyncio import sleep

# connect an LED between a ground pin and the nominated pin - make sure that you use a suitable
# I/O voltage and/or current limiting resistor... this sample script will use the I/O pin and
# pull-up resistors to light the LED bright, dim and off

while True:
    await iface.write(0, True)
    for i in range(4):
        await sleep(0.05)
        await iface.toggle(0)
    print("ON!  --> ", await iface.read(0))
    await sleep(1)

    await iface.pull(0, True)
    await iface.write(0, False, False)
    print("DIM! --> ", await iface.read(0))
    await sleep(1)

    await iface.hiz(0)
    print("OFF! --> ", await iface.read(0))
    await sleep(1)
