from amaranth import *


__all__ = ["LinearFeedbackShiftRegister"]


class LinearFeedbackShiftRegister(Elaboratable):
    """
    A linear feedback shift register. Useful for generating long pseudorandom sequences with
    a minimal amount of logic.

    Use ``CEInserter`` and ``ResetInserter`` transformers to control the LFSR.

    :param degree:
        Width of register, in bits.
    :type degree: int
    :param taps:
        Feedback taps, with bits numbered starting at 1 (i.e. polynomial degrees).
    :type taps: list of int
    :param reset:
        Initial value loaded into the register. Must be non-zero, or only zeroes will be
        generated.
    :type reset: int
    """
    def __init__(self, degree, taps, reset=1):
        assert reset != 0

        self.degree = degree
        self.taps   = taps
        self.reset  = reset

        self.value  = Signal(degree, reset=reset)

    def elaborate(self, platform):
        m = Module()
        feedback = 0
        for tap in self.taps:
            feedback ^= (self.value >> (tap - 1)) & 1
        m.d.sync += self.value.eq((self.value << 1) | feedback)
        return m

    def generate(self):
        """Generate every distinct value the LFSR will take."""
        value = self.reset
        mask  = (1 << self.degree) - 1
        while True:
            yield value
            feedback = 0
            for tap in self.taps:
                feedback ^= (value >> (tap - 1)) & 1
            value = ((value << 1) & mask) | feedback
            if value == self.reset:
                break
