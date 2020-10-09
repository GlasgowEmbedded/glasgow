from glasgow.applet.interface.uart import UARTApplet

# Don't forget to set a new name if you're re-implementing an existing applet!
class CustomUARTApplet(UARTApplet, name="uart-custom"):
    async def interact(self, *args, **kwargs):
        print("Custom UART ready!")
        ret = await super().interact(*args, **kwargs)
        print("Custom UART shutdown...")
        return ret
