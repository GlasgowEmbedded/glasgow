import sys
import os
from os import path

from setuptools import setup, find_packages
from setuptools.command.build_ext import build_ext
from setuptools.command.bdist_egg import bdist_egg
from setuptools.command.sdist import sdist

from distutils import log
from distutils.spawn import spawn
from distutils.dir_util import mkpath
from distutils.errors import DistutilsExecError


class GlasgowBuildExt(build_ext):
    def run(self):
        try:
            libfx2_dir = path.join("..", "vendor", "libfx2", "firmware", "library")
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


class GlasgowSdist(sdist):
    def run(self):
        # Make sure the included ihex files are up to date.
        self.run_command("build_ext")
        sdist.run(self)


def scm_version():
    def local_scheme(version):
        return version.format_choice("+{node}", "+{node}.dirty")
    return {
        "root": "..",
        "relative_to": __file__,
        "version_scheme": "guess-next-dev",
        "local_scheme": local_scheme
    }


setup(
    name="glasgow",
    use_scm_version=scm_version(),
    author="whitequark",
    author_email="whitequark@whitequark.org",
    description="Software for Glasgow, a digital interface multitool",
    #long_description="""TODO""",
    license="0-clause BSD License",
    python_requires="~=3.6",
    setup_requires=[
        "setuptools",
        "setuptools_scm"
    ],
    install_requires=[
        "nmigen",
        "fx2>=0.9",
        "libusb1>=1.6.6",
        "aiohttp",
        "pyvcd",
        "bitarray",
        "crcmod",
    ],
    dependency_links=[
        "git+https://github.com/nmigen/nmigen.git#egg=nmigen",
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
        "sdist": GlasgowSdist,
    },
    project_urls={
        #"Documentation": "https://glasgow.readthedocs.io/",
        "Source Code": "https://github.com/GlasgowEmebedded/Glasgow",
        "Bug Tracker": "https://github.com/GlasgowEmebedded/Glasgow/issues",
    }
)
