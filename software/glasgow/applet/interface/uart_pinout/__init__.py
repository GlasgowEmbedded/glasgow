import asyncio
import logging

from amaranth import Module, Mux, Signal, Cat, Const, unsigned
from amaranth.lib import stream, enum, io, wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import In, Out

from glasgow.abstract import GlasgowPin
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2
from glasgow.gateware.uart import UART

# This should be able to hold most sensible values
MAX_BAUD_WIDTH = 32
# Keep sorted
_DEFAULT_BAUDS = [
    9600,
    19200,
    38400,
    57600,
    115200,
    230400,
    460800,
    921600,
]


class _Parity(enum.Enum, shape=unsigned(2)):
    NoParity = 0x00
    Even = 0x01
    Odd = 0x02


class ModifiableUARTBus(wiring.Component):
    """
    This class will expose the same interface as the UARTBus over in gateware,
    but we just use Signals instead of ports since we're iterating over the
    ports. Essentially the UART that uses this bus will be reading from
    different pins at different times but always be using the same input/
    output
    """

    def __init__(self, ports):

        self._ports = ports
        pincount = len(ports.pins)

        super().__init__(
            {
                # Leave all OE at 0 when this isn't enabled
                "i_enable": In(1),
                # Masks are used to select the pins for rx/tx
                "i_tx_mask": In(pincount),
                "i_rx_mask": In(pincount),
            }
        )

        self.pin_values = Signal(pincount)

        # Implement UARTBus over in gateware, these fields are expected
        self.rx_i = Signal(1)
        self.has_rx = True
        self.tx_o = Signal(1, init=1)
        self.has_tx = True

    def elaborate(self, platform):
        m = Module()

        pins = []

        for i, port in enumerate(self._ports.pins):
            m.submodules[f"pins{i}_buffer"] = pin = io.Buffer("io", port)
            pins.append(pin)

        pincount = len(pins)

        self.pin_values = Signal(pincount)
        m.submodules += FFSynchronizer(Cat(pin.i for pin in pins), self.pin_values)

        # TXOE will be used for the pin .oe values: setting a bit in TXOE enables
        # the output on that bit. We use tx_mask to set the bit.
        txoe = Signal(pincount)
        # TX will be used to set the .o values. We basically just track tx_bit
        # with this and use TXOE to determine which one should actually be enabled
        tx = Signal(pincount)

        m.d.comb += [
            Cat(pin.oe for pin in pins).eq(txoe),
            Cat(pin.o for pin in pins).eq(tx),
        ]

        m.d.comb += self.rx_i.eq(
            ((self.pin_values & self.i_rx_mask) != 0) | (self.i_rx_mask == 0)
        )

        ALL_PINS_HIGH = Const((1 << pincount) - 1, shape=tx.shape())
        ALL_PINS_LOW = Const(0, shape=tx.shape())

        # tx is based on tx_o and the mask when enabled, note that we control
        # .oe in the next line, so even though we're setting all pins not all
        # have output enabled
        m.d.comb += tx.eq(
            Mux(
                self.i_enable,
                Mux(self.tx_o, ALL_PINS_HIGH, ALL_PINS_LOW),
                ALL_PINS_HIGH,
            )
        )

        # txoe will only enable a pin when we are enabled, otherwise disable everything
        m.d.comb += txoe.eq(Mux(self.i_enable, self.i_tx_mask, ALL_PINS_LOW))

        return m


class UARTPinoutComponent(wiring.Component):
    baud_ticks: In(MAX_BAUD_WIDTH)
    nstopbits: In(4)
    enable: In(1)
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    def __init__(self, ports, parity=_Parity.NoParity):
        super().__init__()
        self.bus = ModifiableUARTBus(ports)

        self.parity = (
            "none"
            if parity == _Parity.NoParity
            else ("even" if parity == _Parity.Even else "odd")
        )

        npins = len(ports.pins)

        self.rx_mask = Signal(npins)
        self.tx_mask = Signal(npins)

    def elaborate(self, platform):

        m = Module()

        m.submodules.internal_uart = uart = UART(
            self.bus, _DEFAULT_BAUDS[-1], parity=self.parity
        )

        m.d.comb += [
            self.bus.i_enable.eq(self.enable),
            self.bus.i_rx_mask.eq(self.rx_mask),
            self.bus.i_tx_mask.eq(self.tx_mask),
            uart.bit_cyc.eq(self.baud_ticks),
            uart.tx_data.eq(self.i_stream.payload),
            uart.tx_ack.eq(self.i_stream.valid),
            self.i_stream.ready.eq(uart.tx_rdy),
            self.o_stream.payload.eq(uart.rx_data),
            self.o_stream.valid.eq(uart.rx_rdy),
            uart.rx_ack.eq(self.o_stream.ready),
        ]

        return m


class UARTPinoutInterface:
    def __init__(self, logger, assembly, *, pins, data=b"\x0d", rx_delay_sec=0.05):
        self._logger = logger
        self._sys_clk_period = assembly.sys_clk_period
        self._trace(f"sys_clk_period[{self._sys_clk_period}]")

        self._ports = ports = assembly.add_port_group(pins=pins)
        assembly.use_pulls({pins: "high"})
        self._component = component = assembly.add_submodule(UARTPinoutComponent(ports))

        self._rx_delay_sec = rx_delay_sec
        self._data = data

        self._rrx_mask = assembly.add_rw_register(component.rx_mask)
        self._rtx_mask = assembly.add_rw_register(component.tx_mask)
        self._renable = assembly.add_rw_register(component.enable)
        self._rbaud_ticks = assembly.add_rw_register(component.baud_ticks)
        # self._rparity = assembly.add_rw_register(component.parity)
        self._rnstopbits = assembly.add_rw_register(component.nstopbits)

        self._pipe = assembly.add_inout_pipe(
            component.o_stream,
            component.i_stream,
        )

    def _log(self, lvl, msg, *args):
        self._logger.log(lvl, "uart-pinout: " + msg, *args)

    def _dbg(self, msg, *args):
        self._log(logging.DEBUG, msg, *args)

    def _err(self, msg, *args):
        self._log(logging.ERROR, msg, *args)

    def _warn(self, msg, *args):
        self._log(logging.WARN, msg, *args)

    def _trace(self, msg, *args):
        self._log(logging.TRACE, msg, *args)

    def _info(self, msg, *args):
        self._log(logging.INFO, msg, *args)

    def set_rx_delay_ms(self, ms):
        self._rx_delay_sec = ms / 1000.0

    def set_data(self, data):
        self._data = data

    async def set_rx_pin(self, rx):
        self._dbg(f"Setting RX pin to {rx}")
        await self._rrx_mask.set(1 << rx)

    async def set_tx_pin(self, tx):
        self._dbg(f"Setting TX pin to {tx}")
        await self._rtx_mask.set(1 << tx)

    # async def set_parity(self, parity):
    #    await self._rparity.set(parity.value)

    async def set_nstopbits(self, nstopbits):
        self._dbg(f"Setting nstopbits to {nstopbits}")
        await self._rnstopbits.set(nstopbits)

    async def set_baud(self, baud):
        # Convert the baud rate to the number of ticks of the system clock we need.
        # There will be some error here, but I think it's generally not a big deal.
        baud_ticks = round((1.0 / baud) / self._sys_clk_period)
        self._trace(f"Setting baud to {baud}, ticks {baud_ticks}")
        await self._rbaud_ticks.set(baud_ticks)

    async def try_baud(self, baud):
        await self.set_baud(baud)
        return await self.run()

    async def transact(self):
        """
        Try to transmit the data at a given baud rate and listen for an echo
        """

        if not self._data:
            raise GlasgowAppletError("try_baud called but empty data")

        self._dbg(f"Transacting data: {self._data}")

        await self._renable.set(1)
        res = b""
        await self._pipe.send(self._data)
        await self._pipe.flush()

        # We aren't guaranteed to get a perfect echo, so queue up reads one
        # byte at a time
        for _ in range(len(self._data)):
            read = self._pipe.recv(1)
            try:
                data = await asyncio.wait_for(read, timeout=self._rx_delay_sec)
                res += data
            except TimeoutError:
                self._trace(f"Timed out waiting for RX data, got {res}")
                break

        await self._renable.set(0)
        self._trace(f"Got res: {res}")

        return res or None


class UARTPinoutApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)

    help = "attemps to automatically determine UART pinout and baud rate"
    description = """
    This applet works by simply sending data at various baud rates and waiting
    for data back. If the UART you are testing does not ever echo data, this
    cannot detect that UART!
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "pins", width=range(2, 17), required=True)

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "-d", "--data-hex", default="0d", help="Data to send as hex (default 0d)"
        )
        parser.add_argument(
            "-s",
            "--data-ascii",
            default=None,
            help="Data to send as ASCII with \\ escapes valid",
        ),
        parser.add_argument(
            "--rx-delay-ms",
            default=0,
            type=int,
            help="Time to wait RX delay in ms, if not set this is determined from the chosen bauds",
        )
        parser.add_argument(
            "-b",
            "--bauds",
            default=None,
            help="Comma separated list of bauds to try",
            action="append",
        )
        parser.add_argument(
            "-e",
            "--exclude-pins",
            default=None,
            action="append",
            help="Comma separated list of pin numbers to exclude. Useful for using less pins without rebuilding the applet.",
        )

        parser.add_argument(
            "-T",
            "--tx",
            default=None,
            help="Set the TX pin and look for the RX pin",
        )

        parser.add_argument(
            "-R",
            "--rx",
            default=None,
            help="Set the RX pin and look for the TX pin",
        )

    def build(self, args):

        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)

            self.uart_pinout_iface = UARTPinoutInterface(
                self.logger,
                self.assembly,
                pins=args.pins,
            )

    def _dbg(self, msg, *args):
        self.uart_pinout_iface._dbg(msg, *args)

    def _trace(self, msg, *args):
        self.uart_pinout_iface._trace(msg, *args)

    def _info(self, msg, *args):
        self.uart_pinout_iface._info(msg, *args)

    def calculate_abs_delay(self, bauds, data):
        """
        Get a absolute delay that will account for the slowest baud rate
        """

        slowest = min(bauds)
        # Assuming 1 start bit, 8 data bits, 1 stop bit and, for good measure, 1 parity bit
        bits_per_byte = 11
        bits_for_data = bits_per_byte * len(data)

        longest_msg_time_ms = round((1000.0 / slowest) * bits_for_data)
        # From some experimentation, it makes sense to set a lower bound here
        wait_ms = max(50, longest_msg_time_ms * 2)
        return wait_ms

    def get_data(self, args):
        """
        Retrieve the command line provided data
        """
        if args.data_ascii:
            # Wow
            return args.data_ascii.encode().decode("unicode_escape").encode()
        try:
            return bytes.fromhex(args.data_hex)
        except ValueError:
            raise GlasgowAppletError(f"invalid hex: {args.data_hex}")

    def _get_pin_idx(self, raw, pins, flag):
        """
        Get the index into the pin array for the given GlasgowPin spec
        """
        try:
            pin = GlasgowPin.parse(raw)[0]
        except (ValueError, IndexError):
            raise GlasgowAppletError(f"Invalid pin spec for {flag}: {raw}")

        self._trace(f"Looking for pin {pin}")

        try:
            return pins.index(pin)
        except ValueError:
            raise GlasgowAppletError(f"Exclude pin {raw} (from {flag}) not in pin set")


    def _make_exclude_pins(self, exclude, pins):
        indices = []
        for p in exclude:
            indices.append(self._get_pin_idx(p, pins, "-e/--exclude-pins"))
        return indices


    async def run(self, args):
        data = self.get_data(args)
        bauds = (
            _DEFAULT_BAUDS
            if not args.bauds
            else sorted([int(e) for x in args.bauds for e in x.split(",")])
        )

        for it in bauds:
            if it.bit_length() > MAX_BAUD_WIDTH:
                raise GlasgowAppletError(
                    f"invalid baud passed to --bauds, {it} has a larger bit width ({it.bit_length()}) than the max allowed value ({MAX_BAUD_WIDTH})"
                )

        pins = args.pins
        npins = len(pins)

        if args.exclude_pins:
            exclude = self._make_exclude_pins(args.exclude_pins, pins)
            self._dbg(f"Excluding pins: {exclude}")
        else:
            exclude = []

        abs_delay = args.rx_delay_ms

        if abs_delay == 0:
            abs_delay = self.calculate_abs_delay(bauds, data)
            self._dbg(f"Absolute delay set to {abs_delay}ms")

        if args.tx is not None:
            tx_options = [self._get_pin_idx(args.tx, pins, "-T/--tx")]
        else:
            tx_options = range(npins)

        if args.rx is not None:
            rx_options = [self._get_pin_idx(args.rx, pins, "-R/--rx")]
        else:
            rx_options = range(npins)

        self.uart_pinout_iface.set_rx_delay_ms(abs_delay)
        self.uart_pinout_iface.set_data(data)
        # The gateware UART only supports 1 stop bit
        await self.uart_pinout_iface.set_nstopbits(1)

        for tx in tx_options:

            if tx in exclude:
                continue

            await self.uart_pinout_iface.set_tx_pin(tx)

            for rx in rx_options:

                if rx == tx or rx in exclude:
                    continue

                await self.uart_pinout_iface.set_rx_pin(rx)

                for it in bauds:
                    await self.uart_pinout_iface.set_baud(it)
                    res = await self.uart_pinout_iface.transact()
                    if res:
                        if res == data:
                            print("** ", end="")
                        print(
                            f"TX[{pins[tx]}] RX[{pins[rx]}] BAUD[{it}] DATA[{res.hex()}]"
                        )

    @classmethod
    def tests(cls):
        from . import test

        return test.UARTPinoutAppletTestCase
