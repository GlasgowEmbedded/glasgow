//! This module implements secondary MCU management.
//!
//! On revC and earlier, there is no secondary MCU. On revD, the secondary MCU is an STM32F0 device
//! performing the following ancillary functions: pin strapping for FPGA boot from NVM, and NAFE
//! readout. These functions are not essential and most functions are available without using (or
//! in principle, even populating) the secondary MCU).

#pragma once

enum {
    /// Format: `S ADDR MCU_CMD_LED [0|1] P`.
    /// Enables or disables the STM32 LED.
    MCU_CMD_LED  = 0x10,
    /// Format: `S ADDR MCU_CMD_NAFE W_DATA... [Sr ADDR R_DATA...] P`.
    /// Writes and/or reads an arbitrary amount of bytes via the SPI interface.
    MCU_CMD_NAFE = 0x20,
    /// Format: `S ADDR MCU_CMD_MEAS W_DATA... Sr ADDR R_DATA... P`.
    /// Writes `W_DATA`, then waits for a `DRDY` pulse and reads `R_DATA`.
    /// The NAFE should have these bits set: `SYS_CONFIG0={DRDY_PWDT,DRDY_PIN_EDGE}`.
    MCU_CMD_MEAS = 0x21,
    /// Format: `S ADDR MCU_CMD_FPGA FLASH P`.
    /// If `FLASH == 0`: sets up FPGA for parallel target configuration mode (CFG[2:0]=111).
    /// If `FLASH == 1`: sets up FPGA for serial initiator configuration mode (CFG[2:0]=010).
    MCU_CMD_FPGA = 0x30,
};

#ifndef MCU_PROTOCOL_ONLY

/// Boot the secondary MCU from the `scratch` space. This must be done before enabling USB, as
/// the standard USB library code uses `scratch` to assemble descriptors.
///
/// Returns `mcu_ready`.
bool mcu_bootload();

/// Whether the secondary MCU boot process has succeeded.
extern __bit mcu_ready;

#endif
