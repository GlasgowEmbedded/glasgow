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
            builtins = self.locals["__builtins__"]
            if "_" in builtins:
                if asyncio.iscoroutine(builtins["_"]):
                    self._fut = builtins["_"] = asyncio.ensure_future(builtins["_"])
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
