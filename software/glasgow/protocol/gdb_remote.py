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
    def target_running(self):
        pass

    @abstractmethod
    async def target_stop(self):
        pass

    @abstractmethod
    async def target_resume(self):
        pass

    @abstractmethod
    async def target_single_step(self, addr=None):
        pass

    @abstractmethod
    async def target_get_registers(self):
        pass

    @abstractmethod
    async def target_read_memory(self, address, length):
        pass

    @abstractmethod
    async def target_write_memory(self, address, data):
        pass

    async def gdb_run(self, endpoint):
        self.__non_stop = False

        try:
            no_ack_mode = False

            while True:
                while True:
                    delimiter = await endpoint.recv(1)
                    if delimiter in (b"$", b"\x03"):
                        break
                    elif delimiter == b"+":
                        pass
                    else:
                        self.gdb_log(logging.WARN, "received junk: <%s>", delimiter.hex())

                if delimiter == b"$":
                    command  = await endpoint.recv_until(b"#")
                    checksum = await endpoint.recv(2)
                    try:
                        checksum = int(checksum, 16)
                    except ValueError:
                        checksum = -1
                    if sum(command) & 0xff != checksum:
                        self.gdb_log(logging.ERROR, "invalid checksum for command <%s>", command)
                elif delimiter == b"\x03":
                    command  = b"^C"
                if not no_ack_mode:
                    await endpoint.send(b"+")

                command_asc = command.decode("ascii", errors="replace")
                self.gdb_log(logging.DEBUG, "recv <%s>", command_asc)

                if command == b"QStartNoAckMode":
                    no_ack_mode = True
                    response = b"OK"
                else:
                    try:
                        response = await self.gdb_process(command)
                        command_failed = False
                    except GlasgowAppletError as e:
                        self.gdb_log(logging.ERROR, "command <%s> caused an error: %s",
                                     command_asc, str(e))
                        response = b"E00;%s" % str(e).encode("ascii")
                        command_failed = True

                while True:
                    response_asc = response.decode("ascii", errors="replace")
                    self.gdb_log(logging.DEBUG, "send <%s>", response_asc)

                    await endpoint.send(b"$%s#%02x" % (response, sum(response) & 0xff))
                    if no_ack_mode:
                        break
                    else:
                        ack = await endpoint.recv(1)
                        if ack == b"+":
                            break
                        elif ack == b"-":
                            continue
                        else:
                            self.gdb_log(logging.error, "unrecognized acknowledgement")
                            endpoint.close()

                if command_failed:
                    await endpoint.close()

        except asyncio.CancelledError:
            pass

    async def gdb_process(self, command):
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

            # "Target caught signal 0."
            # Not an actual signal, just needed for protocol compliance.
            return b"S00"

        # "Resume target."
        if command == b"c":
            await self.target_resume()
            return b"OK"

        # "Single-step target [but first jump to this address]."
        if command.startswith(b"s"):
            if len(command) > 1:
                address = int(command[1:], 16)
            else:
                address = None
            await self.target_single_step(address)
            return b"S00"

        # "Interrupt target."
        if command == b"^C":
            await self.target_stop()
            return b"S00"

        # "Detach from target."
        if command == b"D":
            if not self.target_running():
                await self.target_resume()
            return b"OK"

        # "Get all registers of the target."
        if command == b"g":
            registers = bytearray()
            for register in await self.target_get_registers():
                if register is None:
                    registers += b"xx" * self.target_word_size()
                else:
                    registers += b"%.*x" % (self.target_word_size() * 2, register)
            return registers

        # "Get specific register of the target."
        if command.startswith(b"p"):
            number = int(command[1:], 16)
            value  = await self.target_get_register(number)
            return b"%.*x" % (self.target_word_size() * 2, value)

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

        return b""
