import os
import code
import asyncio
import builtins
try:
    import readline
    import rlcompleter
except ModuleNotFoundError:
    readline = None


__all__ = ["AsyncInteractiveConsole"]


class _FutureResult(Exception):
    pass


class AsyncInteractiveConsole(code.InteractiveConsole):
    def __init__(self, *args, run_callback=None, **kwargs):
        super().__init__(*args, **kwargs)

        if readline is not None:
            self._histfile = os.path.expanduser("~/.glasgow-history")
            try:
                readline.read_history_file(self._histfile)
            except FileNotFoundError:
                pass

            completer = rlcompleter.Completer(self.locals)
            readline.parse_and_bind("tab: complete")
            readline.set_completer(completer.complete)

        self.locals["__name__"] = __name__.split(".")[0]
        self.run_callback = run_callback
        self._future = None

    def save_history(self):
        if readline is not None:
            readline.set_history_length(1000)
            readline.write_history_file(self._histfile)

    def runcode(self, code):
        try:
            exec(code, self.locals)
            if hasattr(builtins, "_"):
                if asyncio.iscoroutine(builtins._):
                    async def run_and_wait():
                        result = await builtins._
                        if self.run_callback is not None:
                            await self.run_callback()
                        return result
                    self._future = asyncio.ensure_future(run_and_wait())
        except SystemExit:
            raise
        except:
            self.showtraceback()
        if self._future:
            raise _FutureResult

    async def interact(self):
        while True:
            try:
                super().interact(banner="", exitmsg="")
                break
            except _FutureResult:
                self.resetbuffer()
                try:
                    if not self._future.done():
                        result = await self._future
                    else:
                        result = self._future.result()
                    builtins._ = result
                    if result is not None:
                        print(repr(result))
                except Exception as e:
                    self.showtraceback()
                self._future = None
        self.save_history()
