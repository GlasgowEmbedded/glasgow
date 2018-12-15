# MPSSE reference:
# http://www.ftdichip.com/Support/Documents/AppNotes/AN_135_MPSSE_Basics.pdf
# http://www.ftdichip.com/Support/Documents/AppNotes/ AN_108_Command_Processor_for_MPSSE_and_MCU_Host_Bus_Emulation_Modes.pdf

from nmigen.compat import *
from nmigen.compat.genlib.cdc import MultiReg


__all__ = ['MPSSE']


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
        self.tdo = Signal()
        self.tms = self.ro.tms

        self.loopback = Signal()

        ###

        self.comb += [
            Cat([pad.o  for pad in pads]).eq(self.o),
            Cat([pad.oe for pad in pads]).eq(self.oe),
            If(self.loopback,
                self.tdo.eq(self.ro.tdi)
            ).Else(
                self.tdo.eq(self.ri.tdo)
            )
        ]
        self.specials += [
            MultiReg(Cat([pad.i for pad in pads]), self.i)
        ]


class MPSSEClockGen(Module):
    def __init__(self, divisor, tck, legacy_divisor_en):
        self.clken  = Signal()
        self.clkpos = Signal()
        self.clkneg = Signal()

        self.tcken  = Signal()
        self.tckpos = Signal()
        self.tckneg = Signal()

        ###

        clk2x   = Signal(reset=1)
        counter = Signal.like(divisor)
        self.sync += \
            If(self.clken,
                If(counter == 0,
                    If(legacy_divisor_en,
                        counter.eq(divisor+5)
                    ).Else(
                        counter.eq(divisor)
                    ),
                    clk2x.eq(~clk2x),
                ).Else(
                    counter.eq(counter - 1)
                )
            ).Else(
                If(legacy_divisor_en,
                    counter.eq(divisor+5)
                ).Else(
                    counter.eq(divisor)
                ),
                clk2x.eq(clk2x.reset)
            )

        clkreg = Signal()
        self.sync += \
            clkreg.eq(self.clken & clk2x)
        self.comb += [
            self.clkpos.eq(self.clken & (~clkreg &  clk2x)),
            self.clkneg.eq(self.clken & ( clkreg & ~clk2x))
        ]

        tckstb = Signal()
        self.sync += \
            tck.eq(tck ^ tckstb)
        self.comb += [
            tckstb.eq((self.clkpos | self.clkneg) & self.tcken),
            self.tckpos.eq(tckstb & ~tck),
            self.tckneg.eq(tckstb &  tck)
        ]


class MPSSE(Module):
    def __init__(self, pads):
        self.rx_data = Signal(8)
        self.rx_rdy  = Signal()
        self.rx_ack  = Signal()

        self.tx_data = Signal(8)
        self.tx_rdy  = Signal()
        self.tx_ack  = Signal()

        self.submodules.bus = MPSSEBus(pads)

        ###

        # Execution state

        self.rdivisor  = Record([
            ("lobyte",  8),
            ("hibyte",  8),
        ])
        self.divisor   = self.rdivisor.raw_bits()

        self.legacy_divisor_en = Signal(reset=1)

        self.rposition = Record([
            ("bit",     3),
            ("lobyte",  8),
            ("hibyte",  8),
        ])
        self.position  = self.rposition.raw_bits()

        # Clock generator

        clkgen = MPSSEClockGen(self.divisor, self.bus.tck, self.legacy_divisor_en)
        self.submodules += clkgen

        # Command decoder

        pend_cmd   = Signal(8)
        curr_cmd   = Signal(8)

        is_shift   = Signal()
        shift_cmd  = Record([
            ("wneg",    1),
            ("bits",    1),
            ("rneg",    1),
            ("le",      1),
            ("tdi",     1),
            ("tdo",     1),
            ("tms",     1),
        ])
        self.comb += [
            If(curr_cmd[7:] == 0b0,
                is_shift.eq(1),
                shift_cmd.raw_bits().eq(curr_cmd[:7])
            ).Elif(curr_cmd == 0x8E,
                shift_cmd.raw_bits().eq(0x02)
            ).Elif(curr_cmd == 0x8F,
                shift_cmd.raw_bits().eq(0x00)
            )
        ]

        is_gpio    = Signal()
        gpio_cmd   = Record([
            ("rd",      1),
            ("adr",     1),
        ])
        self.comb += [
            is_gpio.eq(curr_cmd[2:] == 0b100000),
            gpio_cmd.raw_bits().eq(curr_cmd[:2])
        ]

        # Command processor

        self.submodules.fsm = FSM(reset_state="IDLE")
        self.fsm.act("IDLE",
            If(self.rx_rdy,
                self.rx_ack.eq(1),
                NextValue(pend_cmd, self.rx_data),

                If(is_shift,
                    NextValue(self.position, 0),
                    If(shift_cmd.tms,
                        If(shift_cmd.bits & shift_cmd.le & ~shift_cmd.tdi,
                            NextState("SHIFT-LENGTH-BITS")
                        ).Else(
                            NextState("ERROR")
                        )
                    ).Elif(shift_cmd.tdi | shift_cmd.tdo,
                        If((shift_cmd.wneg & ~shift_cmd.tdi) |
                                (shift_cmd.rneg & ~shift_cmd.tdo),
                            NextState("ERROR")
                        ).Elif(shift_cmd.bits,
                            NextState("SHIFT-LENGTH-BITS")
                        ).Else(
                            NextState("SHIFT-LENGTH-LOBYTE")
                        )
                    ).Else(
                        NextState("ERROR")
                    )
                ).Elif(is_gpio,
                    If(gpio_cmd.rd,
                        NextState("GPIO-READ-I")
                    ).Else(
                        NextState("GPIO-WRITE-O")
                    )
                ).Elif(curr_cmd == 0x8E,
                    NextState("SHIFT-LENGTH-BITS")
                ).Elif(curr_cmd == 0x8F,
                    NextState("SHIFT-LENGTH-LOBYTE")
                ).Elif(curr_cmd == 0x86,
                    NextState("DIVISOR-LOBYTE")
                ).Elif(curr_cmd == 0x84,
                    NextValue(self.bus.loopback, 1)
                ).Elif(curr_cmd == 0x85,
                    NextValue(self.bus.loopback, 0)
                ).Elif(curr_cmd == 0x8A,
                    NextValue(self.legacy_divisor_en, 0)
                ).Elif(curr_cmd == 0x8B,
                    NextValue(self.legacy_divisor_en, 1)
                ).Else(
                    NextState("ERROR")
                )
            ).Else(
                NextValue(pend_cmd, 0)
            )
        )
        self.comb += \
            If(self.fsm.ongoing("IDLE"),
                curr_cmd.eq(self.rx_data),
            ).Else(
                curr_cmd.eq(pend_cmd)
            )

        # Shift subcommand, length handling

        begin_shifting = \
            If(shift_cmd.tdi ^ shift_cmd.tms,
                NextState("SHIFT-LOAD")
            ).Else(
                NextState("SHIFT-SETUP")
            )

        self.fsm.act("SHIFT-LENGTH-LOBYTE",
            If(self.rx_rdy,
                self.rx_ack.eq(1),
                NextValue(self.rposition.bit, 7),
                NextValue(self.rposition.lobyte, self.rx_data),
                NextState("SHIFT-LENGTH-HIBYTE")
            )
        )
        self.fsm.act("SHIFT-LENGTH-HIBYTE",
            If(self.rx_rdy,
                self.rx_ack.eq(1),
                NextValue(self.rposition.hibyte, self.rx_data),
                begin_shifting
            )
        )
        self.fsm.act("SHIFT-LENGTH-BITS",
            If(self.rx_rdy,
                self.rx_ack.eq(1),
                NextValue(self.rposition.bit, self.rx_data),
                begin_shifting
            )
        )

        # Shift subcommand, actual shifting

        rx_data_be = Signal(8)
        self.comb += \
            If(~shift_cmd.le,
                rx_data_be.eq(self.rx_data)
            ).Else(
                rx_data_be.eq(Cat([self.rx_data[7 - i] for i in range(8)]))
            )

        bits_in = Signal(8)
        bits_out = Signal(8)

        output_setup = Signal()
        output_hold  = Signal()
        input_setup = Signal()
        input_hold  = Signal()
        self.comb += [
            output_setup.eq(clkgen.tckpos & ~shift_cmd.wneg |
                         clkgen.tckneg &  shift_cmd.wneg),
            output_hold .eq(clkgen.tckpos &  shift_cmd.wneg |
                         clkgen.tckneg & ~shift_cmd.wneg),
            input_setup.eq(clkgen.tckpos & ~shift_cmd.rneg |
                         clkgen.tckneg &  shift_cmd.rneg),
            input_hold .eq(clkgen.tckpos &  shift_cmd.rneg |
                         clkgen.tckneg & ~shift_cmd.rneg),
        ]

        self.fsm.act("SHIFT-LOAD",
            If(self.rx_rdy,
                self.rx_ack.eq(1),
                NextValue(bits_in, rx_data_be << 1),
                If(shift_cmd.tdi,
                    NextValue(self.bus.tdi, rx_data_be[7])
                ).Else(
                    NextValue(self.bus.tms, rx_data_be[7])
                ),
                NextState("SHIFT-SETUP"),
            )
        )
        self.fsm.act("SHIFT-SETUP",
            clkgen.clken.eq(1),
            clkgen.tcken.eq(clkgen.clkneg),
            If(clkgen.clkneg,
                NextState("SHIFT-CLOCK")
            )
        )
        self.fsm.act("SHIFT-CLOCK",
            clkgen.clken.eq(1),
            clkgen.tcken.eq(1),
            If(output_setup,
                NextValue(bits_in, bits_in << 1),
                If(shift_cmd.tdi,
                    NextValue(self.bus.tdi, bits_in[7])
                ).Elif(shift_cmd.tms,
                    NextValue(self.bus.tms, bits_in[7])
                )
            ),
            If(input_setup,
                NextValue(bits_out, bits_out << 1),
                If(shift_cmd.tdo,
                    NextValue(bits_out[0], self.bus.tdo)
                )
            ),
            If(clkgen.clkpos,
                If(self.position == 0,
                    If(shift_cmd.tdo,
                        NextState("SHIFT-REPORT")
                    ).Else(
                        NextState("IDLE")
                    )
                ).Else(
                    NextValue(self.position, self.position - 1)
                )
            )
        )
        self.fsm.act("SHIFT-REPORT",
            self.tx_rdy.eq(1),
            self.tx_data.eq(bits_out),
            If(self.tx_ack,
                NextState("SHIFT-LAST")
            )
        )
        self.fsm.act("SHIFT-LAST",
            If(~self.tx_ack,
                self.tx_rdy.eq(0),
                NextState("IDLE")
            )
        )

        # GPIO read/write subcommand

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

        # Divisor subcommand

        self.fsm.act("DIVISOR-LOBYTE",
            If(self.rx_rdy,
                self.rx_ack.eq(1),
                NextValue(self.rdivisor.lobyte, self.rx_data),
                NextState("DIVISOR-HIBYTE")
            )
        )
        self.fsm.act("DIVISOR-HIBYTE",
            If(self.rx_rdy,
                self.rx_ack.eq(1),
                NextValue(self.rdivisor.hibyte, self.rx_data),
                NextState("IDLE")
            )
        )

        # Error "subcommand"

        self.fsm.act("ERROR",
            self.tx_rdy.eq(1),
            self.tx_data.eq(0xFA),
            If(self.tx_ack,
                NextState("ERROR-DESC")
            )
        )
        self.fsm.act("ERROR-DESC",
            self.tx_rdy.eq(1),
            self.tx_data.eq(pend_cmd),
            If(self.tx_ack,
                NextState("IDLE")
            )
        )

# -------------------------------------------------------------------------------------------------

import unittest

from . import simulation_test


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

        self.clkdiv = 5

    def do_finalize(self):
        self.states = {v: k for k, v in self.dut.fsm.encoding.items()}

    def dut_state(self):
        return self.states[(yield self.dut.fsm.state)]

    def write(self, byte):
        yield self.dut.rx_data.eq(byte)
        yield self.dut.rx_rdy.eq(1)
        for _ in range(32 * self.clkdiv):
            yield
            if (yield self.dut.rx_ack) == 1:
                yield self.dut.rx_data.eq(0)
                yield self.dut.rx_rdy.eq(0)
                yield
                return
        raise Exception("DUT stuck while writing")

    def read(self):
        yield self.dut.tx_ack.eq(1)
        for _ in range(32 * self.clkdiv):
            yield
            if (yield self.dut.tx_rdy) == 1:
                byte = (yield self.dut.tx_data)
                yield self.dut.tx_ack.eq(0)
                yield
                return byte
        raise Exception("DUT stuck while reading")

    def _wait_for_tck(self, at_setup=None):
        setup = None
        for _ in range(64 * self.clkdiv):
            if at_setup:
                setup = (yield from at_setup())
            tckold = (yield self.tck.o)
            yield
            tcknew = (yield self.tck.o)
            if tckold != tcknew:
                break
        if tckold == tcknew:
            raise Exception("DUT ceased driving TCK")
        return setup

    def recv_tdi(self, nbits, pos):
        bits = 0
        for n in range(nbits * 2):
            yield from self._wait_for_tck()
            if (yield self.tck.o) == pos:
                bits = (bits << 1) | (yield self.tdi.o)
        return bits

    def recv_tms(self, nbits, pos):
        bits = 0
        for n in range(nbits * 2):
            yield from self._wait_for_tck()
            if (yield self.tck.o) == pos:
                bits = (bits << 1) | (yield self.tms.o)
        return bits

    def xfer(self, nbits, out_bits, in_bits, out_pos, in_pos):
        for n in range(nbits * 2):
            tdiold = (yield from self._wait_for_tck(
                at_setup=lambda: (yield self.tdi.o)))
            tcknew = (yield self.tck.o)

            if in_pos == tcknew:
                if (yield self.tdi.o) != tdiold:
                    yield; yield; yield; yield
                    raise Exception("DUT violated setup/hold timings")

                in_bit  = in_bits  & (1 << (nbits - n // 2) - 1)
                # print(f"{in_bits:0{nbits}b} {in_bit:0{nbits}b} ")
                if (yield self.tdi.o) != (in_bit != 0):
                    yield; yield; yield; yield
                    raise Exception("DUT clocked out bit {} as {} (expected {})"
                                    .format(n // 2, (yield self.tdi.o), 1 if in_bit else 0))
            if out_pos == tcknew:
                out_bit = out_bits & (1 << (nbits - n // 2) - 1)
                yield self.tdo.i.eq(out_bit)

        for _ in range(16 * self.clkdiv):
            tckold = (yield self.tck.o)
            yield
            tcknew = (yield self.tck.o)
            if tckold != tcknew and in_pos == tcknew:
                raise Exception("DUT spuriously drives TCK")

        return True

    def out_xfer(self, nbits, bits, pos):
        return self.xfer(nbits, bits, 0, pos, False)

    def in_xfer(self, nbits, bits, pos):
        return self.xfer(nbits, 0, bits, False, pos)


class MPSSETestCase(unittest.TestCase):
    def setUp(self):
        self.tb = MPSSETestbench()

    def simulationSetUp(self, tb):
        # speed up tests
        yield tb.dut.legacy_divisor_en.eq(0)

    @simulation_test
    def test_error(self, tb):
        yield from tb.write(0xFF)
        self.assertEqual((yield from tb.read()), 0xFA)
        self.assertEqual((yield from tb.read()), 0xFF)
        self.assertEqual((yield from tb.dut_state()), "IDLE")

    @simulation_test
    def test_gpio_read(self, tb):
        yield tb.i.eq(0xAA55)
        yield
        yield from tb.write(0x81)
        self.assertEqual((yield from tb.read()), 0x55)
        yield from tb.write(0x83)
        self.assertEqual((yield from tb.read()), 0xAA)
        self.assertEqual((yield from tb.dut_state()), "IDLE")

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
        self.assertEqual((yield from tb.dut_state()), "IDLE")

    @simulation_test
    def test_bits_write(self, tb):
        yield from tb.write(0x12)
        yield from tb.write(5)
        self.assertEqual((yield tb.dut.rposition.bit), 5)
        yield from tb.write(0x55)
        self.assertEqual((yield from tb.recv_tdi(5, pos=True)), 0x0A)

    @simulation_test
    def test_clk_bits(self, tb):
        yield from tb.write(0x8E)
        yield from tb.write(5)
        self.assertEqual((yield tb.dut.rposition.bit), 5)
        self.assertEqual((yield from tb.recv_tdi(6, pos=True)), 0x00)
        self.assertEqual((yield tb.dut.bus.tck), 0)
        self.assertEqual((yield from tb.dut_state()), "IDLE")

    @simulation_test
    def test_clk_bytes(self, tb):
        yield from tb.write(0x8F)
        yield from tb.write(5)
        yield from tb.write(0)
        self.assertEqual((yield tb.dut.rposition.lobyte), 5)
        self.assertEqual((yield tb.dut.rposition.hibyte), 0)
        self.assertEqual((yield from tb.recv_tdi(48, pos=True)), 0x00)
        self.assertEqual((yield tb.dut.bus.tck), 0)
        self.assertEqual((yield from tb.dut_state()), "IDLE")

    @simulation_test
    def test_bits_read(self, tb):
        yield from tb.write(0x22)
        yield from tb.write(5)
        self.assertEqual((yield tb.dut.rposition.bit), 5)
        self.assertEqual((yield from tb.read()), 0x00)

    @simulation_test
    def test_legacy_dividor(self, tb):
        # restore pristine MPSSE state
        yield tb.dut.legacy_divisor_en.eq(0)
        self.tb.clkdiv = 5

        # works
        yield from tb.write(0x22)
        yield from tb.write(5)
        self.assertEqual((yield tb.dut.rposition.bit), 5)
        self.assertEqual((yield from tb.read()), 0x00)

        # works
        yield from tb.write(0x8A)
        self.tb.clkdiv = 1
        yield from tb.write(0x22)
        yield from tb.write(5)
        self.assertEqual((yield tb.dut.rposition.bit), 5)
        self.assertEqual((yield from tb.read()), 0x00)

        # fails - timeout
        yield from tb.write(0x8B)
        self.tb.clkdiv = 1
        yield from tb.write(0x22)
        yield from tb.write(5)
        self.assertEqual((yield tb.dut.rposition.bit), 5)
        with self.assertRaises(Exception):
            yield from tb.read()

    @simulation_test
    def test_bits_read_write(self, tb):
        yield from tb.write(0x84)
        yield from tb.write(0x33)
        yield from tb.write(5)
        self.assertEqual((yield tb.dut.rposition.bit), 5)
        yield from tb.write(0x55)
        self.assertEqual((yield from tb.recv_tdi(5, pos=True)), 0x0A)
        self.assertEqual((yield from tb.read()), 0x15) # non-negative read clock

    @simulation_test
    def test_tms_write(self, tb):
        yield from tb.write(0x4A)
        yield from tb.write(5)
        self.assertEqual((yield tb.dut.rposition.bit), 5)
        yield from tb.write(0x55)
        self.assertEqual((yield from tb.recv_tms(5, pos=True)), 0x15)

    @simulation_test
    def test_invalid_tms_commands(self, tb):
        yield from tb.write(0x5A)
        self.assertEqual((yield from tb.dut_state()), "ERROR")
        yield from tb.read()
        yield from tb.read()
        self.assertEqual((yield from tb.dut_state()), "IDLE")
        yield from tb.write(0x42)
        self.assertEqual((yield from tb.dut_state()), "ERROR")
        yield from tb.read()
        yield from tb.read()
        yield from tb.write(0x68)
        self.assertEqual((yield from tb.dut_state()), "ERROR")
        yield from tb.read()
        yield from tb.read()

    @simulation_test
    def test_hibyte_lobyte_write(self, tb):
        yield from tb.write(0x10)
        yield from tb.write(0x05)
        self.assertEqual((yield tb.dut.rposition.lobyte), 0x05)
        yield from tb.write(0x11)
        self.assertEqual((yield tb.dut.rposition.hibyte), 0x11)

    @simulation_test
    def test_divisor_write(self, tb):
        yield from tb.write(0x86)
        yield from tb.write(0x34)
        yield from tb.write(0x12)
        self.assertEqual((yield tb.dut.divisor), 0x1234)
        self.assertEqual((yield from tb.dut_state()), "IDLE")

    def write_single_byte(self, tb, pos):
        yield from tb.write(0x80)
        if pos:
            yield from tb.write(0b0001)
        else:
            yield from tb.write(0b0000)
        yield from tb.write(0b1101)

        if pos:
            yield from tb.write(0x10)
        else:
            yield from tb.write(0x11)
        yield from tb.write(0x00)
        yield from tb.write(0x00)
        yield from tb.write(0xA5)
        self.assertTrue((yield from tb.in_xfer(8, 0b10100101, not pos)))

    @simulation_test
    def test_write_single_byte_clkpos(self, tb):
        yield tb.dut.divisor.eq(1)
        yield from self.write_single_byte(tb, pos=True)

    @simulation_test
    def test_write_single_byte_clkneg(self, tb):
        yield tb.dut.divisor.eq(1)
        yield from self.write_single_byte(tb, pos=False)

    @simulation_test
    def test_write_single_byte_clkneg_fast(self, tb):
        yield from self.write_single_byte(tb, pos=False)

    @simulation_test
    def test_write_single_byte_clkwrong(self, tb):
        yield from tb.write(0x10) # +ve, but we start from tck=0
        yield from tb.write(0x00)
        yield from tb.write(0x00)
        yield from tb.write(0xA5)
        self.assertEqual((yield from tb.recv_tdi(8, pos=False)), 0xA5)
        yield
        self.assertEqual((yield tb.tck.o), 0)
