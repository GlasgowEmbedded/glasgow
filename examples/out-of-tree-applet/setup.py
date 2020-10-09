from setuptools import setup, find_packages

setup(
    name="glasgow-oot",
    description="Example Out-Of-Tree Applet for Glasgow",
    license="0-clause BSD License",
    python_requires="~=3.7",
    install_requires=[
        "glasgow",
    ],
    packages=find_packages(),
    entry_points={
        "glasgow": [
            # NOTE: You don't need to specifically import the class... so long as
            #       it is loaded (e.g: via an import), the applet will be available.
            "glasgow_oot = glasgow_oot",
        ],
    },
)
