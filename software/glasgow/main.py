"""Application entry point.

This module contains utility functions that handle start-up of the Glasgow CLI as well as custom
applications based on the Glasgow API. To begin building your application, copy the following
example:

.. code:: py

    from glasgow.hardware.device import GlasgowDevice
    from glasgow.main import run_async, setup_logging

    @run_async
    async def main():
        setup_logging(level="TRACE")

        device = await GlasgowDevice.find()
        print(device.serial_number)
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from collections.abc import Callable
import os
import sys
import asyncio
import logging as pylogging
import functools

import colorama
if TYPE_CHECKING:
    from PySide6.QtCore import QCoreApplication

from .support.progress import TqdmProgressImpl


__all__ = ["setup_logging", "run_async", "run_async_qtwidgets", "run_async_qtqml"]


class _TerminalFormatter(pylogging.Formatter):
    DEFAULT_COLORS = {
        "TRACE"   : colorama.Fore.LIGHTBLACK_EX,
        "DEBUG"   : colorama.Fore.LIGHTCYAN_EX,
        "INFO"    : colorama.Fore.WHITE,
        "WARNING" : colorama.Fore.LIGHTYELLOW_EX,
        "ERROR"   : colorama.Fore.RED,
        "CRITICAL": colorama.Back.RED,
        "RESET":    colorama.Style.RESET_ALL,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.colors = dict(self.DEFAULT_COLORS)
        for color_override in os.getenv("GLASGOW_COLORS", "").split(":"):
            if color_override:
                level, color = color_override.split("=", 2)
                self.colors[level] = f"\033[{color}m"

    def format(self, record):
        color = self.colors.get(record.levelname, "")
        # glasgow.hardware.foo → g.hardware.foo
        record.name = record.name.replace("glasgow.", "g.")
        # glasgow.hardware.foo → g.h.foo
        record.name = record.name.replace("g.hardware.", "g.h.")
        # glasgow.hardware.build_plan → g.h.bp
        record.name = record.name.replace("g.h.build_plan", "g.h.bp")
        # glasgow.applet.foo → g.a.foo
        record.name = record.name.replace("g.applet.", "g.a.")
        # glasgow.applet.interface. → g.a.i.foo
        record.name = record.name.replace("g.a.interface.", "g.a.i.")
        # applet.memory._25q → applet.memory.25q
        record.name = record.name.replace("._", ".")
        return f"{color}{super().format(record)}{self.colors['RESET']}"\



def setup_logging(*, level: int | str | None = None) -> pylogging.StreamHandler:
    r"""Configure logging.

    The ANSI escape sequences used to colorize the output can be customized via
    the :envvar:`GLASGOW_COLORS` environment variable. Its value must contain a ``:``-delimited
    list of ``<key>=<value>`` pairs, where ``<key>`` is one of ``TRACE``, ``DEBUG``, ``INFO``,
    ``WARNING``, ``ERROR``, ``CRITICAL``, ``RESET``, and ``<value>`` is used as the core of
    an escape sequence :py:`"\033[<value>m"`.

    For example, to make messages with the ``TRACE`` level gray and messages with the ``INFO``
    level white, set ``GLASGOW_COLORS`` to ``TRACE=37:INFO=1;37``.

    A :class:`logging.StreamHandler` writing to :data:`sys.stderr` is created, attached to the root
    logger, and returned.
    """
    term_formatter_args = {"style": "{", "fmt": "{levelname[0]:s}: {name:s}: {message:s}"}
    if sys.stderr.isatty():
        colorama.just_fix_windows_console()
        formatter = _TerminalFormatter(**term_formatter_args)
    else:
        formatter = pylogging.Formatter(**term_formatter_args)

    term_handler = pylogging.StreamHandler(sys.stderr)
    term_handler.setFormatter(formatter)

    root_logger  = pylogging.getLogger()
    root_logger.addHandler(term_handler)
    if level is not None:
        root_logger.setLevel(level)

    return term_handler


def run_async(main: Callable[[], int | None]):
    """Configure the runtime and call :py:`main`.

    This decorator is used as a convenient way to use the Glasgow library in your own scripts.
    The :py:`main` function called from a new :mod:`asyncio` event loop after applying any
    necessary workarounds for platform and library quirks.

    Moreover, if the file with the :meth:`run_async` decorator is directly invoked from the command
    line (as opposed to being imported), it also calls the wrapped :py:`main` function, as if that
    file includes the following code immediately after the definition of :py:`main`:

    .. code:: py

        if __name__ == "__main__":
            main()
    """

    @functools.wraps(main)
    def wrapper():
        # This intercepts stdin/stdout, so do it before creating a logger or anything else that
        # might capture those file objects.
        TqdmProgressImpl().register()

        exit(asyncio.run(main()))

    if sys._getframe(1).f_globals["__name__"] == "__main__":
        wrapper()

    return wrapper


def _run_async_qt[T: QCoreApplication](main: Callable[[], int | None], *, qapp_cls: type[T]):
    from PySide6 import QtAsyncio

    @functools.wraps(main)
    def wrapper():
        # There are three options for setting up the main loop: QApplication (QtWidgets),
        # QGuiApplication (QtQml), and QCoreApplication (CLI). We have to pick one before
        # running `main()`.
        _qapp = qapp_cls(sys.argv)
        QtAsyncio.run(main(), handle_sigint=True)

    if sys._getframe(2).f_globals["__name__"] == "__main__":
        wrapper()

    return wrapper


def run_async_qtwidgets(main: Callable[[], int | None]):
    """Configure the Qt runtime and call :py:`main`.

    This decorator serves the same purpose as :func:`run_async` and works the same way, except that
    it initializes a graphical application using the QtWidgets library.
    """
    from PySide6.QtWidgets import QApplication
    return _run_async_qt(main, qapp_cls=QApplication)


def run_async_qtqml(main: Callable[[], int | None]):
    """Configure the Qt runtime and call :py:`main`.

    This decorator serves the same purpose as :func:`run_async` and works the same way, except that
    it initializes a graphical application using the QtQml library.
    """
    from PySide6.QtGui import QGuiApplication
    return _run_async_qt(main, qapp_cls=QGuiApplication)
