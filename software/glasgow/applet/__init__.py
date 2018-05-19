class GlasgowApplet:
    all_applets = {}

    def __init_subclass__(cls, name, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.all_applets[name] = cls

    def __init__(self, spec):
        self.spec = spec

    @staticmethod
    def add_arguments(parser):
        pass

    def build(self, target):
        raise NotImplemented

    def run(self, device, args):
        raise NotImplemented


from .program_ice40 import ProgramICE40Applet
from .hd44780 import HD44780Applet
