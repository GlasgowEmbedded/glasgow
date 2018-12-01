import functools
from migen import *


__all__ = ["GatewareBuildError", "simulation_test"]


class GatewareBuildError(Exception):
    pass


def simulation_test(case=None, **kwargs):
    def configure_wrapper(case):
        @functools.wraps(case)
        def wrapper(self):
            if hasattr(self, "configure"):
                self.configure(self.tb, **kwargs)
            def setup_wrapper():
                if hasattr(self, "simulationSetUp"):
                    yield from self.simulationSetUp(self.tb)
                yield from case(self, self.tb)
            run_simulation(self.tb, setup_wrapper(), vcd_name="test.vcd")
        return wrapper

    if case is None:
        return configure_wrapper
    else:
        return configure_wrapper(case)
