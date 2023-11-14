from typing import Callable
from amaranth import *
from amaranth.lib.fifo import SyncFIFOBuffered

from . import SignalCompressor

class LAArbeiter(Elaboratable):
    """This Logic Analyzer Arbeiter instanciates n Signal compressors and n Fifos and arbeites the
    output of the fifos in a round robin fashion. Its output format is one length byte followed by
    2*length bytes of compressed channel data. After that the next channel is send with the same
    format.
    """
    def __init__(self, output_fifo: SyncFIFOBuffered, n_channels=16, pressure_threshold=64):
        self.output_fifo = output_fifo
        assert output_fifo.width == 8
        self.input = Signal(n_channels)
        
        self._pressure_threshold = pressure_threshold

        self.fifos = [SyncFIFOBuffered(width=16, depth=256) for _ in range(n_channels)]
        self.compressors = [SignalCompressor(self.input[i]) for i in range(n_channels)]

    def elaborate(self, platform):
        m = Module()

        to_transfer = Signal(8)
        enough_pressure = Signal(len(self.fifos))
        any_enough_pressure = Signal()
        m.d.comb += any_enough_pressure.eq(enough_pressure.any())

        with m.FSM():
            for i in range(len(self.input)):
                fifo = self.fifos[i]
                compressor = self.compressors[i]
                m.submodules[f"fifo_{i}"] = fifo
                m.submodules[f"compressor_{i}"] = compressor

                m.d.comb += fifo.w_en.eq(compressor.valid)
                m.d.comb += fifo.w_data.eq(compressor.value)
    
                m.d.sync += enough_pressure[i].eq(fifo.r_level > self._pressure_threshold)

                def go_to_next(i):
                    with m.If(any_enough_pressure):
                        m.next = f"announce_{(i + 1) % len(self.input)}"
                    with m.Else():
                        m.next = f"wait_{(i + 1) % len(self.input)}"


                with m.State(f"wait_{i}"):
                    with m.If(any_enough_pressure):
                        m.next = f"announce_{i}"
                with m.State(f"announce_{i}"):
                    m.d.comb += self.output_fifo.w_data.eq(fifo.r_level)
                    m.d.comb += self.output_fifo.w_en.eq(1)
                    m.d.sync += to_transfer.eq(fifo.r_level)
                    with m.If(self.output_fifo.w_rdy):
                        with m.If(fifo.r_level > 0):
                            m.next = f"send_{i}_lower"
                        with m.Else():
                            go_to_next(i)

                with m.State(f"send_{i}_lower"):
                    m.d.comb += self.output_fifo.w_data.eq(fifo.r_data[0:8])
                    m.d.comb += self.output_fifo.w_en.eq(1)
                    with m.If(self.output_fifo.w_rdy):
                        m.next = f"send_{i}_upper"

                with m.State(f"send_{i}_upper"):
                    m.d.comb += self.output_fifo.w_data.eq(fifo.r_data[8:16])
                    m.d.comb += self.output_fifo.w_en.eq(1)
                    with m.If(self.output_fifo.w_rdy):
                        m.d.comb += fifo.r_en.eq(1)
                        with m.If(to_transfer > 1):
                            m.next = f"send_{i}_lower"
                            m.d.sync += to_transfer.eq(to_transfer - 1)
                        with m.Else():
                            go_to_next(i)

        return m
    
    @staticmethod
    async def read_chunk(read: Callable[[int], bytes]):
        length = (await read(1))[0]
        contents = (await read(2 * length))
        return [contents[2*i+1] << 8 | contents[2*i] for i in range(length)]
