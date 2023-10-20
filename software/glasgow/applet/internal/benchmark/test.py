from ... import *
from . import BenchmarkApplet


class BenchmarkAppletTestCase(GlasgowAppletTestCase, applet=BenchmarkApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
