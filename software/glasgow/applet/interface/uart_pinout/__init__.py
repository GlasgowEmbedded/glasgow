import asyncio
import logging

from amaranth import Elaboratable, Module, Mux, Signal, Cat, Const, unsigned
from amaranth.build import ResourceError
from amaranth.lib import stream, enum, io, wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import In, Out

from glasgow.applet import GlasgowAppletError, GlasgowAppletV2
from glasgow.gateware.uart import UART


class _Command(enum.Enum, shape=unsigned(8)):
    Start = 0x00
    SetData = 0x01


class _Status(enum.Enum, shape=unsigned(8)):
    OK = 0x00
    Error = 0x1
    NoData = 0x02
    InvalidCommand = 0x03
    InvalidState = 0x04


class _Parity(enum.Enum, shape=unsigned(2)):
    NoParity = 0x00
    Even = 0x01
    Odd = 0x02


# By default, we allocate enough space for 8 bytes
_DEFAULT_MAX_DATABITS = 64
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


class LedDriver(wiring.Component):
    i_on: In(1)
    o_on: Out(1)

    def __init__(self, cyc=0.50):
        self._on_for = int(cyc * 100)
        self._counter = Signal(7)
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.d.comb += self.o_on.eq(self.i_on & (self._counter < self._on_for))
        m.d.sync += self._counter.eq(self._counter + 1)

        return m


def _get_led(platform, num):
    if platform is None:
        return None
    try:
        return platform.request("led", num, dir="-")
    except ResourceError:
        return None


def clear_led(platform, m, lednum):
    led = _get_led(platform, lednum)
    if led is None:
        return
    m.submodules[f"led{lednum}"] = led_buf = io.Buffer("o", led)
    m.d.comb += led_buf.o.eq(0)


def drive_led(platform, m, sig, lednum):
    led = _get_led(platform, lednum)
    if led is None:
        return
    m.submodules[f"led{lednum}"] = led_buf = io.Buffer("o", led)
    m.submodules[f"led{lednum}_driver"] = driver = LedDriver()
    m.d.comb += driver.i_on.eq(sig)
    m.d.comb += led_buf.o.eq(driver.o_on)


class Ticker(Elaboratable):

    def __init__(self, tick_width):
        self._tick_width = tick_width
        self.i_tick_count = Signal(tick_width)

        self.i_reset = Signal(1)
        self.o_tick = Signal(1)

    def elaborate(self, platform):
        m = Module()

        ticks = Signal(self._tick_width)

        m.d.comb += self.o_tick.eq(ticks == 0)

        with m.If(self.i_tick_count == 0):
            # Hold ticks above 0 so o_tick never goes high. Seems like a bit of
            # an hack here that ticks.eq(0) is not the way to do this but
            # whatever.
            m.d.sync += ticks.eq(1)
        with m.Elif(self.i_reset | (ticks == 0)):
            m.d.sync += ticks.eq(self.i_tick_count - 1)
        with m.Else():
            m.d.sync += ticks.eq(ticks - 1)

        return m


class HostCommunication(wiring.Component):

    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    def __init__(
        self,
        pin_values,
        max_databits,
    ):
        super().__init__()

        self.o_data = Signal(max_databits)
        self.o_data_len = Signal(8)

        self.o_start = Signal(1)

        self.i_running = Signal(1)

        self.i_rx_data = Signal(max_databits)
        self._rx_data = Signal(max_databits)
        self.i_rx_data_len = Signal(8)
        self._rx_data_len = Signal(8)
        self.i_rx_data_valid = Signal(1)
        self.i_rx_data_rdy = Signal(1)

        self._recv_bytes_remaining = Signal(8)
        self._max_databits = max_databits
        self._pin_values = pin_values

    def elaborate(self, platform):
        m = Module()

        with m.FSM() as fsm:

            drive_led(platform, m, ~fsm.ongoing("IDLE"), 3)
            m.d.comb += self.i_rx_data_rdy.eq(fsm.ongoing("IDLE"))

            with m.State("IDLE"):
                with m.If(self.i_rx_data_valid):
                    m.d.sync += [
                        self._rx_data_len.eq(self.i_rx_data_len),
                        self._rx_data.eq(self.i_rx_data),
                        self.o_stream.payload.eq(self.i_rx_data_len),
                    ]
                    m.next = "SEND-RX-RESULT"

                with m.Elif(self.i_stream.valid):
                    m.d.comb += self.i_stream.ready.eq(1)

                    with m.If(self.i_stream.payload == _Command.SetData):
                        m.next = "RECV-DATA-LEN"

                    with m.Elif(self.i_stream.payload == _Command.Start):
                        with m.If(self.i_running):
                            m.d.sync += self.o_stream.payload.eq(_Status.InvalidState)
                            m.next = "SEND-BYTE"
                        with m.Elif(self.o_data_len == 0):
                            m.d.sync += self.o_stream.payload.eq(_Status.NoData)
                            m.next = "SEND-BYTE"
                        with m.Else():
                            m.d.sync += self.o_stream.payload.eq(_Status.OK)
                            m.next = "SEND-START"
                    with m.Else():
                        m.d.sync += self.o_stream.payload.eq(_Status.InvalidCommand)
                        m.next = "SEND-BYTE"

            with m.State("SEND-START"):
                m.d.comb += self.o_stream.valid.eq(1)
                with m.If(self.o_stream.ready):
                    m.d.comb += self.o_start.eq(1)
                    m.next = "IDLE"

            with m.State("SEND-BYTE"):
                m.d.comb += self.o_stream.valid.eq(1)
                with m.If(self.o_stream.ready):
                    m.next = "IDLE"

            with m.State("SEND-RX-RESULT"):
                m.d.comb += self.o_stream.valid.eq(1)
                with m.If(self.o_stream.ready):
                    with m.If(self._rx_data_len == 0):
                        m.next = "IDLE"
                    with m.Else():
                        m.d.sync += [
                            self.o_stream.payload.eq(self._rx_data[0:8]),
                            self._rx_data.eq(self._rx_data[8:]),
                            self._rx_data_len.eq(self._rx_data_len - 1),
                        ]

            with m.State("RECV-DATA-LEN"):
                with m.If(self.i_stream.valid):
                    m.d.sync += self._recv_bytes_remaining.eq(self.i_stream.payload)
                    m.d.sync += self.o_data_len.eq(self.i_stream.payload)
                    m.d.comb += self.i_stream.ready.eq(1)
                    m.next = "RECV-DATA"

            with m.State("RECV-DATA"):
                with m.If(self._recv_bytes_remaining == 0):
                    m.d.sync += self.o_stream.payload.eq(_Status.OK)
                    m.next = "SEND-BYTE"

                with m.Elif(self.i_stream.valid):
                    m.d.sync += self.o_data.eq(
                        Cat(
                            self.i_stream.payload,
                            self.o_data,
                        )
                    )
                    m.d.sync += self._recv_bytes_remaining.eq(
                        self._recv_bytes_remaining - 1
                    )
                    m.d.comb += self.i_stream.ready.eq(1)

        return m


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
        # the output on that bit. We use host_comm.o_tx_mask to set the bit.
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


class RXTimeout(wiring.Component):
    """
    Encapsulates the timeout logic for RX on the UART

    When o_timeout goes high, the RX pin has timed out and we assume nothing else is
    coming. The timer is set by the user or determined by the lowest baud rate. Each
    byte received from the UART should reset the timer.
    """

    i_absolute_delay_ticks: In(24)
    i_byte_received: In(1)
    i_reset: In(1)
    o_timeout: Out(1)

    def elaborate(self, platform):
        m = Module()

        m.submodules.ticker = ticker = Ticker(24)
        m.d.comb += [
            ticker.i_tick_count.eq(self.i_absolute_delay_ticks),
            self.o_timeout.eq(ticker.o_tick),
        ]

        with m.If(self.i_reset | self.i_byte_received):
            m.d.comb += ticker.i_reset.eq(1)

        return m


class UARTPinoutComponent(wiring.Component):
    baud_ticks: In(unsigned(MAX_BAUD_WIDTH))
    absolute_delay_ticks: In(unsigned(24))
    nstopbits: In(unsigned(4))

    def __init__(self, ports, max_databits, parity=_Parity.NoParity):
        super().__init__()
        self.bus = ModifiableUARTBus(ports)
        self._max_databits = max_databits

        pstr = (
            "none"
            if parity == _Parity.NoParity
            else ("even" if parity == _Parity.Even else "odd")
        )

        npins = len(ports.pins)

        self.rx_mask = Signal(npins)
        self.tx_mask = Signal(npins)

        self._rx_data = Signal(max_databits)
        self._rx_data_len = Signal(8)
        self._tx_data = Signal(max_databits)
        self._tx_data_len = Signal(8)
        self._tx_data_remaining = Signal(8)
        self._enabled = Signal(1)

        # Not sure if this is ideal..?
        self.uart = UART(self.bus, _DEFAULT_BAUDS[-1], parity=pstr)
        self.rx_timeout = RXTimeout()

        self.host_comm = HostCommunication(
            self.bus.pin_values,
            max_databits,
        )

    def elaborate(self, platform):

        m = Module()

        m.submodules.internal_uart = self.uart
        m.submodules.host_comm = self.host_comm
        m.submodules.rx_timeout = self.rx_timeout

        m.d.comb += [
            self.host_comm.i_running.eq(self._enabled),
            self.bus.i_enable.eq(self._enabled),
            self.uart.tx_data.eq(self._tx_data[0:8]),
            self.uart.bit_cyc.eq(self.baud_ticks),
        ]

        drive_led(platform, m, self._enabled, 0)
        # Since these idle high, it is maybe more noticeable to drive them with the inverse
        drive_led(platform, m, ~self.bus.rx_i, 1)
        drive_led(platform, m, ~self.bus.tx_o, 2)

        for i in range(4, 5):
            clear_led(platform, m, i)

        with m.FSM() as fsm:

            m.d.comb += self._enabled.eq(~fsm.ongoing("IDLE"))

            with m.State("IDLE"):
                self._on_idle(m)
            with m.State("UART-ACTIVE"):
                self._on_uart_active(m)
            with m.State("SEND-HOST-RESPONSE"):
                self._on_send_host_response(m)

        return m

    def _on_send_host_response(self, m):
        with m.If(self.host_comm.i_rx_data_rdy):
            m.d.comb += self.host_comm.i_rx_data.eq(self._rx_data)
            m.d.comb += self.host_comm.i_rx_data_len.eq(self._rx_data_len)
            m.d.comb += self.host_comm.i_rx_data_valid.eq(1)
            m.next = "IDLE"

    def _on_uart_active(self, m):
        # Hold the RX timeout in reset until we've sent everything and also
        # reset when we see some data on RX
        m.d.comb += self.rx_timeout.i_byte_received.eq(
            (self._tx_data_remaining > 0) | self.uart.rx_rdy
        )
        self._uart_tx(m)
        self._uart_rx(m)

    def _uart_tx(self, m):
        with m.If(self.uart.tx_rdy):
            with m.If(self._tx_data_remaining > 0):
                m.d.sync += [
                    self._tx_data.eq(self._tx_data[8:]),
                    self._tx_data_remaining.eq(self._tx_data_remaining - 1),
                ]
                m.d.comb += self.uart.tx_ack.eq(1)


    def _uart_rx(self, m):
        with m.If(self._rx_data_len == self._tx_data_len):
            # If we received all the data we sent, go ahead to SEND-HOST-RESPONSE
            m.next = "SEND-HOST-RESPONSE"

        with m.Elif(self.rx_timeout.o_timeout):
            # Timeout fired, don't expect any more data on RX and let the host know
            # if we saw anything
            m.next = "SEND-HOST-RESPONSE"

        with m.Elif(self.uart.rx_rdy):
            m.d.sync += [
                self._rx_data.eq(
                    Cat(self.uart.rx_data, self._rx_data)
                ),
                self._rx_data_len.eq(self._rx_data_len + 1),
            ]

            m.d.comb += self.uart.rx_ack.eq(1)

    def _on_idle(self, m):
        m.d.comb += self.rx_timeout.i_reset.eq(1)

        with m.If(self.host_comm.o_start):
            m.d.sync += [
                # Clear state
                self._rx_data.eq(0),
                self._rx_data_len.eq(0),

                self._tx_data_remaining.eq(self.host_comm.o_data_len),

                # Latch data parameters for the UART
                self._tx_data.eq(self.host_comm.o_data),
                self._tx_data_len.eq(self.host_comm.o_data_len),

                # Select the pins
                self.bus.i_rx_mask.eq(self.rx_mask),
                self.bus.i_tx_mask.eq(self.tx_mask),

                # Update the timeout state
                self.rx_timeout.i_absolute_delay_ticks.eq(self.absolute_delay_ticks),
            ]

            m.next = "UART-ACTIVE"


class UARTPinoutInterface:
    def __init__(
        self,
        logger,
        assembly,
        *,
        pins,
        max_databits,
    ):
        self._logger = logger
        self._sys_clk_period = assembly.sys_clk_period
        self._trace(f"sys_clk_period[{self._sys_clk_period}]")

        self._ports = ports = assembly.add_port_group(pins=pins)
        assembly.use_pulls({pins: "high"})
        self._component = component = assembly.add_submodule(
            UARTPinoutComponent(ports, max_databits)
        )

        self._rrx_mask = assembly.add_rw_register(component.rx_mask)
        self._rtx_mask = assembly.add_rw_register(component.tx_mask)

        self._rbaud_ticks = assembly.add_rw_register(component.baud_ticks)
        self._rabs_delay_ticks = assembly.add_rw_register(
            component.absolute_delay_ticks
        )
        # self._rparity = assembly.add_rw_register(component.parity)
        self._rnstopbits = assembly.add_rw_register(component.nstopbits)

        self._datalen = 0

        self._pipe = assembly.add_inout_pipe(
            component.host_comm.o_stream,
            component.host_comm.i_stream,
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

    async def set_data(self, data):
        self._dbg(f"Setting data to {data.hex()}")
        self._datalen = len(data)
        data = data[::-1]
        await self._send_cmd(_Command.SetData, data=data)

    async def set_rx_pin(self, rx):
        self._dbg(f"Setting RX pin to {rx}")
        await self._rrx_mask.set(1 << rx)

    async def set_tx_pin(self, tx):
        self._dbg(f"Setting TX pin to {tx}")
        await self._rtx_mask.set(1 << tx)

    async def get_rx_result(self):
        """
        Retrieve the result found on RX, if any
        """
        self._trace("Waiting for result...")
        nbytes = (await self._pipe.recv(1))[0]
        if nbytes == 0:
            return None
        # We're going to recieve the bytes in reverse order since that
        # made the FPGA logic simpler, just turn em around
        res = await self._pipe.recv(nbytes)
        return res[::-1]

    # async def set_parity(self, parity):
    #    await self._rparity.set(parity.value)

    async def set_nstopbits(self, nstopbits):
        self._dbg(f"Setting nstopbits to {nstopbits}")
        await self._rnstopbits.set(nstopbits)

    async def set_abs_delay_ms(self, delay_ms):
        nticks = round(((1 / self._sys_clk_period) / 1000) * delay_ms)
        self._dbg(f"Setting delay ms to {delay_ms} (nticks = {nticks})")
        await self._rabs_delay_ticks.set(nticks)

    async def set_baud(self, baud):
        # Convert the baud rate to the number of ticks of the system clock we need.
        # There will be some error here, but I think it's generally not a big deal.
        baud_ticks = round((1.0 / baud) / self._sys_clk_period)
        self._trace(f"Setting baud to {baud}, ticks {baud_ticks}")
        await self._rbaud_ticks.set(baud_ticks)

    async def start(self):
        self._trace("Starting")
        await self._send_cmd(_Command.Start)

    async def try_baud(self, baud):
        """
        Try to transmit the data at a given baud rate

        This requires that set_data has already been called to set the data
        """

        if self._datalen == 0:
            raise GlasgowAppletError("try_baud called before set_data")

        await self.set_baud(baud)
        await self.start()

        res = await self.get_rx_result()
        if res is None:
            self._dbg(f"No RX")
        else:
            self._dbg(f"Got RX {res.hex()}")
        return res

    async def _send_int(self, i):
        nbytes = (i.bit_length() + 7) // 8
        raw_bytes = i.to_bytes(nbytes, "big")
        await self._send_len_data(raw_bytes)

    async def _ensure_status(self):
        """
        Read a single byte and check if it is _Status.OK, throwing if not
        """
        if (stat := await self._get_byte()) != _Status.OK.value:
            raise GlasgowAppletError(f"Unexpected status: {stat}")

    async def _get_byte(self):
        self._trace("Waiting for byte")
        raw = await self._pipe.recv(1)
        return raw[0]

    async def _send_cmd(self, cmd, *, data=None, res=True):
        """
        Send a single command with optional data and status checking
        """
        await self._pipe.send([cmd.value])
        if data is not None:
            self._trace("Sending data")
            if isinstance(data, bytes):
                await self._send_len_data(data)
            else:
                await self._send_int(data)
        await self._pipe.flush()
        if res:
            await self._ensure_status()

    async def _send_len_data(self, data):
        """
        Send data with a single byte length prefix
        """
        datalen = len(data)
        if datalen > 0xFF:
            raise GlasgowAppletError("can't send more than 0xFF bytes of data")
        self._trace(f"Sending {datalen} bytes of data {data.hex()}")
        barr = bytearray([datalen, *data])
        await self._pipe.send(barr)


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
        parser.add_argument(
            "--max-datalen",
            default=(_DEFAULT_MAX_DATABITS // 8),
            help="Maximum length of probe data in bytes",
        )

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "-d", "--data-hex", default="0d", help="Data to send as hex (default 0d)"
        )
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
            help="Comma separated list of pin numbers to exclude. These will be numeric and correspond to the pin index in the list of pins. Useful for using less pins without rebuilding the applet.",
        )

    def build(self, args):

        if args.max_datalen < 0:
            raise GlasgowAppletError("--max-datalen must be positive")

        databits = args.max_datalen * 8

        if databits < _DEFAULT_MAX_DATABITS:
            max_databits = _DEFAULT_MAX_DATABITS
        else:
            max_databits = databits

        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)

            self.uart_pinout_iface = UARTPinoutInterface(
                self.logger,
                self.assembly,
                pins=args.pins,
                max_databits=max_databits,
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

    async def run(self, args):
        try:
            data = bytes.fromhex(args.data_hex)
        except ValueError:
            raise GlasgowAppletError(f"invalid hex: {args.data_hex}")

        if len(data) > args.max_datalen:
            raise GlasgowAppletError(f"passed data overflows --max-datalen! {len(data)} > {args.max_datalen}")

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
            exclude = [int(e) for e in args.exclude_pins.split(",")]
        else:
            exclude = []

        abs_delay = args.rx_delay_ms

        if abs_delay == 0:
            abs_delay = self.calculate_abs_delay(bauds, data)
            self._dbg(f"Absolute delay set to {abs_delay}ms")

        await self.uart_pinout_iface.set_data(data)
        await self.uart_pinout_iface.set_abs_delay_ms(abs_delay)
        # The gateware UART only supports 1 stop bit
        await self.uart_pinout_iface.set_nstopbits(1)

        for tx in range(npins):

            if tx in exclude:
                continue

            await self.uart_pinout_iface.set_tx_pin(tx)

            for rx in range(npins):

                if rx == tx or rx in exclude:
                    continue

                await self.uart_pinout_iface.set_rx_pin(rx)

                for it in bauds:
                    self._dbg(f"Trying baud {it}")
                    res = await self.uart_pinout_iface.try_baud(it)
                    if res:
                        if res == data:
                            print("** ", end="")
                        print(f"TX[{pins[tx]}] RX[{pins[rx]}] BAUD[{it}] DATA[{res.hex()}]")

    @classmethod
    def tests(cls):
        from . import test

        return test.UARTPinoutAppletTestCase
