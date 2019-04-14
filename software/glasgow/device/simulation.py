import asyncio


__all__ = ["GlasgowSimulationDevice"]


class GlasgowSimulationDevice:
    def __init__(self, target):
        self._target = target
        self._regs   = target.registers

    @asyncio.coroutine
    def read_register(self, addr, width=1):
        assert addr < self._regs.reg_count
        yield self._regs.regs_r[addr]

    @asyncio.coroutine
    def write_register(self, addr, value, width=1):
        assert addr < self._target.registers.reg_count
        yield self._regs.regs_w[addr].eq(value)
