from typing import Any, TextIO
from contextlib import AbstractAsyncContextManager, asynccontextmanager
import sys
import json
import inspect
import unittest


__all__ = ["MockRecorder", "MockReplayer"]


class MockRecorder:
    def __init__(self, case: unittest.TestCase, fixture: TextIO, mocked: Any):
        self.__case    = case
        self.__fixture = fixture
        self.__mocked  = mocked

    @staticmethod
    def __dump_object(obj):
        if isinstance(obj, bytes):
            return {"__class__": "bytes", "hex": obj.hex()}
        if isinstance(obj, bytearray):
            return {"__class__": "bytearray", "hex": obj.hex()}
        if isinstance(obj, memoryview):
            return {"__class__": "memoryview", "hex": obj.hex()}
        raise TypeError("%s is not serializable" % type(obj))

    def __dump_stanza(self, stanza):
        # TODO: remove once applets are migrated to V2 API
        if hasattr(self.__case, "_recording") and not self.__case._recording:
            return
        json.dump(fp=self.__fixture, default=self.__dump_object, obj=stanza)
        self.__fixture.write("\n")

    def __dump_method(self, call, kind, args, kwargs, result):
        self.__dump_stanza({
            "call":   call,
            "kind":   kind,
            "args":   args,
            "kwargs": kwargs,
            "result": result
        })

    def __getattr__(self, attr):
        mocked = getattr(self.__mocked, attr)
        if inspect.ismethod(mocked):
            def wrapper(*args, **kwargs):
                result = mocked(*args, **kwargs)
                if isinstance(result, AbstractAsyncContextManager):
                    @asynccontextmanager
                    async def cmgr_wrapper():
                        value = await result.__aenter__()
                        self.__dump_method(attr, "asynccontext.enter", (), {}, value)
                        try:
                            yield value
                        finally:
                            exc_type, exc_value, traceback = sys.exc_info()
                            self.__dump_method(attr, "asynccontext.exit", (exc_value,), {}, None)
                            await result.__aexit__(exc_type, exc_value, traceback)
                    return cmgr_wrapper()
                elif inspect.isawaitable(result):
                    async def coro_wrapper():
                        coro_result = await result
                        self.__dump_method(attr, "asyncmethod", args, kwargs, coro_result)
                        return coro_result
                    return coro_wrapper()
                else:
                    self.__dump_method(attr, "method", args, kwargs, result)
                    return result
            return wrapper

        return mocked


class MockReplayer:
    def __init__(self, case: unittest.TestCase, fixture: TextIO):
        self.__case    = case
        self.__fixture = fixture

    @staticmethod
    def __load_object(obj):
        if "__class__" not in obj:
            return obj
        if obj["__class__"] == "bytes":
            return bytes.fromhex(obj["hex"])
        if obj["__class__"] == "bytearray":
            return bytearray.fromhex(obj["hex"])
        if obj["__class__"] == "memoryview":
            return memoryview(bytes.fromhex(obj["hex"]))
        assert False

    def __load(self):
        json_str = self.__fixture.readline()
        return json.loads(s=json_str, object_hook=self.__load_object)

    @staticmethod
    def __upgrade(stanza):
        """Upgrade an object to the latest schema."""
        if "method" in stanza:
            stanza["call"] = stanza.pop("method")
            if stanza.pop("async"):
                stanza["kind"] = "asyncmethod"
            else:
                stanza["kind"] = "method"
        return stanza

    def __getattr__(self, attr):
        stanza = self.__upgrade(self.__load())
        self.__case.assertEqual(attr, stanza["call"])
        if stanza["kind"] == "asynccontext.enter":
            @asynccontextmanager
            async def mock():
                assert () == tuple(stanza["args"])
                assert {} == stanza["kwargs"]
                try:
                    yield stanza["result"]
                finally:
                    exc_type, exc_value, traceback = sys.exc_info()
                    exit_stanza = self.__load()
                    self.__case.assertEqual(attr, exit_stanza["call"])
                    self.__case.assertEqual("asynccontext.exit", exit_stanza["kind"])
                    self.__case.assertEqual((exc_value,), tuple(exit_stanza["args"]))
                    assert {} == exit_stanza["kwargs"]
                    assert None == exit_stanza["result"]
        elif stanza["kind"] == "asyncmethod":
            async def mock(*args, **kwargs):
                self.__case.assertEqual(args, tuple(stanza["args"]))
                self.__case.assertEqual(kwargs, stanza["kwargs"])
                return stanza["result"]
        elif stanza["kind"] == "method":
            def mock(*args, **kwargs):
                self.__case.assertEqual(args, tuple(stanza["args"]))
                self.__case.assertEqual(kwargs, stanza["kwargs"])
                return stanza["result"]
        else:
            assert False, f"unknown stanza {stanza['kind']}"
        return mock
