import logging


logging.addLevelName(5, 'TRACE')
logging.TRACE = 5
logging.Logger.trace = lambda self, msg, *args, **kwargs: \
    self.log(logging.TRACE, msg, *args, **kwargs)
