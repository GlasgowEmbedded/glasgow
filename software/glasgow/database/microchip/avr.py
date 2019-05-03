from collections import namedtuple, defaultdict


__all__ = ["devices", "devices_by_signature"]


AVRDevice = namedtuple("AVRDevice",
    ("name", "signature",
     "calibration_size", "fuses_size",
     "program_size", "program_page",
     "eeprom_size",  "eeprom_page"))


devices = [
    AVRDevice("ATtiny13a",
        signature=(0x1e, 0x90, 0x07),
        calibration_size=2, fuses_size=2,
        program_size=1024, program_page=32,
        eeprom_size=64, eeprom_page=4),
    AVRDevice("ATtiny25",
        signature=(0x1e, 0x91, 0x08),
        calibration_size=2, fuses_size=3,
        program_size=1024, program_page=32,
        eeprom_size=128, eeprom_page=4),
    AVRDevice("ATtiny45",
        signature=(0x1e, 0x92, 0x06),
        calibration_size=2, fuses_size=3,
        program_size=2048, program_page=64,
        eeprom_size=256, eeprom_page=4),
    AVRDevice("ATtiny85",
        signature=(0x1e, 0x93, 0x0B),
        calibration_size=2, fuses_size=3,
        program_size=4096, program_page=64,
        eeprom_size=512, eeprom_page=4),
]

devices_by_signature = defaultdict(lambda: None,
    ((device.signature, device) for device in devices))
