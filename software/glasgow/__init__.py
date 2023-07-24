from importlib import metadata as importlib_metadata

__version__ = importlib_metadata.version(__package__)

import logging


logging.addLevelName(5, "TRACE")
logging.TRACE = 5
logging.Logger.trace = lambda self, msg, *args, **kwargs: \
    self.log(logging.TRACE, msg, *args, **kwargs)
