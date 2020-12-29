from setuptools import setup, find_packages


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
    python_requires="~=3.7",
    setup_requires=[
        "setuptools",
        "setuptools_scm"
    ],
    install_requires=[
        "nmigen",
        "fx2>=0.9",
        "libusb1>=1.8.1",
        "aiohttp",
        "pyvcd",
        "bitarray",
        "crcmod",
    ],
    extras_require={
        "toolchain": [
            "nmigen-yosys",
            "yowasp-yosys",
            "yowasp-nextpnr-ice40-5k",
            "yowasp-nextpnr-ice40-8k",
        ],
    },
    dependency_links=[
        "git+https://github.com/nmigen/nmigen.git#egg=nmigen",
    ],
    packages=find_packages(),
    package_data={"glasgow.device": ["firmware.ihex"]},
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
    project_urls={
        #"Documentation": "https://glasgow.readthedocs.io/",
        "Source Code": "https://github.com/GlasgowEmebedded/Glasgow",
        "Bug Tracker": "https://github.com/GlasgowEmebedded/Glasgow/issues",
    }
)
