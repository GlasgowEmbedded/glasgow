import crcmod


__all__ = ["crc8_nrf24l", "crc16_nrf24l"]


def crc8_nrf24l(data, *, bits):
    rem = 0xff
    for i, byte in enumerate(data):
        if (i + 1) * 8 > bits:
            byte &= ~((1 << (8 - bits % 8)) - 1)
        rem = rem ^ byte
        for j in range(8):
            if i * 8 + j == bits:
                return rem
            if rem & 0x80:
                rem = (rem << 1) ^ 0x07
            else:
                rem = rem << 1
            rem &= 0xff
    return rem


def crc16_nrf24l(data, *, bits):
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

