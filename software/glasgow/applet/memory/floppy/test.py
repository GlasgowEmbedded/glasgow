from ... import *
from . import MemoryFloppyApplet


class MemoryFloppyAppletTestCase(GlasgowAppletV2TestCase, applet=MemoryFloppyApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @applet_v2_simulation_test()
    async def test_command_roundtrip(self, applet, ctx):
        await applet.floppy_iface._sync()

        with self.assertRaisesRegex(ValueError, "between 0 and 159"):
            await applet.floppy_iface.seek_track(160)
