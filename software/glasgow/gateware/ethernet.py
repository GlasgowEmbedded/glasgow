from amaranth import *
from amaranth.lib import data, wiring, stream
from amaranth.lib.wiring import In, Out
from amaranth.lib.crc.catalog import CRC32_ETHERNET

from glasgow.gateware.stream import AsyncQueue, PacketQueue, PacketExtender
from glasgow.gateware.crc import ChecksumAppender, ChecksumVerifier


__all__ = [
    "AbstractDriver", "LoopbackDriver",
    "Enframer", "Deframer", "Controller",
]


class AbstractDriver(wiring.Component):
    def __init__(self, signature={}):
        self.cd_mac = ClockDomain()

        super().__init__({
            "i": In(stream.Signature(data.StructLayout({
                "data": 8,
                "end":  1,
            }))),
            "o": Out(stream.Signature(data.StructLayout({
                "data": 8,
                "end":  1,
            }), always_ready=True)),
            **signature
        })


class LoopbackDriver(AbstractDriver):
    def elaborate(self, platform):
        m = Module()

        m.d.comb += self.cd_mac.clk.eq(ClockSignal())
        m.d.comb += self.cd_mac.rst.eq(ResetSignal())

        wiring.connect(m, wiring.flipped(self.i), wiring.flipped(self.o))

        return m


class Enframer(wiring.Component):
    i: In(stream.Signature(data.StructLayout({
        "data":  8,
        "first": 1,
        "last":  1,
    })))
    o: Out(stream.Signature(data.StructLayout({
        "data":  8,
        "end":   1,
    })))

    def elaborate(self, platform):
        m = Module()

        count = Signal(4)
        with m.FSM():
            with m.State("Preamble"):
                with m.If(self.i.valid):
                    m.d.comb += self.o.valid.eq(1)
                    m.d.comb += self.o.p.data.eq(0x55)
                    with m.If(self.o.ready):
                        m.d.sync += count.eq(count + 1)
                        with m.If(count == 6):
                            m.d.sync += count.eq(0)
                            m.next = "Start Delimiter"

            with m.State("Start Delimiter"):
                m.d.comb += self.o.valid.eq(1)
                m.d.comb += self.o.p.data.eq(0xd5)
                with m.If(self.o.ready):
                    m.d.sync += count.eq(0)
                    m.next = "Frame Data"

            with m.State("Frame Data"):
                m.d.comb += self.o.valid.eq(1)
                m.d.comb += self.o.p.data.eq(self.i.p.data)
                with m.If(self.o.ready):
                    m.d.comb += self.i.ready.eq(1)
                    with m.If(~self.i.valid):
                        m.next = "Underflow"
                    with m.Elif(self.i.p.last):
                        m.next = "Interpacket Gap"

            with m.State(f"Interpacket Gap"):
                m.d.comb += self.o.valid.eq(1)
                m.d.comb += self.o.p.end.eq(1)
                with m.If(self.o.ready):
                    m.d.sync += count.eq(count + 1)
                    with m.If(count == 11):
                        m.d.sync += count.eq(0)
                        m.next = "Preamble"

            with m.State("Underflow"):
                pass # should never happen

        return m


class Deframer(wiring.Component):
    i: In(stream.Signature(data.StructLayout({
        "data":  8,
        "end":  1,
    }), always_ready=True))
    o: Out(stream.Signature(data.StructLayout({
        "data":  8,
        "first": 1,
        "last":  1,
        "end":   1,
    })))

    def elaborate(self, platform):
        m = Module()

        m.d.comb += self.o.p.data.eq(self.i.p.data)

        with m.FSM():
            with m.State("Idle"):
                with m.If(self.i.valid):
                    with m.If(self.i.p.end):
                        m.next = "Preamble"

            with m.State("Preamble"):
                with m.If(self.i.valid):
                    with m.If(~self.i.p.end & (self.i.p.data == 0xd5)):
                        m.d.sync += self.o.p.first.eq(1)
                        m.next = "Frame Data"

            with m.State("Frame Data"):
                with m.If(self.i.valid):
                    m.d.sync += self.o.p.first.eq(0)
                    m.d.comb += self.o.p.end.eq(self.i.p.end)
                    m.d.comb += self.o.valid.eq(1)
                    with m.If(~self.o.ready):
                        m.next = "Idle" # discard the rest of the packet
                    with m.Elif(self.i.p.end):
                        m.next = "Preamble"

        return m


class Controller(wiring.Component):
    i: In(stream.Signature(data.StructLayout({
        "data":  8,
        "end":   1,
    })))
    o: Out(stream.Signature(data.StructLayout({
        "data":  8,
        "end":   1,
    })))

    tx_bypass: In(1)
    rx_bypass: In(1)

    def __init__(self, driver):
        self.driver = driver

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.domains.mac = self.driver.cd_mac

        m.submodules.tx_cdc_fifo = tx_cdc_fifo = AsyncQueue(
            shape=self.i.p.shape(), depth=8, o_domain="mac")
        wiring.connect(m, tx_cdc_fifo.i, wiring.flipped(self.i))

        m.submodules.tx_queue = tx_queue = DomainRenamer("mac")(
            PacketQueue(8, data_depth=2048, size_depth=32))
        m.d.comb += [
            tx_queue.i.valid.eq(tx_cdc_fifo.o.valid),
            tx_queue.i.p.data.eq(tx_cdc_fifo.o.p.data),
            tx_queue.i.p.end.eq(tx_cdc_fifo.o.p.end),
            tx_cdc_fifo.o.ready.eq(tx_queue.i.ready),
        ]

        m.submodules.tx_padder = tx_padder = DomainRenamer("mac")(
            PacketExtender(8, min_length=60, padding=0x00))
        with m.If(~self.tx_bypass):
            wiring.connect(m, tx_padder.i, tx_queue.o)

        m.submodules.fcs_appender = fcs_appender = DomainRenamer("mac")(
            ChecksumAppender(CRC32_ETHERNET))
        wiring.connect(m, fcs_appender.i, tx_padder.o)

        m.submodules.enframer = enframer = DomainRenamer("mac")(Enframer())
        with m.If(~self.tx_bypass):
            wiring.connect(m, enframer.i, fcs_appender.o)
        with m.Else():
            wiring.connect(m, enframer.i, tx_queue.o)

        m.submodules.driver = driver = self.driver
        wiring.connect(m, driver.i, enframer.o)

        m.submodules.deframer = deframer = DomainRenamer("mac")(Deframer())
        wiring.connect(m, deframer.i, driver.o)

        m.submodules.fcs_verifier = fcs_verifier = DomainRenamer("mac")(
            ChecksumVerifier(CRC32_ETHERNET))
        with m.If(~self.rx_bypass):
            wiring.connect(m, fcs_verifier.i, deframer.o)

        m.submodules.rx_queue = rx_queue = DomainRenamer("mac")(
            PacketQueue(8, data_depth=2048, size_depth=32))
        with m.If(~self.rx_bypass):
            m.d.comb += [
                rx_queue.i.valid.eq(fcs_verifier.o.valid),
                rx_queue.i.p.data.eq(fcs_verifier.o.p.data),
                rx_queue.i.p.first.eq(fcs_verifier.o.p.first),
                rx_queue.i.p.last.eq(fcs_verifier.o.p.last),
                fcs_verifier.o.ready.eq(rx_queue.i.valid),
            ]
        with m.Else():
            wiring.connect(m, rx_queue.i, deframer.o)

        m.submodules.rx_cdc_fifo = rx_cdc_fifo = AsyncQueue(
            shape=rx_queue.o.p.shape(), depth=8, i_domain="mac")
        wiring.connect(m, rx_cdc_fifo.i, rx_queue.o)

        with m.FSM():
            with m.State("Data"):
                m.d.comb += [
                    self.o.valid.eq(rx_cdc_fifo.o.valid),
                    self.o.p.data.eq(rx_cdc_fifo.o.p.data),
                    rx_cdc_fifo.o.ready.eq(self.o.ready),
                ]
                with m.If(rx_cdc_fifo.o.valid & rx_cdc_fifo.o.ready & rx_cdc_fifo.o.p.last):
                    m.next = "End"

            with m.State("End"):
                m.d.comb += [
                    self.o.valid.eq(1),
                    self.o.p.end.eq(1),
                ]
                with m.If(self.o.ready):
                    m.next = "Data"

        return m
