import pkg_resources

for entry_point in pkg_resources.iter_entry_points('glasgow'):
    entry_point.load()
