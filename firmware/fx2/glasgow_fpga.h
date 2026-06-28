//! This module contains all FPGA related functionality. This includes FPGA volatile and
//! non-volatile configuration, FPGA register access, FPGA FIFO communication, and FPGA alert
//! handling.
//!
//! While the bulk of operations is done via special EP2OUT modes, some operatons (activation
//! of a new volatile or non-volatile configuration; register access; alert handling) are done
//! via the EP1 management protocol.

#pragma once

/// Low-bandwidth or out-of-band communication with the FPGA design is done via I2C/SMBus.
/// Currently, the register address is 8-bit, with no paging. There are two segments of the address
/// space: standard registers and applet registers.
///
/// Every register up to and including `FPGA_REG_PRIVATE_LAST` is a standard register. These
/// registers are implemented by the Glasgow framework, use SMBus "Read Byte" and "Write Byte"
/// framing, and are used for essential management tasks. They are read-only via EP1 requests even
/// if architecturally defined as read-write.
///
/// Applet registers have no restrictions placed on them besides that one address byte is used.
enum fpga_reg {
  /// RO, 8-bit, reads as 0xA5. This register is used by the Glasgow framework to verify that
  /// the FPGA SMBus interface works. It is primarily used to provide a better diagnostic for
  /// a few dozen faulty devices shipped by 1bitSquared. This register may not be present in
  /// fully custom bitstreams, so we don't check it in firmware to not make life excessively
  /// difficult for people who want to load those.
  FPGA_REG_HEALTH = 0x00,

  /// RW, 4-bit (aligned to 8-bit). This register is used to reset FPGA-side USB FIFOs. The Glasgow
  /// framework may also use it to reset the applet logic, although this is subject to change, and
  /// the register should be used in the firmware strictly to reflect the state of corresponding
  /// USB interface.
  FPGA_REG_PIPE_RST = 0x01,

  /// RO, 8-bit. This register is used by the FPGA to indicate an out-of-band alert condition.
  /// The nALERT line will be asserted iff any of the bits in this register are set. Reading
  /// the register clears the bits that have been reported as set and releases the nALERT line.
  ///
  /// Note: while most alerts handled by the firmware indicate fault conditions, the use model
  /// for FPGA alerts is similar to IRQs, so the ERR LED indication is not used for them.
  FPGA_REG_ALERTS = 0x02,

  /// Presence, width, and framing are applet-specific after `FPGA_REG_PRIVATE_LAST`.
  FPGA_REG_PRIVATE_LAST = FPGA_REG_ALERTS
};

/// Initialize the FPGA interface.
///
/// Should be called after CPU reset.
void fpga_init();

/// Load FPGA configuration from NVM. May be used only when the USB interface is inactive.
/// Returns `true` if configuration succeeded, `false` on any error.
bool fpga_load_nvmem();

/// Configure the FPGA-side logic for interface number `iface` and alternate setting `mode`.
/// This performs one of several actions depending on parameters and ambient state:
///  * When selecting `IFACE_EP2OUT` and `EP_MODE_CFG`, the FPGA is reset and put into volatile
///    configuration mode. Requires other interfaces to be in `EP_MODE_OFF`.
///  * When selecting `IFACE_EP2OUT` and `EP_MODE_NVM`, the FPGA is reset and its non-volatile
///    memory is prepared for writing. Requires other interfaces to be in `EP_MODE_OFF`.
///  * When selecting `IFACE_EP2OUT` and `EP_MODE_OFF`, and the previous mode was `EP_MODE_CFG` or
///    `EP_MODE_NVM`, the FPGA configuration is finished, and the FIFOs are enabled.
///  * When selecting any interface and `EP_MODE_2X` or `EP_MODE_4X` (the latter, if allowed by
///    FX2 hardware for that interface), the FPGA-side USB FIFO (pipe) is put into and then taken
///    out of reset. This fulfills contract of the standard "Set Interface" request. Requires
///    the FPGA to be configured and the write to the `FPGA_REG_PIPE_RST` register to succeed.
///  * When selecting any interface and `EP_MODE_OFF`, and the previous mode was `EP_MODE_2X` or
///    `EP_MODE_4X`, the FPGA-side USB FIFO (pipe) is put into reset.
///
/// If any constraint described above with "reqiures ..." is violated, this function returns
/// `false`. In other words, this function implements "interlocks" that ensure invalid states are
/// never entered. Returning a stall condition in response to a `Set Interface` request gets
/// surfaced as `LIBUSB_ERROR_OTHER`; this can be used to prevent enabling an interface, but not
/// disabling an interface (configuring it as `EP_MODE_OFF`) because the kernel ignores stalls.
/// With the one exception of failing to write to the `FPGA_REG_PIPE_RST` register when disabling
/// an interface that was previously configured as `EP_MODE_2X` or `EP_MODE_4X`, no errors are
/// returned if `mode == EP_MODE_OFF`; the exceptional condition should never happen but if it does
/// then it would be easier to see in a captured USB trace.
bool fpga_configure(enum interface iface, enum ep_mode mode);

/// Reset all FPGA pipes. Fulfills contract of the standard "Set Configuration" request.
bool fpga_reset_pipes();

/// Handle deferred tasks for volatile or non-volatile configuration load.
///
/// Precondition: `IFACE_EP2OUT` has mode `EP_MODE_CFG` or `EP_MODE_NVM`.
void fpga_poll_cfg();

/// Handle deferred tasks for nALERT low event.
void fpga_poll_alert();

/// Read or write non-volatile FPGA bitstream memory on revC (I2C EEPROM technology).
///
/// Precondition: `addr + length <= 0x21000`.
/// Precondition: reads and writes fall do not cross 0x10000 aligned blocks.
bool nvmem_xfer_bitstream_revabc(__xdata uint8_t *buffer, uint32_t addr, uint16_t length, bool write);

/// Erase, write, and verify non-volatile FPGA bitstream memory on revD (SPI Flash technology).
///
/// Precondition: sequence of calls must start at `addr == 0` and continue in ascending order
/// without gaps.
bool nvmem_write_bitstream_revd(__xdata uint8_t *buffer, uint32_t addr, uint16_t length);
