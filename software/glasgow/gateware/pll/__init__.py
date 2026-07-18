from __future__ import annotations
from typing import Literal
from collections.abc import Iterator
from collections import defaultdict
from dataclasses import dataclass

from amaranth import *
from amaranth import tracer
from amaranth.vendor import SiliconBluePlatform, LatticePlatform


__all__ = [
    "ConstraintError", "Degrees", "Absolute", "Channel", "ClockPlan",
    "ecp5", "ice40",
]


class ConstraintError(Exception):
    """Raised when a constraint or requirement that is a part of a clock plan is unsastisfiable."""


@dataclass(frozen=True)
class Absolute:
    """Phase delay expressed as an absolute time offset."""

    # TODO(amaranth-0.6): replace with `Period`
    value: float


@dataclass(frozen=True)
class Degrees:
    """Phase delay expressed as an angle, relative to the reference clock."""

    value: float


@dataclass(frozen=True, kw_only=True)
class Channel:
    """PLL output channel.

    Describes a single PLL output channel: its period, phase, and driven clock domain(s).

    The phase parameter measures the angle between the output clock as sampled at the clock
    domain's :py:`clk` signal (after any platform-appropriate clock buffer and clock tree injection
    delays), and the phase reference node. It can be left as :py:`None` if no specific relationship
    is required.

    Two channels with the same phase and an integer ratio of frequencies will be aligned relative
    to the falling edge of the channel with the lesser frequency.
    """

    # TODO(amaranth-0.6): replace with `Period`
    period:    float # in seconds
    phase:     None | Degrees | Absolute = None
    phase_ref: None | Channel = None
    tolerance: float = 100/1e6 # expressed as a ratio; 100 ppm by default

    def __post_init__(self):
        if self.phase is None and self.phase_ref is not None:
            raise ValueError("phase reference cannot be specified without a phase requirement")


class ClockPlan:
    """PLL clock plan.

    Describes every output channel of a PLL, their phase relationships to each other and the input
    clock, and the clock domains driven by the output channels.

    Only a small subset of expressible clock plans can actually be implemented by any specific
    hardware block. The :meth:`create` method validates the clock plan and returns a platform
    specific PLL instance implementing it. Any constraint violations are reported at the point
    where this method is called, before elaboration.

    In certain situations, the PLL must be placed explicitly; this is useful to eliminate run to
    run variability, or to work around toolchain bugs. The platform- and toolchain-specific
    :py:`location` parameter can be used to do so.
    """

    def __init__(self, ref_period: float, *, location: None | str = None):
        self._ref_period = ref_period
        self._location = location
        self._channels = defaultdict[Channel, list[ClockDomain]](lambda: [])

    @property
    def ref_period(self) -> float:
        """Period of reference clock."""
        return self._ref_period

    @property
    def location(self) -> None | str:
        """Physical location of the PLL instance, if locked."""
        return self._location

    def __len__(self) -> int:
        """Number of channels."""
        return len(self._channels)

    def __iter__(self) -> Iterator[Channel]:
        """Iterate all channels."""
        return iter(self._channels)

    def __getitem__(self, channel: Channel) -> list[ClockDomain]:
        """Retrieve clock domains that belong to a channel."""
        if channel not in self._channels:
            raise KeyError
        return list(self._channels[channel])

    def add_domain(self, channel: Channel, *, name: str | None = None,
                   clk_edge: Literal["pos", "neg"] = "pos",
                   async_reset: bool = False) -> ClockDomain:
        """Add a clock domain to a channel.

        The clock domain is always created with a reset signal that is asserted whenever the PLL
        is unlocked.

        Multiple domains can use the same channel. Whenever two :py:`channel` objects compare equal
        and the :py:`clk_edge` for them is the same, both of the corresponding clock domains will
        be driven by the same clock signal and the deassertion of their reset signals will happen
        simultaneously.
        """
        if name is None:
            name = tracer.get_var_name()
        domain = ClockDomain(name, clk_edge=clk_edge, async_reset=async_reset, local=True)
        self._channels[channel].append(domain)
        return domain

    def create(self, platform, *, domain: str = "sync", debug: bool = False) -> Elaboratable:
        """Create a PLL instance.

        The clock signal of :py:`domain` is used as the reference clock for the PLL.

        If :py:`debug` is true, a platform-specific description of the computed PLL configuration
        is printed to standard output.
        """
        # Run some generic validation first so that platform-specific code can assume they hold.
        if len(self) == 0:
            return Module() # degenerate case
        if all(channel.phase_ref is not None for channel in self):
            raise ConstraintError(f"at least one channel must use input clock as phase reference")
        for channel in self:
            if channel.phase_ref is not None:
                if channel.phase_ref not in self:
                    raise ConstraintError(
                        f"phase reference of channel {channel} is not included in the clock plan")
                if (channel.phase_ref.period != channel.period and
                        isinstance(channel.phase, Absolute)):
                    raise ConstraintError(
                        f"absolute phase delay relative to a reference channel requires channels "
                        f"to have exactly matching periods")

        match platform:
            case LatticePlatform():
                return ecp5._create(self, domain, debug=debug)
            case SiliconBluePlatform():
                return ice40._create(self, domain, debug=debug)
            case _:
                raise NotImplementedError("unsupported platform")


# Make submodules always accessible, without a need to explicitly importing them.
from . import ecp5, ice40
