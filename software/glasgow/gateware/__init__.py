import functools
from migen import *


__all__ = ["simulation_test"]


def simulation_test(case):
    @functools.wraps(case)
    def wrapper(self):
        def setup_wrapper():
            if hasattr(self, "simulationSetUp"):
                yield from self.simulationSetUp(self.tb)
            yield from case(self, self.tb)
        run_simulation(self.tb, setup_wrapper(), vcd_name="test.vcd")
    return wrapper
