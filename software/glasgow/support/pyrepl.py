import os
import code
import asyncio
import readline


__all__ = ["AsyncInteractiveConsole"]


class _FutureResult(Exception):
    pass


import readline

class AsyncInteractiveConsole(code.InteractiveConsole):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._histfile = os.path.expanduser("~/.glasgow-history")
        try:
            readline.read_history_file(self._histfile)
        except FileNotFoundError:
            pass

        self._fut = None

    def save_history(self):
        readline.set_history_length(1000)
        readline.write_history_file(self._histfile)

    def runcode(self, code):
        try:
            exec(code, self.locals)
            result = self.locals["__builtins__"]["_"]
            if asyncio.iscoroutine(result):
                self._fut = self.locals["__builtins__"]["_"] = asyncio.ensure_future(result)
        except SystemExit:
            raise
        except:
            self.showtraceback()
        if self._fut:
            raise _FutureResult

    async def interact(self):
        while True:
            try:
                super().interact(banner="")
                break
            except _FutureResult:
                self.resetbuffer()
                try:
                    if not self._fut.done():
                        result = await self._fut
                    else:
                        result = self._fut.result()
                    if result is not None:
                        print(repr(result))
                except Exception as e:
                    self.showtraceback()
                self._fut = None
        self.save_history()
