import re
import os
import ast
import sys
import logging
import asyncio
import typing
from abc import ABCMeta, abstractmethod

from ..applet import GlasgowAppletError


__all__ = ["GDBRemote", "GDBRemoteError"]


class GDBRemoteError(Exception):
    pass


class GDBRemote(metaclass=ABCMeta):
    @abstractmethod
    def gdb_log(self, level, message, *args):
        pass

    @abstractmethod
    def target_word_size(self) -> int:
        """Target word size, in bytes."""

    @abstractmethod
    def target_endianness(self) -> typing.Literal["big", "little"]:
        """Target endianness; either ``"big"`` or ``"little"``."""

    @abstractmethod
    def target_triple(self) -> str:
        """Target triple."""

    @abstractmethod
    def target_features(self) -> dict[str, bytes]:
        """Target features. Notable keys include ``target.xml``."""

    @abstractmethod
    def target_running(self) -> bool:
        """Whether the target is running. ``True`` if running, ``False`` if halted."""

    @abstractmethod
    async def target_stop(self):
        """Stops the target. Only called if ``target_running() == True``."""

    @abstractmethod
    async def target_continue(self):
        """Resumes the target. Only called if ``target_running() == False``."""

    @abstractmethod
    async def target_single_step(self):
        """Single-steps the target. Only called if ``target_running() == False``."""

    @abstractmethod
    async def target_detach(self):
        """Detaches from the target. Typically, this method clears all breakpoints and resumes
        execution."""

    @abstractmethod
    async def target_get_registers(self) -> list[int]:
        """Returns the values of all registers, in the order GDB expects them to be in."""

    @abstractmethod
    async def target_set_registers(self, values: list[int]):
        """Updates the values of all registers, in the order GDB expects them to be in."""

    @abstractmethod
    async def target_get_register(self, number: int) -> int:
        """Returns the value of one register, with the number GDB uses."""

    @abstractmethod
    async def target_set_register(self, number: int, value: int):
        """Updates the value of one register, with the number GDB uses."""

    @abstractmethod
    async def target_read_memory(self, address: int, length: int) -> bytes | bytearray | memoryview:
        """Reads system memory."""

    @abstractmethod
    async def target_write_memory(self, address: int, data: bytes):
        """Writes system memory."""

    @abstractmethod
    async def target_set_software_breakpt(self, address: int, kind: int):
        """Sets software breakpoint at given address. This could fail if the memory at this address
        is not writable.

        Raises ``NotImplementedError`` if this breakpoint type isn't supported."""
        raise NotImplementedError

    @abstractmethod
    async def target_clear_software_breakpt(self, address: int, kind: int):
        """Clears software breakpoint previously set at given address.

        Raises ``NotImplementedError`` if this breakpoint type isn't supported."""
        raise NotImplementedError

    @abstractmethod
    async def target_set_instr_breakpt(self, address: int, kind: int):
        """Sets hardware breakpoint at given address. This could fail if the amount of available
        hardware breakpoints is exceeded.

        Raises ``NotImplementedError`` if this breakpoint type isn't supported."""
        raise NotImplementedError

    @abstractmethod
    async def target_clear_instr_breakpt(self, address: int, kind: int):
        """Clears hardware breakpoint previously set at given address.

        Raises ``NotImplementedError`` if this breakpoint type isn't supported."""
        raise NotImplementedError

    async def gdb_run(self, endpoint):
        self.__error_strings = None
        self.__quirk_byteorder = False
        self.__eval_environment = getattr(self, "_GDBRemote__eval_environment", {"iface": self})

        try:
            no_ack_mode = False

            while True:
                while True:
                    delimiter = await endpoint.recv(1)
                    if delimiter == b"$":
                        break
                    elif delimiter in (b"+", b"\x03"):
                        pass
                    else:
                        self.gdb_log(logging.WARN, "received junk: <%s>", delimiter.hex())

                command  = await endpoint.recv_until(b"#")
                checksum = await endpoint.recv(2)
                try:
                    checksum = int(checksum, 16)
                except ValueError:
                    checksum = -1
                if sum(command) & 0xff != checksum:
                    self.gdb_log(logging.ERROR, "invalid checksum for command %r", command)
                if not no_ack_mode:
                    await endpoint.send(b"+")

                command_asc = command.decode("ascii", errors="replace")
                self.gdb_log(logging.DEBUG, "recv %r", command_asc)

                if command == b"QStartNoAckMode":
                    no_ack_mode = True
                    response = b"OK"
                    command_failed = False
                else:
                    try:
                        response = await self._gdb_process(command, lambda: endpoint.recv_wait())
                        command_failed = False
                    except GDBRemoteError as e:
                        response = (0, str(e))
                    except NotImplementedError as e:
                        response = (98, "not implemented")
                    except GlasgowAppletError as e:
                        self.gdb_log(logging.ERROR, "command %r caused an unrecoverable "
                                                    "error: %s",
                                     command_asc, str(e))
                        response = (99, str(e))
                        command_failed = True

                if isinstance(response, tuple):
                    if not command_failed:
                        self.gdb_log(logging.WARNING, "command %r caused an error: %s",
                                     command_asc, response[1])

                    error_num, error_msg = response
                    if self.__error_strings == "lldb":
                        response = f"E{error_num:02x};{error_msg}".encode("ascii")
                    elif self.__error_strings == "gdb":
                        response = f"E.{error_msg}".encode("ascii")
                    else:
                        response = f"E{error_num:02x}".encode("ascii")

                while True:
                    response_asc = response.decode("ascii", errors="replace")
                    self.gdb_log(logging.DEBUG, "send %r", response_asc)

                    await endpoint.send(b"$%s#%02x" % (response, sum(response) & 0xff))
                    if no_ack_mode:
                        break
                    else:
                        ack = await endpoint.recv(1)
                        while ack == b"\x03":
                            ack = await endpoint.recv(1)
                        if ack == b"+":
                            break
                        elif ack == b"-":
                            continue
                        else:
                            self.gdb_log(logging.ERROR, "unrecognized acknowledgement %r",
                                         ack.decode("ascii", errors="replace"))
                            await endpoint.close()
                            return

                if command_failed:
                    await endpoint.close()
                    return

        except EOFError:
            pass

    async def _gdb_process(self, command, make_recv_fut):
        def binary_escape(data):
            return re.sub(rb"[#$}*]", lambda m: bytes([0x7d, m[0][0] ^ 0x20]), data)

        word_size, byteorder = self.target_word_size(), self.target_endianness()

        if self.__quirk_byteorder:
            # The GDB server protocol commands `gGpP` are specified as:
            #
            #    [...] Each byte of register data is described by two hex digits. The bytes with
            #    the register are transmitted in target byte order.
            #
            # Leaving aside that you must be doing some really good (or bad) drugs for this
            # way of defining the protocol that mostly uses big-endian hex numbers to look sensible
            # for you, this is an unambiguous way to do it.
            #
            # Unfortunately, LLDB then implements it as (see e.g. the function
            # `GDBRemoteCommunicationClient::WriteAllRegisters`):
            #
            #     StreamString payload;
            #     payload.PutChar('G');
            #     payload.PutBytesAsRawHex8(data.data(), data.size(),
            #                                 endian::InlHostByteOrder(),
            #                                 endian::InlHostByteOrder());
            #
            # So we have to detect LLDB somehow (`qHostInfo` is not used by GDB nor is it likely
            # to ever be used by GDB) and change the byte order to the one LLDB itself probably
            # (we can't know for sure) uses. We assume we run on the same host as LLDB.
            byteorder = sys.byteorder

        # (lldb) "Send me human-readable error messages."
        if command == b"QEnableErrorStrings":
            self.__error_strings = "lldb"
            return b"OK"

        # (lldb) "What are the properties of machine the target is running on?"
        if command == b"qHostInfo":
            if byteorder != sys.byteorder:
                self.__quirk_byteorder = True
                self.gdb_log(logging.WARNING,
                    "enabling workaround for using LLDB with a target of differing endianness; "
                    "see https://github.com/llvm/llvm-project/issues/138536 for details; "
                    "expect brokenness")

            info = [
                (b"ptrsize", self.target_word_size()),
                (b"endian",  self.target_endianness()),
                (b"triple",  self.target_triple()),
            ]
            return b"".join(b"%b:%b;" % (key, str(value).encode("ascii"))
                            for key, value in info)

        # "I support these protocol features. Which protocol features are supported by the stub?"
        if command.startswith(b"qSupported"):
            gdb_features = command[11:].split(b";")
            if b"error-message+" in gdb_features:
                self.__error_strings = "gdb"
            stub_features = [b"vContSupported+", b"qXfer:features:read+"]
            return b";".join(stub_features)

        # "Which resume actions do you support?"
        if command == b"vCont?":
            # Even though we don't actually support `C`, without it, GDB will refuse to use `vCont`.
            # And if it doesn't use `vCont`, it doesn't use single-stepping either, even though we
            # make it available under `s`. Something similar happens with `S`, where GDB will use
            # `vCont`, but will not use single-stepping unless both `s` and `S` are declared to be
            # available. (Instead, it will attempt to write a software breakpoint to memory without
            # even checking if the write succeeded.)
            return b"vCont;c;C;s;S"

        # "Please use a vCont action you don't actually support but have to declare in order for me
        # to actually do single-stepping."
        if command.startswith((b"vCont;C", b"vCont;S")):
            return (97, "unsupported vCont command")

        # "Tell me everything you know about the target features (architecture, registers, etc.)"
        if command.startswith(b"qXfer:features:read:"):
            annex, offset_length = command[20:].decode("ascii").split(":")
            offset, length = map(lambda x: int(x, 16), offset_length.split(","))
            if data := self.target_features().get(annex):
                assert isinstance(data, (bytes, bytearray))
                hex_chunk = binary_escape(data[offset:offset + length])
                if offset + length >= len(data):
                    return b"l" + hex_chunk
                else:
                    return b"m" + hex_chunk
            else:
                return (1, f"unsupported annex {annex!r}")

        # "Am I attached to a new process, or to an existing one?"
        if command == b"qAttached":
            # "Attached to an existing process"
            # Not actually a process, but we want the debugger to detach when it quits,
            # not kill the target.
            return b"1"

        # "Why is the target stopped?"
        if command == b"?":
            # This is a bit tricky. The debugger expects that the target is already stopped
            # when it connects, and so there's no "target isn't stopped yet" response [other
            # than the "non-stop" mode, which doesn't work for unrelated reasons], but we
            # don't stop targets upon connection because protocols like JTAG and SWD do not
            # require that and we want debugging to be as seamless as possible.
            #
            # So, we only stop the target when we positively have to have it stopped.
            if self.target_running():
                await self.target_stop()

            # "Target caught signal SIGTRAP."
            return b"T05thread:0;"

        # "Resume target."
        if command in (b"c", b"vCont;c"):
            continue_task = asyncio.create_task(self.target_continue())
            interrupt_fut = asyncio.ensure_future(make_recv_fut())
            await asyncio.wait([continue_task, interrupt_fut], return_when=asyncio.FIRST_COMPLETED)
            if interrupt_fut.done():
                continue_task.cancel()
                await interrupt_fut
                await asyncio.wait([continue_task]) # wait for the cancellation to finish
                assert continue_task.cancelled()
                # If we ever implement non-stop mode, then instead of blocking the entire GDB
                # remote server on continue, we'd wait on the continue future in the background
                # and notify GDB on completion.
                await self.target_stop()
            else:
                interrupt_fut.cancel()
                await continue_task
            return b"T05thread:0;"

        # "Single-step target [but first jump to this address]."
        if command == b"s" or command.startswith(b"vCont;s"):
            await self.target_single_step()
            return b"T05thread:0;"

        # "Detach from target."
        if command == b"D":
            await self.target_detach()
            return b"OK"

        # "Get all registers of the target."
        if command == b"g":
            response = bytearray()
            for value in await self.target_get_registers():
                response += value.to_bytes(word_size, byteorder)
            return response.hex().encode("ascii")

        # "Get specific register of the target."
        if command.startswith(b"p"):
            number = int(command[1:], 16)
            value  = await self.target_get_register(number)
            return value.to_bytes(word_size, byteorder).hex().encode("ascii")

        # "Set all registers of the target."
        if command.startswith(b"G"):
            values = []
            for start in range(len(command[1::word_size * 2])):
                value = int(command[start:start + word_size * 2], 16).to_bytes(word_size, "big")
                values.append(int.from_bytes(value, byteorder))
            await self.target_set_registers(values)

        # "Set specific register of the target."
        if command.startswith(b"P"):
            number, value = command[1:].split(b"=")
            number = int(number, 16)
            value  = int.from_bytes(int(value, 16).to_bytes(word_size, "big"), byteorder)
            await self.target_set_register(number, value)
            return b"OK"

        # "Read specified memory range of the target."
        if command.startswith(b"m"):
            address, length = map(lambda x: int(x, 16), command[1:].split(b","))
            data = await self.target_read_memory(address, length)
            return data.hex().encode("ascii")

        # "Write specified memory range of the target."
        if command.startswith(b"M"):
            location, data = command[1:].split(b":")
            address, _length = map(lambda x: int(x, 16), location.split(b","))
            await self.target_write_memory(address, bytes.fromhex(data.decode("ascii")))
            return b"OK"

        # "Set software breakpoint."
        if command.startswith(b"Z0"):
            address, kind = map(lambda x: int(x, 16), command[3:].split(b","))
            try:
                await self.target_set_software_breakpt(address, kind)
                return b"OK"
            except NotImplementedError:
                return b""

        # "Clear software breakpoint."
        if command.startswith(b"z0"):
            address, kind = map(lambda x: int(x, 16), command[3:].split(b","))
            try:
                await self.target_clear_software_breakpt(address, kind)
                return b"OK"
            except NotImplementedError:
                return b""

        # "Set hardware breakpoint."
        if command.startswith(b"Z1"):
            address, kind = map(lambda x: int(x, 16), command[3:].split(b","))
            try:
                await self.target_set_instr_breakpt(address, kind)
                return b"OK"
            except NotImplementedError:
                return b""

        # "Clear hardware breakpoint."
        if command.startswith(b"z1"):
            address, kind = map(lambda x: int(x, 16), command[3:].split(b","))
            try:
                await self.target_clear_instr_breakpt(address, kind)
                return b"OK"
            except NotImplementedError:
                return b""

        # "Execute this code."
        if command.startswith(b"qRcmd,"):
            enable_env_var, enable_env_value = "GLASGOW_GDB_MONITOR", "unsafe"
            if os.environ.get(enable_env_var) != enable_env_value:
                return (95,
                    f"to enable Python support in GDB monitor command, set "
                    f"{enable_env_var}={enable_env_value} in the GDB server environment"
                )

            code = bytes.fromhex(command[6:].decode("ascii")).decode("ascii")
            try:
                try: # As far as I can tell, there's no better way to do this.
                    code = compile(code, "<gdb monitor command>", "eval",
                        flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
                except SyntaxError:
                    code = compile(code, "<gdb monitor command>", "exec",
                        flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
                result = eval(code, self.__eval_environment, self.__eval_environment)
                if asyncio.iscoroutine(result):
                    result = await result
                if result is None:
                    return b"OK"
                else:
                    return f"{result!r}\n".encode("ascii").hex().encode("ascii")
            except Exception as e:
                return (96, str(e))

        return b""
