# Network Block Device (NBD) protocol, server side implementation.
# Ref: https://github.com/NetworkBlockDevice/nbd/blob/master/doc/proto.md
# Ref: https://github.com/NetworkBlockDevice/nbd/blob/master/cliserv.h
# Ref: https://github.com/NetworkBlockDevice/nbd/blob/master/nbd.h
# Accession: G00089
import asyncio, logging, struct, argparse
from dataclasses import dataclass

from glasgow.support.endpoint import *


__all__ = ["NBDServer"]


# from cliserv.h

NBD_OPT_EXPORT_NAME      = 1
NBD_OPT_ABORT            = 2
NBD_OPT_LIST             = 3
NBD_OPT_STARTTLS         = 5
NBD_OPT_INFO             = 6
NBD_OPT_GO               = 7
NBD_OPT_STRUCTURED_REPLY = 8

NBD_REP_ACK                 = (1) #/**< ACK a request. Data: option number to be acked */
NBD_REP_SERVER              = (2) #/**< Reply to NBD_OPT_LIST (one of these per server; must be followed by NBD_REP_ACK to signal the end of the list */
NBD_REP_INFO                = (3) #/**< Reply to NBD_OPT_INFO */
NBD_REP_FLAG_ERROR          = (1 << 31)   #/** If the high bit is set, the reply is an error */
NBD_REP_ERR_UNSUP           = (1 | NBD_REP_FLAG_ERROR)    #/**< Client requested an option not understood by this version of the server */
NBD_REP_ERR_POLICY          = (2 | NBD_REP_FLAG_ERROR)    #/**< Client requested an option not allowed by server configuration. (e.g., the option was disabled) */
NBD_REP_ERR_INVALID         = (3 | NBD_REP_FLAG_ERROR)    #/**< Client issued an invalid request */
NBD_REP_ERR_PLATFORM        = (4 | NBD_REP_FLAG_ERROR)    #/**< Option not supported on this platform */
NBD_REP_ERR_TLS_REQD        = (5 | NBD_REP_FLAG_ERROR)    #/**< TLS required */
NBD_REP_ERR_UNKNOWN         = (6 | NBD_REP_FLAG_ERROR)    #/**< NBD_OPT_INFO or ..._GO requested on unknown export */
NBD_REP_ERR_BLOCK_SIZE_REQD = (8 | NBD_REP_FLAG_ERROR)    #/**< Server is not willing to serve the export without the block size being negotiated */

NBD_FLAG_FIXED_NEWSTYLE = (1 << 0)
NBD_FLAG_NO_ZEROES      = (1 << 1)

#* Info types */
NBD_INFO_EXPORT    = (0)
NBD_INFO_NAME      = (1)
NBD_INFO_DESCRIPTION =   (2)
NBD_INFO_BLOCK_SIZE =(3)

# from nbd.h

NBD_CMD_READ = 0
NBD_CMD_WRITE = 1
NBD_CMD_DISC = 2
NBD_CMD_FLUSH = 3
NBD_CMD_TRIM = 4
NBD_CMD_CACHE = 5
NBD_CMD_WRITE_ZEROES = 6
NBD_CMD_BLOCK_STATUS = 7
NBD_CMD_RESIZE = 8

NBD_FLAG_HAS_FLAGS  = (1 << 0)   #/* Flags are there */
NBD_FLAG_READ_ONLY  = (1 << 1)   #/* Device is read-only */
NBD_FLAG_SEND_FLUSH = (1 << 2)   #/* Send FLUSH */
NBD_FLAG_SEND_FUA   = (1 << 3)   #/* Send FUA (Force Unit Access) */
NBD_FLAG_ROTATIONAL = (1 << 4)   #/* Use elevator algorithm - rotational media */
NBD_FLAG_SEND_TRIM  = (1 << 5)   #/* Send TRIM (discard) */
NBD_FLAG_SEND_WRITE_ZEROES = (1 << 6) #   /* Send NBD_CMD_WRITE_ZEROES */
NBD_FLAG_SEND_DF    = (1 << 7)   #/* Send NBD_CMD_FLAG_DF */
NBD_FLAG_CAN_MULTI_CONN = (1 << 8)#   /* multiple connections are okay */

# from proto.md

NBD_REQUEST_MAGIC = 0x25609513
NBD_SIMPLE_REPLY_MAGIC = 0x67446698

NBDMAGIC      = 0x4e42444d41474943
IHAVEOPT      = 0x49484156454F5054
CLISERV_MAGIC = 0x0000420281861253
REPLY_MAGIC   = 0x0003e889045565a9


@dataclass
class Request:
    flags: int
    command: int
    cookie: int
    offset: int
    length: int


class NBDServer:
    def __init__(self, endpoint, logger, *, writable=False):
        self._endpoint = endpoint
        self._logger = logger
        self._writable = writable

    # public API
    async def handle(self):
        # "The NBD protocol has two phases: the handshake and the transmission."
        await self._endpoint.recv_wait()
        await self._handshake()
        await self._transmission()

    # callbacks
    async def device_size(self):
        return 0

    async def device_read(self, offset, length):
        return bytes(length)

    async def device_write(self, offset, data):
        pass

    # internal methods
    async def _send16(self, value):
        await self._endpoint.send(struct.pack(">H", value))

    async def _send32(self, value):
        await self._endpoint.send(struct.pack(">I", value))

    async def _send64(self, value):
        await self._endpoint.send(struct.pack(">Q", value))

    async def _recv16(self):
        data = await self._endpoint.recv(2)
        return struct.unpack(">H", data)[0]

    async def _recv32(self):
        data = await self._endpoint.recv(4)
        return struct.unpack(">I", data)[0]

    async def _recv64(self):
        data = await self._endpoint.recv(8)
        return struct.unpack(">Q", data)[0]

    async def _handshake(self):
        # "During the handshake, a connection is established and an exported
        # NBD device along other protocol parameters are negotiated between the
        # client and the server."
        await self._fixed_newstyle_negotiation()

    async def _fixed_newstyle_negotiation(self):
        handshake_flags = NBD_FLAG_FIXED_NEWSTYLE | NBD_FLAG_NO_ZEROES
        await self._send64(NBDMAGIC)
        await self._send64(IHAVEOPT)
        await self._send16(handshake_flags)
        client_flags = await self._recv32()
        self._logger.trace(f'client flags: {client_flags}')
        unsupported = client_flags & ~handshake_flags
        if unsupported:
            raise RuntimeError(f"Unsupported client flags: {unsupported:#x}")
        await self._option_haggling()

    async def _option_haggling(self):
        # "At this point, we move on to option haggling, during which point the
        # client can send one or (in fixed newstyle) more options to the server"
        done = False
        while not done:
            option, data = await self._recv_option()
            self._logger.trace(f"option: {option}, {data=}")
            if option == NBD_OPT_GO:
                done = True
                await self._send_info(option)
                await self._send_option(option, NBD_REP_ACK, struct.pack('>I', option))
            else:
                self._logger.warning(f"client requested unknown option {option}")
                await self._send_option(option, NBD_REP_ERR_UNSUP)

    async def _send_info(self, option):
        transmission_flags = NBD_FLAG_HAS_FLAGS
        if not self._writable:
            transmission_flags |= NBD_FLAG_READ_ONLY

        info = struct.pack('>HQH', NBD_INFO_EXPORT, await self.device_size(), transmission_flags)
        await self._send_option(option, NBD_REP_INFO, info)

    async def _recv_option(self):
        # Receive an option from the client
        magic = await self._recv64()
        if magic != IHAVEOPT:
            raise RuntimeError(f"Expected IHAVEOPT, got {magic:08x}")
        option = await self._recv32()
        length = await self._recv32()
        data = await self._endpoint.recv(length)
        return option, data

    async def _send_option(self, option, status, data=b''):
        # Reply to a client's option request
        await self._send64(REPLY_MAGIC)
        await self._send32(option)
        await self._send32(status)
        await self._send32(len(data))
        await self._endpoint.send(data)

    async def _transmission(self):
        # "After a successful handshake, the client and the server proceed to
        # the transmission phase in which the export is read from and written
        # to."
        #
        # "There are three message types in the transmission phase: the
        # request, the simple reply, and the structured reply chunk. The
        # transmission phase consists of a series of transactions, where the
        # client submits requests and the server sends corresponding replies
        # with either a single simple reply or a series of one or more
        # structured reply chunks per request. The phase continues until either
        # side terminates transmission; this can be performed cleanly only by
        # the client."
        while True:
            req = await self._recv_request()
            self._logger.trace(f"command {req.command}, length {req.length}")
            if req.command == NBD_CMD_READ:
                data = await self.device_read(req.offset, req.length)
                await self._write_simple_reply(0, req.cookie, data)
            elif req.command == NBD_CMD_WRITE:
                data = await self._endpoint.recv(req.length)
                await self.device_write(req.offset, data)
                await self._write_simple_reply(0, req.cookie)
            elif req.command == NBD_CMD_DISC:
                await self._endpoint.close()
                break;
            else:
                await self._write_simple_reply(NBD_REP_ERR_INVALID, req.cookie)

    async def _recv_request(self):
        magic = await self._recv32()
        assert magic == NBD_REQUEST_MAGIC
        flags = await self._recv16()
        command = await self._recv16()
        cookie = await self._recv64()
        offset = await self._recv64()
        length = await self._recv32()
        return Request(flags=flags, command=command, cookie=cookie, offset=offset, length=length)

    async def _write_simple_reply(self, error, cookie, data=b''):
        await self._send32(NBD_SIMPLE_REPLY_MAGIC)
        await self._send32(error)
        await self._send64(cookie)
        await self._endpoint.send(data)


async def main():
    parser = argparse.ArgumentParser(description='NBD ramdisk')
    parser.add_argument('--size', type=int, help='size in bytes', default=0x100000)
    ServerEndpoint.add_argument(parser, "endpoint")
    args = parser.parse_args()

    logging.basicConfig(level=logging.TRACE)
    logger = logging.getLogger(__name__)

    disk = bytearray(args.size)
    class Ramdisk(NBDServer):
        async def device_size(self):
            return args.size

        async def device_read(self, offset, length):
            return disk[offset:offset+length]

        async def device_write(self, offset, data):
            disk[offset:offset+len(data)] = data

    endpoint = await ServerEndpoint("socket", logger, args.endpoint,
        deprecated_cancel_on_eof=True)
    conn = Ramdisk(endpoint, logger, writable=True)
    await conn.handle()


if __name__ == '__main__':
    asyncio.run(main())
