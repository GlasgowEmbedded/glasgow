from typing import Callable, List
from amaranth import *
from amaranth.lib.fifo import SyncFIFOBuffered

from .signal_compressor import SignalCompressor
from .step_encoder import StepEncoder
from .argmax import ArgMax

class LAArbiter(Elaboratable):
    """This Logic Analyzer arbiter instanciates n Signal compressors and n Fifos and arbeites the
    output of the fifos based on priority. Its output format is one byte of 
    [4bit channel][4bit length encoded using the table below] followed by 2*length bytes of 
    compressed channel data.
    """

    LENGTH_ENCODING = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 255]

    def __init__(self, output_fifo: SyncFIFOBuffered, n_channels=16):
        self.output_fifo = output_fifo
        assert output_fifo.width == 8
        self.input = Signal(n_channels)
    
    def elaborate(self, platform):
        m = Module()

        fifos: List[SyncFIFOBuffered] = []
        encoded_fifo_levels = []
        for i, sig in enumerate(self.input):
            fifo = SyncFIFOBuffered(width=16, depth=256)  # this is exactly one ice40 bram
            m.submodules[f"fifo_{i}"] = fifo
            fifos.append(fifo)

            compressor = SignalCompressor(sig)
            m.submodules[f"compressor_{i}"] = compressor
            m.d.comb += fifo.w_en.eq(compressor.valid)
            m.d.comb += fifo.w_data.eq(compressor.value)
            
            step_encoder = StepEncoder(fifo.r_level, self.LENGTH_ENCODING)
            m.submodules[f"step_encoder_{i}"] = step_encoder
            encoded_fifo_levels.append(step_encoder.output)

        fifo_r_data = Array(fifo.r_data for fifo in fifos)
        fifo_r_en = Array(fifo.r_en for fifo in fifos)
        fifo_r_rdy = Array(fifo.r_rdy for fifo in fifos)
        length_decoding = Array(self.LENGTH_ENCODING)

        # the argmax introduces 2 cycles of latency with pipelining to meet timing
        # to acomodate for that we get the real level of the selected fifo in a combinatorial path
        # it does not matter if we select a suboptimal fifo but it is bad if we assume a wrong level
        argmax = m.submodules.argmax = ArgMax(encoded_fifo_levels, sync_levels=[1, 3])
        max_fifo_idx = argmax.max_idx
        encoded_fifo_levels_array = Array(encoded_fifo_levels)
        max_fifo_level_encoded = Signal(4)
        m.d.comb += max_fifo_level_encoded.eq(encoded_fifo_levels_array[max_fifo_idx])
        max_fifo_level = Signal(8)
        m.d.comb += max_fifo_level.eq(length_decoding[max_fifo_level_encoded])
        max_fifo_r_rdy = Signal()
        m.d.comb += max_fifo_r_rdy.eq(fifo_r_rdy[max_fifo_idx])

        to_transfer = Signal(4)
        current_channel = Signal(4)
        with m.FSM():
            with m.State("wait"):
                with m.If(max_fifo_r_rdy):
                    m.next = "announce"

            with m.State("announce"):
                m.d.sync += to_transfer.eq(max_fifo_level)
                m.d.sync += current_channel.eq(max_fifo_idx)

                m.d.comb += self.output_fifo.w_data.eq(Cat(max_fifo_idx, max_fifo_level_encoded))
                m.d.comb += self.output_fifo.w_en.eq(max_fifo_r_rdy)
                with m.If(~max_fifo_r_rdy):
                    m.next = "wait"
                with m.Elif(self.output_fifo.w_rdy):
                    m.next = "send_lower"

            with m.State("send_lower"):
                    m.d.comb += self.output_fifo.w_data.eq(fifo_r_data[current_channel][0:8])
                    m.d.comb += self.output_fifo.w_en.eq(1)
                    with m.If(self.output_fifo.w_rdy):
                        m.next = "send_upper"
            with m.State("send_upper"):
                m.d.comb += self.output_fifo.w_data.eq(fifo_r_data[current_channel][8:16])
                m.d.comb += self.output_fifo.w_en.eq(1)
                with m.If(self.output_fifo.w_rdy):
                    m.d.comb += fifo_r_en[current_channel].eq(1)
                    with m.If(to_transfer > 1):
                        m.next = "send_lower"
                        m.d.sync += to_transfer.eq(to_transfer - 1)
                    with m.Else():
                        with m.If(max_fifo_r_rdy):
                            m.next = "announce"
                        with m.Else():
                            m.next = "wait"

        return m
    
    @staticmethod
    async def read_chunk(read: Callable[[int], bytes]):
        header = (await read(1))[0]
        if header is None:
            return None
        channel = header & 0b1111
        length_encoded = header >> 4
        length = LAArbiter.LENGTH_ENCODING[length_encoded]
        contents = (await read(2 * length))
        if contents is None:
            return None
        return channel, [contents[2*i+1] << 8 | contents[2*i] for i in range(length)]
