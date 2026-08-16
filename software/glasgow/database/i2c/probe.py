from glasgow.arch.i2c import ProbeDevice


__all__ = ["devices"]


devices = [
    ProbeDevice("Bosch Sensortec", "BMP280",
        {0b1110110, 0b1110111}, "S AW 0xD0 Sr AR 0x58 P"),
    ProbeDevice("Bosch Sensortec", "BME280",
        {0b1110110, 0b1110111}, "S AW 0xD0 Sr AR 0x60 P"),

    ProbeDevice("ONsemi", "FUSB302BMPX/FUSB302BVMPX/FUSB302BUCX",
        {0b0100010}, "S AW 0x01 Sr AR 0b100100?? P"),
    ProbeDevice("ONsemi", "FUSB302B01MPX",
        {0b0100011}, "S AW 0x01 Sr AR 0b100101?? P"),
    ProbeDevice("ONsemi", "FUSB302B10MPX",
        {0b0100100}, "S AW 0x01 Sr AR 0b100110?? P"),
    ProbeDevice("ONsemi", "FUSB302B11MPX",
        {0b0100101}, "S AW 0x01 Sr AR 0b100111?? P"),

    # Begin sourced from FastIMU (https://github.com/LiquidCGS/FastIMU)
    # (except for counterfeit/unidentified devices)
    ProbeDevice("InvenSense/TDK",               "MPU6050",  {0x68, 0x69}, "S AW 0x75 Sr AR 0x68 P"),
    ProbeDevice("InvenSense/TDK",               "MPU6500",  {0x68, 0x69}, "S AW 0x75 Sr AR 0x70 P"),
    ProbeDevice("InvenSense/TDK",               "MPU9250",  {0x68, 0x69}, "S AW 0x75 Sr AR 0x71 P"),
    ProbeDevice("InvenSense/TDK",               "MPU9255",  {0x68, 0x69}, "S AW 0x75 Sr AR 0x73 P"),
    ProbeDevice("InvenSense/TDK",               "MPU6515",  {0x68, 0x69}, "S AW 0x75 Sr AR 0x74 P"),
    ProbeDevice("InvenSense/TDK",               "MPU6886",  {0x68, 0x69}, "S AW 0x75 Sr AR 0x19 P"),
    ProbeDevice("Bosch Sensortec",              "BMI160",   {0x69, 0x68}, "S AW 0x00 Sr AR 0xD1 P"),
    ProbeDevice("ST Microelectronics",          "LSM6DS3",  {0x6B, 0x6A}, "S AW 0x0F Sr AR 0x69 P"),
    ProbeDevice("ST Microelectronics",          "LSM6DSL",  {0x6B, 0x6A}, "S AW 0x0F Sr AR 0x6A P"),
    ProbeDevice("InvenSense/TDK",               "ICM20689", {0x68, 0x69}, "S AW 0x75 Sr AR 0x98 P"),
    ProbeDevice("InvenSense/TDK",               "ICM20690", {0x68, 0x69}, "S AW 0x75 Sr AR 0x20 P"),
    ProbeDevice("InvenSense/TDK",               "ICM20948", {0x68, 0x69}, "S AW 0x00 Sr AR 0xEA P"),
    ProbeDevice("QST",                          "QMI8658",  {0x6B, 0x6A}, "S AW 0x00 Sr AR 0x05 P"),
    ProbeDevice("Bosch Sensortec",              "BMI055",   {0x18, 0x19}, "S AW 0x00 Sr AR 0xFA P"),
    ProbeDevice("Honeywell",                    "HMC5883L", {0x1E},       "S AW 0x0C Sr AR 0x33 P"),
    ProbeDevice("QST",                          "QMC5883L", {0x0D},       "S AW 0x0D Sr AR 0xFF P"),
    ProbeDevice("Asahi Kasei Microdevices",     "AK8975",   {0x0C, 0x0D}, "S AW 0x01 Sr AR 0x09 P"),
    ProbeDevice("Asahi Kasei Microdevices",     "AK8975",   {0x0E, 0x0F}, "S AW 0x01 Sr AR 0x09 P"),
    ProbeDevice("Asahi Kasei Microdevices",     "AK8963",   {0x0C, 0x0D}, "S AW 0x01 Sr AR 0x9A P"),
    ProbeDevice("Asahi Kasei Microdevices",     "AK8963",   {0x0E, 0x0F}, "S AW 0x01 Sr AR 0x9A P"),
    ProbeDevice("Bosch Sensortec",              "BMM150",   {0x13, 0x12,
                                                             0x11, 0x10}, "S AW 0x40 Sr AR 0x32 P"),
    ProbeDevice("ST Microelectronics",          "LSM6DSR",  {0x6B, 0x6A}, "S AW 0x0F Sr AR 0x6B P"),
    ProbeDevice("ST Microelectronics",          "LSM6DSO",  {0x6B, 0x6A}, "S AW 0x0F Sr AR 0x6C P"),
    ProbeDevice("QST",                          "QMI8610",  {0x6B, 0x6A}, "S AW 0x00 Sr AR 0xFC P"),
    ProbeDevice("InvenSense/TDK",               "ICG20330", {0x68, 0x69}, "S AW 0x75 Sr AR 0x92 P"),
    ProbeDevice("InvenSense/TDK",               "IAM20380", {0x68, 0x69}, "S AW 0x75 Sr AR 0xB5 P"),
    ProbeDevice("InvenSense/TDK",               "IAM20381", {0x68, 0x69}, "S AW 0x75 Sr AR 0xB6 P"),
    ProbeDevice("InvenSense/TDK",               "ICM20600", {0x68, 0x69}, "S AW 0x75 Sr AR 0x11 P"),
    ProbeDevice("InvenSense/TDK",               "ICM20601", {0x68, 0x69}, "S AW 0x75 Sr AR 0xAC P"),
    ProbeDevice("InvenSense/TDK",               "ICM20602", {0x68, 0x69}, "S AW 0x75 Sr AR 0x12 P"),
    ProbeDevice("InvenSense/TDK",               "ICM20608", {0x68, 0x69}, "S AW 0x75 Sr AR 0xAF P"),
    ProbeDevice("InvenSense/TDK",               "ICM20609", {0x68, 0x69}, "S AW 0x75 Sr AR 0xA6 P"),
    ProbeDevice("InvenSense/TDK",               "ICM20648", {0x68, 0x69}, "S AW 0x00 Sr AR 0xE0 P"),
    ProbeDevice("InvenSense/TDK",               "ICM20649", {0x68, 0x69}, "S AW 0x00 Sr AR 0xE1 P"),
    ProbeDevice("InvenSense/TDK",               "ICG20660", {0x68, 0x69}, "S AW 0x75 Sr AR 0xA9 P"),
    ProbeDevice("InvenSense/TDK",               "IAM20680", {0x68, 0x69}, "S AW 0x75 Sr AR 0x91 P"),
    ProbeDevice("InvenSense/TDK",               "IIM42351", {0x68, 0x69}, "S AW 0x75 Sr AR 0x6C P"),
    ProbeDevice("InvenSense/TDK",               "IIM42352", {0x68, 0x69}, "S AW 0x75 Sr AR 0x6D P"),
    ProbeDevice("InvenSense/TDK",               "ICM40627", {0x68, 0x69}, "S AW 0x75 Sr AR 0x4E P"),
    ProbeDevice("InvenSense/TDK",               "ICM42605", {0x68, 0x69}, "S AW 0x75 Sr AR 0x42 P"),
    ProbeDevice("InvenSense/TDK",               "IIM42652", {0x68, 0x69}, "S AW 0x75 Sr AR 0x6F P"),
    ProbeDevice("InvenSense/TDK",               "ICM42670", {0x68, 0x69}, "S AW 0x75 Sr AR 0x67 P"),
    ProbeDevice("InvenSense/TDK",               "ICM42688", {0x68, 0x69}, "S AW 0x75 Sr AR 0xDB P"),
    ProbeDevice("InvenSense/TDK",               "MPU3050",  {0x68, 0x69}, "S AW 0x00 Sr AR 0x68 P"),
    # End sourced from FastIMU
]


def print_all():
    for device in devices:
        print(repr(device))


if __name__ == "__main__":
    print_all()
