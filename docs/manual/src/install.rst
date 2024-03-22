Installing & updating
=====================

.. _initial-setup:

Initial setup
-------------

A lot of care and effort has been put into making the use of the software stack as seamless as possible. In particular, every dependency where it is possible is shipped via the `Python package index <pypi_>`__ (including the USB driver and the FPGA toolchains) to make installation and upgrades as seamless as they can be.

If these instructions don't work for you, please `file a bug <file-a-bug_>`__ so that the experience can be improved for everyone.

.. _file-a-bug: https://github.com/GlasgowEmbedded/glasgow/issues/new

.. tab:: Linux

    You will need to have `git <git-lin_>`__, `Python <python-lin_>`__, and `pipx`_ installed. To install these, run:

    .. tab:: Debian

        .. code:: console

            $ sudo apt install -y --no-install-recommends git pipx
            $ pipx ensurepath

    .. tab:: Arch

        .. code:: console

            $ sudo pacman -Sy git python-pipx
            $ pipx ensurepath

    .. tab:: Fedora

        .. code:: console

            $ sudo dnf install -y git pipx
            $ pipx ensurepath

    The ``pipx ensurepath`` command may prompt you to reopen the terminal window; do so.

    Navigate to a convenient working directory and download the source code:

    .. code:: console

        $ git clone https://github.com/GlasgowEmbedded/glasgow

    Configure your system to allow access to the Glasgow hardware for anyone logged in to the physical terminal, and apply the rules to any devices that are already plugged in:

    .. code:: console

        $ sudo cp glasgow/config/70-glasgow.rules /etc/udev/rules.d
        $ sudo udevadm control --reload
        $ sudo udevadm trigger -v -c add -s usb -a idVendor=20b7 -a idProduct=9db1

    Install the Glasgow software for the current user:

    .. code:: console

        $ pipx install -e 'glasgow/software[builtin-toolchain]'

    To update the software to its newest revision, navigate to your working directory and run:

    .. code:: console

        $ git -C glasgow pull
        $ pipx reinstall glasgow

    After setup, confirm that the Glasgow utility is operational by running:

    .. code:: console

        $ glasgow --version
        $ glasgow build --rev C3 uart

    Plug in your device and confirm that it is discovered by running:

    .. code:: console

        $ glasgow list
        C3-20230729T201611Z

.. tab:: Windows

    You will need to have `git <git-win_>`__, `Python <python-win_>`__, and `pipx`_ installed.  To install git and Python, follow the instructions from their respective pages. To install pipx, run:

    .. code:: doscon

        > py -3 -m pip install --user pipx
        > py -3 -m pipx ensurepath

    The ``py -3 -m pipx ensurepath`` command may prompt you to reopen the terminal window; do so.

    Navigate to a convenient working directory (it is highly recommended to use a local directory, e.g. ``%LOCALAPPDATA%``, since running Glasgow software from a network drive or a roaming profile causes significant slowdown) and download the source code:

    .. code:: doscon

        > git clone https://github.com/GlasgowEmbedded/glasgow

    Install the Glasgow software for the current user:

    .. code:: doscon

        > pipx install -e glasgow/software[builtin-toolchain]

    To update the software to its newest revision, navigate to your working directory and run:

    .. code:: doscon

        > git -C glasgow pull
        > pipx reinstall glasgow

    After setup, confirm that the Glasgow utility is operational by running:

    .. code:: doscon

        > glasgow --version
        > glasgow build --rev C3 uart

    Plug in your device and confirm that it is discovered by running:

    .. code:: doscon

        > glasgow list
        C3-20230729T201611Z

.. tab:: macOS

    You will need to have `pipx`_ installed. If you haven't already, install `Homebrew <https://brew.sh/>`_. To install pipx, run:

    .. code:: console

        $ brew install pipx
        $ pipx ensurepath

    The ``pipx ensurepath`` command may prompt you to reopen the terminal window; do so.

    Navigate to a convenient working directory and download the source code:

    .. code:: console

        $ git clone https://github.com/GlasgowEmbedded/glasgow

    Install the Glasgow software for the current user:

    .. code:: console

        $ pipx install -e 'glasgow/software[builtin-toolchain]'

    To update the software to its newest revision, navigate to your working directory and run:

    .. code:: console

        $ git -C glasgow pull
        $ pipx reinstall glasgow

    After setup, confirm that the Glasgow utility is operational by running:

    .. code:: console

        $ glasgow --version
        $ glasgow build --rev C3 uart

    Plug in your device and confirm that it is discovered by running:

    .. code:: console

        $ glasgow list
        C3-20230729T201611Z

.. tab:: FreeBSD

    You will need to have `pipx`_, `Yosys`_, `nextpnr`_, and `icestorm`_ installed. To install these packages, run:

    .. code:: console

        $ sudo pkg install pip pipx yosys abc nextpnr icestorm
        $ pipx ensurepath

    The ``pipx ensurepath`` command may prompt you to reopen the terminal window; do so.

    Navigate to a convenient working directory and download the source code:

    .. code:: console

        $ git clone https://github.com/GlasgowEmbedded/glasgow

    Install the Glasgow software for the current user:

    .. code:: console

        $ pipx install -e 'glasgow/software'

    To update the software to its newest revision, navigate to your working directory and run:

    .. code:: console

        $ git -C glasgow pull
        $ pipx reinstall glasgow

    After setup, confirm that the Glasgow utility is operational by running:

    .. code:: console

        $ glasgow --version
        $ glasgow build --rev C3 uart

    Plug in your device and confirm that it is discovered by running:

    .. code:: console

        $ glasgow list
        C3-20230729T201611Z

.. _git-lin: https://git-scm.com/download/linux
.. _git-win: https://git-scm.com/download/win
.. _python-lin: https://www.python.org/downloads/source/
.. _python-win: https://www.python.org/downloads/windows/
.. _pypi: https://pypi.org/
.. _pipx: https://pipx.pypa.io/stable/
.. _Yosys: https://github.com/YosysHQ/yosys
.. _nextpnr: https://github.com/YosysHQ/yosys
.. _icestorm: https://github.com/YosysHQ/icestorm


Using a system FPGA toolchain
-----------------------------

The steps above install the `YoWASP`_ FPGA toolchain, which is a good low-friction option, especially for people whose primary competence is not in software, since it does not require any additional installation steps. However, the YoWASP toolchain is noticeably slower compared to a native code code toolchain (usually by a factor of less than 2×). The YoWASP toolchain is also not available for all platforms and architectures; notably, 32-bit Raspberry Pi is not covered.

If you already have the required tools (``yosys``, ``nextpnr-ice40``, ``icepack``) installed or are willing to `install <oss-cad-suite_>`__ them, you can update your profile to set the environment variable ``GLASGOW_TOOLCHAIN`` to ``system,builtin``, which prioritizes using the system tools over the YoWASP tools. The default value is ``builtin,system``, which causes the system tools to be used only if the YoWASP tools are not present or not runnable.

.. _yowasp: https://yowasp.org/
.. _oss-cad-suite: https://github.com/YosysHQ/oss-cad-suite-build


Developing the Glasgow software
-------------------------------

The steps above install the Glasgow software using ``pipx install -e``, which performs an *editable install*: changes to the downloaded source code modify the behavior of the next invocation of the ``glasgow`` tool. Changes to ``pyproject.toml``, most importantly to the dependencies or list of applet entrypoints, are not picked up until ``pipx reinstall`` is manually run.

If you want to have your global Glasgow installation be independent from the source code check-out, you can omit the ``-e`` argument in the instructions above. You can use any way of managing virtual environments for your development workflow, but we use and recommend `PDM`_.

.. _pdm: https://pdm-project.org/
