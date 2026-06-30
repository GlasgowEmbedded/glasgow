#include <stddef.h>
#include <string.h>
#include <fx2lib.h>
#include <fx2regs.h>
#include <fx2ints.h>
#include <fx2usb.h>
#include <fx2delay.h>
#include <fx2i2c.h>
#include <usbmicrosoft.h>
#include <usbweb.h>
#include "glasgow.h"
#include "version.h"

const __idata uint8_t nibble_mask[] = { 0x1, 0x2, 0x4, 0x8 };

enum {
  // Microsoft requests
  USB_DESC_STRING_MS_INDEX        = 0xEE,
  USB_REQ_GET_MS_DESCRIPTOR       = 0xC0,
  // WebUSB requests
  USB_REQ_GET_WEBUSB_DESCRIPTOR   = 0xD0,
};

// bcdDevice is a 16-bit number where the high byte indicates the API revision and the low byte
// indicates the hardware revision. If the firmware is not flashed (only the FX2 header is present)
// then the high byte is zero (as configured by `glasgow factory`). The low byte can be zero on
// legacy devices with old or no firmware where the hardware revision is present only in
// the Glasgow configuration block. Loading new firmware ensures it is present in the FX2 header.

usb_desc_device_c usb_device = {
  .bLength              = sizeof(struct usb_desc_device),
  .bDescriptorType      = USB_DESC_DEVICE,
  .bcdUSB               = 0x0210,
  .bDeviceClass         = USB_DEV_CLASS_VENDOR,
  .bDeviceSubClass      = USB_DEV_SUBCLASS_VENDOR,
  .bDeviceProtocol      = USB_DEV_PROTOCOL_VENDOR,
  .bMaxPacketSize0      = 64,
  .idVendor             = VID_QIHW,
  .idProduct            = PID_GLASGOW,
  .bcdDevice            = 0, // filled in descr_init()
  .iManufacturer        = 1,
  .iProduct             = 2,
  .iSerialNumber        = 3,
  .bNumConfigurations   = 1,
};

usb_desc_device_qualifier_c usb_device_qualifier = {
  .bLength              = sizeof(struct usb_desc_device_qualifier),
  .bDescriptorType      = USB_DESC_DEVICE_QUALIFIER,
  .bcdUSB               = 0x0200,
  .bDeviceClass         = USB_DEV_CLASS_PER_INTERFACE,
  .bDeviceSubClass      = USB_DEV_SUBCLASS_PER_INTERFACE,
  .bDeviceProtocol      = USB_DEV_PROTOCOL_PER_INTERFACE,
  .bMaxPacketSize0      = 8,
  .bNumConfigurations   = 0,
};

#define USB_INTERFACE(bInterfaceNumber_, bAltSetting_, bNumEndpoints_, iInterface_)       \
  {                                                                                       \
    .bLength              = sizeof(struct usb_desc_interface),                            \
    .bDescriptorType      = USB_DESC_INTERFACE,                                           \
    .bInterfaceNumber     = bInterfaceNumber_,                                            \
    .bAlternateSetting    = bAltSetting_,                                                 \
    .bNumEndpoints        = bNumEndpoints_,                                               \
    .bInterfaceClass      = USB_IFACE_CLASS_VENDOR,                                       \
    .bInterfaceSubClass   = USB_IFACE_SUBCLASS_VENDOR,                                    \
    .bInterfaceProtocol   = USB_IFACE_PROTOCOL_VENDOR,                                    \
    .iInterface           = iInterface_,                                                  \
  }

// EP1 interface (mgmt)
usb_desc_interface_c usb_interface_0_disabled =
  USB_INTERFACE(/*bInterfaceNumber=*/0, /*bAltSetting=*/0, /*bNumEndpoints=*/0, /*iInterface*/0);
usb_desc_interface_c usb_interface_0_enabled =
  USB_INTERFACE(/*bInterfaceNumber=*/0, /*bAltSetting=*/1, /*bNumEndpoints=*/2, /*iInterface*/0);
// EP2 interface (2x/4x/cfg/nvm)
usb_desc_interface_c usb_interface_1_disabled =
  USB_INTERFACE(/*bInterfaceNumber=*/1, /*bAltSetting=*/0, /*bNumEndpoints=*/0, /*iInterface*/0);
usb_desc_interface_c usb_interface_1_enabled_2x =
  USB_INTERFACE(/*bInterfaceNumber=*/1, /*bAltSetting=*/1, /*bNumEndpoints=*/1, /*iInterface*/4);
usb_desc_interface_c usb_interface_1_enabled_4x =
  USB_INTERFACE(/*bInterfaceNumber=*/1, /*bAltSetting=*/2, /*bNumEndpoints=*/1, /*iInterface*/5);
usb_desc_interface_c usb_interface_1_enabled_cfg =
  USB_INTERFACE(/*bInterfaceNumber=*/1, /*bAltSetting=*/3, /*bNumEndpoints=*/1, /*iInterface*/6);
usb_desc_interface_c usb_interface_1_enabled_nvm =
  USB_INTERFACE(/*bInterfaceNumber=*/1, /*bAltSetting=*/4, /*bNumEndpoints=*/1, /*iInterface*/7);
// EP4 interface (2x)
usb_desc_interface_c usb_interface_2_disabled =
  USB_INTERFACE(/*bInterfaceNumber=*/2, /*bAltSetting=*/0, /*bNumEndpoints=*/0, /*iInterface*/0);
usb_desc_interface_c usb_interface_2_enabled_2x =
  USB_INTERFACE(/*bInterfaceNumber=*/2, /*bAltSetting=*/1, /*bNumEndpoints=*/1, /*iInterface*/4);
// EP6 interface (2x/4x)
usb_desc_interface_c usb_interface_3_disabled =
  USB_INTERFACE(/*bInterfaceNumber=*/3, /*bAltSetting=*/0, /*bNumEndpoints=*/0, /*iInterface*/0);
usb_desc_interface_c usb_interface_3_enabled_2x =
  USB_INTERFACE(/*bInterfaceNumber=*/3, /*bAltSetting=*/1, /*bNumEndpoints=*/1, /*iInterface*/4);
usb_desc_interface_c usb_interface_3_enabled_4x =
  USB_INTERFACE(/*bInterfaceNumber=*/3, /*bAltSetting=*/2, /*bNumEndpoints=*/1, /*iInterface*/5);
// EP8 interface (2x)
usb_desc_interface_c usb_interface_4_disabled =
  USB_INTERFACE(/*bInterfaceNumber=*/4, /*bAltSetting=*/0, /*bNumEndpoints=*/0, /*iInterface*/0);
usb_desc_interface_c usb_interface_4_enabled_2x =
  USB_INTERFACE(/*bInterfaceNumber=*/4, /*bAltSetting=*/1, /*bNumEndpoints=*/1, /*iInterface*/4);

#define USB_BULK_ENDPOINT(bEndpointAddress_)                                              \
  {                                                                                       \
    .bLength              = sizeof(struct usb_desc_endpoint),                             \
    .bDescriptorType      = USB_DESC_ENDPOINT,                                            \
    .bEndpointAddress     = bEndpointAddress_,                                            \
    .bmAttributes         = USB_XFER_BULK,                                                \
    .wMaxPacketSize       = 512,                                                          \
    .bInterval            = 0,                                                            \
  }

usb_desc_endpoint_c usb_endpoint_1_out =
  USB_BULK_ENDPOINT(/*bEndpointAddress=*/1|USB_DIR_OUT);
usb_desc_endpoint_c usb_endpoint_1_in =
  USB_BULK_ENDPOINT(/*bEndpointAddress=*/1|USB_DIR_IN);
usb_desc_endpoint_c usb_endpoint_2_out =
  USB_BULK_ENDPOINT(/*bEndpointAddress=*/2|USB_DIR_OUT);
usb_desc_endpoint_c usb_endpoint_4_out =
  USB_BULK_ENDPOINT(/*bEndpointAddress=*/4|USB_DIR_OUT);
usb_desc_endpoint_c usb_endpoint_6_in =
  USB_BULK_ENDPOINT(/*bEndpointAddress=*/6|USB_DIR_IN );
usb_desc_endpoint_c usb_endpoint_8_in =
  USB_BULK_ENDPOINT(/*bEndpointAddress=*/8|USB_DIR_IN );

usb_configuration_c usb_config = {
  {
    .bLength              = sizeof(struct usb_desc_configuration),
    .bDescriptorType      = USB_DESC_CONFIGURATION,
    .bNumInterfaces       = 5,
    .bConfigurationValue  = 1,
    .iConfiguration       = 0,
    .bmAttributes         = USB_ATTR_RESERVED_1,
    .bMaxPower            = 250,
  },
  {
    // EP1 interface (mgmt)
    { .interface  = &usb_interface_0_disabled     },
    { .interface  = &usb_interface_0_enabled      },
      { .endpoint    = &usb_endpoint_1_out          },
      { .endpoint    = &usb_endpoint_1_in           },
    // EP2 interface (2x/4x/cfg/nvm)
    { .interface  = &usb_interface_1_disabled     },
    { .interface  = &usb_interface_1_enabled_2x   },
      { .endpoint   = &usb_endpoint_2_out           },
    { .interface  = &usb_interface_1_enabled_4x   },
      { .endpoint   = &usb_endpoint_2_out           },
    { .interface  = &usb_interface_1_enabled_cfg  },
      { .endpoint   = &usb_endpoint_2_out           },
    { .interface  = &usb_interface_1_enabled_nvm  },
      { .endpoint   = &usb_endpoint_2_out           },
    // EP4 interface (2x)
    { .interface  = &usb_interface_2_disabled     },
    { .interface  = &usb_interface_2_enabled_2x   },
      { .endpoint   = &usb_endpoint_4_out           },
    // EP6 interface (2x/4x)
    { .interface  = &usb_interface_3_disabled     },
    { .interface  = &usb_interface_3_enabled_2x   },
      { .endpoint   = &usb_endpoint_6_in            },
    { .interface  = &usb_interface_3_enabled_4x   },
      { .endpoint   = &usb_endpoint_6_in            },
    // EP8 interface (2x)
    { .interface  = &usb_interface_4_disabled     },
    { .interface  = &usb_interface_4_enabled_2x   },
      { .endpoint   = &usb_endpoint_8_in            },
    { 0 }
  }
};

usb_configuration_set_c usb_configs[] = {
  &usb_config,
};

usb_ascii_string_c usb_strings[] = {
  [0] = DEFAULT_MANUFACTURER,
  [1] = ORIGINAL_PRODUCT_WORD " Interface Explorer; " GIT_REVISION,
  [2] = "XX-XXXXXXXXXXXXXXXX",
  [3] = "2X",
  [4] = "4X",
  [5] = "CFG",
  [6] = "NVM",
};

usb_desc_platform_capability_webusb_c usb_capability_webusb = {
  .bLength                = sizeof(struct usb_desc_platform_capability_webusb),
  .bDescriptorType        = USB_DESC_DEVICE_CAPABILITY,
  .bDevCapabilityType     = USB_DEV_CAP_PLATFORM,
  .PlatformCapablityUUID  = USB_PLATFORM_CAPABILITY_UUID_WEBUSB,
  .bcdVersion             = 0x0100,
  .bVendorCode            = USB_REQ_GET_WEBUSB_DESCRIPTOR,
  .iLandingPage           = 1,
};

usb_descriptor_set_c usb_descriptor_set = {
  .device           = &usb_device,
  .device_qualifier = &usb_device_qualifier,
  .config_count     = ARRAYSIZE(usb_configs),
  .configs          = usb_configs,
  .string_count     = ARRAYSIZE(usb_strings),
  .strings          = usb_strings,
  .capability_count = 1,
  .capabilities     = &usb_capability_webusb,
};

usb_desc_microsoft_v10_c usb_microsoft = {
  .bLength          = sizeof(struct usb_desc_microsoft_v10),
  .bDescriptorType  = USB_DESC_STRING,
  .qwSignature      = USB_DESC_MICROSOFT_V10_SIGNATURE,
  .bMS_VendorCode   = 0xC0,
};

usb_desc_ms_ext_compat_id_c usb_ms_ext_compat_id = {
  .dwLength         = sizeof(struct usb_desc_ms_ext_compat_id) +
                      sizeof(struct usb_desc_ms_compat_function),
  .bcdVersion       = 0x0100,
  .wIndex           = USB_DESC_MS_EXTENDED_COMPAT_ID,
  .bCount           = 1,
  .functions        = {
    {
      .bFirstInterfaceNumber  = 0,
      .bReserved1             = 1,
      .compatibleID           = "WINUSB",
    },
  }
};

usb_desc_ms_ext_property_c usb_ms_ext_properties = {
  .dwLength         = sizeof(struct usb_desc_ms_ext_property),
  .bcdVersion       = 0x0100,
  .wIndex           = USB_DESC_MS_EXTENDED_PROPERTIES,
  .wCount           = 0,
};

usb_desc_url_c usb_webusb_url = {
  .bLength          = sizeof(struct usb_desc_url) + sizeof(WEBUSB_URL) - 1,
  .bDescriptorType  = USB_DESC_URL,
  .bScheme          = USB_URL_SCHEME_HTTPS,
  .bURL             = WEBUSB_URL,
};

void handle_usb_get_descriptor(enum usb_descriptor type, uint8_t index)
{
  if (type == USB_DESC_STRING && index == USB_DESC_STRING_MS_INDEX) {
    xmemcpy(scratch, (__xdata void *)&usb_microsoft, usb_microsoft.bLength);
    SETUP_EP0_IN_DESC(scratch);
  } else {
    usb_serve_descriptor(&usb_descriptor_set, type, index);
  }
}

void config_init()
{
  __xdata unsigned char load_cmd;
  if (!eeprom_xfer(I2C_ADDR_FX2_MEM, 0, &load_cmd, sizeof(load_cmd), /*write=*/false))
    goto fail;
  if (load_cmd == 0xff) {
    goto fail;
  } else if (load_cmd == 0xc2) {
    // A C2 load, used on devices with firmware, automatically loads configuration.
  } else if (load_cmd == 0xc0) {
    // A C0 load, used on factory-programmed devices without firmware, does not, so
    // load it explicitly.
    if (!eeprom_xfer(I2C_ADDR_FX2_MEM, 8 + 4, (__xdata void *)&glasgow_config,
                     sizeof(glasgow_config), /*write=*/false))
      goto fail;
  }
  if (!(glasgow_config.flags & CONFIG_FLAG_API_LEVEL_GE_7)) {
    xmemclr((__xdata void *)&glasgow_config.bitstream_size,
            sizeof(glasgow_config.bitstream_size) + sizeof(glasgow_config.bitstream_id));
    glasgow_config.voltage_limit[0] = glasgow_config.voltage_limit[2];
    glasgow_config.voltage_limit[1] = glasgow_config.voltage_limit[3];
    // Don't write changes to flash to avoid confusing old firmware if it's flashed.
  }
  return;

fail:
  // Configuration block is corrupted or missing, load default configuration so that
  // we don't hang or present nonsensical descriptors.
  glasgow_config.revision = GLASGOW_REV_NA;
  xmemcpy((__xdata void *)glasgow_config.serial, (__xdata void *)"9999999999999999",
          sizeof(glasgow_config.serial));
  glasgow_config.bitstream_size = 0;
}

bool config_save(uint8_t offset, uint8_t size)
{
  return eeprom_xfer(I2C_ADDR_FX2_MEM, 8 + 4 + offset,
                     ((__xdata uint8_t *)&glasgow_config) + offset,
                     size,
                     /*write=*/true);
}

#define usb_string_at_index(index) ((__xdata char *)usb_strings[index - 1])

void strings_init()
{
  // Populate descriptors from device configuration, if any.
  __xdata struct usb_desc_device *desc_device = (__xdata struct usb_desc_device *)usb_device;
  __xdata char *desc_string;

  // Set revision from configuration if any, or pretend to be an unflashed device if it's missing.
  if (glasgow_config.revision != GLASGOW_REV_NA) {
    desc_device->bcdDevice = (GLASGOW_API_LEVEL << 8) | glasgow_config.revision;
  } else {
    desc_device->idVendor  = VID_CYPRESS;
    desc_device->idProduct = PID_FX2;
  }

  // Set manufacturer from configuration if it's set. Most devices will have this field zeroed,
  // leaving the manufacturer string at the default value.
  if (glasgow_config.manufacturer[0] != '\0') {
    desc_string = usb_string_at_index(1);
    xmemcpy(&desc_string[0], (__xdata void *)glasgow_config.manufacturer,
            sizeof(glasgow_config.manufacturer));
  }

  // Set product based on configuration flags.
  // Replace the beginning of "Glasgow Interface Explorer" in the string table if
  // the "modified from original design" flag is set in the configuration.
  if (glasgow_config.flags & CONFIG_FLAG_MODIFIED_DESIGN) {
    desc_string = usb_string_at_index(2);
    xmemcpy(&desc_string[0], (__xdata void *)MODIFIED_PRODUCT_WORD,
            sizeof(MODIFIED_PRODUCT_WORD) - 1); // without trailing \0
  }

  // Set serial number from configuration. Serial number must be always valid, and the firmware
  // fixes up the serial number in `config_init()` if the configuration is corrupted or missing.
  desc_string = usb_string_at_index(3);
  desc_string[0] = 'A' + (glasgow_config.revision >> 4) - 1;
  desc_string[1] = '0' + (glasgow_config.revision & 0xF);
  xmemcpy(&desc_string[3], (__xdata void *)glasgow_config.serial,
          sizeof(glasgow_config.serial));
}

void handle_usb_setup(__xdata struct usb_req_setup *req)
{
  register bool req_dir_in = (req->bmRequestType & USB_DIR_IN);

  if (req->bmRequestType != (USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_IN) &&
      req->bmRequestType != (USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_OUT)) {
    goto stall_ep0_return;
  }

  // Microsoft descriptor requests
  if (req_dir_in &&
      req->bRequest == USB_REQ_GET_MS_DESCRIPTOR &&
      req->wIndex == USB_DESC_MS_EXTENDED_COMPAT_ID) {
    xmemcpy(scratch, (__xdata void *)&usb_ms_ext_compat_id, usb_ms_ext_compat_id.dwLength);
    SETUP_EP0_IN_DESC(scratch);
    return;
  }
  if (req_dir_in &&
      req->bRequest == USB_REQ_GET_MS_DESCRIPTOR &&
      req->wIndex == USB_DESC_MS_EXTENDED_PROPERTIES) {
    xmemcpy(scratch, (__xdata void *)&usb_ms_ext_properties, usb_ms_ext_properties.dwLength);
    SETUP_EP0_IN_DESC(scratch);
    return;
  }
  if (req_dir_in &&
      req->bRequest == USB_REQ_GET_WEBUSB_DESCRIPTOR &&
      req->wIndex == /*GET_URL*/ 0x02 &&
      req->wValue == 1 &&
      (glasgow_config.flags & CONFIG_FLAG_ADVERTISE_WEBUSB)) {
    xmemcpy(scratch, (__xdata void *)&usb_webusb_url, usb_webusb_url.bLength);
    SETUP_EP0_IN_DATA(scratch, usb_webusb_url.bLength);
    return;
  }

  // Factor out the stall exit to reduce code size.
stall_ep0_return:
  STALL_EP0();
}

__idata uint8_t usb_alt_setting[5];

bool handle_usb_set_configuration(uint8_t config_value)
{
  mgmt_init();
  fpga_reset_pipes();

  usb_config_value = config_value;
  for (uint8_t intf = 0; intf < ARRAYSIZE(usb_alt_setting); intf++)
    usb_alt_setting[intf] = 0;
  return true;
}

bool handle_usb_set_interface(uint8_t interface, uint8_t alt_setting)
{
  if (interface == IFACE_MGMT) {
    // There's a race condition between this call and processing of management packets.
    // It's not entirely clear how to fix it.
    mgmt_init();
  } else {
    if (!fpga_configure(interface, alt_setting))
      return false;
  }

  usb_reset_data_toggles(&usb_descriptor_set, interface, alt_setting);
  usb_alt_setting[interface] = alt_setting;
  return true;
}

void handle_usb_get_interface(uint8_t interface)
{
  EP0BUF[0] = usb_alt_setting[interface];
  SETUP_EP0_IN_BUF(1);
}

void gpio_init()
{
  // These bitmasks are OK regardless of the board revision.
  // This way of initializing GPIOs is somewhat convoluted, but saves quite a bit of code size.
  OEA = 0x02; IOA = 0x00;
  OED = 0xff; IOD = 0x00;
  OEB = 0x1c; IOB = 0x00;
  // The parallel bus is mutually exclusive with PORTB. Now that we've put the FPGA in reset,
  // disable the bus thus enabling PORTB (if it wasn't already).
  IFCONFIG = 0;
  // Configure IE0 as negedge sensitive.
  IT0 = true;
  EX0 = true;
}

__bit test_leds = 0;

void leds_init()
{
  // Use timer 2 in 16-bit timer mode for ACT LED.
  T2CON = _CPRL2;
  ET2 = true;
  // Set up endpoint interrupts for ACT LED.
  EPIE = _EPI_EP0IN|_EPI_EP0OUT|_EPI_EP1IN|_EPI_EP1OUT|_EPI_EP2|_EPI_EP4|_EPI_EP6|_EPI_EP8;
}

enum mgmt_result leds_mgmt_test()
{
  test_leds = mgmt_req.test_leds.enabled;
  uint8_t leds_mask = (glasgow_config.revision < GLASGOW_REV_D0) ? 0x3c : 0x34;
  IOD = IOD & ~leds_mask;
  if (test_leds) {
    IOD |= ((mgmt_req.test_leds.state << PIND_LED_FX2) & leds_mask);
  } else {
    IO_LED_FX2 = 1;
    IO_LED_ICE_REVABC = (glasgow_config.revision < GLASGOW_REV_D0) && IO_FPGA_DONE;
  }
  return RES_ACK;
}

void isr_IE0() __interrupt(_INT_IE0)
{
  // Light the ERR LED before the alert processing begins.
  if (!test_leds)
    IO_LED_ERR = 1;
}

void isr_TF2() __interrupt(_INT_TF2)
{
  // Dim the ACT LED.
  if (!test_leds)
    IO_LED_ACT = 0;
  TR2 = false;
  TF2 = false;
}

void isr_EPn() __interrupt
{
  // Light the ACT LED.
  if (!test_leds)
    IO_LED_ACT = 1;
  // Let timer 2 run, at the maximum reload value we get a pulse width of around 16ms.
  TR2 = 1;
  // Clear all EPn IRQs, since we don't really need this IRQ to be fine-grained.
  CLEAR_USB_IRQ();
  EPIRQ = _EPI_EP0IN|_EPI_EP0OUT|_EPI_EP1IN|_EPI_EP1OUT|_EPI_EP2|_EPI_EP4|_EPI_EP6|_EPI_EP8;
}

void isr_EP0IN()  __interrupt __naked { __asm ljmp _isr_EPn __endasm; }
void isr_EP0OUT() __interrupt __naked { __asm ljmp _isr_EPn __endasm; }
void isr_EP1IN()  __interrupt __naked { __asm ljmp _isr_EPn __endasm; }
void isr_EP1OUT() __interrupt __naked { __asm ljmp _isr_EPn __endasm; }
void isr_EP2()    __interrupt __naked { __asm ljmp _isr_EPn __endasm; }
void isr_EP4()    __interrupt __naked { __asm ljmp _isr_EPn __endasm; }
void isr_EP6()    __interrupt __naked { __asm ljmp _isr_EPn __endasm; }
void isr_EP8()    __interrupt __naked { __asm ljmp _isr_EPn __endasm; }

int main()
{
  // Use new FIFO features.
  REVCTL = _ENH_PKT|_DYN_OUT;

  // Run at 48 MHz, drive CLKOUT.
  CPUCS = _CLKOE|_CLKSPD1;

  // All of our I2C devices can run at 400 kHz.
  I2CTL = _400KHZ;

  // Set up configuration. This must come before anything that is parameterized by revision.
  config_init();
  strings_init();

  // Initialize subsystems.
  gpio_init();
  leds_init();
  port_init();
  fpga_init();

  if (glasgow_config.revision >= GLASGOW_REV_D0) {
    // TODO: load STM32 with firmware
    IO_MCU_nRESET_REVD = 0;
    IO_MCU_BOOT0_REVD = 1;
    IO_MCU_nRESET_REVD = 1;
  }

  // Load flashed bitstream, if any.
  if (glasgow_config.bitstream_size != 0) {
    IO_LED_ERR = !fpga_load_nvmem();
  }

  // Finally, enumerate.
  usb_init(/*reconnect=*/true);

  while (1) {
    // Handle pending events.
    if (usb_alt_setting[IFACE_MGMT] == EP_MODE_ON)
      mgmt_poll();
    if (usb_alt_setting[IFACE_EP2OUT] >= EP_MODE_CFG) // EP_MODE_CFG or EP_MODE_NVM
      fpga_poll_cfg();
    if (!IO_nALERT) {
      // While the nALERT line is connected to an interrupt-capable pin, we do not handle the alert
      // in the body of the interrupt. Rationale:
      //  - On revABC01, the ADC081C chip is known to behave erratically when automatic conversion
      //    is enabled (see `port.c` for details). As a result, alert functionality is disabled.
      //  - On revC23D, the INA233 chip's alert line is hardwired to disable that port's supply
      //    voltage. As a result, detecting and clearing the alert is not time-critical.
      //  - The I2C API is not interrupt-safe, and if an I2C transaction is already in progress,
      //    attempting to access the I2C bus may result in unpredictable consequences.
      // Instead, the interrupt is used to pre-light the ERR LED, indicating that something went
      // wrong even if the firmware hangs while handling it (e.g. due to an I2C lockup).
      port_poll_alert();
      fpga_poll_alert();
    }

    if (!test_leds) {
      // There are few things more frustrating than having your debug tools fail you. Power-only
      // USB cables are regretfully common. If the device finds itself without an address it should
      // indicate this unusual condition, though in a gentle way because there are legitimate
      // reasons for this to happen (PC in suspend, Glasgow used 'offline', etc).
      if (FNADDR == 0) {
        // If no address is assigned, slowly breathe. (Or, during enumeration, abruptly blink.
        // That's okay though.)
        switch (USBFRAMEH >> 1) {
          case 0b00: IO_LED_FX2 = 1; break;
          case 0b10: IO_LED_FX2 = 0; break;
          case 0b01:
          case 0b11: IO_LED_FX2 ^= 1; break;
        }
      } else {
        // Got plugged in, light up permanently.
        IO_LED_FX2 = true;
      }
      // On revD0 and later, this LED is connected directly to FPGA's configuration done output.
      if (glasgow_config.revision < GLASGOW_REV_D0)
        IO_LED_ICE_REVABC = IO_FPGA_DONE;
    }
  }
}
