import logging
from migen.fhdl.specials import Special


__all__ = ["PLL"]


class PLL(Special):
    def __init__(self, f_in, f_out, odomain, idomain="sys", logger=None):
        super().__init__()
        self.logger  = logger or logging.getLogger(__name__)
        self.f_in    = float(f_in)
        self.f_out   = float(f_out)
        self.odomain = odomain
        self.idomain = idomain

    def rename_clock_domain(self, old, new):
        if self.idomain == old:
            self.idomain = new
        if self.odomain == old:
            self.odomain = new

    def list_clock_domains(self):
        return {self.idomain, self.odomain}
