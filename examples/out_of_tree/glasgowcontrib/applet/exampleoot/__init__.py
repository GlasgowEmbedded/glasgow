import logging

from glasgow.applet import *


class ExampleOOTApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "example out-of-tree applet"
    description = """
    An example of an applet that is loaded from an externally installed package.

    This applet does not implement any functionality.
    """
