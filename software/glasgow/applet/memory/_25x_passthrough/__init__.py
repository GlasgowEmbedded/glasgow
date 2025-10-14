import logging
from amaranth import *
from amaranth.lib import wiring, io, cdc
from amaranth.lib.wiring import In

from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet import GlasgowAppletV2
from collections import namedtuple


__all__ = ["Memory25xPassThroughComponent", "Memory25xPassThroughApplet"]

DIR_1_BIT_ACCESS = 0b1101 # The high bits might operate as WP/HOLD/RESET bits
DIR_2_BIT_READ   = 0b1100 # The high bits might operate as WP/HOLD/RESET bits
DIR_4_BIT_READ   = 0b0000
DIR_2_BIT_WRITE  = 0b1111
DIR_4_BIT_WRITE  = 0b1111

Phase = namedtuple("Phase",
                   "cycles direction xip_mode_bits")
# cycles=None means repeat until CS deassertion

Command = namedtuple("Command",
                     "code name")

chips = {
    "mx25l6436f" : {
        "continuous_read": lambda high, low: high ^ low == 0xff,
        "commands": {
            Command(0x3B, "DREAD"): [
                Phase(24,   DIR_1_BIT_ACCESS, False),
                Phase(None, DIR_2_BIT_READ,   False),
            ],
            Command(0x6B, "QREAD"): [
                Phase(24,   DIR_1_BIT_ACCESS, False),
                Phase(None, DIR_4_BIT_READ  , False),
            ],
            Command(0x38, "4PP"): [
                Phase(None, DIR_4_BIT_WRITE,  False),
            ],
            Command(0xBB, "2READ"): [
                Phase(12,   DIR_2_BIT_WRITE,  False),
                Phase(2,    DIR_2_BIT_WRITE,  False),
                    # ^^ XIP not supported for 2READ
                Phase(None, DIR_2_BIT_READ,   False),
            ],
            Command(0xEB, "4READ"): [
                Phase(6,    DIR_4_BIT_WRITE,  False),
                Phase(2,    DIR_4_BIT_WRITE,  True ),
                Phase(None, DIR_4_BIT_READ,   False),
            ],
        },
    },
    "w25q80dv": {
        "continuous_read": lambda high, low: high & 3 == 0b10,
        "allowed_to_not_drive_second_nibble_of_mode_bits": True,
        "commands": {
            Command(0x3B, "Fast Read Dual Output"): [
                Phase(24,   DIR_1_BIT_ACCESS, False),
                Phase(None, DIR_2_BIT_READ,   False),
            ],
            Command(0x6B, "Fast Read Quad Output"): [
                Phase(24,   DIR_1_BIT_ACCESS, False),
                Phase(None, DIR_4_BIT_READ  , False),
            ],
            (Command(0xBB, "Fast Read Dual I/O"),
             Command(0x92, "Read Manufacturer / Device ID Dual I/O")): [
                Phase(12,   DIR_2_BIT_WRITE,  False),
                Phase(2,    DIR_2_BIT_WRITE,  True),
                Phase(None, DIR_2_BIT_READ,   False),
            ],
            (Command(0xEB, "Fast Read Quad I/O"),
             Command(0xE7, "Word Read Quad I/O"),
             Command(0xE3, "Octal Word Read Quad I/O"),
             Command(0x94, "Read Manufacturer / Device ID Quad I/O")): [
                Phase(6,    DIR_4_BIT_WRITE,  False),
                Phase(2,    DIR_4_BIT_WRITE,  True ),
                Phase(None, DIR_4_BIT_READ,   False),
            ],
            (Command(0x32, "Quad Input Page Program"),
             Command(0x77, "Set Burst with Wrap")): [
                Phase(None, DIR_4_BIT_WRITE,  False),
            ],
        },
    },
}


class Memory25xPassThroughComponent(wiring.Component):
    reset: In(1)

    def __init__(self, ports, chip_spec:dict,
                 drive_second_nibble_continuous_read_mode:bool,
                 sys_clk_period: float, statistics_led_refresh_hz: float, address_cycles=24):
        self._ports = ports
        self._address_cycles = address_cycles
        self._chip_spec = chip_spec
        self._skip_second_nibble = False
        if "allowed_to_not_drive_second_nibble_of_mode_bits" in chip_spec and \
           chip_spec["allowed_to_not_drive_second_nibble_of_mode_bits"] and \
           not drive_second_nibble_continuous_read_mode:
            self._skip_second_nibble = True

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

        def get_commands(commands):
            if type(commands) is Command:
                commands = (commands,)
            codes = [command.code for command in commands]
            codes_str = "_".join([f"{code:02x}h" for code in codes])
            return codes, codes_str

        xip_submodes = {}
        for commands, phases in self._chip_spec["commands"].items():
            codes, codes_str = get_commands(commands)
            for phase_ind in range(len(phases)):
                if phases[phase_ind].xip_mode_bits:
                    xip_submodes[codes_str] = (
                        Signal(name=f"xip_submode_cmd_{codes_str}", reset_less=True),
                        f"Command_{codes_str}_phase_0")
                    break

        with m.FSM(domain="qspi"):
            with m.State("Wait-Command"):
                with m.If(xip_mode):
                    # We're in the wrong state, this clock cycle is actually
                    # transferring the first address bits
                    m.d.qspi += dir_io_pre.eq(DIR_4_BIT_WRITE)
                    m.d.qspi += addr_bit_cnt.eq(1)
                    for xip_submode in xip_submodes.values():
                        with m.If(xip_submode[0]):
                            m.next = xip_submode[1]
                with m.Else():
                    m.d.qspi += command.eq(Cat(cio_buffer[0].i, command))
                    with m.If(bit_cnt == 7):
                        m.d.qspi += addr_bit_cnt.eq(0)
                        with m.Switch(Cat(cio_buffer[0].i, command)):
                            for commands, phases in self._chip_spec["commands"].items():
                                codes, codes_str = get_commands(commands)
                                with m.Case(*codes):
                                    m.d.qspi += dir_io_pre.eq(phases[0].direction)
                                    if len(phases) == 1:
                                        assert phases[0].cycles is None
                                        m.next = "Wait-Cs-Deassert"
                                    else:
                                        m.next = f"Command_{codes_str}_phase_0"
                            with m.Default():
                                m.next = "Wait-Cs-Deassert"
            for commands, phases in self._chip_spec["commands"].items():
                _, codes_str = get_commands(commands)
                for phase_ind in range(len(phases) - 1):
                    with m.State(f"Command_{codes_str}_phase_{phase_ind}"):
                        m.d.qspi += addr_bit_cnt.eq(addr_bit_cnt + 1)
                        if phases[phase_ind].xip_mode_bits:
                            m.d.qspi += xip_submodes[codes_str][0].eq(1)
                            m.d.qspi += p_high.eq(Cat(*[item.i for item in cio_buffer]))
                        with m.If(1 if self._skip_second_nibble and phases[phase_ind].xip_mode_bits
                                    else addr_bit_cnt == phases[phase_ind].cycles - 1 ):
                            if phases[phase_ind].xip_mode_bits:
                                if not self._skip_second_nibble:
                                    m.d.qspi_i2c_rst += xip_mode.eq(
                                        self._chip_spec["continuous_read"](
                                            p_high, Cat(*[item.i for item in cio_buffer])))
                                else:
                                    m.d.qspi_i2c_rst += xip_mode.eq(
                                        self._chip_spec["continuous_read"](
                                            Cat(*[item.i for item in cio_buffer]), None))
                            m.d.qspi += xip_mode_data.eq(1)
                            m.d.qspi += dir_io_pre.eq(phases[phase_ind + 1].direction)
                            if phase_ind == len(phases) - 2:
                                assert phases[phase_ind + 1].cycles is None
                                m.next = "Wait-Cs-Deassert"
                            else:
                                m.d.qspi += addr_bit_cnt.eq(0)
                                m.next = f"Command_{codes_str}_phase_{phase_ind + 1}"
            with m.State("Wait-Cs-Deassert"):
                pass

        return m


class Memory25xPassThroughInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 cs: GlasgowPin, sck: GlasgowPin, io: GlasgowPin,
                 ccs: GlasgowPin, csck: GlasgowPin, cio: GlasgowPin,
                 chip_spec: dict, drive_second_nibble_continuous_read_mode: bool):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(cs=cs, sck=sck, io=io,
                                        ccs=ccs, csck=csck, cio=cio)
        component = assembly.add_submodule(Memory25xPassThroughComponent(ports, chip_spec=chip_spec,
            drive_second_nibble_continuous_read_mode=drive_second_nibble_continuous_read_mode,
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

    Examples of systems and configurations this has been tested on:
    - On a RP2040 test jig, with Winbond W25Q80DVUXIE memory, running a system clock running at
      125MHz when fully up and running (except when stated otherwise). This system has an
      `additional_delay_ns` of about 14.0..14.3ns.:
      - SCLK=30MHz Can be achieved by setting clk_sys to 60MHz, PICO_FLASH_SPI_CLKDIV=2. Note
        that the the 2nd stage bootloader configures an RX_SAMPLE_DLY of 1 system clock cycle,
        that is why this frequency works correctly.
      - SCLK=77MHz Can be achieved by setting clk_sys to 154MHz, PICO_FLASH_SPI_CLKDIV=2, and
        using RX_SAMPLE_DLY=4. However note that this sample delay is larger then half an SCLK
        clock cycle, which means that in this mode there is now a minimum clock frequency
        constraint as well, i.e. the system clock must not be slower than around 110MHz, so care
        must be taken that the application does not use dynamic frequency scaling, and it doesn't
        reinitialize the system clock after the SPI has been switched to this speed. This speed
        needed two two software tweaks to make it possible:
        - for the normal second stage bootloader a setting of PICO_FLASH_SPI_CLKDIV=8 was used,
          (keeping the original RX_SAMPLE_DLY=1) that it sets. This was necessary, for the SPI
          interface to operate correctly when the system clock switches to 154MHz.
        - When making non-xip memory accesses, the pico-sdk calls into a copy of the second stage
          bootloader to restart xip-mode. The pico-sdk code was hacked to use a different
          second stage bootloader to restore xip mode that would use PICO_FLASH_SPI_CLKDIV=2, and
          RX_SAMPLE_DLY=4. Then a routine was written to exit XIP mode, and re-enter it, while
          doing nothing else. This was called after configuring the pll.
        - The system must not ever reduce the speed the system clock without also returning the
          SPI_CLKDIV to 8.
      - The maximum sample delay supported by the RP2050 is 4 sysclk cycles, and the SCK frequency
        is also derived from the system clock. For this reason it's not possible to achieve higher
        than 77MHz on this test jig. (When trying to set a sample delay of 5, the RP2040 just
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

        parser.add_argument("--chip", choices = chips.keys(), required=True,
                            help="Select compatible chip type")

        parser.add_argument("-d", "--drive-second-nibble-continuous-read-mode", action="store_true",
                            help="The second nibble of some Continuous Read/eXecute-In-Place mode "
                            "bits is don't care. So for those chips, the default is to not drive "
                            "the lower nibble")

    def build(self, args):
        with self.assembly.add_applet(self):
            chip_spec = chips[args.chip]
            if args.drive_second_nibble_continuous_read_mode:
                if "allowed_to_not_drive_second_nibble_of_mode_bits" not in chip_spec or \
                   not chip_spec["allowed_to_not_drive_second_nibble_of_mode_bits"]:
                    assert False, "This chip does not allow to skip driving the second nibble"

            self.assembly.use_voltage(args.voltage)
            self.assembly.use_pulls({args.cs: "high"})
            self.memory_25x_passthrough_iface = Memory25xPassThroughInterface(
                self.logger,self.assembly,
                cs=args.cs, sck=args.sck, io=args.io, ccs=args.ccs, csck=args.csck, cio=args.cio,
                chip_spec=chip_spec,
                drive_second_nibble_continuous_read_mode=
                    args.drive_second_nibble_continuous_read_mode)

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
