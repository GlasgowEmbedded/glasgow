import pkg_resources
try:
    __version__ = pkg_resources.get_distribution(__name__).version
except pkg_resources.DistributionNotFound:
    __version__ = 'unknown'

import logging


logging.addLevelName(5, "TRACE")
logging.TRACE = 5
logging.Logger.trace = lambda self, msg, *args, **kwargs: \
    self.log(logging.TRACE, msg, *args, **kwargs)
