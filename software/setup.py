from os import path

from setuptools import setup, find_packages
from setuptools.command.build_ext import build_ext
from setuptools.command.bdist_egg import bdist_egg

from distutils.spawn import spawn
from distutils.dir_util import mkpath


class GlasgowBuildExt(build_ext):
    def run(self):
        firmware_dir = path.join("..", "firmware")
        spawn(["make", "-C", path.join(firmware_dir)], dry_run=self.dry_run)

        bootloader_ihex = path.join(firmware_dir, "glasgow.ihex")
        self.copy_file(bootloader_ihex, "glasgow")


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
    install_requires=["fx2"],
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
