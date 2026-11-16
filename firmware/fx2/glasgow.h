//! The Glasgow Interface Explorer firmware is composed of multiple semi-independent modules, all
//! referenced from this header. Unfortunately, there is a great deal of interdependence between
//! these modules; we recommend reading the documentation included in all other `glasgow_*.h` files
//! before working on the firmware.
//!
//! In this iteration of the firmware (it was completely rewritten to implement API level 7),
//! virtually all interaction with the host is done via BULK IN/OUT packets, with CONTROL IN/OUT
//! packets being used only to implement the standard USB functionality. This makes the interface
//! less dependent on design quirks of USB and easily tunneled over TCP/IP.
//!
//! The FX2 hardware has six USB endpoints available: EP1IN, EP1OUT, EP2, EP4, EP6, and EP8. These
//! are not all equal in capability. EP1IN/OUT are single buffered 64 byte endpoints that are only
//! accessible by the 8051 core. (Note that USB requires BULK endpoints to be 512 bytes in size for
//! USB HS. We cannot meet that requirement, but this does not change much besides technically
//! making the firmware non-compliant without a waiver.) EP2468 are, in context of this firmware,
//! double or quad buffered 512 byte endpoints that are accessible by the 8051 core or the FPGA
//! via the FIFO interface; firmware access is much slower.
//!
//! USB does not allow accessing endpoints directly; rather, they must be allocated to interfaces.
//! Interfaces are nominally independent units of device functionality, although in this case we
//! cannot and do not make them fully independent (see [fpga_configure] for an explanation of
//! the interface configuration interlocks). We have five interfaces: `IFACE_MGMT` that includes
//! EP1IN/OUT and is independent of the other four, and `IFACE_EP[2468]*` that include only
//! the relevant endpoint. This is done to give applets maximum possible flexibility: this scheme
//! makes it possible to allocate all four endpoints to the same applet, or each to one of four
//! applets. Currently, each of the EP2468 interfaces has a fixed direction, but this will likely
//! be relaxed in the future.
//!
//! There are two main usage constraints on EP2468 interfaces. First, the underlying buffer memory
//! is not sufficient to use quad buffering with every endpoint; only some endpoints can be
//! configured as quad-buffered, and only by stealing buffer memory from another endpoint. Second,
//! EP2 must be special: on revD, it is used to quickly upload the quite large ECP5 configuration
//! data via the FPGA's parallel bus by using the GPIF. Since USB does not permit including one
//! endpoint in two different interfaces (within the same configuration), this constraint required
//! overloading the EP2 interface with volatile (`EP_MODE_CFG`) and non-volatile (`EP_MODE_NVM`)
//! FPGA configuration functionality, as well as additional interlocks. Since the use of GPIF for
//! volatile ECP5 configuration required surfacing a usage constraint on EP2 in the USB interface,
//! the volatile iCE40 configuration and FPGA NVM programming were implemented using the same USB
//! interface. (On revD, the FPGA must be in reset to program the FPGA NVM due to pin sharing.)
//! Note that there is an additional constraint for the `EP_MODE_NVM` mode: the bitstream must be
//! written in maximum length (512-byte) packets, except the last packet may be shorter.
//!
//! The USB interface architecture is a part of the public API, however, we do not treat it as
//! stable, and it is expected to change as necessary to accommodate future development and work
//! around OS-specific USB issues. Third party software must, therefore, examine the configuration
//! descriptor to associate applet pipes with specific USB endpoints. When an applet is designed
//! for use with third party software that directly communicates with the hardware over USB,
//! the applet will generate and output a "USB connection string" including the serial number,
//! interface numbers corresponding to applet pipes, and alternate settings for each of the used
//! interfaces. This string removes the need for third party software to hardcode any aspects of
//! the USB interface, and only requires it to look up the endpoint in the interface descriptor.

#pragma once

#include <stdbool.h>
#include <stdint.h>

/// The default Cypress FX2 VID/PID pair. Used only when the configuration block is missing, to
/// make it easier to use existing tools like `fx2tool` to manipulate the device.
#define VID_CYPRESS   0x04b4
#define PID_FX2       0x8613

/// The official Qi Hardware Glasgow Interface Explorer VID/PID pair.
#define VID_QIHW      0x20b7
#define PID_GLASGOW   0x9db1

/// USB iManufacturer descriptor value that is used when `glasgow_config.manufacturer[0] == '\0'`.
#define DEFAULT_MANUFACTURER  "whitequark research\0\0\0" // CONFIG_SIZE_MANUFACTURER bytes long

/// USB iProduct descriptor value is composed from one of the following words (depending on whether
/// `glasgow_config.flags & CONFIG_FLAG_MODIFIED_DESIGN`) and ` Interface Explorer`.
#define ORIGINAL_PRODUCT_WORD "Glasgow"
#define MODIFIED_PRODUCT_WORD "Another"

/// WebUSB URL descriptor value. Clicking on a WebUSB notification displayed by the browser will
/// cause it to navigate to this domain (with the `https://` scheme).
#define WEBUSB_URL            "webusb.glasgow-embedded.org"

/// Advertised USB interfaces
enum interface {
  IFACE_MGMT   = 0, // aka EP1IN/EP1OUT
  IFACE_EP2OUT = 1,
  IFACE_EP4OUT = 2,
  IFACE_EP6IN  = 3,
  IFACE_EP8IN  = 4,
};

/// Advertised alternate settings of USB interfaces
enum ep_mode {
  EP_MODE_OFF  = 0, // valid for any interface
  EP_MODE_ON   = 1, // valid for IFACE_MGMT
  EP_MODE_2X   = 1, // valid for IFACE_EP[2468]*; double buffered applet FIFO
  EP_MODE_4X   = 2, // valid for IFACE_EP[26]*; quad buffered applet FIFO
  EP_MODE_CFG  = 3, // valid for IFACE_EP2; volatile FPGA configuration
  EP_MODE_NVM  = 4, // valid for IFACE_EP2; non-volatile FPGA configuration
};

/// I2C definitions
#include "glasgow_i2c.h"

/// GPIO definitions
#include "glasgow_gpio.h"

/// SMBus microcode engine
#include "glasgow_smbus.h"

/// Configuration module
#include "glasgow_config.h"

/// Management module
#include "glasgow_mgmt.h"

/// Port module
#include "glasgow_port.h"

/// FPGA module
#include "glasgow_fpga.h"

/// Secondary MCU module
#include "glasgow_mcu.h"

/// Surprisingly more efficient than `1<<x`.
extern const __idata uint8_t nibble_mask[4];
