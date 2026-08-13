//! This module contains FX2 I2C address table.
//!
//! Where possible, Glasgow revisions use the same I2C address to implement the same function.
//! In certain cases, addresses have been modified across revisions to avoid conflicts, and
//! the related constants are suffixed with `_REV*`. Refer to the schematic to see the address
//! table for any individual hardware revision, but be aware that revision C2 has an address
//! conflict due to an oversight.
//!
//! See [glasgow_smbus.h] for more information about the I2C bus handling. The following I2C
//! devices are compliant with the SMBus specification, for the purposes of the FX2 firmware
//! implementation (i.e. SMBus support may be explicitly advertised, or the protocol may be
//! de-facto SMBus compatible as described):
//!   * softcore (de-facto; standard registers only)
//!   * DAC081C  (de-facto; requires endian swap)
//!   * ADC081C  (de-facto: requires endian swap)
//!   * DAC43204 (advertised)
//!   * INA233   (advertised)
//!   * PCA64xxA (advertised)
//!   * FUSB302  (de-facto)
//!   * TMP112   (advertised)

#pragma once

/// I2C addresses (in 7-bit or "unshifted" format).
///
/// Note: some addresses may not be used in the firmware and are specified only for completeness.
enum {
  I2C_ADDR_FPGA               = 0b0001000u, // softcore
  I2C_ADDR_STM32_APP_REVD     = 0b0001010u, // STM32 (application)
  // Memories
  I2C_ADDR_FX2_MEM            = 0b1010001u, // BL24C256A (32 KiB)
  I2C_ADDR_ICE_MEM_REVABC     = 0b1010010u, // CAT24M01X (128 KiB)
  // DACs
  I2C_ADDR_IOA_DAC_REVABC012  = 0b0001100u, // DAC081C
  I2C_ADDR_IOA_DAC_REVC3      = 0b0001110u, // DAC081C
  I2C_ADDR_IOB_DAC            = 0b0001101u, // DAC081C
  I2C_ADDR_ALL_DAC_REVABC     = 0b1001000u, // DAC081C
  I2C_ADDR_ALL_DAC_REVD       = 0b1001000u, // DAC43204
  I2C_ADDR_BRCAST_DAC_REVD    = 0b1000111u, // DAC43204
  // ADCs
  I2C_ADDR_IOA_ADC_REVABC01   = 0b1010100u, // ADC081C
  I2C_ADDR_IOB_ADC_REVABC01   = 0b1010101u, // ADC081C
  I2C_ADDR_IOA_ADC_REVC23     = 0b1000000u, // INA233
  I2C_ADDR_IOB_ADC_REVC23     = 0b1000001u, // INA233
  I2C_ADDR_IOA_ADC_REVD       = 0b1001100u, // INA233
  I2C_ADDR_IOB_ADC_REVD       = 0b1001101u, // INA233
  I2C_ADDR_IOC_ADC_REVD       = 0b1001110u, // INA233
  I2C_ADDR_IOD_ADC_REVD       = 0b1001111u, // INA233
  // Pulls
  I2C_ADDR_IOA_PULL_REVC      = 0b0100000u, // PCA6408A
  I2C_ADDR_IOB_PULL_REVC      = 0b0100001u, // PCA6408A
  I2C_ADDR_IOAC_PULL_REVD     = 0b0100000u, // PCA6416A
  I2C_ADDR_IODB_PULL_REVD     = 0b0100001u, // PCA6416A
  // Misc
  I2C_ADDR_THERMOMETER_REVD1  = 0b1001001u, // TMP112
  I2C_ADDR_USB_PD_REVD        = 0b0100011u, // FUSB302
  I2C_ADDR_STM32_BOOT_REVD    = 0b1010110u, // STM32 (bootloader)
  // Reserved
  I2C_ADDR_SMBUS_ARA          = 0b0001100u, // SMBus Alert Response Address
};

/// Transfer data to/from a 24-series EEPROM at unshifted I2C address `chip`. Two-byte addressing
/// is used. Writes must be split into page-aligned chunks by the caller.
bool eeprom_xfer(uint8_t chip, uint16_t addr, __xdata uint8_t *buf, uint16_t len, bool write);
