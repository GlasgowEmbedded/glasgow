import re
import os
import sys
import ast
import errno
import codeop
import signal
import logging
import asyncio
import builtins
import traceback
try:
    import readline
    import rlcompleter
except ModuleNotFoundError:
    readline = None

from .asignal import wait_for_signal


logger = logging.getLogger(__loader__.name)


class AsyncInteractiveConsole:
    def __init__(self, locals, *, run_callback=None):
        self.locals = {"__name__": "__console__", "sleep": asyncio.sleep, **locals}
        self.run_callback = run_callback

        self._buffer = []
        self._compile = codeop.CommandCompiler()
        self._compile.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT

        if readline is not None:
            self._init_readline()

    def _init_readline(self):
        self._history_filename = os.path.expanduser("~/.glasgow-history")
        try:
            readline.read_history_file(self._history_filename)
        except OSError as exc:
            if exc.errno == errno.EINVAL: # (screaming internally)
                assert "libedit" in readline.__doc__
                # i did not come up with the line above myself.
                # this is what cpython devs recommend to detect whether `import readline` imports
                # GNU readline or libedit. AAAAAAAAAA
                with open(self._history_filename, "r") as f:
                    history = f.readlines()
                assert history[:1] != ["_HiStOrY_V2_"], "History file already converted"
                backup_filename = f"{self._history_filename}.gnu"
                with open(backup_filename, "w") as f:
                    f.writelines(history)
                new_filename = f"{self._history_filename}.new"
                with open(f"{self._history_filename}.new", "w") as f:
                    f.write("_HiStOrY_V2_\n")
                    f.writelines([
                        re.sub(r"[ \\]", lambda m: f"\\{ord(m[0]):03o}", line)
                        for line in history
                    ])
                os.rename(new_filename, self._history_filename)
                logger.warning(f"this Python distribution uses libedit instead of GNU readline, "
                               f"and their history file formats are not compatible")
                logger.warning(f"REPL history file has been converted from the GNU readline format "
                               f"to the libedit format; backup saved to {backup_filename}")
                # meow, why can't libedit do this itself ;_; am sad cat
                readline.read_history_file(self._history_filename)
        except FileNotFoundError:
            pass

        completer = rlcompleter.Completer(self.locals)
        readline.parse_and_bind("tab: complete")
        readline.set_completer(completer.complete)

    def _save_readline(self):
        readline.set_history_length(1000)
        readline.write_history_file(self._history_filename)

    async def _run_code(self, code):
        try:
            future = eval(code, self.locals)
            if asyncio.iscoroutine(future):
                await future
            if self.run_callback is not None:
                await self.run_callback()
        except (SystemExit, KeyboardInterrupt, asyncio.CancelledError):
            raise
        except BaseException as e:
            lines = traceback.format_exception(type(e), e, e.__traceback__)
            print("".join(lines), end="", file=sys.stderr)

    async def _compile_line(self, line, *, filename="<console>", symbol="single"):
        self._buffer.append(line)
        try:
            code = self._compile("\n".join(self._buffer), filename, symbol)
        except (OverflowError, SyntaxError, ValueError) as e:
            self._buffer = []
            lines = traceback.format_exception_only(type(e), e)
            print("".join(lines), end="", file=sys.stderr)
        else:
            if code is not None:
                self._buffer = []
                await self._run_code(code)

    async def interact(self):
        while True:
            try:
                prompt = "... " if self._buffer else ">>> "
                try:
                    # This is a blocking call! On Windows, non-blocking stdin reads are a lot more
                    # trouble than they are worth; see python-trio/trio#174 for details. Release
                    # control to asyncio before blocking to make sure that any pending callbacks
                    # are executed.
                    await asyncio.sleep(0)
                    line = input(prompt)
                except EOFError:
                    print("", file=sys.stderr)
                    break
                else:
                    sigint_task = asyncio.ensure_future(wait_for_signal(signal.SIGINT))
                    compile_task = asyncio.ensure_future(self._compile_line(line))
                    done, pending = await asyncio.wait([sigint_task, compile_task],
                        return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
                    await compile_task
            except asyncio.CancelledError:
                print("\nasyncio.CancelledError", file=sys.stderr)
            except KeyboardInterrupt:
                print("\nKeyboardInterrupt", file=sys.stderr)
                self._buffer = []
            else:
                if readline is not None:
                    self._save_readline()
