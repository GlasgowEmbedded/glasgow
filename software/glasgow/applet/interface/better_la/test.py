import unittest
import random
from amaranth import *

from ....gateware import simulation_test
from ....applet import GlasgowAppletTestCase, applet_simulation_test, synthesis_test
from .signal_compressor import SignalCompressor
from .arbeiter import LAArbeiter
from . import BetterLAApplet


class SignalCompressorTestCase(unittest.TestCase):
    def setUp(self):
        self.tb = SignalCompressor(Signal(name="input"))

    @simulation_test
    def test_rlu(self, tb):
        for _ in range(100):
            yield
        yield self.tb.signal.eq(1)
        for _ in range(100):
            yield
        yield self.tb.signal.eq(0)
        yield

        assert (yield self.tb.valid) == 1
        duration_list = SignalCompressor.decode_pkg((yield self.tb.value))
        assert SignalCompressor.expand_duration_list(duration_list) == [1] * 100

    @simulation_test
    def test_fallback(self, tb):
        tx_string = "1011001001010000111100010010011100011100101010001010111001111000"
        tx = [int(x) for x in tx_string]

        rx = []
        for x in tx:
            yield self.tb.signal.eq(x)
            if (yield self.tb.valid):
                rx.append((yield self.tb.value))
            yield


        decoded = []
        for pkg in rx:
            decoded.extend(SignalCompressor.expand_duration_list(SignalCompressor.decode_pkg(pkg)))
        
        print(f"saved {100 - (len(rx) * 16 / len(decoded) * 100)}%")
        assert decoded[2:] == tx[:len(decoded)-2]

    @simulation_test
    def test_decode(self, tb):
        random.seed(0)
        tx = []
        for _ in range(100):
            val = random.randint(0, 1)
            length = random.randint(1, 7) if random.randint(0, 1) else random.randint(1, 250)
            tx.extend(val for _ in range(length))
        
        rx = []
        for x in tx:
            yield self.tb.signal.eq(x)
            if (yield self.tb.valid):
                rx.append((yield self.tb.value))
            yield


        decoded = []
        for pkg in rx:
            decoded.extend(SignalCompressor.expand_duration_list(SignalCompressor.decode_pkg(pkg)))
        
        print(f"saved {100 - (len(rx) * 16 / len(decoded) * 100)}%")
        assert decoded[2:] == tx[:len(decoded)-2]


class BetterLAAppletTestCase(GlasgowAppletTestCase, applet=BetterLAApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def setup_demo_source(self):
        self.build_simulated_applet()
        mux_iface = self.applet.mux_interface
        m = Module()
        m.d.sync += mux_iface.pads.i_t.i.eq(mux_iface.pads.i_t.i + 1)
        self.target.add_submodule(m)

    @applet_simulation_test("setup_demo_source", ["--pins-i", "0:15"])
    async def test_smoke(self):
        applet = await self.run_simulated_applet()
        channels = [[] for _ in range(16)]
        for _ in range(15):
            for n, channel in enumerate(channels):
                chunk = await LAArbeiter.read_chunk(applet.read)
                assert len(chunk) < 255 - 16
                for pkg in chunk:
                    duration_list = SignalCompressor.decode_pkg(pkg)
                    expanded = SignalCompressor.expand_duration_list(duration_list)
                    channel.extend(expanded)
        for i, channel in enumerate(channels):
            duration = 0
            last = 0
            for j, x in enumerate(channel[3:]):
                if x == last:
                    duration += 1
                else:
                    assert duration == 2**i, f"channel {i} at position {j}"
                    duration = 1
                    last = x
