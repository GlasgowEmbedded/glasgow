from collections import namedtuple

__all__ = ["devices"]

CCDevice = namedtuple("CCDevice", ["name", "flash_word_size", "flash_page_size", "write_block_size"])

devices = {
    0x01: CCDevice(name="CC1110", flash_word_size=2, flash_page_size=1024, write_block_size=512),
    0x11: CCDevice(name="CC1111", flash_word_size=2, flash_page_size=1024, write_block_size=512),
    0x81: CCDevice(name="CC2510", flash_word_size=2, flash_page_size=1024, write_block_size=512),
    0x91: CCDevice(name="CC2511", flash_word_size=2, flash_page_size=1024, write_block_size=512),
    0x85: CCDevice(name="CC2430", flash_word_size=4, flash_page_size=2048, write_block_size=2048),
    0x89: CCDevice(name="CC2431", flash_word_size=4, flash_page_size=2048, write_block_size=2048),
}
