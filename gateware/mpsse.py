from migen import *
from migen.genlib.fsm import *
from migen.genlib.cdc import MultiReg


class MPSSEBus(Module):
    layout = [
        ("tck",   1),
        ("tdi",   1),
        ("tdo",   1),
        ("tms",   1),
        ("gpiol", 4),
        ("gpioh", 8)
    ]

    def __init__(self, pads):
        assert len(pads) >= 4 # at least TDI, TDO, TCK, TMS

        self.ri  = Record(self.layout)
        self.ro  = Record(self.layout)
        self.roe = Record(self.layout)

        self.i   = self.ri.raw_bits()
        self.o   = self.ro.raw_bits()
        self.oe  = self.roe.raw_bits()

        self.xi  = Array([self.i [0:8], self.i [8:16]])
        self.xo  = Array([self.o [0:8], self.o [8:16]])
        self.xoe = Array([self.oe[0:8], self.oe[8:16]])

        self.tck = self.ro.tck
        self.tdi = self.ro.tdi
        self.tdo = self.ri.tdo
        self.tms = self.ro.tms

        ###

        self.comb += [
            Cat([pad.o  for pad in pads]).eq(self.o),
            Cat([pad.oe for pad in pads]).eq(self.oe),
        ]
        self.specials += [
            MultiReg(Cat([pad.i for pad in pads]), self.i)
        ]


class MPSSE(Module):
    def __init__(self, pads):
        self.rx_data = Signal(8)
        self.rx_rdy  = Signal()
        self.rx_ack  = Signal()

        self.tx_data = Signal(8)
        self.tx_rdy  = Signal()
        self.tx_ack  = Signal()

        self.submodules.bus = bus = MPSSEBus(pads)

        ###

        pend_cmd   = Signal(8)
        curr_cmd   = Signal(8)

        is_gpio    = Signal()
        gpio_cmd   = Record([
            ("rd",   1),
            ("adr",  1),
        ])
        self.comb += [
            is_gpio.eq(curr_cmd[2:] == 0b100000),
            gpio_cmd.raw_bits().eq(curr_cmd[:2])
        ]

        self.submodules.fsm = FSM(reset_state="IDLE")
        self.fsm.act("IDLE",
            If(self.rx_rdy,
                self.rx_ack.eq(1),
                NextValue(pend_cmd, self.rx_data),

                If(is_gpio,
                    If(gpio_cmd.rd,
                        NextState("GPIO-READ-I")
                    ).Else(
                        NextState("GPIO-WRITE-O")
                    )
                )
            )
        )
        self.fsm.act("GPIO-READ-I",
            self.tx_rdy.eq(1),
            self.tx_data.eq(self.bus.xi[gpio_cmd.adr]),
            If(self.tx_ack,
                NextState("IDLE")
            )
        )
        self.fsm.act("GPIO-WRITE-O",
            If(self.rx_rdy,
                self.rx_ack.eq(1),
                NextValue(self.bus.xo[gpio_cmd.adr], self.rx_data),
                NextState("GPIO-WRITE-OE")
            )
        )
        self.fsm.act("GPIO-WRITE-OE",
            If(self.rx_rdy,
                self.rx_ack.eq(1),
                NextValue(self.bus.xoe[gpio_cmd.adr], self.rx_data),
                NextState("IDLE")
            )
        )

        self.comb += \
            If(self.fsm.ongoing("IDLE"),
                curr_cmd.eq(self.rx_data),
            ).Else(
                curr_cmd.eq(pend_cmd)
            )

    def do_finalize(self):
        print(self.fsm.encoding)

# -------------------------------------------------------------------------------------------------

import functools
import unittest


def simulation_test(case):
    @functools.wraps(case)
    def wrapper(self):
        tb = self.testbench_cls()
        run_simulation(tb, case(self, tb), vcd_name="test.vcd")
    return wrapper


class MPSSETestbench(Module):
    def __init__(self):
        self.tck   = TSTriple()
        self.tdi   = TSTriple()
        self.tdo   = TSTriple()
        self.tms   = TSTriple()
        self.gpiol = [TSTriple() for _ in range(4)]
        self.gpioh = [TSTriple() for _ in range(8)]

        self.pads  = [self.tck, self.tdi, self.tdo, self.tms,
                      *self.gpiol, *self.gpioh]
        self.i     = Cat([pad.i  for pad in self.pads])
        self.o     = Cat([pad.o  for pad in self.pads])
        self.oe    = Cat([pad.oe for pad in self.pads])

        self.submodules.dut = MPSSE(self.pads)

    def write(self, byte):
        yield self.dut.rx_data.eq(byte)
        yield self.dut.rx_rdy.eq(1)
        for _ in range(10):
            yield
            if (yield self.dut.rx_ack) == 1:
                yield self.dut.rx_data.eq(0)
                yield self.dut.rx_rdy.eq(0)
                yield
                return
        raise Exception("DUT stuck while writing")

    def read(self):
        for _ in range(10):
            if (yield self.dut.tx_rdy) == 1:
                byte = (yield self.dut.tx_data)
                yield self.dut.tx_ack.eq(1)
                yield
                yield self.dut.tx_ack.eq(0)
                return byte
            yield
        raise Exception("DUT stuck while reading")


class MPSSETestCase(unittest.TestCase):
    testbench_cls = MPSSETestbench

    @simulation_test
    def test_gpio_read(self, tb):
        yield tb.i.eq(0xAA55)
        yield
        yield from tb.write(0x81)
        self.assertEqual((yield from tb.read()), 0x55)
        yield from tb.write(0x83)
        self.assertEqual((yield from tb.read()), 0xAA)

    @simulation_test
    def test_gpio_write(self, tb):
        yield from tb.write(0x80)
        yield from tb.write(0xA1)
        yield from tb.write(0x52)
        self.assertEqual((yield tb.o),  0x00A1)
        self.assertEqual((yield tb.oe), 0x0052)
        yield from tb.write(0x82)
        yield from tb.write(0x7E)
        yield from tb.write(0x81)
        self.assertEqual((yield tb.o),  0x7EA1)
        self.assertEqual((yield tb.oe), 0x8152)
