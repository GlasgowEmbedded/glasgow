# Ref: Microchip MEC1618/MEC1618i Low Power 32-bit Microcontroller with Embedded Flash
# Document Number: DS00002339A
# Accession: G00005

from ...support.bitstruct import *


__all__ = [
    # JTAG registers
    "DR_RESET_TEST",
    # Flash registers
    "Flash_Mbx_Index_addr", "Flash_Mbx_Data_addr",
    "Flash_Data_addr", "Flash_Address_addr", "Flash_Command_addr", "Flash_Status_addr",
    "Flash_Config_addr", "Flash_Init_addr", "Flash_Command", "Flash_Mode_Standby",
    "Flash_Mode_Read", "Flash_Mode_Program", "Flash_Mode_Erase", "Flash_Status",
    "Flash_Config",
]

DR_RESET_TEST = bitstruct("DR_RESET_TEST", 32, [
    # Probably ME. It seems to work for me, but none of SMSC documents ever coherently point
    # to a single DR with the ME bit *or* specify the location of the ME bit. Cursed.
    ("ME",      1),
    ("VCC_POR", 1),
    ("VTR_POR", 1),
    ("POR_EN",  1),
    (None,      27),
    ("GANG_EN", 1),
])

Flash_base_addr     = 0xff_3800

Flash_Mbx_Index_addr = Flash_base_addr + 0x00
Flash_Mbx_Data_addr  = Flash_base_addr + 0x04

Flash_Data_addr     = Flash_base_addr + 0x100
Flash_Address_addr  = Flash_base_addr + 0x104
Flash_Command_addr  = Flash_base_addr + 0x108
Flash_Status_addr   = Flash_base_addr + 0x10c
Flash_Config_addr   = Flash_base_addr + 0x110
Flash_Init_addr     = Flash_base_addr + 0x114

Flash_Command = bitstruct("Flash_Command", 32, [
    ("Flash_Mode",  2),
    ("Burst",       1),
    ("EC_Int",      1),
    (None,          4),
    ("Reg_Ctl",     1),
    (None,         23),
])

Flash_Mode_Standby  = 0
Flash_Mode_Read     = 1
Flash_Mode_Program  = 2
Flash_Mode_Erase    = 3

Flash_Status = bitstruct("Flash_Status", 32, [
    ("Busy",            1),
    ("Data_Full",       1),
    ("Address_Full",    1),
    ("Boot_Lock",       1),
    (None,              1),
    ("Boot_Block",      1),
    ("Data_Block",      1),
    ("EEPROM_Block",    1),
    ("Busy_Err",        1),
    ("CMD_Err",         1),
    ("Protect_Err",     1),
    (None,             21),
])

Flash_Config = bitstruct("Flash_Config", 32, [
    ("Reg_Ctl_En",      1),
    ("Host_Ctl",        1),
    ("Boot_Lock",       1),
    ("Boot_Protect_En", 1),
    ("Data_Protect",    1),
    ("Inhibit_JTAG",    1),
    (None,              2),
    ("EEPROM_Access",   1),
    ("EEPROM_Protect",  1),
    ("EEPROM_Force_Block", 1),
    (None,             21),
])
