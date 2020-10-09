import os
import pkg_resources

if "GLASGOW_DISABLE_OOT" not in os.environ:
    for entry_point in pkg_resources.iter_entry_points('glasgow'):
        entry_point.load()
