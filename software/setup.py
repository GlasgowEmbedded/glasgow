import os
from os import path

from setuptools import setup, find_packages
from setuptools.command.build_ext import build_ext
from setuptools.command.bdist_egg import bdist_egg

from distutils import log
from distutils.spawn import spawn
from distutils.dir_util import mkpath
from distutils.errors import DistutilsExecError

import versioneer


class GlasgowBuildExt(build_ext):
    def run(self):
        try:
            libfx2_dir = path.join("..", "vendor", "libfx2", "firmware")
            spawn(["make", "-C", path.join(libfx2_dir)], dry_run=self.dry_run)

            firmware_dir = path.join("..", "firmware")
            spawn(["make", "-C", path.join(firmware_dir)], dry_run=self.dry_run)

            glasgow_ihex = path.join(firmware_dir, "glasgow.ihex")
            self.copy_file(glasgow_ihex, "glasgow")
        except DistutilsExecError as e:
            if os.access(path.join("glasgow", "glasgow.ihex"), os.R_OK):
                log.info("using prebuilt firmware")
            else:
                raise


class GlasgowBdistEgg(bdist_egg):
    def run(self):
        # Allow installing as a dependency via pip.
        self.run_command("build_ext")
        bdist_egg.run(self)


setup(
    name="glasgow",
    version=versioneer.get_version(),
    author="whitequark",
    author_email="whitequark@whitequark.org",
    #description="TODO",
    #long_description="""TODO""",
    license="0-clause BSD License",
    install_requires=[
        "versioneer",
        "migen>=0.9.1",
        "fx2>=0.6",
        "libusb1>=1.6.6",
        "aiohttp",
        "pyvcd",
        "bitarray",
        "crcmod",
    ],
    packages=find_packages(),
    package_data={"": ["*.ihex"]},
    entry_points={
        "console_scripts": [
            "glasgow = glasgow.cli:main"
        ],
    },
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved', # ' :: 0-clause BSD License', (not in PyPI)
        'Topic :: Software Development :: Embedded Systems',
        'Topic :: System :: Hardware',
    ],
    cmdclass={
        "build_ext": GlasgowBuildExt,
        "bdist_egg": GlasgowBdistEgg,
        **versioneer.get_cmdclass()
    },
    project_urls={
        #"Documentation": "https://glasgow.readthedocs.io/",
        "Source Code": "https://github.com/GlasgowEmebedded/Glasgow",
        "Bug Tracker": "https://github.com/GlasgowEmebedded/Glasgow/issues",
    }
)
