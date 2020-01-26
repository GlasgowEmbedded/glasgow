import crcmod


# CRC for the on-air format, where packets may not be a multiple of 8 bit.
def crc_nrf24l(data, *, bits):
    rem = 0xffff
    for i, byte in enumerate(data):
        if (i + 1) * 8 > bits:
            byte &= ~((1 << (8 - bits % 8)) - 1)
        rem = rem ^ (byte << 8)
        for j in range(8):
            if i * 8 + j == bits:
                return rem
            if rem & 0x8000:
                rem = (rem << 1) ^ 0x1021
            else:
                rem = rem << 1
            rem &= 0xffff
    return rem

