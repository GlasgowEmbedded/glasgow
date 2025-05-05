import re
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
        self.__non_stop = False
        self.__error_strings = False

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
                    if self.__error_strings:
                        response = f"E{error_num:02d};{error_msg}".encode("ascii")
                    else:
                        response = f"E{error_num:02d}".encode("ascii")

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

        # (lldb) "Send me human-readable error messages."
        if command == b"QEnableErrorStrings":
            self.__error_strings = True
            return b"OK"

        # (lldb) "What are the properties of machine the target is running on?"
        if command == b"qHostInfo":
            info = [
                (b"ptrsize", self.target_word_size()),
                (b"endian",  self.target_endianness()),
                (b"triple",  self.target_triple()),
            ]
            return b"".join(b"%b:%b;" % (key, str(value).encode("ascii"))
                            for key, value in info)

        # "I support these protocol features. Which protocol features are supported by the stub?"
        if command.startswith(b"qSupported"):
            return b"qXfer:features:read+"

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
            return b"S05"

        # "Resume target."
        if command == b"c":
            continue_fut  = asyncio.ensure_future(self.target_continue())
            interrupt_fut = asyncio.ensure_future(make_recv_fut())
            await asyncio.wait([continue_fut, interrupt_fut], return_when=asyncio.FIRST_COMPLETED)
            if interrupt_fut.done():
                await interrupt_fut
            else:
                interrupt_fut.cancel()
            if continue_fut.done():
                await continue_fut
            else:
                continue_fut.cancel()
                await self.target_stop()
            return b"S05"

        # "Single-step target [but first jump to this address]."
        if command == b"s":
            await self.target_single_step()
            return b"S05"

        # "Detach from target."
        if command == b"D":
            await self.target_detach()
            return b"OK"

        # "Get all registers of the target."
        if command == b"g":
            values = bytearray()
            for register in await self.target_get_registers():
                values += b"%.*x" % (self.target_word_size() * 2, register)
            return values

        # "Get specific register of the target."
        if command.startswith(b"p"):
            number = int(command[1:], 16)
            value  = await self.target_get_register(number)
            return b"%.*x" % (self.target_word_size() * 2, value)

        # "Set all registers of the target."
        if command.startswith(b"G"):
            values = command[1:]
            registers = []
            while values:
                registers.append(int(values[:self.target_word_size() * 2]))
                values = values[self.target_word_size() * 2:]
            await self.target_set_registers(registers)

        # "Set specific register of the target."
        if command.startswith(b"P"):
            number, value = map(lambda x: int(x, 16), command[1:].split(b"="))
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

        return b""
