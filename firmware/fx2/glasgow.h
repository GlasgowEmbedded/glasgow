#pragma once

#include <stdbool.h>
#include <stdint.h>

// Branding
#define VID_CYPRESS   0x04b4
#define PID_FX2       0x8613

#define VID_QIHW      0x20b7
#define PID_GLASGOW   0x9db1

#define DEFAULT_MANUFACTURER  "whitequark research\0\0\0" // CONFIG_SIZE_MANUFACTURER bytes long
#define ORIGINAL_PRODUCT_WORD "Glasgow"
#define MODIFIED_PRODUCT_WORD "Another"
#define WEBUSB_URL            "webusb.glasgow-embedded.org"

// Version API
enum {
  // Board revisions
  //
  // The revision byte encodes the letter X and digit N in "revXN" in the high and low nibble
  // respectively. The high nibble is the letter (1 means 'A') and the low nibble is the digit.
  // This means that host software can always decode a revision to be human-readable, even if
  // the hardware is newer than the software.
  GLASGOW_REV_A  = 0x10,
  GLASGOW_REV_B  = 0x20,
  GLASGOW_REV_C0 = 0x30,
  GLASGOW_REV_C1 = 0x31,
  GLASGOW_REV_C2 = 0x32,
  GLASGOW_REV_C3 = 0x33,
  GLASGOW_REV_D0 = 0x40,
  GLASGOW_REV_NA = 0xF9,

  // API compatibility level
  GLASGOW_API_LEVEL = 0x07,
};

// NVM API
bool eeprom_xfer(uint8_t chip, uint16_t addr, __xdata uint8_t *buf, uint16_t len, bool write);

// Configuration API
enum {
  /// Size of the bitstream ID field.
  CONFIG_SIZE_BITSTREAM_ID      = 8,

  /// Size of the manufacturer name field.
  CONFIG_SIZE_MANUFACTURER      = 22,

  /// Modified from the original design files. This flag must be set if the PCBA has been modified
  /// from the design files published in https://github.com/GlasgowEmbedded/glasgow/ in any way
  /// except those exempted in https://glasgow-embedded.org/latest/build.html. It will be set when
  /// running `glasgow factory --using-modified-design-files=yes`.
  CONFIG_FLAG_MODIFIED_DESIGN   = 0b00000001,

  /// Configuration block corresponds to API level 7. Prior to that, `bitstream_id` was twice as
  /// wide and `voltage_limit` had 2 entries.
  CONFIG_FLAG_API_LEVEL_GE_7    = 0b00000010,

  /// Advertise a WebUSB URL. Defaults to off, since it can be quite annoying, seeing as every
  /// instance of Chrome, including embedded in applications such as Steam Web Helper (!), will
  /// display a notification every time the device enumerates, and many people will never use
  /// the WebUSB version of the software. Devices will ship from the factory with the flag on.
  CONFIG_FLAG_ADVERTISE_WEBUSB  = 0b00000100,
};

__xdata __at(0x4000 - CONF_SIZE) struct glasgow_config {
  uint8_t   revision;
  char      serial[16];
  uint32_t  bitstream_size;
  char      bitstream_id[CONFIG_SIZE_BITSTREAM_ID];
  uint32_t  unused;
  uint16_t  voltage_limit[4];
  char      manufacturer[CONFIG_SIZE_MANUFACTURER];
  uint8_t   flags; // last field in a 64-byte configuration block
} glasgow_config;

void config_init();
bool config_save(uint8_t offset, uint8_t size);

// Host interface definitions
enum interface {
  IFACE_MGMT   = 0,
  IFACE_EP2OUT = 1,
  IFACE_EP4OUT = 2,
  IFACE_EP6IN  = 3,
  IFACE_EP8IN  = 4,
};

enum ep_mode {
  EP_MODE_OFF  = 0,
  EP_MODE_ON   = 1, // for IFACE_MGMT
  EP_MODE_2X   = 1, // for IFACE_EP[2468]*
  EP_MODE_4X   = 2, // for IFACE_EP[26]*
  EP_MODE_CFG  = 3, // for IFACE_EP2
  EP_MODE_NVM  = 4, // for IFACE_EP2
};

// I2C definitions
#include "glasgow_i2c.h"

// GPIO definitions
#include "glasgow_gpio.h"

// SMBus engine
#include "glasgow_smbus.h"

// Management API
#include "glasgow_mgmt.h"

// Port API
#include "glasgow_port.h"

// FPGA API
#include "glasgow_fpga.h"

// Surprisingly more efficient than `1<<x`.
static const __idata uint8_t nibble_mask[] = { 0x1, 0x2, 0x4, 0x8 };
