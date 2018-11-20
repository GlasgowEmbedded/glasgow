import os
from os import path

from setuptools import setup, find_packages
from setuptools.command.build_ext import build_ext
from setuptools.command.bdist_egg import bdist_egg

from distutils import log
from distutils.spawn import spawn
from distutils.dir_util import mkpath
from distutils.errors import DistutilsExecError


class GlasgowBuildExt(build_ext):
    def run(self):
        try:
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
    version="0.1",
    author="whitequark",
    author_email="whitequark@whitequark.org",
    #description="TODO",
    #long_description="""TODO""",
    license="0-clause BSD License",
    install_requires=["migen", "fx2>=0.6", "pyvcd", "bitarray", "crcmod"],
    dependency_links=[
        "git+https://github.com/m-labs/migen.git#egg=migen",
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
    },
    project_urls={
        #"Documentation": "https://glasgow.readthedocs.io/",
        "Source Code": "https://github.com/whitequark/Glasgow",
        "Bug Tracker": "https://github.com/whitequark/Glasgow/issues",
    }
)
