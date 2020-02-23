from collections import namedtuple

__all__ = ["devices"]

CCDevice = namedtuple("CCDevice", ["name", "flash_word_size", "flash_page_size", "write_block_size","write_protect_sizes"])

# CC1110x/CC251x
_8k_write_protect_sizes =   {0:0b111,  8:0x000}
_16k_write_protect_sizes =  {0:0b111, 16:0x000}
_32k_write_protect_sizes =  {0:0b111,  1:0b110, 2:0b101, 4:0b100,  8:0b011, 16:0b010, 24:0b001,  32:0b000}

# CC243x
_243x_32k_write_protect_sizes =  {0:0b111,  2:0b110, 4:0b101, 8:0b100, 16:0b011, 32:0b010}
_243x_64k_write_protect_sizes =  {0:0b111,  2:0b110, 4:0b101, 8:0b100, 16:0b011, 32:0b010, 64:0b001}
_243x_128k_write_protect_sizes = {0:0b111,  2:0b110, 4:0b101, 8:0b100, 16:0b011, 32:0b010, 64:0b001, 128:0b000}

devices = {
    (0x01,8):   CCDevice(name="CC1110F8",  flash_word_size=2, flash_page_size=1024, write_block_size=512,  write_protect_sizes=_8k_write_protect_sizes),
    (0x01,16):  CCDevice(name="CC1110F16", flash_word_size=2, flash_page_size=1024, write_block_size=1024, write_protect_sizes=_16k_write_protect_sizes),
    (0x01,32):  CCDevice(name="CC1110F32", flash_word_size=2, flash_page_size=1024, write_block_size=1024, write_protect_sizes=_32k_write_protect_sizes),
    (0x11,8):   CCDevice(name="CC1111F8",  flash_word_size=2, flash_page_size=1024, write_block_size=512,  write_protect_sizes=_8k_write_protect_sizes),
    (0x11,16):  CCDevice(name="CC1111F16", flash_word_size=2, flash_page_size=1024, write_block_size=1024, write_protect_sizes=_16k_write_protect_sizes),
    (0x11,32):  CCDevice(name="CC1111F32", flash_word_size=2, flash_page_size=1024, write_block_size=1024, write_protect_sizes=_32k_write_protect_sizes),
    (0x81,8):   CCDevice(name="CC2510F8",  flash_word_size=2, flash_page_size=1024, write_block_size=512,  write_protect_sizes=_8k_write_protect_sizes),
    (0x81,16):  CCDevice(name="CC2510F16", flash_word_size=2, flash_page_size=1024, write_block_size=1024, write_protect_sizes=_16k_write_protect_sizes),
    (0x81,32):  CCDevice(name="CC2510F32", flash_word_size=2, flash_page_size=1024, write_block_size=1024, write_protect_sizes=_32k_write_protect_sizes),
    (0x91,8):   CCDevice(name="CC2511F8",  flash_word_size=2, flash_page_size=1024, write_block_size=512,  write_protect_sizes=_8k_write_protect_sizes),
    (0x91,16):  CCDevice(name="CC2511F16", flash_word_size=2, flash_page_size=1024, write_block_size=1024, write_protect_sizes=_16k_write_protect_sizes),
    (0x91,32):  CCDevice(name="CC2511F32", flash_word_size=2, flash_page_size=1024, write_block_size=1024, write_protect_sizes=_32k_write_protect_sizes),
    (0x85,32):  CCDevice(name="CC2430F32", flash_word_size=4, flash_page_size=2048, write_block_size=4096, write_protect_sizes=_243x_32k_write_protect_sizes),
    (0x85,64):  CCDevice(name="CC2430F64", flash_word_size=4, flash_page_size=2048, write_block_size=4096, write_protect_sizes=_243x_64k_write_protect_sizes),
    (0x85,128): CCDevice(name="CC2430F128",flash_word_size=4, flash_page_size=2048, write_block_size=4096, write_protect_sizes=_243x_128k_write_protect_sizes),
    (0x89,32):  CCDevice(name="CC2431F32", flash_word_size=4, flash_page_size=2048, write_block_size=4096, write_protect_sizes=_243x_32k_write_protect_sizes),
    (0x89,64):  CCDevice(name="CC2431F64", flash_word_size=4, flash_page_size=2048, write_block_size=4096, write_protect_sizes=_243x_64k_write_protect_sizes),
    (0x89,128): CCDevice(name="CC2431F128",flash_word_size=4, flash_page_size=2048, write_block_size=4096, write_protect_sizes=_243x_128k_write_protect_sizes),
}
