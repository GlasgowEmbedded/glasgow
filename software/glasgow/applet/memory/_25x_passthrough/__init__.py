import logging
from amaranth import *
from amaranth.lib import wiring, io, cdc
from amaranth.lib.wiring import In

from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet import GlasgowAppletV2


__all__ = ["Memory25xPassThroughComponent", "Memory25xPassThroughApplet"]

DIR_1_BIT_ACCESS = 0b1101 # The high bits might operate as WP/HOLD/RESET bits
DIR_2_BIT_READ   = 0b1100 # The high bits might operate as WP/HOLD/RESET bits
DIR_4_BIT_READ   = 0b0000
DIR_2_BIT_WRITE  = 0b1111
DIR_4_BIT_WRITE  = 0b1111

COMMAND_DREAD = 0x3B
COMMAND_2READ = 0xBB
COMMAND_QREAD = 0x6B
COMMAND_4READ = 0xEB
COMMAND_4PP   = 0x38 # Specific to Macronix

COMMAND_WORD_READ_QUAD_IO = 0xE7 # Winbond
COMMAND_OCTAL_WORD_READ_QUAD_IO = 0xE3 # Winbond
# TODO: ^^ E3 may be "Advanced sector protection command" on some other Macronix chips
# Find a chip like that and check for compatibility.
COMMAND_READ_MFR_DEV_ID_DUAL_IO = 0x92 # Winbond
COMMAND_READ_MFR_DEV_ID_QUAD_IO = 0x94 # Winbond
COMMAND_QUAD_INPUT_PAGE_PROGRAM = 0x32 # Winbond
COMMAND_SET_BURST_WITH_WRAP = 0x77 # Winbond
# ^^ On Macronix this is a burst read command and it's not quad I/O but that's not a problem.


class Memory25xPassThroughComponent(wiring.Component):
    reset: In(1)

    def __init__(self, ports, xip_style_winbond: bool, xip_style_macronix: bool,
                 drive_low_nibble_continuous_read_mode:bool,
                 sys_clk_period: float, statistics_led_refresh_hz: float, address_cycles=24):
        self._ports = ports
        self._address_cycles = address_cycles
        self._xip_style_winbond = xip_style_winbond
        self._xip_style_macronix = xip_style_macronix
        self._drive_low_nibble_continuous_read_mode = drive_low_nibble_continuous_read_mode
        self._sys_clk_period = sys_clk_period
        self._statistics_led_refresh_hz = statistics_led_refresh_hz

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        try:
            self.leds = [platform.request("led", n) for n in range(5)]
        except ResourceError:
            self.leds = []

        m.submodules.cs_buffer  = cs_buffer  = io.Buffer("o", self._ports.cs)
        io_buffer = []
        for i in range(len(self._ports.io)):
            m.submodules[f"io_buffer_{i}"] = io_buffer_i  = io.Buffer("io", self._ports.io[i])
            io_buffer.append(io_buffer_i)
        m.submodules.sck_buffer  = sck_buffer  = io.Buffer("o", self._ports.sck)

        m.submodules.ccs_buffer  = ccs_buffer  = io.Buffer("i", self._ports.ccs)
        cio_buffer = []
        for i in range(len(self._ports.cio)):
            m.submodules[f"cio_buffer_{i}"] = cio_buffer_i  = io.Buffer("io", self._ports.cio[i])
            cio_buffer.append(cio_buffer_i)
        m.submodules.csck_buffer  = csck_buffer  = io.Buffer("i", self._ports.csck)

        dir_io_comb = Signal(4)
        m.d.comb += (
            cs_buffer.o.eq(ccs_buffer.i),
            sck_buffer.o.eq(csck_buffer.i)
        )
        for i in range(len(io_buffer)):
            m.d.comb += (
                io_buffer[i].oe.eq(dir_io_comb[i]),
                cio_buffer[i].oe.eq(~dir_io_comb[i]),
                io_buffer[i].o.eq(cio_buffer[i].i),
                cio_buffer[i].o.eq(io_buffer[i].i)
            )

        if platform is not None:
            platform.add_clock_constraint(csck_buffer.i, 96e6)

        m.domains.qspi = cd_qspi = ClockDomain(async_reset=True, local=True)
        m.d.comb += cd_qspi.rst.eq(ccs_buffer.i)
        m.d.comb += cd_qspi.clk.eq(csck_buffer.i)

        m.domains.qspi_i2c_rst = cd_qspi_i2c_rst = ClockDomain(async_reset=True, local=True)
        m.d.comb += cd_qspi_i2c_rst.rst.eq(self.reset)
        m.d.comb += cd_qspi_i2c_rst.clk.eq(csck_buffer.i)

        # A falling edge clock domain really is necessary.
        # There are cases when bus turnaround must happen before the next rising clock
        # edge, and cannot happn on this rising clock edge, or the chip might sample the
        # command, or address wrong.
        m.domains.qspi_b = cd_qspi_b = ClockDomain(async_reset=True, local=True)
        m.d.comb += cd_qspi_b.rst.eq(ccs_buffer.i)
        m.d.comb += cd_qspi_b.clk.eq(~csck_buffer.i)

        bit_cnt = Signal(3)
        m.d.qspi += bit_cnt.eq(bit_cnt + 1)

        command = Signal(8)

        xip_mode = Signal(init=0) # Can only be reset via i2c register
        xip_mode_dual = Signal(reset_less=True)
        xip_mode_data = Signal()

        dir_io_pre = Signal(4, init=DIR_1_BIT_ACCESS)
        dir_io_falling = Signal(4, init=DIR_1_BIT_ACCESS)
        m.d.qspi_b += dir_io_falling.eq(dir_io_pre)

        m.d.comb += dir_io_comb.eq(Mux(xip_mode & ~xip_mode_data,
                                       DIR_4_BIT_WRITE,
                                       dir_io_pre))

        addr_bit_cnt = Signal(range(self._address_cycles))

        p_high = Signal(4)

        sck_samp = Signal()
        m.submodules += cdc.FFSynchronizer(csck_buffer.i, sck_samp)
        cs_samp = Signal()
        m.submodules += cdc.FFSynchronizer(ccs_buffer.i, cs_samp)
        xip_mode_samp = Signal()
        m.submodules += cdc.FFSynchronizer(xip_mode, xip_mode_samp)

        busy = Signal()
        busy_non_xip = Signal()
        busy_xip = Signal()

        sck_samp_ff = Signal()
        m.d.sync += sck_samp_ff.eq(sck_samp)
        m.d.comb += busy.eq((sck_samp != sck_samp_ff) & (cs_samp == 0))
        m.d.comb += busy_non_xip.eq(busy & ~xip_mode_samp)
        m.d.comb += busy_xip.eq(busy & xip_mode_samp)

        STATS_TIMER_CYCLES = int(1 / self._sys_clk_period / self._statistics_led_refresh_hz)
        statistics_timer = Signal(range(STATS_TIMER_CYCLES))
        m.d.sync += statistics_timer.eq(statistics_timer + 1)
        busy_non_xip_latching = Signal()
        busy_xip_latching = Signal()

        m.d.sync += busy_non_xip_latching.eq(busy_non_xip_latching | busy_non_xip)
        m.d.sync += busy_xip_latching.eq(busy_xip_latching | busy_xip)

        with m.If(statistics_timer == STATS_TIMER_CYCLES - 1):
            m.d.sync += statistics_timer.eq(0)
            m.d.sync += busy_non_xip_latching.eq(0)
            m.d.sync += busy_xip_latching.eq(0)
            m.d.sync += self.leds[1].o.eq(busy_non_xip_latching | busy_non_xip)
            m.d.sync += self.leds[3].o.eq(busy_xip_latching | busy_xip)

        m.d.comb += self.leds[2].o.eq(xip_mode)

        with m.FSM(domain="qspi"):
            with m.State("Wait-Command"):
                with m.If(xip_mode):
                    # We're in the wrong state, this clock cycle is actually
                    # transferring the first address bits
                    m.d.qspi += dir_io_pre.eq(DIR_4_BIT_WRITE)
                    m.d.qspi += addr_bit_cnt.eq(1)
                    m.next = "Wait-4READ-Address"
                with m.Else():
                    m.d.qspi += command.eq(Cat(cio_buffer[0].i, command))
                    with m.If(bit_cnt == 7):
                        m.d.qspi += addr_bit_cnt.eq(0)
                        with m.Switch(Cat(cio_buffer[0].i, command)):
                            with m.Case(COMMAND_2READ,
                                        COMMAND_READ_MFR_DEV_ID_DUAL_IO):
                                m.d.qspi += dir_io_pre.eq(DIR_2_BIT_WRITE)
                                m.next = "Wait-2READ-Address"
                            with m.Case(COMMAND_4READ,
                                        COMMAND_WORD_READ_QUAD_IO,
                                        COMMAND_OCTAL_WORD_READ_QUAD_IO,
                                        COMMAND_READ_MFR_DEV_ID_QUAD_IO):
                                m.d.qspi += dir_io_pre.eq(DIR_4_BIT_WRITE)
                                m.next = "Wait-4READ-Address"
                            with m.Case(COMMAND_DREAD):
                                m.next = "Wait-DREAD-Address"
                            with m.Case(COMMAND_QREAD):
                                m.next = "Wait-QREAD-Address"
                            with m.Case(COMMAND_4PP,
                                        COMMAND_QUAD_INPUT_PAGE_PROGRAM,
                                        COMMAND_SET_BURST_WITH_WRAP):
                                m.d.qspi += dir_io_pre.eq(DIR_4_BIT_WRITE)
                                m.next = "Wait-Cs-Deassert"
                            with m.Default():
                                m.next = "Wait-Cs-Deassert"
            with m.State("Wait-2READ-Address"):
                m.d.qspi += addr_bit_cnt.eq(addr_bit_cnt + 1)
                with m.If(addr_bit_cnt == self._address_cycles // 2 - 1):
                    m.d.qspi += xip_mode_dual.eq(1)
                    m.next = "Wait-XIP-mode-bits-high"
            with m.State("Wait-4READ-Address"):
                m.d.qspi += addr_bit_cnt.eq(addr_bit_cnt + 1)
                with m.If(addr_bit_cnt == self._address_cycles // 4 - 1):
                    m.d.qspi += xip_mode_dual.eq(0)
                    m.next = "Wait-XIP-mode-bits-high"
            with m.State("Wait-XIP-mode-bits-high"):
                # Read P[7:4] bits, a.k.a. Read M[7:4]
                p_high_nxt = Cat(*[item.i for item in cio_buffer])
                m.d.qspi += p_high.eq(p_high_nxt)
                if self._xip_style_winbond and not self._drive_low_nibble_continuous_read_mode:
                    m.d.qspi_i2c_rst += xip_mode.eq(p_high_nxt & 3 == 0b10)
                    m.d.qspi += xip_mode_data.eq(1)
                    m.d.qspi += dir_io_pre.eq(Mux(xip_mode_dual, DIR_2_BIT_READ, DIR_4_BIT_READ))
                    m.next = "Wait-Cs-Deassert"
                else:
                    m.next = "Wait-XIP-mode-bits-low"
            with m.State("Wait-XIP-mode-bits-low"):
                # Read P[3:0] bits, a.k.a. Read M[3:0]
                if self._xip_style_winbond:
                    m.d.qspi_i2c_rst += xip_mode.eq(p_high & 3 == 0b10)
                elif self._xip_style_macronix:
                    # Macronix performance enhance mode
                    m.d.qspi_i2c_rst += xip_mode.eq(
                        (p_high ^ Cat(*[item.i for item in cio_buffer])) == 0xf)
                m.d.qspi += xip_mode_data.eq(1)
                m.d.qspi += dir_io_pre.eq(Mux(xip_mode_dual, DIR_2_BIT_READ, DIR_4_BIT_READ))
                m.next = "Wait-Cs-Deassert"
            with m.State("Wait-DREAD-Address"):
                m.d.qspi += addr_bit_cnt.eq(addr_bit_cnt + 1)
                with m.If(addr_bit_cnt == self._address_cycles - 1):
                    dir_io_pre.eq(DIR_2_BIT_READ)
                    m.next = "Wait-Cs-Deassert"
            with m.State("Wait-QREAD-Address"):
                m.d.qspi += addr_bit_cnt.eq(addr_bit_cnt + 1)
                with m.If(addr_bit_cnt == self._address_cycles - 1):
                    m.d.qspi += dir_io_pre.eq(DIR_4_BIT_READ)
                    m.next = "Wait-Cs-Deassert"
            with m.State("Wait-Cs-Deassert"):
                pass

        return m


class Memory25xPassThroughInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 cs: GlasgowPin, sck: GlasgowPin, io: GlasgowPin,
                 ccs: GlasgowPin, csck: GlasgowPin, cio: GlasgowPin,
                 xip_style_winbond: bool, xip_style_macronix: bool,
                 drive_low_nibble_continuous_read_mode: bool):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(cs=cs, sck=sck, io=io,
                                        ccs=ccs, csck=csck, cio=cio)
        component = assembly.add_submodule(Memory25xPassThroughComponent(ports,
            xip_style_winbond=xip_style_winbond, xip_style_macronix=xip_style_macronix,
            drive_low_nibble_continuous_read_mode = drive_low_nibble_continuous_read_mode,
            sys_clk_period=assembly.sys_clk_period, statistics_led_refresh_hz=25))
        self._reset = assembly.add_rw_register(component.reset)

    def _log(self, message, *args):
        self._logger.log(self._level, "Memory25xPassThrough: " + message, *args)

    async def reset(self):
        self._log("Resetting xip_mode status, as requested")
        await self._reset.set(1)
        await self._reset.set(0)


class Memory25xPassThroughApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "pass through 25-series SPI Flash transactions"
    description = """
    Pass through transactions from an external controller to memories compatible with 25-series
    Flash memory, such as Winbond W25Q80DVUXIE and Macronix MX25L6436F, or hundreds of other
    memories that typically have "25X" where X is a letter in their part number.

    This applet is intended to be used when it's not possible to reprogram the SPI Flash chip
    in-circuit (mostly for electrical reasons, i.e. many other devices powered by the same power
    rail and no series diode present that would otherwise isolate the flash memory.). In this
    situation the user is forced to remove the memory and reprogram it outside of the circuit.
    If many cycles of reprogramming and testing are necessary, then it becomes really tedious to
    move the SPI flash chip in and out of its intended circuit. This applet helps with that
    problem, by connecting up both controller and target to the Glasgow. When the memory has to be
    reprogrammed, one can use the `memory-25x` applet, after which this applet can be started,
    to allow the original device under test to access the memory.

    25-series flash memories don't follow a single standard, and have many differences between
    them, and this applet needs to know some of the differences between them, especially when it
    comes to switching to 2-bit or 4-bit data transfer modes, because it needs to be able to
    correctly set IO pin directions, and at the right time. For this reason, this applet may not
    be compatible with all the 25-series Flash memories supported by the `memory-25x` applet.

    The pinout of a typical 25-series IC is as follows:

    ::

                16-pin                     8-pin
        IO3/HOLD# @ * SCK               CS# @ * VCC
              VCC * * IO0/COPI     IO1/CIPO * * IO3/HOLD#
              N/C * * N/C           IO2/WP# * * SCK
              N/C * * N/C               GND * * IO0/COPI
              N/C * * N/C
              N/C * * N/C
              CS# * * GND
         IO1/CIPO * * IO2/WP#

    The default pin assignment follows the pinouts above in the clockwise direction, on port A,
    making it easy to connect the memory with probes or, alternatively, crimp an IDC cable wired
    to a SOIC clip. The name of the memory-side pin arguments match the names of the `memory-25x`
    applet pin arguments, and the default pin assignment matches as well to allow for easy
    switching between the applets. The pin names that start with an additional "c" are the
    controller-side pins, they default to port B, matching the pinout of the target on port A.
    The memory-side default pin assignments also match the default pin assignments for the
    `spi-flashrom` applet, however the pin argument names are not compatible.

    Three leds are configured as such:
    - U2 = busy in non-xip mode
    - U3 = currently in xip mode
    - U4 = busy in non-xip mode

    The busy leds latch on for at least 25ms, to make it easier to observe when only sporadic
    traffic is present.

    Please note that although the logic in this applet may be able to run at high clock
    frequencies, the overall system clock frequency achievable may be limited because of
    propagation time through the Glasgow, which has to be observed twice: First the SCK falling
    edge has to pass through the Glasgow from the controller to the memory, and then the memory
    outputs data in response to that which has to pass back through the Glasgow to the controller.
    On one glasgow a single propagation delay has been measured as 9ns. This may be different on
    other Glasgows. To this 2*9ns delay other system delays have to be added, such as memory
    clock-to-output delay, controller setup time, and other system delays, and all of it has to
    fit into half an SCK clock cycle, because the controller samples data on the rising edge.
    The clocks' duty cycle also has an effect. The exact maximum frequency is hard to predict,
    but you can estimate it using this equation: `1000MHz / (2 * 9ns + additional_delays_ns) / 2`

    Some controllers support a feature that allows delaying the sampling of input signals. This
    feature is called `offset` in glasgow's qspi controller, and the Raspberry Pi RP2040 micro-
    controller calls it `RX_SAMPLE_DLY`. If this feature is enabled, then higher clock frequencies
    can be achieved. The equation looks like this, when a sample delaying feature is enabled:
    `1000MHz / (2 * 9ns + additional_delays_ns - sample_delay_ns) / 2`

    Examples of working/non-working systems and configurations this has been tested on:
    - On a RP2040 test jig, with Winbond W25Q80DVUXIE memory, running a system clock running at
      125MHz when fully up and running (except when stated otherwise):
      - Works: SCLK=15.62MHz RX_SAMPLE_DLY=1 (resulting in 8ns sample delay @ clk_sys=125MHz) -
        the default second-stage bootloader has a hardcoded RX_SAMPLE_DLY=1
      - Fails: SCLK=20.83MHz RX_SAMPLE_DLY=1 (resulting in 8ns sample delay @ clk_sys=125MHz) -
        the default second-stage bootloader has a hardcoded RX_SAMPLE_DLY=1
      - Works: SCLK=20.83MHz RX_SAMPLE_DLY=2 (resulting in 16ns sample delay @ clk_sys=125MHz) -
        the second state bootloader was modified to force RX_SAMPLE_DLY=2
      - Fails: SCLK=31.25MHz RX_SAMPLE_DLY=2 (resulting in 16ns sample delay @ clk_sys=125MHz) -
        the second state bootloader was modified to force RX_SAMPLE_DLY=2
      - Works: SCLK=31.25MHz RX_SAMPLE_DLY=3 (resulting in 24ns sample delay @ clk_sys=125MHz) -
        This sample delay is longer than half a SCLK clock cycle. Because on the RP2040 platform
        the SSI controller is clocked from the system clock, and the sample delay is configured
        in number of system clock cycles, when the system is running at slower speeds (such as
        during initialization), the actual sample delay will be a lot larger than 24ns, and this
        can cause us to sample the signal too late. This introduces a minimum clock frequency
        constraint too. To check that this example works, the bootloader was configured to only
        SCLK=15.62MHz, and then the speed was raised later on in software, when the system clock
        was up and running.
      - Fails: SCLK=62.5MHz RX_SAMPLE_DLY=3 (resulting in 24ns sample delay @ clk_sys=125MHz)
      - Works: SCLK=62.5MHz RX_SAMPLE_DLY=4 (resulting in 32ns sample delay @ clk_sys=125MHz) -
        this also results in a minimum clock frequency requirement, so extreme care should be taken
        for the system to not lower its clock frequency after the sample delay is set to 4 system
        clock cycles.
      - Fails: SCLK=15.62MHz RX_SAMPLE_DLY=0 (resulting in 0ns sample delay) - the second stage
        bootloader was modified to force RX_SAMPLE_DLY=0
      - Works: SCLK=15.50MHz RX_SAMPLE_DLY=0 (resulting in 0ns sample delay) - the second stage
        bootloader was modified to force RX_SAMPLE_DLY=0, and the pico-sdk was edited to set a
        system clock of 124MHz
      - Works: SCLK=77.50MHz RX_SAMPLE_DLY=4 (resulting in 25.8ns sample delay) - this was achieved
        with a second stage bootloader dividing down the system clock by 8, and a sample delay of
        4, in order to not fail when the system clock is configured to be higher, and the pico-sdk
        was edited to set a system clock of 155MHz
      - according to these results the additional delay of this test jig must be between
        14.0..14.3ns
      - The maximum sample delay supported by the RP2050 is 4 sysclk cycles, and the SCK frequency
        is also derived from the system clock. For this reason it's not possible to achieves higher
        that 77.5MHz on this test jig. (When trying to set a sample delay of 5, the RP2040 just
        seems to behave as if the sample delay was 0). Higher speeds may be possible with this
        applet, if a different controller has more control over the sampling delay.
    """
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        # The target-side interface should match argument names and defaults for the memory-25x
        # applet
        access.add_pins_argument(parser, "cs",  required=True,          default="A5")
        access.add_pins_argument(parser, "io",  required=True, width=4, default="A2,A4,A3,A0",
            help="bind the applet I/O lines 'copi', 'cipo', 'wp', 'hold' to PINS")
        access.add_pins_argument(parser, "sck", required=True,          default="A1")
        # There are more pins needed than 1 port can handle so let's use symmetric defaults on
        # the B side for the controller-side interface:
        access.add_pins_argument(parser, "ccs",  required=True,          default="B5")
        access.add_pins_argument(parser, "cio",  required=True, width=4, default="B2,B4,B3,B0",
            help="bind the applet I/O lines 'copi', 'cipo', 'wp', 'hold' to PINS")
        access.add_pins_argument(parser, "csck", required=True,          default="B1")

        parser.add_argument(
            "-W", "--xip-style-winbond", action="store_true",
            help="React to Winbond-style XIP requests. i.e. we go into XIP mode when M[5:4]=0b10")
        parser.add_argument(
            "-M", "--xip-style-macronix", action="store_true",
            help="React to Macronix-style XIP requests. i.e. we go into XIP mode when "
                 "M[7:4]^M[3:0]==0xf")
        parser.add_argument(
            "-d", "--drive-low-nibble-continuous-read-mode", action="store_true",
            help="The low nibble of winbond-style Continuous Read/eXecute-In-Place mode bits is "
                 "don't care. So the default is to not drive the lower nibble")

    def build(self, args):
        with self.assembly.add_applet(self):
            assert not(args.xip_style_winbond and args.xip_style_macronix), \
                "Cannot have both xip styles supported at the same time"
            if args.drive_low_nibble_continuous_read_mode:
                assert args.xip_style_winbond, "Must specify --xip-style-winbond to not drive " \
                    "low nibble"
            self.assembly.use_voltage(args.voltage)
            self.assembly.use_pulls({args.cs: "high"})
            self.memory_25x_passthrough_iface = Memory25xPassThroughInterface(
                self.logger,self.assembly,
                cs=args.cs, sck=args.sck, io=args.io, ccs=args.ccs, csck=args.csck, cio=args.cio,
                xip_style_winbond=args.xip_style_winbond,
                xip_style_macronix=args.xip_style_macronix,
                drive_low_nibble_continuous_read_mode=args.drive_low_nibble_continuous_read_mode)

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "-r", "--reset", action="store_true",
            help="Reset the xip_mode status.")

    async def run(self, args):
        if args.reset:
            await self.memory_25x_passthrough_iface.reset()

    @classmethod
    def tests(cls):
        from . import test
        return test.Memory25xPassThroughAppletTestCase
