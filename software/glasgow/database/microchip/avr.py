from collections import namedtuple, defaultdict


__all__ = ["devices", "devices_by_signature"]


AVRDevice = namedtuple("AVRDevice", (
    "name", "signature",
    # All sizes in bytes
    "calibration_size", "fuses_size",
    "program_size", "program_page",
    "eeprom_size", "eeprom_page",
))

def ATtiny(name, signature, program_size, program_page, eeprom_size, fuses_size=2):
    return AVRDevice("ATtiny{}".format(name), signature=signature,
                     calibration_size=2, fuses_size=fuses_size,
                     program_size=program_size, program_page=program_page,
                     eeprom_size=eeprom_size, eeprom_page=4)

def ATmega(name, signature, program_size, program_page, eeprom_size):
    return AVRDevice("ATmega{}".format(name), signature=signature,
                     calibration_size=1, fuses_size=3,
                     program_size=program_size, program_page=program_page,
                     eeprom_size=eeprom_size, eeprom_page=4)


devices = [
    # ATtiny series
    ATtiny("13a",  (0x1e, 0x90, 0x07), program_size=1024,  program_page=32,  eeprom_size=64,
                                       fuses_size=2),
    ATtiny("25",   (0x1e, 0x91, 0x08), program_size=1024,  program_page=32,  eeprom_size=128),
    ATtiny("45",   (0x1e, 0x92, 0x06), program_size=2048,  program_page=64,  eeprom_size=256),
    ATtiny("85",   (0x1e, 0x93, 0x0B), program_size=4096,  program_page=64,  eeprom_size=512),
    # ATmega series
    ATmega("48",   (0x1e, 0x92, 0x05), program_size=4096,  program_page=64,  eeprom_size=256),
    ATmega("48P",  (0x1e, 0x92, 0x0a), program_size=4096,  program_page=64,  eeprom_size=256),
    ATmega("88",   (0x1e, 0x93, 0x0a), program_size=8192,  program_page=64,  eeprom_size=512),
    ATmega("88P",  (0x1e, 0x93, 0x0f), program_size=8192,  program_page=64,  eeprom_size=512),
    ATmega("168",  (0x1e, 0x94, 0x06), program_size=16384, program_page=128, eeprom_size=512),
    ATmega("168P", (0x1e, 0x94, 0x0b), program_size=16384, program_page=128, eeprom_size=512),
    ATmega("328",  (0x1e, 0x95, 0x14), program_size=32768, program_page=128, eeprom_size=1024),
    ATmega("328P", (0x1e, 0x95, 0x0f), program_size=32768, program_page=128, eeprom_size=1024),
    ATmega("16U4", (0x1e, 0x94, 0x88), program_size=16384, program_page=128, eeprom_size=512),
    ATmega("32U4", (0x1e, 0x95, 0x87), program_size=32768, program_page=128, eeprom_size=1024),
]

devices_by_signature = defaultdict(lambda: None,
    ((device.signature, device) for device in devices))
