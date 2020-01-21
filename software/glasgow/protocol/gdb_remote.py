import re
import logging
import asyncio
from abc import ABCMeta, abstractmethod

from ..applet import GlasgowAppletError


__all__ = ["GDBRemote"]


class GDBRemote(metaclass=ABCMeta):
    @abstractmethod
    def gdb_log(self, level, message, *args):
        pass

    @abstractmethod
    def target_word_size(self):
        pass

    @abstractmethod
    def target_endianness(self):
        pass

    @abstractmethod
    def target_triple(self):
        pass

    @abstractmethod
    def target_register_names(self):
        pass

    @abstractmethod
    def target_running(self):
        pass

    @abstractmethod
    async def target_stop(self):
        pass

    @abstractmethod
    async def target_continue(self):
        pass

    @abstractmethod
    async def target_single_step(self):
        pass

    @abstractmethod
    async def target_detach(self):
        pass

    @abstractmethod
    async def target_get_registers(self):
        pass

    @abstractmethod
    async def target_set_registers(self, registers):
        pass

    @abstractmethod
    async def target_get_register(self, number):
        pass

    @abstractmethod
    async def target_set_register(self, number, value):
        pass

    @abstractmethod
    async def target_read_memory(self, address, length):
        pass

    @abstractmethod
    async def target_write_memory(self, address, data):
        pass

    @abstractmethod
    async def target_set_software_breakpt(self, address):
        pass

    @abstractmethod
    async def target_clear_software_breakpt(self, address):
        pass

    @abstractmethod
    async def target_set_instr_breakpt(self, address):
        pass

    @abstractmethod
    async def target_clear_instr_breakpt(self, address):
        pass

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
                    self.gdb_log(logging.ERROR, "invalid checksum for command '%s'", command)
                if not no_ack_mode:
                    await endpoint.send(b"+")

                command_asc = command.decode("ascii", errors="replace")
                self.gdb_log(logging.DEBUG, "recv '%s'", command_asc)

                if command == b"QStartNoAckMode":
                    no_ack_mode = True
                    response = b"OK"
                    command_failed = False
                else:
                    try:
                        response = await self._gdb_process(command, lambda: endpoint.recv_wait())
                        command_failed = False
                    except GlasgowAppletError as e:
                        self.gdb_log(logging.ERROR, "command '%s' caused an unrecoverable "
                                                    "error: %s",
                                     command_asc, str(e))
                        response = (99, str(e))
                        command_failed = True

                if isinstance(response, tuple):
                    if not command_failed:
                        self.gdb_log(logging.WARNING, "command '%s' caused an error: %s",
                                     command_asc, response[4:].decode("ascii"))

                    error_num, error_msg = response
                    if self.__error_strings:
                        response = "E{:02d};{}".format(error_num, error_msg).encode("ascii")
                    else:
                        response = "E{:02d}".format(error_num).encode("ascii")

                while True:
                    response_asc = response.decode("ascii", errors="replace")
                    self.gdb_log(logging.DEBUG, "send '%s'", response_asc)

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
                            self.gdb_log(logging.ERROR, "unrecognized acknowledgement '%s'",
                                         ack.decode("ascii", errors="replace"))
                            await endpoint.close()
                            return

                if command_failed:
                    await endpoint.close()
                    return

        except asyncio.CancelledError:
            pass

    async def _gdb_process(self, command, make_recv_fut):
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
                if register is None:
                    values += b"xx" * self.target_word_size()
                else:
                    values += b"%.*x" % (self.target_word_size() * 2, register)
            return values

        # "Get specific register of the target."
        if command.startswith(b"p"):
            number = int(command[1:], 16)
            if number < len(self.target_register_names()):
                value  = await self.target_get_register(number)
                return b"%.*x" % (self.target_word_size() * 2, value)
            else:
                return (0, "unrecognized register")

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
            if number < len(self.target_register_names()):
                await self.target_set_register(number, value)
                return b"OK"
            else:
                return (0, "unrecognized register")

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
            address, _kind = map(lambda x: int(x, 16), command[3:].split(b","))
            if await self.target_set_software_breakpt(address):
                return b"OK"
            else:
                return (0, "cannot set software breakpoint")

        # "Clear software breakpoint."
        if command.startswith(b"z0"):
            address, _kind = map(lambda x: int(x, 16), command[3:].split(b","))
            if await self.target_clear_software_breakpt(address):
                return b"OK"
            else:
                return (0, "software breakpoint not set")

        # "Set hardware breakpoint."
        if command.startswith(b"Z1"):
            address, _kind = map(lambda x: int(x, 16), command[3:].split(b","))
            if await self.target_set_instr_breakpt(address):
                return b"OK"
            else:
                return (0, "out of hardware breakpoints")

        # "Clear hardware breakpoint."
        if command.startswith(b"z1"):
            address, _kind = map(lambda x: int(x, 16), command[3:].split(b","))
            if await self.target_clear_instr_breakpt(address):
                return b"OK"
            else:
                return (0, "hardware breakpoint not set")

        return b""
