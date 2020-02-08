# Top-level interface to run the Glasgow tests.

import unittest
from setuptools.command.test import ScanningLoader


if __name__ == "__main__":
    unittest.main(module="glasgow", testLoader=ScanningLoader())
