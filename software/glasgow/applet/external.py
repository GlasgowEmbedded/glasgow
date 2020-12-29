import os
import sys
import logging
import traceback
import pkg_resources

logger = logging.getLogger(__name__)

if "GLASGOW_DISABLE_OOT" not in os.environ:
    for entry_point in pkg_resources.iter_entry_points('glasgow'):
        try:
            entry_point.load()
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            exc_frame = traceback.extract_tb(exc_tb)[-1]
            exc_source = "{}:{}".format(exc_frame.filename, exc_frame.lineno)
            logger.error("failed to load external applet: %s: %s: %s", entry_point.name, exc_source, e)
