
from collections import namedtuple, defaultdict


__all__ = ["devices", "devices_by_signature"]


AVRDevice = namedtuple("AVRDevice",
    ("name", "signature",
     "calibration_size", "fuses_size",
     "program_size", "program_page",
     "eeprom_size",  "eeprom_page"))

undefined = None # heh

devices = [

    # extracted from http://packs.download.atmel.com/Atmel.ATautomotive_DFP.1.2.118.atpack:

    AVRDevice("ATA5272",
        signature=(0x1e, 0x93, 0x87),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATA5505",
        signature=(0x1e, 0x94, 0x87),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATA5700M322",
        signature=(0x1e, 0x95, 0x67),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x8000, program_page=0x40,
        eeprom_size=0x0880, eeprom_page=0x10),

    AVRDevice("ATA5702M322",
        signature=(0x1e, 0x95, 0x69),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x8000, program_page=0x40,
        eeprom_size=0x0880, eeprom_page=0x10),

    AVRDevice("ATA5781",
        signature=(0x1e, 0x95, 0x64),
        calibration_size=None, fuses_size=0x0001,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=0x10),

    AVRDevice("ATA5782",
        signature=(0x1e, 0x95, 0x65),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x5000, program_page=0x40,
        eeprom_size=0x0400, eeprom_page=0x10),

    AVRDevice("ATA5783",
        signature=(0x1e, 0x95, 0x66),
        calibration_size=None, fuses_size=0x0001,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=0x10),

    AVRDevice("ATA5787",
        signature=(0x1e, 0x94, 0x6c),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x5200, program_page=0x40,
        eeprom_size=0x0400, eeprom_page=0x10),

    AVRDevice("ATA5790",
        signature=(0x1e, 0x94, 0x61),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0800, eeprom_page=0x10),

    AVRDevice("ATA5790N",
        signature=(0x1e, 0x94, 0x62),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0800, eeprom_page=0x10),

    AVRDevice("ATA5791",
        signature=(0x1e, 0x94, 0x62),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0800, eeprom_page=0x10),

    AVRDevice("ATA5795",
        signature=(0x1e, 0x93, 0x61),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0800, eeprom_page=0x10),

    AVRDevice("ATA5831",
        signature=(0x1e, 0x95, 0x61),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x5000, program_page=0x40,
        eeprom_size=0x0400, eeprom_page=0x10),

    AVRDevice("ATA5832",
        signature=(0x1e, 0x95, 0x62),
        calibration_size=None, fuses_size=0x0001,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=0x10),

    AVRDevice("ATA5833",
        signature=(0x1e, 0x95, 0x63),
        calibration_size=None, fuses_size=0x0001,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=0x10),

    AVRDevice("ATA5835",
        signature=(0x1e, 0x94, 0x6b),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x5200, program_page=0x40,
        eeprom_size=0x0400, eeprom_page=0x10),

    AVRDevice("ATA6285",
        signature=(0x1e, 0x93, 0x82),
        calibration_size=None, fuses_size=0x0002,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0140, eeprom_page=0x04),

    AVRDevice("ATA6286",
        signature=(0x1e, 0x93, 0x82),
        calibration_size=None, fuses_size=0x0002,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0140, eeprom_page=0x04),

    AVRDevice("ATA6612C",
        signature=(0x1e, 0x93, 0x0a),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATA6613C",
        signature=(0x1e, 0x94, 0x06),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATA6614Q",
        signature=(0x1e, 0x95, 0x0f),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATA6616C",
        signature=(0x1e, 0x93, 0x87),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATA6617C",
        signature=(0x1e, 0x94, 0x87),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATA664251",
        signature=(0x1e, 0x94, 0x87),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATA8210",
        signature=(0x1e, 0x95, 0x65),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x5000, program_page=0x40,
        eeprom_size=0x0400, eeprom_page=0x10),

    AVRDevice("ATA8215",
        signature=(0x1e, 0x95, 0x64),
        calibration_size=None, fuses_size=0x0001,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=0x10),

    AVRDevice("ATA8510",
        signature=(0x1e, 0x95, 0x61),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x5000, program_page=0x40,
        eeprom_size=0x0400, eeprom_page=0x10),

    AVRDevice("ATA8515",
        signature=(0x1e, 0x95, 0x63),
        calibration_size=None, fuses_size=0x0001,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=0x10),

    AVRDevice("ATtiny416auto",
        signature=(0x1E, 0x92, 0x28),
        calibration_size=None, fuses_size=0xA,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0080, eeprom_page=0x20),

    # extracted from http://packs.download.atmel.com/Atmel.ATmega_DFP.1.3.300.atpack:

    AVRDevice("AT90CAN128",
        signature=(0x1e, 0x97, 0x81),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x20000, program_page=0x100,
        eeprom_size=0x1000, eeprom_page=0x08),

    AVRDevice("AT90CAN32",
        signature=(0x1e, 0x95, 0x81),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x100,
        eeprom_size=0x0400, eeprom_page=0x08),

    AVRDevice("AT90CAN64",
        signature=(0x1e, 0x96, 0x81),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("AT90PWM1",
        signature=(0x1e, 0x93, 0x83),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("AT90PWM161",
        signature=(0x1e, 0x94, 0x8B),
        calibration_size=2, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("AT90PWM216",
        signature=(0x1e, 0x94, 0x83),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("AT90PWM2B",
        signature=(0x1e, 0x93, 0x83),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("AT90PWM316",
        signature=(0x1e, 0x94, 0x83),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("AT90PWM3B",
        signature=(0x1e, 0x93, 0x83),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("AT90PWM81",
        signature=(0x1e, 0x93, 0x88),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("AT90USB1286",
        signature=(0x1e, 0x97, 0x82),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x20000, program_page=0x100,
        eeprom_size=0x1000, eeprom_page=0x08),

    AVRDevice("AT90USB1287",
        signature=(0x1e, 0x97, 0x82),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x20000, program_page=0x100,
        eeprom_size=0x1000, eeprom_page=0x08),

    AVRDevice("AT90USB162",
        signature=(0x1e, 0x94, 0x82),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("AT90USB646",
        signature=(0x1e, 0x96, 0x82),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("AT90USB647",
        signature=(0x1e, 0x96, 0x82),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("AT90USB82",
        signature=(0x1e, 0x93, 0x82),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega128",
        signature=(0x1e, 0x97, 0x02),
        calibration_size=4, fuses_size=0x0003,
        program_size=0x20000, program_page=0x100,
        eeprom_size=0x1000, eeprom_page=0x08),

    AVRDevice("ATmega1280",
        signature=(0x1e, 0x97, 0x03),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x20000, program_page=0x100,
        eeprom_size=0x1000, eeprom_page=0x08),

    AVRDevice("ATmega1281",
        signature=(0x1e, 0x97, 0x04),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x20000, program_page=0x100,
        eeprom_size=0x1000, eeprom_page=0x08),

    AVRDevice("ATmega1284",
        signature=(0x1e, 0x97, 0x06),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x20000, program_page=0x100,
        eeprom_size=0x1000, eeprom_page=0x08),

    AVRDevice("ATmega1284P",
        signature=(0x1e, 0x97, 0x05),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x20000, program_page=0x100,
        eeprom_size=0x1000, eeprom_page=0x08),

    AVRDevice("ATmega1284RFR2",
        signature=(0x1e, 0xa7, 0x03),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x20000, program_page=0x100,
        eeprom_size=0x1000, eeprom_page=0x08),

    AVRDevice("ATmega128A",
        signature=(0x1e, 0x97, 0x02),
        calibration_size=4, fuses_size=0x0003,
        program_size=0x20000, program_page=0x100,
        eeprom_size=0x1000, eeprom_page=0x08),

    AVRDevice("ATmega128RFA1",
        signature=(0x1e, 0xa7, 0x01),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x20000, program_page=0x100,
        eeprom_size=0x1000, eeprom_page=0x08),

    AVRDevice("ATmega128RFR2",
        signature=(0x1e, 0xa7, 0x02),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x20000, program_page=0x100,
        eeprom_size=0x1000, eeprom_page=0x08),

    AVRDevice("ATmega16",
        signature=(0x1e, 0x94, 0x03),
        calibration_size=4, fuses_size=0x0002,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega1608",
        signature=(0x1E, 0x94, 0x27),
        calibration_size=None, fuses_size=0xA,
        program_size=0x4000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x20),

    AVRDevice("ATmega1609",
        signature=(0x1E, 0x94, 0x26),
        calibration_size=None, fuses_size=0xA,
        program_size=0x4000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x20),

    AVRDevice("ATmega162",
        signature=(0x1e, 0x94, 0x04),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega164A",
        signature=(0x1e, 0x94, 0x0f),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega164P",
        signature=(0x1e, 0x94, 0x0a),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega164PA",
        signature=(0x1e, 0x94, 0x0a),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega165A",
        signature=(0x1e, 0x94, 0x10),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega165P",
        signature=(0x1e, 0x94, 0x07),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega165PA",
        signature=(0x1e, 0x94, 0x07),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega168",
        signature=(0x1e, 0x94, 0x06),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega168A",
        signature=(0x1e, 0x94, 0x06),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega168P",
        signature=(0x1e, 0x94, 0x0b),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega168PA",
        signature=(0x1e, 0x94, 0x0b),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega168PB",
        signature=(0x1e, 0x94, 0x15),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega169A",
        signature=(0x1e, 0x94, 0x11),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega169P",
        signature=(0x1e, 0x94, 0x05),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega169PA",
        signature=(0x1e, 0x94, 0x05),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega16A",
        signature=(0x1e, 0x94, 0x03),
        calibration_size=4, fuses_size=0x0002,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega16HVA",
        signature=(0x1e, 0x94, 0x0c),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATmega16HVB",
        signature=(0x1e, 0x94, 0x0d),
        calibration_size=None, fuses_size=0x0002,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega16HVBrevB",
        signature=(0x1e, 0x94, 0x0d),
        calibration_size=None, fuses_size=0x0002,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega16M1",
        signature=(0x1e, 0x94, 0x84),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega16U2",
        signature=(0x1e, 0x94, 0x89),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega16U4",
        signature=(0x1e, 0x94, 0x88),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega2560",
        signature=(0x1e, 0x98, 0x01),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x40000, program_page=0x100,
        eeprom_size=0x1000, eeprom_page=0x08),

    AVRDevice("ATmega2561",
        signature=(0x1e, 0x98, 0x02),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x40000, program_page=0x100,
        eeprom_size=0x1000, eeprom_page=0x08),

    AVRDevice("ATmega2564RFR2",
        signature=(0x1e, 0xa8, 0x03),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x40000, program_page=0x100,
        eeprom_size=0x2000, eeprom_page=0x08),

    AVRDevice("ATmega256RFR2",
        signature=(0x1e, 0xa8, 0x02),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x40000, program_page=0x100,
        eeprom_size=0x2000, eeprom_page=0x08),

    AVRDevice("ATmega32",
        signature=(0x1e, 0x95, 0x02),
        calibration_size=4, fuses_size=0x0002,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega3208",
        signature=(0x1E, 0x95, 0x30),
        calibration_size=None, fuses_size=0xA,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0100, eeprom_page=0x40),

    AVRDevice("ATmega3209",
        signature=(0x1E, 0x95, 0x31),
        calibration_size=None, fuses_size=0xA,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0100, eeprom_page=0x40),

    AVRDevice("ATmega324A",
        signature=(0x1e, 0x95, 0x15),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega324P",
        signature=(0x1e, 0x95, 0x08),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega324PA",
        signature=(0x1e, 0x95, 0x11),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega324PB",
        signature=(0x1e, 0x95, 0x17),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega325",
        signature=(0x1e, 0x95, 0x05),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega3250",
        signature=(0x1e, 0x95, 0x06),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega3250A",
        signature=(0x1e, 0x95, 0x06),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega3250P",
        signature=(0x1e, 0x95, 0x0e),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega3250PA",
        signature=(0x1e, 0x95, 0x0e),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega325A",
        signature=(0x1e, 0x95, 0x05),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega325P",
        signature=(0x1e, 0x95, 0x0d),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega325PA",
        signature=(0x1e, 0x95, 0x0d),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega328",
        signature=(0x1e, 0x95, 0x14),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega328P",
        signature=(0x1e, 0x95, 0x0f),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega328PB",
        signature=(0x1e, 0x95, 0x16),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega329",
        signature=(0x1e, 0x95, 0x03),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega3290",
        signature=(0x1e, 0x95, 0x04),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega3290A",
        signature=(0x1e, 0x95, 0x04),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega3290P",
        signature=(0x1e, 0x95, 0x0c),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega3290PA",
        signature=(0x1e, 0x95, 0x0c),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega329A",
        signature=(0x1e, 0x95, 0x03),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega329P",
        signature=(0x1e, 0x95, 0x0b),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega329PA",
        signature=(0x1e, 0x95, 0x0b),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega32A",
        signature=(0x1e, 0x95, 0x02),
        calibration_size=4, fuses_size=0x0002,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega32C1",
        signature=(0x1e, 0x95, 0x86),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega32HVB",
        signature=(0x1e, 0x95, 0x10),
        calibration_size=None, fuses_size=0x0002,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega32HVBrevB",
        signature=(0x1e, 0x95, 0x10),
        calibration_size=None, fuses_size=0x0002,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega32M1",
        signature=(0x1e, 0x95, 0x84),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega32U2",
        signature=(0x1e, 0x95, 0x8a),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega32U4",
        signature=(0x1e, 0x95, 0x87),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega406",
        signature=(0x1e, 0x95, 0x07),
        calibration_size=None, fuses_size=0x0002,
        program_size=0xa000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega48",
        signature=(0x1e, 0x92, 0x05),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATmega4808",
        signature=(0x1E, 0x96, 0x50),
        calibration_size=None, fuses_size=0xA,
        program_size=0xC000, program_page=0x80,
        eeprom_size=0x0100, eeprom_page=0x40),

    AVRDevice("ATmega4809",
        signature=(0x1E, 0x96, 0x51),
        calibration_size=None, fuses_size=0xA,
        program_size=0xC000, program_page=0x80,
        eeprom_size=0x0100, eeprom_page=0x40),

    AVRDevice("ATmega48A",
        signature=(0x1e, 0x92, 0x05),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATmega48P",
        signature=(0x1e, 0x92, 0x0a),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATmega48PA",
        signature=(0x1e, 0x92, 0x0a),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATmega48PB",
        signature=(0x1e, 0x92, 0x10),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATmega64",
        signature=(0x1e, 0x96, 0x02),
        calibration_size=4, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega640",
        signature=(0x1e, 0x96, 0x08),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x1000, eeprom_page=0x08),

    AVRDevice("ATmega644",
        signature=(0x1e, 0x96, 0x09),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega644A",
        signature=(0x1e, 0x96, 0x09),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega644P",
        signature=(0x1e, 0x96, 0x0a),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega644PA",
        signature=(0x1e, 0x96, 0x0a),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega644RFR2",
        signature=(0x1e, 0xa6, 0x03),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega645",
        signature=(0x1e, 0x96, 0x05),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega6450",
        signature=(0x1e, 0x96, 0x06),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega6450A",
        signature=(0x1e, 0x96, 0x06),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega6450P",
        signature=(0x1e, 0x96, 0x0e),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega645A",
        signature=(0x1e, 0x96, 0x05),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega645P",
        signature=(0x1e, 0x96, 0x0D),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega649",
        signature=(0x1e, 0x96, 0x03),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega6490",
        signature=(0x1e, 0x96, 0x04),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega6490A",
        signature=(0x1e, 0x96, 0x04),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega6490P",
        signature=(0x1e, 0x96, 0x0C),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega649A",
        signature=(0x1e, 0x96, 0x03),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega649P",
        signature=(0x1e, 0x96, 0x0b),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega64A",
        signature=(0x1e, 0x96, 0x02),
        calibration_size=4, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega64C1",
        signature=(0x1e, 0x96, 0x86),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega64HVE2",
        signature=(0x1e, 0x96, 0x10),
        calibration_size=None, fuses_size=0x0002,
        program_size=0x10000, program_page=0x80,
        eeprom_size=0x0400, eeprom_page=0x04),

    AVRDevice("ATmega64M1",
        signature=(0x1e, 0x96, 0x84),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega64RFR2",
        signature=(0x1e, 0xa6, 0x02),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x10000, program_page=0x100,
        eeprom_size=0x0800, eeprom_page=0x08),

    AVRDevice("ATmega8",
        signature=(0x1e, 0x93, 0x07),
        calibration_size=4, fuses_size=0x0002,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega808",
        signature=(0x1E, 0x93, 0x26),
        calibration_size=None, fuses_size=0xA,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x20),

    AVRDevice("ATmega809",
        signature=(0x1E, 0x93, 0x2A),
        calibration_size=None, fuses_size=0xA,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x20),

    AVRDevice("ATmega8515",
        signature=(0x1e, 0x93, 0x06),
        calibration_size=4, fuses_size=0x0002,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega8535",
        signature=(0x1e, 0x93, 0x08),
        calibration_size=4, fuses_size=0x0002,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega88",
        signature=(0x1e, 0x93, 0x0a),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega88A",
        signature=(0x1e, 0x93, 0x0a),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega88P",
        signature=(0x1e, 0x93, 0x0f),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega88PA",
        signature=(0x1e, 0x93, 0x0f),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega88PB",
        signature=(0x1e, 0x93, 0x16),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega8A",
        signature=(0x1e, 0x93, 0x07),
        calibration_size=4, fuses_size=0x0002,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATmega8HVA",
        signature=(0x1e, 0x93, 0x10),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x2000, program_page=0x80,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATmega8U2",
        signature=(0x1e, 0x93, 0x89),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    # extracted from http://packs.download.atmel.com/Atmel.ATtiny_DFP.1.3.229.atpack:

    AVRDevice("ATtiny10",
        signature=(0x1e, 0x90, 0x03),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x0400, program_page=0x80,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATtiny102",
        signature=(0x1e, 0x90, 0x0c),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x0400, program_page=0x80,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATtiny104",
        signature=(0x1e, 0x90, 0x0b),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x0400, program_page=0x80,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATtiny11",
        signature=(0x1e, 0x90, 0x04),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x0400, program_page=0x00,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATtiny12",
        signature=(0x1e, 0x90, 0x05),
        calibration_size=1, fuses_size=0x0001,
        program_size=0x0400, program_page=0x00,
        eeprom_size=0x0040, eeprom_page=0x02),

    AVRDevice("ATtiny13",
        signature=(0x1e, 0x90, 0x07),
        calibration_size=2, fuses_size=0x0002,
        program_size=0x0400, program_page=0x20,
        eeprom_size=0x0040, eeprom_page=0x04),

    AVRDevice("ATtiny13A",
        signature=(0x1e, 0x90, 0x07),
        calibration_size=2, fuses_size=0x0002,
        program_size=0x0400, program_page=0x20,
        eeprom_size=0x0040, eeprom_page=0x04),

    AVRDevice("ATtiny15",
        signature=(0x1e, 0x90, 0x06),
        calibration_size=1, fuses_size=0x0001,
        program_size=0x0400, program_page=0x00,
        eeprom_size=0x0040, eeprom_page=0x02),

    AVRDevice("ATtiny1604",
        signature=(0x1E, 0x94, 0x25),
        calibration_size=None, fuses_size=0xA,
        program_size=0x4000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x20),

    AVRDevice("ATtiny1606",
        signature=(0x1E, 0x94, 0x24),
        calibration_size=None, fuses_size=0xA,
        program_size=0x4000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x20),

    AVRDevice("ATtiny1607",
        signature=(0x1E, 0x94, 0x23),
        calibration_size=None, fuses_size=0xA,
        program_size=0x4000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x20),

    AVRDevice("ATtiny1614",
        signature=(0x1E, 0x94, 0x22),
        calibration_size=None, fuses_size=0xA,
        program_size=0x4000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x20),

    AVRDevice("ATtiny1616",
        signature=(0x1E, 0x94, 0x21),
        calibration_size=None, fuses_size=0xA,
        program_size=0x4000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x20),

    AVRDevice("ATtiny1617",
        signature=(0x1E, 0x94, 0x20),
        calibration_size=None, fuses_size=0xA,
        program_size=0x4000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x20),

    AVRDevice("ATtiny1634",
        signature=(0x1e, 0x94, 0x12),
        calibration_size=None, fuses_size=0x0003,
        program_size=0x4000, program_page=0x20,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATtiny167",
        signature=(0x1e, 0x94, 0x87),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x4000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATtiny20",
        signature=(0x1e, 0x91, 0x0f),
        calibration_size=1, fuses_size=0x0001,
        program_size=0x0800, program_page=0x80,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATtiny202",
        signature=(0x1E, 0x91, 0x23),
        calibration_size=None, fuses_size=0xA,
        program_size=0x0800, program_page=0x40,
        eeprom_size=0x0040, eeprom_page=0x20),

    AVRDevice("ATtiny204",
        signature=(0x1E, 0x91, 0x22),
        calibration_size=None, fuses_size=0xA,
        program_size=0x0800, program_page=0x40,
        eeprom_size=0x0040, eeprom_page=0x20),

    AVRDevice("ATtiny212",
        signature=(0x1E, 0x91, 0x21),
        calibration_size=None, fuses_size=0xA,
        program_size=0x0800, program_page=0x40,
        eeprom_size=0x0040, eeprom_page=0x20),

    AVRDevice("ATtiny214",
        signature=(0x1E, 0x91, 0x20),
        calibration_size=None, fuses_size=0xA,
        program_size=0x0800, program_page=0x40,
        eeprom_size=0x0040, eeprom_page=0x20),

    AVRDevice("ATtiny2313",
        signature=(0x1e, 0x91, 0x0a),
        calibration_size=2, fuses_size=0x0003,
        program_size=0x0800, program_page=0x20,
        eeprom_size=0x0080, eeprom_page=0x04),

    AVRDevice("ATtiny2313A",
        signature=(0x1e, 0x91, 0x0a),
        calibration_size=2, fuses_size=0x0003,
        program_size=0x0800, program_page=0x20,
        eeprom_size=0x0080, eeprom_page=0x04),

    AVRDevice("ATtiny24",
        signature=(0x1e, 0x91, 0x0b),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x0800, program_page=0x20,
        eeprom_size=0x0080, eeprom_page=0x04),

    AVRDevice("ATtiny24A",
        signature=(0x1e, 0x91, 0x0b),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x0800, program_page=0x20,
        eeprom_size=0x0080, eeprom_page=0x04),

    AVRDevice("ATtiny25",
        signature=(0x1e, 0x91, 0x08),
        calibration_size=2, fuses_size=0x0003,
        program_size=0x0800, program_page=0x20,
        eeprom_size=0x0080, eeprom_page=0x04),

    AVRDevice("ATtiny26",
        signature=(0x1e, 0x91, 0x09),
        calibration_size=4, fuses_size=0x0002,
        program_size=0x0800, program_page=0x20,
        eeprom_size=0x0080, eeprom_page=0x04),

    AVRDevice("ATtiny261",
        signature=(0x1e, 0x91, 0x0c),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x0800, program_page=0x20,
        eeprom_size=0x0080, eeprom_page=0x04),

    AVRDevice("ATtiny261A",
        signature=(0x1e, 0x91, 0x0c),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x0800, program_page=0x20,
        eeprom_size=0x0080, eeprom_page=0x04),

    AVRDevice("ATtiny3214",
        signature=(0x1E, 0x95, 0x20),
        calibration_size=None, fuses_size=0xA,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0100, eeprom_page=0x40),

    AVRDevice("ATtiny3216",
        signature=(0x1E, 0x95, 0x21),
        calibration_size=None, fuses_size=0xA,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0100, eeprom_page=0x40),

    AVRDevice("ATtiny3217",
        signature=(0x1E, 0x95, 0x22),
        calibration_size=None, fuses_size=0xA,
        program_size=0x8000, program_page=0x80,
        eeprom_size=0x0100, eeprom_page=0x40),

    AVRDevice("ATtiny4",
        signature=(0x1e, 0x8f, 0x0a),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x0200, program_page=0x80,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATtiny40",
        signature=(0x1e, 0x92, 0x0e),
        calibration_size=1, fuses_size=0x0001,
        program_size=0x1000, program_page=0x80,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATtiny402",
        signature=(0x1E, 0x92, 0x27),
        calibration_size=None, fuses_size=0xA,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0080, eeprom_page=0x20),

    AVRDevice("ATtiny404",
        signature=(0x1E, 0x92, 0x26),
        calibration_size=None, fuses_size=0xA,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0080, eeprom_page=0x20),

    AVRDevice("ATtiny406",
        signature=(0x1E, 0x92, 0x25),
        calibration_size=None, fuses_size=0xA,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0080, eeprom_page=0x20),

    AVRDevice("ATtiny412",
        signature=(0x1E, 0x92, 0x23),
        calibration_size=None, fuses_size=0xA,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0080, eeprom_page=0x20),

    AVRDevice("ATtiny414",
        signature=(0x1E, 0x92, 0x22),
        calibration_size=None, fuses_size=0xA,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0080, eeprom_page=0x20),

    AVRDevice("ATtiny416",
        signature=(0x1E, 0x92, 0x21),
        calibration_size=None, fuses_size=0xA,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0080, eeprom_page=0x20),

    AVRDevice("ATtiny417",
        signature=(0x1E, 0x92, 0x20),
        calibration_size=None, fuses_size=0xA,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0080, eeprom_page=0x20),

    AVRDevice("ATtiny4313",
        signature=(0x1e, 0x92, 0x0d),
        calibration_size=2, fuses_size=0x0003,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATtiny43U",
        signature=(0x1e, 0x92, 0x0c),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0040, eeprom_page=0x04),

    AVRDevice("ATtiny44",
        signature=(0x1e, 0x92, 0x07),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATtiny441",
        signature=(0x1e, 0x92, 0x15),
        calibration_size=2, fuses_size=0x0003,
        program_size=0x1000, program_page=0x10,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATtiny44A",
        signature=(0x1e, 0x92, 0x07),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATtiny45",
        signature=(0x1e, 0x92, 0x06),
        calibration_size=2, fuses_size=0x0003,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATtiny461",
        signature=(0x1e, 0x92, 0x08),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATtiny461A",
        signature=(0x1e, 0x92, 0x08),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATtiny48",
        signature=(0x1e, 0x92, 0x09),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x1000, program_page=0x40,
        eeprom_size=0x0040, eeprom_page=0x04),

    AVRDevice("ATtiny5",
        signature=(0x1e, 0x8f, 0x09),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x0200, program_page=0x80,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATtiny804",
        signature=(0x1E, 0x93, 0x25),
        calibration_size=None, fuses_size=0xA,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0080, eeprom_page=0x20),

    AVRDevice("ATtiny806",
        signature=(0x1E, 0x93, 0x24),
        calibration_size=None, fuses_size=0xA,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0080, eeprom_page=0x20),

    AVRDevice("ATtiny807",
        signature=(0x1E, 0x93, 0x23),
        calibration_size=None, fuses_size=0xA,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0080, eeprom_page=0x20),

    AVRDevice("ATtiny814",
        signature=(0x1E, 0x93, 0x22),
        calibration_size=None, fuses_size=0xA,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0080, eeprom_page=0x20),

    AVRDevice("ATtiny816",
        signature=(0x1E, 0x93, 0x21),
        calibration_size=None, fuses_size=0xA,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0080, eeprom_page=0x20),

    AVRDevice("ATtiny817",
        signature=(0x1E, 0x93, 0x20),
        calibration_size=None, fuses_size=0xA,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0080, eeprom_page=0x20),

    AVRDevice("ATtiny828",
        signature=(0x1e, 0x93, 0x14),
        calibration_size=2, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0100, eeprom_page=0x04),

    AVRDevice("ATtiny84",
        signature=(0x1e, 0x93, 0x0c),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATtiny841",
        signature=(0x1e, 0x93, 0x15),
        calibration_size=2, fuses_size=0x0003,
        program_size=0x2000, program_page=0x10,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATtiny84A",
        signature=(0x1e, 0x93, 0x0c),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATtiny85",
        signature=(0x1e, 0x93, 0x0b),
        calibration_size=2, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATtiny861",
        signature=(0x1e, 0x93, 0x0d),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATtiny861A",
        signature=(0x1e, 0x93, 0x0d),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATtiny87",
        signature=(0x1e, 0x93, 0x87),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x80,
        eeprom_size=0x0200, eeprom_page=0x04),

    AVRDevice("ATtiny88",
        signature=(0x1e, 0x93, 0x11),
        calibration_size=1, fuses_size=0x0003,
        program_size=0x2000, program_page=0x40,
        eeprom_size=0x0040, eeprom_page=0x04),

    AVRDevice("ATtiny9",
        signature=(0x1e, 0x90, 0x08),
        calibration_size=None, fuses_size=0x0001,
        program_size=0x0400, program_page=0x80,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAM3A_DFP.1.0.50.atpack:

    AVRDevice("ATSAM3A4C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3A8C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAM3N_DFP.1.0.62.atpack:

    AVRDevice("ATSAM3N00A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3N00B",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3N0A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3N0B",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3N0C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3N1A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3N1B",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3N1C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3N2A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3N2B",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3N2C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3N4A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3N4B",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3N4C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAM3S_DFP.1.0.70.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAM3U_DFP.1.0.49.atpack:

    AVRDevice("ATSAM3U1C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3U1E",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3U2C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3U2E",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3U4C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3U4E",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAM3X_DFP.1.0.50.atpack:

    AVRDevice("ATSAM3X4C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3X4E",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3X8C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3X8E",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM3X8H",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAM4C_DFP.1.0.86.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAM4E_DFP.1.1.57.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAM4L_DFP.1.1.61.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAM4N_DFP.1.0.49.atpack:

    AVRDevice("ATSAM4N16B",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM4N16C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM4N8A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM4N8B",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAM4N8C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAM4S_DFP.1.0.56.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAMB11_DFP.2.3.190.atpack:

    AVRDevice("ATBTLC1000WLCSP",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMB11G18A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMB11ZR",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=None, program_page=None,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAMC20_DFP.1.1.151.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAMC21_DFP.1.2.176.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAMD09_DFP.1.1.76.atpack:

    AVRDevice("ATSAMD09C13A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x2000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMD09D14A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x4000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAMD10_DFP.1.1.77.atpack:

    AVRDevice("ATSAMD10C13A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x2000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMD10C14A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x4000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMD10D13AM",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x2000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMD10D13AS",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x2000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMD10D14AM",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x4000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMD10D14AS",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x4000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMD10D14AU",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x4000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAMD11_DFP.1.1.81.atpack:

    AVRDevice("ATSAMD11C14A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x4000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMD11D14AM",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x4000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMD11D14AS",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x4000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMD11D14AU",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x4000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAMD20_DFP.1.3.124.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAMD21_DFP.1.3.331.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAMD51_DFP.1.2.139.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAMDA1_DFP.1.2.50.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAME51_DFP.1.1.129.atpack:

    AVRDevice("ATSAME51J18A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x40000, program_page=512,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAME51J19A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x80000, program_page=512,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAME51J20A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x100000, program_page=512,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAME51N19A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x80000, program_page=512,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAME51N20A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x100000, program_page=512,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAME53_DFP.1.1.118.atpack:

    AVRDevice("ATSAME53J18A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x40000, program_page=512,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAME53J19A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x80000, program_page=512,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAME53J20A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x100000, program_page=512,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAME53N19A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x80000, program_page=512,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAME53N20A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x100000, program_page=512,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAME54_DFP.1.1.134.atpack:

    AVRDevice("ATSAME54N19A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x80000, program_page=512,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAME54N20A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x100000, program_page=512,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAME54P19A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x80000, program_page=512,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAME54P20A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x100000, program_page=512,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAME70_DFP.2.4.166.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAMG_DFP.2.1.97.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAMHA1_DFP.1.1.55.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAML10_DFP.1.0.158.atpack:

    AVRDevice("ATSAML10D14A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x4000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML10D15A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x8000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML10D16A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x10000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML10E14A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x4000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML10E15A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x8000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML10E16A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x10000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAML11_DFP.1.0.109.atpack:

    AVRDevice("ATSAML11D14A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x4000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML11D15A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x8000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML11D16A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x10000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML11E14A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x4000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML11E15A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x8000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML11E16A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x10000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAML21_DFP.1.2.125.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAML22_DFP.1.2.77.atpack:

    AVRDevice("ATSAML22G16A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x10000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML22G17A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x20000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML22G18A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x40000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML22J16A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x10000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML22J17A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x20000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML22J18A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x40000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML22N16A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x10000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML22N17A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x20000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAML22N18A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x40000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAMR21_DFP.1.1.72.atpack:

    AVRDevice("ATSAMR21E16A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x10000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMR21E17A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x20000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMR21E18A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x40000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMR21E19A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x40000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMR21G16A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x10000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMR21G17A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x20000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMR21G18A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x40000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAMR30_DFP.1.1.35.atpack:

    AVRDevice("ATSAMR30E18A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x40000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMR30G18A",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x40000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAMR34_DFP.1.0.11.atpack:

    AVRDevice("ATSAMR34J16B",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x10000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMR34J17B",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x20000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMR34J18B",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x40000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAMR35_DFP.1.0.10.atpack:

    AVRDevice("ATSAMR35J16B",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x10000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMR35J17B",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x20000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATSAMR35J18B",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x40000, program_page=64,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.SAMS70_DFP.2.4.134.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAMV70_DFP.2.4.130.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.SAMV71_DFP.2.4.182.atpack:

    # extracted from http://packs.download.atmel.com/Atmel.UC3A_DFP.1.0.53.atpack:

    AVRDevice("AT32UC3A0128",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A0256",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00040000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A0512",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00080000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A1128",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A1256",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00040000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A1512",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00080000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A3128",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A3128S",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A3256",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00040000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A3256S",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00040000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A364",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00010000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A364S",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00010000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A4128",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=0x00000001,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A4128S",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=0x00000001,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A4256",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=0x00000001,
        program_size=0x00040000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A4256S",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=0x00000001,
        program_size=0x00040000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A464",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=0x00000001,
        program_size=0x00010000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3A464S",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=0x00000001,
        program_size=0x00010000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.UC3B_DFP.1.0.29.atpack:

    AVRDevice("AT32UC3B0128",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3B0256",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00040000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3B0512",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00080000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3B064",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00010000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3B1128",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3B1256",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00040000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3B1512",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00080000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3B164",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00010000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.UC3C_DFP.1.0.49.atpack:

    AVRDevice("AT32UC3C0128C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3C0256C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00040000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3C0512C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00080000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3C064C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00010000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3C1128C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3C1256C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00040000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3C1512C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00080000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3C164C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00010000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3C2128C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3C2256C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00040000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3C2512C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00080000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3C264C",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00010000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.UC3D_DFP.1.0.54.atpack:

    AVRDevice("ATUC128D3",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATUC128D4",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATUC64D3",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00010000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATUC64D4",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00010000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.UC3L_DFP.1.0.59.atpack:

    AVRDevice("AT32UC3L0128",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3L016",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x4000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3L0256",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00040000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3L032",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x8000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("AT32UC3L064",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00010000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATUC128L3U",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATUC128L4U",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00020000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATUC256L3U",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00040000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATUC256L4U",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00040000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATUC64L3U",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00010000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    AVRDevice("ATUC64L4U",
        signature=(undefined, undefined, undefined),
        calibration_size=None, fuses_size=None,
        program_size=0x00010000, program_page=None,
        eeprom_size=None, eeprom_page=None),

    # extracted from http://packs.download.atmel.com/Atmel.XMEGAA_DFP.1.1.68.atpack:

    AVRDevice("ATxmega128A1",
        signature=(0x1E, 0x97, 0x4C),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega128A1U",
        signature=(0x1E, 0x97, 0x4C),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega128A3",
        signature=(0x1E, 0x97, 0x42),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega128A3U",
        signature=(0x1E, 0x97, 0x42),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega128A4U",
        signature=(0x1E, 0x97, 0x46),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega16A4",
        signature=(0x1E, 0x94, 0x41),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=32),

    AVRDevice("ATxmega16A4U",
        signature=(0x1E, 0x94, 0x41),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=32),

    AVRDevice("ATxmega192A3",
        signature=(0x1E, 0x97, 0x44),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x800, eeprom_page=32),

    AVRDevice("ATxmega192A3U",
        signature=(0x1E, 0x97, 0x44),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x800, eeprom_page=32),

    AVRDevice("ATxmega256A3",
        signature=(0x1E, 0x98, 0x42),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x1000, eeprom_page=32),

    AVRDevice("ATxmega256A3B",
        signature=(0x1E, 0x98, 0x43),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x1000, eeprom_page=32),

    AVRDevice("ATxmega256A3BU",
        signature=(0x1E, 0x98, 0x43),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x1000, eeprom_page=32),

    AVRDevice("ATxmega256A3U",
        signature=(0x1E, 0x98, 0x42),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x1000, eeprom_page=32),

    AVRDevice("ATxmega32A4",
        signature=(0x1E, 0x95, 0x41),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=32),

    AVRDevice("ATxmega32A4U",
        signature=(0x1E, 0x95, 0x41),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=32),

    AVRDevice("ATxmega64A1",
        signature=(0x1E, 0x96, 0x4E),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega64A1U",
        signature=(0x1E, 0x96, 0x4E),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega64A3",
        signature=(0x1E, 0x96, 0x42),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega64A3U",
        signature=(0x1E, 0x96, 0x42),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega64A4U",
        signature=(0x1E, 0x96, 0x46),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    # extracted from http://packs.download.atmel.com/Atmel.XMEGAB_DFP.1.1.55.atpack:

    AVRDevice("ATxmega128B1",
        signature=(0x1E, 0x97, 0x4D),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega128B3",
        signature=(0x1E, 0x97, 0x4B),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega64B1",
        signature=(0x1E, 0x96, 0x52),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega64B3",
        signature=(0x1E, 0x96, 0x51),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    # extracted from http://packs.download.atmel.com/Atmel.XMEGAC_DFP.1.1.50.atpack:

    AVRDevice("ATxmega128C3",
        signature=(0x1E, 0x97, 0x52),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega16C4",
        signature=(0x1E, 0x94, 0x43),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=32),

    AVRDevice("ATxmega192C3",
        signature=(0x1E, 0x97, 0x51),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega256C3",
        signature=(0x1E, 0x98, 0x46),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x1000, eeprom_page=32),

    AVRDevice("ATxmega32C3",
        signature=(0x1E, 0x95, 0x49),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=32),

    AVRDevice("ATxmega32C4",
        signature=(0x1E, 0x95, 0x44),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=32),

    AVRDevice("ATxmega384C3",
        signature=(0x1E, 0x98, 0x45),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x1000, eeprom_page=32),

    AVRDevice("ATxmega64C3",
        signature=(0x1E, 0x96, 0x49),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    # extracted from http://packs.download.atmel.com/Atmel.XMEGAD_DFP.1.1.63.atpack:

    AVRDevice("ATxmega128D3",
        signature=(0x1E, 0x97, 0x48),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega128D4",
        signature=(0x1E, 0x97, 0x47),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega16D4",
        signature=(0x1E, 0x94, 0x42),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=32),

    AVRDevice("ATxmega192D3",
        signature=(0x1E, 0x97, 0x49),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x800, eeprom_page=32),

    AVRDevice("ATxmega256D3",
        signature=(0x1E, 0x98, 0x44),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x1000, eeprom_page=32),

    AVRDevice("ATxmega32D3",
        signature=(0x1E, 0x95, 0x4A),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=32),

    AVRDevice("ATxmega32D4",
        signature=(0x1E, 0x95, 0x42),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=32),

    AVRDevice("ATxmega384D3",
        signature=(0x1E, 0x98, 0x47),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x1000, eeprom_page=32),

    AVRDevice("ATxmega64D3",
        signature=(0x1E, 0x96, 0x4A),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    AVRDevice("ATxmega64D4",
        signature=(0x1E, 0x96, 0x47),
        calibration_size=None, fuses_size=0x0006,
        program_size=None, program_page=None,
        eeprom_size=0x0800, eeprom_page=32),

    # extracted from http://packs.download.atmel.com/Atmel.XMEGAE_DFP.1.2.51.atpack:

    AVRDevice("ATxmega16E5",
        signature=(0x1E, 0x94, 0x45),
        calibration_size=None, fuses_size=0x0007,
        program_size=None, program_page=None,
        eeprom_size=0x0200, eeprom_page=32),

    AVRDevice("ATxmega32E5",
        signature=(0x1E, 0x95, 0x4C),
        calibration_size=None, fuses_size=0x0007,
        program_size=None, program_page=None,
        eeprom_size=0x0400, eeprom_page=32),

    AVRDevice("ATxmega8E5",
        signature=(0x1E, 0x93, 0x41),
        calibration_size=None, fuses_size=0x0007,
        program_size=None, program_page=None,
        eeprom_size=0x0200, eeprom_page=32),

    # extracted from http://packs.download.atmel.com/ARM.CMSIS.5.4.0.atpack:



]

devices_by_signature = defaultdict(lambda: None,
    ((device.signature, device) for device in devices))
