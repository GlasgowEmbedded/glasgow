from amaranth import *
from amaranth.lib import wiring, io


__all__ = ["GlasgowPlatformPort", "GlasgowPlatform"]


class GlasgowPlatformPort(io.PortLike):
    def __init__(self, *, io, oe=None):
        assert oe is None or len(io) == len(oe)
        self._io_port = io
        self._oe_port = oe

    @property
    def io_port(self):
        return self._io_port

    @property
    def oe_port(self):
        return self._oe_port

    @property
    def direction(self):
        return self.io_port.direction

    def __len__(self):
        return len(self.io_port)

    def __invert__(self):
        return GlasgowPlatformPort(io=~self.io_port, oe=self.oe_port)

    def __getitem__(self, key):
        if self.oe_port is None:
            return GlasgowPlatformPort(io=self.io_port[key])
        else:
            return GlasgowPlatformPort(io=self.io_port[key], oe=self.oe_port[key])

    def __add__(self, other):
        if type(other) is GlasgowPlatformPort:
            if self.oe_port is None and other.oe_port is None:
                return GlasgowPlatformPort(io=self.io_port + other.io_port)
            elif self.oe_port is not None and other.oe_port is not None:
                return GlasgowPlatformPort(io=self.io_port + other.io_port,
                                           oe=self.oe_port + other.oe_port)
            assert False
        else:
            return NotImplemented


class GlasgowPlatform:
    def _init_glasgow_pins(self, *clauses):
        self.glasgow_pins = {}
        for glasgow_prefix, amaranth_prefix, numbers in clauses:
            for number in numbers:
                port_name = f"{glasgow_prefix}{number}" if len(numbers) > 1 else glasgow_prefix
                pin_parts = self.request(amaranth_prefix, number, dir={"io": "-", "oe": "-"})
                self.glasgow_pins[port_name] = GlasgowPlatformPort(
                    io=pin_parts.io, oe=getattr(pin_parts, "oe", None))

    @property
    def file_templates(self):
        # Do not require yosys to be present for toolchain_prepare() to finish.
        file_templates = dict(super().file_templates)
        del file_templates["{{name}}.debug.v"]
        return file_templates

    def toolchain_program(self, products, name):
        bitstream = products.get(f"{name}.bin")
        async def do_program():
            from ..device import GlasgowDevice
            device = GlasgowDevice()
            await device.download_bitstream(bitstream)
            device.close()
        asyncio.get_event_loop().run_until_complete(do_program())

    def get_io_buffer(self, buffer):
        if isinstance(buffer.port, GlasgowPlatformPort):
            m = Module()
            # Determine the domains that clocked buffers must belong to.
            i_domain_kwarg, o_domain_kwarg = dict(), dict()
            if isinstance(buffer, (io.FFBuffer, io.DDRBuffer)):
                i_domain_kwarg = dict(i_domain=buffer.i_domain)
                o_domain_kwarg = dict(o_domain=buffer.o_domain)
            # Create an inner buffer of the same type driving `io_port`.
            m.submodules.io = io_buffer = type(buffer)(buffer.direction, buffer.port.io_port,
                                                       **i_domain_kwarg, **o_domain_kwarg)
            wiring.connect(m, wiring.flipped(buffer), io_buffer)
            # If necessary (on revC+), create another buffer driving `oe_port` while being careful
            # to match the latency of `io_port`.
            if buffer.port.oe_port is not None:
                m.submodules.oe = oe_buffer = type(buffer)("o", buffer.port.oe_port,
                                                           **o_domain_kwarg)
                if buffer.direction in (io.Direction.Output, io.Direction.Bidir):
                    oe_wide = buffer.oe.replicate(len(buffer.port.oe_port))
                    if isinstance(buffer, (io.Buffer, io.FFBuffer)):
                        m.d.comb += oe_buffer.o.eq(oe_wide)
                    elif isinstance(buffer, io.DDRBuffer):
                        m.d.comb += oe_buffer.o.eq(oe_wide.replicate(2))
                    else:
                        raise TypeError(f"I/O buffer {buffer!r} is not supported")
            return m
        else:
            return super().get_io_buffer(buffer)
