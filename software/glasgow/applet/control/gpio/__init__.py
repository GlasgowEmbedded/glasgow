import enum
import logging
from amaranth import *
from amaranth.lib import io
from amaranth.lib.cdc import FFSynchronizer

from ... import *


class Op(enum.IntEnum):
    READ   = 0x00
    WRITE  = 0x01
    TOGGLE = 0x02


class ControlGPIOSubtarget(Elaboratable):
    def __init__(self, ports, in_fifo, out_fifo):
        self.ports = ports
        self.in_fifo = in_fifo
        self.out_fifo = out_fifo

    def elaborate(self, platform):
        m = Module()

        ios = [ io.Buffer("io", p) for p in self.ports.io ]
        m.submodules += ios

        in_raw = Cat(*( p.i for p in ios ))
        in_buf = Signal.like(in_raw)
        m.submodules += FFSynchronizer(in_raw, in_buf, reset=1)

        op_channel = Signal(4)
        op_level   = Signal(1)
        op_enable  = Signal(1)
        op_decode  = Cat(op_channel, op_level, op_enable)

        with m.FSM():
            with m.State("IDLE"):
                m.d.comb += self.out_fifo.r_en.eq(1)
                with m.If(self.out_fifo.r_rdy):
                    m.d.sync += op_decode.eq(self.out_fifo.r_data[2:])
                    with m.Switch(self.out_fifo.r_data[:2]):
                        with m.Case(Op.READ):
                            m.next = "READ"
                        with m.Case(Op.WRITE):
                            m.next = "WRITE"
                        with m.Case(Op.TOGGLE):
                            m.next = "TOGGLE"

            with m.State("READ"):
                for n,p in enumerate(ios):
                    with m.If(op_channel == n):
                        m.d.comb += [
                            self.in_fifo.w_data.eq(Cat(Const(Op.READ, 2), op_channel, p.i)),
                            self.in_fifo.w_en.eq(1),
                        ]
                with m.If(self.in_fifo.w_rdy):
                    m.next = "IDLE"

            with m.State("WRITE"):
                for n,p in enumerate(ios):
                    with m.If(op_channel == n):
                        m.d.sync += [
                            p.o.eq(op_level),
                            p.oe.eq(op_enable),
                        ]
                m.next = "IDLE"

            with m.State("TOGGLE"):
                for n,p in enumerate(ios):
                    with m.If(op_channel == n):
                        m.d.sync += [
                            p.o.eq(~p.o),
                            p.oe.eq(op_enable),
                        ]
                m.next = "IDLE"

        return m


class ControlGPIOInterface:
    def __init__(self, device, interface, pins):
        self.device = device
        self.lower = interface
        self.pins = pins

    async def _run_op(self, operation, channel, level=False, enable=False):
        pin = self.pins[channel] # raise an IndexError if it's invalid

        cmd = 0 \
            | ((operation << 0)  & 0x03) \
            | ((channel   << 2)  & 0x3c) \
            | (0x40 if level  else 0x00) \
            | (0x80 if enable else 0x00)

        await self.lower.write([ cmd ])
        await self.lower.flush()

        if operation in ( Op.READ, ):
            ret = await self.lower.read(1)
            return bool(ret[0] & 0x40)

    async def read(self, channel):
        return await self._run_op(Op.READ, channel)

    async def write(self, channel, level, enable=True):
        await self._run_op(Op.WRITE, channel, level, enable)

    async def toggle(self, channel, enable=True):
        await self._run_op(Op.TOGGLE, channel, enable=enable)

    async def pull(self, channel, level, enable=True):
        pin = self.pins[channel]
        if level:
            await self.device.set_pulls("AB", high={ pin.number })
        else:
            await self.device.set_pulls("AB", low ={ pin.number })

    async def hiz(self, channel):
        await self.write(channel, False, False)
        await self.pull(channel, False, False)


class ControlGPIOApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "control I/O pins from your computer"
    description = """
    Control Glasgow's I/O pins as standard GPIO pins, from Python running on your computer. Pins
    may be used as Inputs (i.e: read), as Outputs (i.e: written), set High-Impendance (e.g: open-
    drain), and the pull-up and pull-down state can be controlled.

    Beware that pins nominated with the --pins-io argument will be translated and zero-indexed...
    for example, `--pins-io 1,2` will present Glasgow's pin 1 as channel 0.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "io", width=range(1, 16), default=(0, ))

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(ControlGPIOSubtarget(
            ports=iface.get_port_group(io=args.pin_set_io),
            in_fifo=iface.get_in_fifo(),
            out_fifo=iface.get_out_fifo(),
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return ControlGPIOInterface(device, iface, args.pin_set_io)

    @classmethod
    def tests(cls):
        from . import test
        return test.ControlServoAppletTestCase
