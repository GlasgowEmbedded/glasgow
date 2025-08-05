import enum


__all__ = ["SerprogCommand", "SerprogBus"]


class SerprogCommand(enum.IntEnum):
    """Serprog commands and responses, based on:

    - https://review.coreboot.org/plugins/gitiles/flashrom/+/refs/tags/v1.0.2/serprog.h
    - https://review.coreboot.org/plugins/gitiles/flashrom/+/refs/tags/v1.0.2/Documentation/serprog-protocol.txt
    """

    ACK               = 0x06
    NAK               = 0x15
    CMD_NOP           = 0x00    # No operation
    CMD_Q_IFACE       = 0x01    # Query interface version
    CMD_Q_CMDMAP      = 0x02    # Query supported commands bitmap
    CMD_Q_PGMNAME     = 0x03    # Query programmer name
    CMD_Q_SERBUF      = 0x04    # Query Serial Buffer Size
    CMD_Q_BUSTYPE     = 0x05    # Query supported bustypes
    CMD_Q_CHIPSIZE    = 0x06    # Query supported chipsize (2^n format)
    CMD_Q_OPBUF       = 0x07    # Query operation buffer size
    CMD_Q_WRNMAXLEN   = 0x08    # Query Write to opbuf: Write-N maximum length
    CMD_R_BYTE        = 0x09    # Read a single byte
    CMD_R_NBYTES      = 0x0A    # Read n bytes
    CMD_O_INIT        = 0x0B    # Initialize operation buffer
    CMD_O_WRITEB      = 0x0C    # Write opbuf: Write byte with address
    CMD_O_WRITEN      = 0x0D    # Write to opbuf: Write-N
    CMD_O_DELAY       = 0x0E    # Write opbuf: udelay
    CMD_O_EXEC        = 0x0F    # Execute operation buffer
    CMD_SYNCNOP       = 0x10    # Special no-operation that returns NAK+ACK
    CMD_Q_RDNMAXLEN   = 0x11    # Query read-n maximum length
    CMD_S_BUSTYPE     = 0x12    # Set used bustype(s).
    CMD_O_SPIOP       = 0x13    # Perform SPI operation.
    CMD_S_SPI_FREQ    = 0x14    # Set SPI clock frequency
    CMD_S_PIN_STATE   = 0x15    # Enable/disable output drivers


class SerprogBus(enum.IntEnum):
    """Bus types supported by the serprog protocol."""

    PARALLEL = (1 << 0)
    LPC = (1 << 1)
    FHW = (1 << 2)
    SPI = (1 << 3)
