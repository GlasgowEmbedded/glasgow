from glasgow.arch.i2c import ProbeDevice


__all__ = ["devices"]


devices = [
    ProbeDevice("Bosch Sensortec", "BMP280",
        {0b1110110, 0b1110111}, "S AW 0xD0 Sr AR 0x58 P"),
    ProbeDevice("Bosch Sensortec", "BME280",
        {0b1110110, 0b1110111}, "S AW 0xD0 Sr AR 0x60 P"),

    ProbeDevice("InvenSense", "MPU-60X0",
        {0b1101000, 0b1101001}, "S AW 0d117 Sr AR 0b?110100? P"),

    ProbeDevice("ONsemi", "FUSB302BMPX/FUSB302BVMPX/FUSB302BUCX",
        {0b0100010}, "S AW 0x01 Sr AR 0b100100?? P"),
    ProbeDevice("ONsemi", "FUSB302B01MPX",
        {0b0100011}, "S AW 0x01 Sr AR 0b100101?? P"),
    ProbeDevice("ONsemi", "FUSB302B10MPX",
        {0b0100100}, "S AW 0x01 Sr AR 0b100110?? P"),
    ProbeDevice("ONsemi", "FUSB302B11MPX",
        {0b0100101}, "S AW 0x01 Sr AR 0b100111?? P"),
]


def print_all():
    for device in devices:
        print(repr(device))


if __name__ == "__main__":
    print_all()
