from collections import defaultdict, namedtuple


__all__ = ["devices", "devices_by_idcode", "devices_by_name"]


ECP5Device = namedtuple("ECP5Device", ("name", "idcode"))


devices = [
    ECP5Device("LFE5U-12",    idcode=0x21111043),
    ECP5Device("LFE5U-25",    idcode=0x41111043),
    ECP5Device("LFE5U-45",    idcode=0x41112043),
    ECP5Device("LFE5U-85",    idcode=0x41113043),
    ECP5Device("LFE5UM-25",   idcode=0x01111043),
    ECP5Device("LFE5UM-45",   idcode=0x01112043),
    ECP5Device("LFE5UM-85",   idcode=0x01113043),
    ECP5Device("LFE5UM5G-25", idcode=0x81111043),
    ECP5Device("LFE5UM5G-45", idcode=0x81112043),
    ECP5Device("LFE5UM5G-85", idcode=0x81113043),
]

devices_by_idcode = defaultdict(lambda: None,
    ((device.idcode, device) for device in devices))

devices_by_name = defaultdict(lambda: None,
    ((device.name, device) for device in devices))
