class GlasgowApplet:
    all_applets = {}

    def __init_subclass__(cls, name, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.all_applets[name] = cls


from .program_ice40 import ProgramICE40Applet
