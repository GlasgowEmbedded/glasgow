# Ref: Microchip MEC1618/MEC1618i Low Power 32-bit Microcontroller with Embedded Flash
# Document Number: DS00002339A
# Accession: G00005

from glasgow.support.bitstruct import bitstruct


__all__ = [
    # JTAG registers
    "DR_RESET_TEST",
    # Flash registers
    "Flash_Mbx_Index_addr", "Flash_Mbx_Data_addr",
    "Flash_Data_addr", "Flash_Address_addr", "Flash_Command_addr", "Flash_Status_addr",
    "Flash_Config_addr", "Flash_Init_addr", "Flash_Command", "Flash_Mode_Standby",
    "Flash_Mode_Read", "Flash_Mode_Program", "Flash_Mode_Erase", "Flash_Status",
    "Flash_Config", "EEPROM_Data_addr", "EEPROM_Address_addr", "EEPROM_Command_addr",
    "EEPROM_Status_addr", "EEPROM_Configuration_addr", "EEPROM_Unlock_addr",
    "EEPROM_Command", "EEPROM_Status", "EEPROM_Mode_Standby", "EEPROM_Mode_Read",
    "EEPROM_Mode_Program", "EEPROM_Mode_Erase",
]

class DR_RESET_TEST(bitstruct, width=32):
    ME: int      = 1
    VCC_POR: int = 1
    VTR_POR: int = 1
    POR_EN: int  = 1
    _0: int      = 27
    GANG_EN: int = 1

Flash_base_addr     = 0xff_3800

Flash_Mbx_Index_addr = Flash_base_addr + 0x00
Flash_Mbx_Data_addr  = Flash_base_addr + 0x04

Flash_Data_addr     = Flash_base_addr + 0x100
Flash_Address_addr  = Flash_base_addr + 0x104
Flash_Command_addr  = Flash_base_addr + 0x108
Flash_Status_addr   = Flash_base_addr + 0x10c
Flash_Config_addr   = Flash_base_addr + 0x110
Flash_Init_addr     = Flash_base_addr + 0x114

class Flash_Command(bitstruct, width=32):
    Flash_Mode: int = 2
    Burst: int      = 1
    EC_Int: int     = 1
    _0: int         = 4
    Reg_Ctl: int    = 1
    _1: int         = 23

Flash_Mode_Standby  = 0
Flash_Mode_Read     = 1
Flash_Mode_Program  = 2
Flash_Mode_Erase    = 3

class Flash_Status(bitstruct, width=32):
    Busy: int         = 1
    Data_Full: int    = 1
    Address_Full: int = 1
    Boot_Lock: int    = 1
    _0: int           = 1
    Boot_Block: int   = 1
    Data_Block: int   = 1
    EEPROM_Block: int = 1  # This bit is related to EEPROM emulation, not present on some variants.
    Busy_Err: int     = 1
    CMD_Err: int      = 1
    Protect_Err: int  = 1
    _1: int           = 21

class Flash_Config(bitstruct, width=32):
    Reg_Ctl_En: int         = 1
    Host_Ctl: int           = 1
    Boot_Lock: int          = 1
    Boot_Protect_En: int    = 1
    Data_Protect: int       = 1
    Inhibit_JTAG: int       = 1
    _0: int                 = 2
    EEPROM_Access: int      = 1
    EEPROM_Protect: int     = 1
    EEPROM_Force_Block: int = 1
    _1: int                 = 21

EEPROM_base_addr          = 0xf0_2c00

EEPROM_Data_addr          = EEPROM_base_addr + 0x00
EEPROM_Address_addr       = EEPROM_base_addr + 0x04
EEPROM_Command_addr       = EEPROM_base_addr + 0x08
EEPROM_Status_addr        = EEPROM_base_addr + 0x0c
EEPROM_Configuration_addr = EEPROM_base_addr + 0x10
EEPROM_Unlock_addr        = EEPROM_base_addr + 0x20

class EEPROM_Command(bitstruct, width=32):
    EEPROM_Mode: int = 2
    Burst: int       = 1
    _0: int          = 29

class EEPROM_Status(bitstruct, width=32):
    Busy: int         = 1
    Data_Full: int    = 1
    Address_Full: int = 1
    _0: int           = 4
    EEPROM_Block: int = 1
    Busy_Err: int     = 1
    CMD_Err: int      = 1
    _1: int           = 22

EEPROM_Mode_Standby  = 0
EEPROM_Mode_Read     = 1
EEPROM_Mode_Program  = 2
EEPROM_Mode_Erase    = 3
