//! This module handles board configuration: factory, non-volatile, and volatile. All other modules
//! depend on the configuration block to be available and contain sensible values.

#pragma once

/// Board revision. Stored in the configuration block and is used to select appropriate behavior
/// for all of the revision-dependent features.
///
/// The revision byte encodes the letter X and digit N in "revXN" in the high and low nibble
/// respectively. The high nibble is the letter (1 means 'A') and the low nibble is the digit.
/// This means that host software can always decode a revision into a product name, even if
/// the hardware is newer than the software.
///
/// The `GLASGOW_REV_NA` revision is used when the configuration block is invalid. It will never
/// be allocated to real hardware.
enum glasgow_rev {
  GLASGOW_REV_A  = 0x10, // revA0 with current nomenclature, revA at the time it was designed
  GLASGOW_REV_B  = 0x20, // revB0 with current nomenclature, revB at the time it was designed
  GLASGOW_REV_C0 = 0x30,
  GLASGOW_REV_C1 = 0x31,
  GLASGOW_REV_C2 = 0x32,
  GLASGOW_REV_C3 = 0x33,
  GLASGOW_REV_D0 = 0x40,

  GLASGOW_REV_NA = 0xF9,
};

enum {
  /// API compatibility level. This constant is used to ensure that the firmware and the software
  /// agree on the management protocol. Must match `glasgow.hardware.device.CUR_API_LEVEL`.
  ///
  /// The board revision and the API compatibility level are combined in the `bcdDevice` field
  /// of the device descriptor, which the software uses to determine if a device is compatible
  /// without having to actively interrogate the hardware.
  GLASGOW_API_LEVEL = 0x07,
};

enum {
  /// Size of the bitstream ID field.
  CONFIG_SIZE_BITSTREAM_ID      = 8,
  /// Size of the manufacturer name field.
  CONFIG_SIZE_MANUFACTURER      = 22,
};

enum config_flags: uint8_t {
  /// Modified from the original design files. This flag must be set if the PCBA has been modified
  /// from the design files published in https://github.com/GlasgowEmbedded/glasgow/ in any way
  /// except those exempted in https://glasgow-embedded.org/latest/build.html. It will be set when
  /// running `glasgow factory --using-modified-design-files=yes`.
  CONFIG_FLAG_MODIFIED_DESIGN   = 0b00000001,

  /// Configuration block corresponds to API level 7. Prior to that, `bitstream_id` was twice as
  /// wide and `voltage_limit` had 2 entries. Set during factory or routine flashing, as well as
  /// during automatic configuration upgrade.
  CONFIG_FLAG_API_LEVEL_GE_7    = 0b00000010,

  /// Advertise a WebUSB URL. Defaults to off, since it can be quite annoying, seeing as every
  /// instance of Chrome, including embedded in applications such as Steam Web Helper (!), will
  /// display a notification every time the device enumerates, and many people will never use
  /// the WebUSB version of the software. Devices will ship from the factory with the flag on.
  CONFIG_FLAG_ADVERTISE_WEBUSB  = 0b00000100,
};

/// The configuration block has a dual role: when stored in the FX2 NVM, it describes non-volatile
/// configuration of the device, and when loaded in the FX2 RAM (this is done by the FX2 boot logic
/// or in [config_init] depending on whether C0 or C2 loads are used), it describes volatile,
/// current state. Some fields always match between the two roles, and some fields may diverge at
/// runtime.
__xdata __at(0x4000 - CONF_SIZE) struct glasgow_config {
  /// Board revision. Set during factory flashing.
  uint8_t   revision; // actually [enum glasgow_rev]

  /// Board serial number. Set during factory flashing. Up to this point, every board has been
  /// issued a serial number in the ISO 8601 format (e.g. `20260717T125940Z`), but in the future
  /// the format may change, e.g. to assist contract manufacturers with RMA handling. Must be
  /// treated as an opaque string.
  char      serial[16];

  /// Size of FPGA bitstream programmed in NVM. Set via management commands. If zero, NVM does not
  /// contain a bitstream.
  uint32_t  bitstream_size;

  /// Identifier of FPGA bitstream programmed in volatiler or non-volatile memory. May diverge at
  /// runtime if a board has a non-volatile bitstream programmed, and subsequently the FPGA is
  /// reconfigured with a different bitstream at runtime. Set via management commands.
  ///
  /// In the past, this field has overlapped the current `unused` and `voltage_limit[0..1]` fields,
  /// meaning stale random data may be contained in the latter fields if an new firmware is loaded
  /// together with an old configuration block in the FX2 NVM.
  char      bitstream_id[CONFIG_SIZE_BITSTREAM_ID];

  /// Reserved for future use.
  uint32_t  unused;

  /// Vlimit value, in millivolts; Vsupply may not be configured to be above this value. Set via
  /// management commands. Used to prevent 'fat-fingering' a command that would raise Vsupply to
  /// a destructive level. If zero, no limit is applied. (In the past, the value 5500 was used when
  /// no limit was applied.)
  uint16_t  voltage_limit[4];

  /// Manufacturer name. Set during factory flashing. Copied into USB string descriptors.
  char      manufacturer[CONFIG_SIZE_MANUFACTURER];

  /// Configuration flags. Set during factory flashing, routine flashing (the `glasgow flash`
  /// command), and during automatic configuration upgrades, depending on the specific flag.
  /// See documentation of individual flags for details.
  uint8_t   flags; // actually [enum config_flags]
} glasgow_config;

/// Initialize the configuration block. Ensures that `glasgow_config` is filled with data from
/// the FX2 NVM, regardless of whether C0 or C2 load was used. Performs minimal validation of
/// configuration contents, ensuring that `glasgow_config.revision` is set to one of the values
/// of [enum glasgow_rev], and that `glasgow_config.serial` is set to an alphanumeric value.
///
/// Should be called after CPU reset and strictly before any other `*_init` routine; these other
/// functions will often branch on `glasgow_config.revision`.
void config_init();

/// Persist a slice of the configuration block to FX2 NVM. Callers should persist only the modified
/// parts of the configuration rather than the entire block to guard against corruption if power
/// fails during the operation.
///
/// Precondition: `offset + size <= sizeof(glasgow_config)`.
bool config_save(uint8_t offset, uint8_t size);
