from glasgow.arch.qspi import nor
from glasgow.protocol.sfdp import SFDPJEDECEnter4ByteAddressingMethods
from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_hardware_test
from . import Memory25QApplet


class Memory25QAppletTestCase(GlasgowAppletV2TestCase, applet=Memory25QApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    # Flash used for testing: Macronix MX25L6445E
    hardware_args = "-V 3.3"
    dut_jedec_id = (0xc2, 0x2017)
    dut_params = {
        "address_bytes":   3,
        "page_size":       64,
        "opcode_erase_4k": 0x20,
    }

    @staticmethod
    def _deinitialize(applet: Memory25QApplet):
        # pretend we haven't read out SFDP even if we did; this lets preparation code use
        # the full complement of opcodes without affecting the tests
        applet.m25q_iface.cmds = nor.CommandSet()
        applet.m25q_iface.sfdp = None

    @applet_v2_hardware_test(args=hardware_args, mocks=["m25q_iface.qspi"])
    async def test_api_power_cycle(self, applet: Memory25QApplet):
        await applet.m25q_iface.power_up()
        await applet.m25q_iface.power_down()

    async def prepare_common(self, applet: Memory25QApplet):
        await applet.m25q_iface.power_up()
        await applet.m25q_iface.write_status_reg_1(nor.StatusReg1(0))

    @applet_v2_hardware_test(args=hardware_args, mocks=["m25q_iface.qspi"], prepare=prepare_common)
    async def test_api_jedec_id(self, applet: Memory25QApplet):
        self.assertEqual(await applet.m25q_iface.jedec_id(), self.dut_jedec_id)

    @applet_v2_hardware_test(args=hardware_args, mocks=["m25q_iface.qspi"], prepare=prepare_common)
    async def test_api_read_sfdp(self, applet: Memory25QApplet):
        await applet.m25q_iface.read_sfdp(0, 0x100)

    @applet_v2_hardware_test(args=hardware_args, mocks=["m25q_iface.qspi"])
    async def test_api_initialize(self, applet: Memory25QApplet):
        await applet.m25q_iface.initialize()

    _pattern = b"".join(f"{index:08x}".encode() for index in range(0, 0x40000, 8))

    async def prepare_erase(self, applet: Memory25QApplet):
        await self.prepare_common(applet)
        await applet.m25q_iface.initialize()
        await applet.m25q_iface.erase_data(0, 0x80000)
        await applet.m25q_iface.program_data(0, self._pattern)
        self._deinitialize(applet)

    @applet_v2_hardware_test(args=hardware_args, mocks=["m25q_iface.qspi"], prepare=prepare_erase)
    async def test_api_read_data(self, applet: Memory25QApplet):
        applet.m25q_iface.cmds.use_explicit(**self.dut_params) # type:ignore
        await applet.m25q_iface.read_data(0, 0x20000)

    @applet_v2_hardware_test(args=hardware_args, mocks=["m25q_iface.qspi"], prepare=prepare_erase)
    async def test_api_erase_data_all(self, applet: Memory25QApplet):
        applet.m25q_iface.cmds.use_explicit(**self.dut_params) # type:ignore
        await applet.m25q_iface.erase_data_all()
        data = await applet.m25q_iface.read_data(0x00000, 0x10000)
        assert data == b"\xff" * len(data)

    @applet_v2_hardware_test(args=hardware_args, mocks=["m25q_iface.qspi"], prepare=prepare_erase)
    async def test_api_erase_data_4k(self, applet: Memory25QApplet):
        applet.m25q_iface.cmds.use_explicit(**self.dut_params) # type:ignore
        await applet.m25q_iface.erase_data(0x01000, 0x21000)
        data = await applet.m25q_iface.read_data(0x01000, 0x21000)
        assert data == b"\xff" * len(data)
        data = await applet.m25q_iface.read_data(0x00000, 0x1000)
        assert data == self._pattern[0x00000:0x01000]
        data = await applet.m25q_iface.read_data(0x22000, 0x1000)
        assert data == self._pattern[0x22000:0x23000]

    @applet_v2_hardware_test(args=hardware_args, mocks=["m25q_iface.qspi"], prepare=prepare_erase)
    async def test_api_erase_data_sfdp(self, applet: Memory25QApplet):
        await applet.m25q_iface.initialize()
        assert nor.Command.EraseData64K in applet.m25q_iface.cmds
        await applet.m25q_iface.erase_data(0x01000, 0x21000)
        data = await applet.m25q_iface.read_data(0x01000, 0x21000)
        assert data == b"\xff" * len(data)
        data = await applet.m25q_iface.read_data(0x00000, 0x1000)
        assert data == self._pattern[0x00000:0x01000]
        data = await applet.m25q_iface.read_data(0x22000, 0x1000)
        assert data == self._pattern[0x22000:0x23000]

    async def prepare_empty(self, applet: Memory25QApplet):
        await self.prepare_common(applet)
        await applet.m25q_iface.initialize()
        await applet.m25q_iface.erase_data(0, 0x10000)
        self._deinitialize(applet)

    @applet_v2_hardware_test(args=hardware_args, mocks=["m25q_iface.qspi"], prepare=prepare_empty)
    async def test_api_program_data_aligned(self, applet: Memory25QApplet):
        applet.m25q_iface.cmds.use_explicit(**self.dut_params) # type:ignore
        for size, addr in [(64, 0x0000), (1024, 0x1000)]:
            pattern = b"abcd" * (size // 4)
            await applet.m25q_iface.program_data(addr, pattern)
            readback = await applet.m25q_iface.read_data(addr, len(pattern))
            assert pattern == readback

    @applet_v2_hardware_test(args=hardware_args, mocks=["m25q_iface.qspi"], prepare=prepare_empty)
    async def test_api_program_data_unaligned(self, applet: Memory25QApplet):
        applet.m25q_iface.cmds.use_explicit(**self.dut_params) # type:ignore
        for size, addr in [(64, 0x0000), (1024, 0x1000)]:
            pattern = b"abcd" * (size // 4)
            await applet.m25q_iface.program_data(addr + 7, pattern)
            readback = await applet.m25q_iface.read_data(addr, len(pattern) + 14)
            assert b"\xff" * 7 + pattern + b"\xff" * 7 == readback

    async def prepare_write(self, applet: Memory25QApplet):
        await self.prepare_common(applet)
        await applet.m25q_iface.initialize()
        await applet.m25q_iface.erase_data(0, 0x10000)
        await applet.m25q_iface.program_data(0, self._pattern[:0x10000])
        self._deinitialize(applet)

    @applet_v2_hardware_test(args=hardware_args, mocks=["m25q_iface.qspi"], prepare=prepare_write)
    async def test_api_write_data(self, applet: Memory25QApplet):
        applet.m25q_iface.cmds.use_explicit(**self.dut_params) # type:ignore
        for size, addr, offset in [
            (0x1000, 0x0000, 0x0000), # aligned
            (0x1000, 0x4000, 0x0100), # unaligned
        ]:
            overlay = b"abcd" * (size // 4)
            before = await applet.m25q_iface.read_data(addr, addr + size * 2)
            await applet.m25q_iface.write_data(addr + offset, overlay)
            after = await applet.m25q_iface.read_data(addr, addr + size * 2)
            assert before[:offset] + overlay + before[offset + size:] == after

    @applet_v2_hardware_test(args=hardware_args, mocks=["m25q_iface.qspi"], prepare=prepare_common)
    async def test_api_write_status_reg_1(self, applet: Memory25QApplet):
        await applet.m25q_iface.write_status_reg_1(nor.StatusReg1.BP1|nor.StatusReg1.BP2)
        sr1 = await applet.m25q_iface.read_status_reg_1()
        assert sr1 & nor.StatusReg1.BPALL == nor.StatusReg1.BP1|nor.StatusReg1.BP2

    async def prepare_4byte(self, applet: Memory25QApplet):
        await self.prepare_common(applet)
        await applet.m25q_iface.initialize()
        await applet.m25q_iface.erase_data(0, 0x10000)
        self._deinitialize(applet)

    # Flash used for testing: ISSI IS25LP128
    @applet_v2_hardware_test(args="-V 3.3", mocks=["m25q_iface.qspi"], prepare=prepare_4byte)
    async def test_api_4byte_CommandB7h(self, applet: Memory25QApplet):
        await applet.m25q_iface.initialize()
        jedec_params = applet.m25q_iface.jedec_params
        assert (jedec_params and jedec_params.enter_4_byte_addressing &
                                    SFDPJEDECEnter4ByteAddressingMethods.CommandB7h)
        await applet.m25q_iface.program_data(0xf80, bytes(range(256)))
        await applet.m25q_iface.erase_data(0x1000, 0x1000)
        readout = await applet.m25q_iface.read_data(0, 0x2000)
        assert readout == b"\xff" * 0xf80 + bytes(range(128)) + b"\xff" * 0x1000
