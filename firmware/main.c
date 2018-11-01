#include <string.h>
#include <fx2lib.h>
#include <fx2regs.h>
#include <fx2ints.h>
#include <fx2usb.h>
#include <fx2delay.h>
#include <fx2i2c.h>
#include <fx2eeprom.h>
#include <usbmicrosoft.h>
#include "glasgow.h"

usb_desc_device_c usb_device = {
  .bLength              = sizeof(struct usb_desc_device),
  .bDescriptorType      = USB_DESC_DEVICE,
  .bcdUSB               = 0x0200,
  .bDeviceClass         = 255,
  .bDeviceSubClass      = 255,
  .bDeviceProtocol      = 255,
  .bMaxPacketSize0      = 64,
  .idVendor             = VID_QIHW,
  .idProduct            = PID_GLASGOW,
  .bcdDevice            = 0x0100,
  .iManufacturer        = 1,
  .iProduct             = 2,
  .iSerialNumber        = 3,
  .bNumConfigurations   = 2,
};

usb_desc_configuration_c usb_configs[] = {
  {
    .bLength              = sizeof(struct usb_desc_configuration),
    .bDescriptorType      = USB_DESC_CONFIGURATION,
    .wTotalLength         = sizeof(struct usb_desc_configuration) +
                            4 * sizeof(struct usb_desc_interface) +
                            4 * sizeof(struct usb_desc_endpoint),
    .bNumInterfaces       = 2,
    .bConfigurationValue  = 1,
    .iConfiguration       = 4,
    .bmAttributes         = USB_ATTR_RESERVED_1,
    .bMaxPower            = 250,
  },
  {
    .bLength              = sizeof(struct usb_desc_configuration),
    .bDescriptorType      = USB_DESC_CONFIGURATION,
    .wTotalLength         = sizeof(struct usb_desc_configuration) +
                            2 * sizeof(struct usb_desc_interface) +
                            2 * sizeof(struct usb_desc_endpoint),
    .bNumInterfaces       = 1,
    .bConfigurationValue  = 2,
    .iConfiguration       = 5,
    .bmAttributes         = USB_ATTR_RESERVED_1,
    .bMaxPower            = 250,
  },
};

#define USB_INTERFACE(bInterfaceNumber_, bAlternateSetting_, bNumEndpoints_, iInterface_) \
  {                                                                                       \
    .bLength              = sizeof(struct usb_desc_interface),                            \
    .bDescriptorType      = USB_DESC_INTERFACE,                                           \
    .bInterfaceNumber     = bInterfaceNumber_,                                            \
    .bAlternateSetting    = bAlternateSetting_,                                           \
    .bNumEndpoints        = bNumEndpoints_,                                               \
    .bInterfaceClass      = 255,                                                          \
    .bInterfaceSubClass   = 255,                                                          \
    .bInterfaceProtocol   = 255,                                                          \
    .iInterface           = iInterface_,                                                  \
  }

usb_desc_interface_c usb_interfaces[] = {
  // No endpoints
  USB_INTERFACE(/*bInterfaceNumber=*/0, /*bAlternateSetting=*/0, /*bNumEndpoints=*/0,
                /*iInterface=*/6),
  // EP2OUT BULK + EP6IN BULK
  USB_INTERFACE(/*bInterfaceNumber=*/0, /*bAlternateSetting=*/1, /*bNumEndpoints=*/2,
                /*iInterface=*/7),
  // No endpoints
  USB_INTERFACE(/*bInterfaceNumber=*/1, /*bAlternateSetting=*/0, /*bNumEndpoints=*/0,
                /*iInterface=*/8),
  // EP4OUT BULK + EP8IN BULK
  USB_INTERFACE(/*bInterfaceNumber=*/1, /*bAlternateSetting=*/1, /*bNumEndpoints=*/2,
                /*iInterface=*/9),
  // No endpoints
  USB_INTERFACE(/*bInterfaceNumber=*/0, /*bAlternateSetting=*/0, /*bNumEndpoints=*/0,
                /*iInterface=*/10),
  // EP2OUT BULK + EP6IN BULK
  USB_INTERFACE(/*bInterfaceNumber=*/0, /*bAlternateSetting=*/1, /*bNumEndpoints=*/2,
                /*iInterface=*/11),
};

#define USB_BULK_ENDPOINT(bEndpointAddress_)                                              \
  {                                                                                       \
    .bLength              = sizeof(struct usb_desc_endpoint),                             \
    .bDescriptorType      = USB_DESC_ENDPOINT,                                            \
    .bEndpointAddress     = bEndpointAddress_,                                            \
    .bmAttributes         = USB_XFER_BULK,                                                \
    .wMaxPacketSize       = 512,                                                          \
    .bInterval            = 0,                                                            \
  }

usb_desc_endpoint_c usb_endpoints[] = {
  // EP2OUT BULK
  USB_BULK_ENDPOINT(/*bEndpointAddress=*/2|USB_DIR_OUT),
  // EP6IN  BULK
  USB_BULK_ENDPOINT(/*bEndpointAddress=*/6|USB_DIR_IN ),
  // EP4OUT BULK
  USB_BULK_ENDPOINT(/*bEndpointAddress=*/4|USB_DIR_OUT),
  // EP8IN  BULK
  USB_BULK_ENDPOINT(/*bEndpointAddress=*/8|USB_DIR_IN ),
  // EP2OUT BULK
  USB_BULK_ENDPOINT(/*bEndpointAddress=*/2|USB_DIR_OUT),
  // EP6IN  BULK
  USB_BULK_ENDPOINT(/*bEndpointAddress=*/6|USB_DIR_IN ),
};

usb_ascii_string_c usb_strings[] = {
  [0] = "whitequark research",
  [1] = "Glasgow Debug Tool",
  [2] = "X-XXXXXXXXXXXXXXXX",
  // Configurations
  [3] = "Pipe Q at {2x512B EP2OUT/EP6IN}, R at {2x512B EP4OUT/EP8IN}",
  [4] = "Pipe Q at {4x512B EP2OUT/EP6IN}",
  // Interfaces
  [5] = "Pipe Q disabled",
  [6] = "Pipe Q at {2x512B EP2OUT/EP6IN BULK}",
  [7] = "Pipe R disabled",
  [8] = "Pipe R at {2x512B EP4OUT/EP8IN BULK}",
  [9] = "Pipe Q disabled",
  [10] = "Pipe Q at {4x512B EP2OUT/EP6IN BULK}",
};

usb_descriptor_set_c usb_descriptor_set = {
  .device          = &usb_device,
  .config_count    = ARRAYSIZE(usb_configs),
  .configs         = usb_configs,
  .interface_count = ARRAYSIZE(usb_interfaces),
  .interfaces      = usb_interfaces,
  .endpoint_count  = ARRAYSIZE(usb_endpoints),
  .endpoints       = usb_endpoints,
  .string_count    = ARRAYSIZE(usb_strings),
  .strings         = usb_strings,
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

void handle_usb_get_descriptor(enum usb_descriptor type, uint8_t index) {
  if(type == USB_DESC_STRING && index == 0xEE) {
    xmemcpy(scratch, (__xdata void *)&usb_microsoft, usb_microsoft.bLength);
    SETUP_EP0_IN_DESC(scratch);
  } else {
    usb_serve_descriptor(&usb_descriptor_set, type, index);
  }
}

static void config_init() {
  unsigned char load_cmd;
  if(!eeprom_read(I2C_ADDR_FX2_MEM, 0, &load_cmd, sizeof(load_cmd), /*double_byte=*/true))
    goto fail;
  if(load_cmd == 0xff) {
    goto fail;
  } else if(load_cmd == 0xc2) {
    // A C2 load, used on devices with firmware, automatically loads configuration.
    return;
  } else if(load_cmd == 0xc0) {
    // A C0 load, used on factory-programmed devices without firmware, does not, so
    // load it explicitly.
    if(!eeprom_read(I2C_ADDR_FX2_MEM, 8 + 4, (__xdata void *)&glasgow_config,
                    sizeof(glasgow_config), /*double_byte=*/true))
      goto fail;
    return;
  }

fail:
  // Configuration block is corrupted or missing, load default configuration so that
  // we don't hang or present nonsensical descriptors.
  glasgow_config.revision = 'Z';
  xmemcpy((__xdata void *)glasgow_config.serial, (__xdata void *)"9999999999999999",
          sizeof(glasgow_config.serial));
  glasgow_config.bitstream_size = 0;
}

// Populate descriptors from device configuration, if any.
static void descriptors_init() {
  __xdata struct usb_desc_device *desc_device = (__xdata struct usb_desc_device *)usb_device;
  __xdata char *desc_serial = (__xdata char *)usb_strings[usb_device.iSerialNumber - 1];

  desc_device->bcdDevice |= 1 + glasgow_config.revision - 'A';
  desc_serial[0] = glasgow_config.revision;
  xmemcpy(&desc_serial[2], (__xdata void *)glasgow_config.serial,
          sizeof(glasgow_config.serial));
}

enum {
  // Glasgow requests
  USB_REQ_EEPROM       = 0x10,
  USB_REQ_FPGA_CFG     = 0x11,
  USB_REQ_STATUS       = 0x12,
  USB_REQ_REGISTER     = 0x13,
  USB_REQ_IO_VOLT      = 0x14,
  USB_REQ_SENSE_VOLT   = 0x15,
  USB_REQ_ALERT_VOLT   = 0x16,
  USB_REQ_POLL_ALERT   = 0x17,
  USB_REQ_BITSTREAM_ID = 0x18,
  USB_REQ_IOBUF_ENABLE = 0x19,
  USB_REQ_LIMIT_VOLT   = 0x1A,
  // Cypress requests
  USB_REQ_CYPRESS_EEPROM_DB = 0xA9,
  // libfx2 requests
  USB_REQ_LIBFX2_PAGE_SIZE  = 0xB0,
  // Microsoft requests
  USB_REQ_GET_MS_DESCRIPTOR = 0xC0,
};

enum {
  // Status bits
  ST_ERROR    = 1<<0,
  ST_FPGA_RDY = 1<<1,
  ST_ALERT    = 1<<2,
};

// We use a self-clearing error latch. That is, when an error condition occurs,
// we light up the ERR LED, and set ST_ERROR bit in the status register.
// When the status register is next read, the ST_ERROR bit is cleared and the LED
// is turned off.
//
// The reason for this design is that stalling an OUT transfer results in
// an USB timeout, and we want to indicate error conditions faster.
static uint8_t status;

static void update_leds() {
  led_err_set(status & (ST_ERROR | ST_ALERT));
  led_fpga_set(status & ST_FPGA_RDY);
}

static void latch_status_bit(uint8_t bit) {
  status |= bit;
  update_leds();
}

static bool check_status_bit(uint8_t bit) {
  return status & bit;
}

static bool reset_status_bit(uint8_t bit) {
  if(status & bit) {
    status &= ~bit;
    update_leds();
    return true;
  }
  return false;
}

// We perform lengthy operations in the main loop to avoid hogging the interrupt.
// This flag is used for synchronization between the main loop and the ISR;
// to allow new SETUP requests to arrive while the previous one is still being
// handled (with all data received), the flag should be reset as soon as
// the entire SETUP request is parsed.
static volatile bool pending_setup;

void handle_usb_setup(__xdata struct usb_req_setup *req) {
  req;
  if(pending_setup) {
    STALL_EP0();
  } else {
    pending_setup = true;
  }
}

uint8_t usb_alt_setting[2];

bool handle_usb_set_configuration(uint8_t config_value) {
  switch(config_value) {
    case 0: break;
    case 1: fifo_configure(/*two_ep=*/false); break;
    case 2: fifo_configure(/*two_ep=*/true);  break;
    default: return false;
  }

  usb_config_value = config_value;
  usb_alt_setting[0] = 0;
  usb_alt_setting[1] = 0;

  usb_reset_data_toggles(&usb_descriptor_set, /*interface=*/0xff, /*alt_setting=*/0xff);
  return true;
}

bool handle_usb_set_interface(uint8_t interface, uint8_t alt_setting) {
  bool two_ep;

  switch(usb_config_value) {
    case 1: two_ep = false; break;
    case 2: two_ep = true;  break;
    default: return false;
  }

  if(alt_setting == 1) {
    // The interface is being (re)activated, so reset the FIFOs.
    fifo_reset(two_ep, (1 << interface));
  }

  usb_alt_setting[interface] = alt_setting;

  usb_reset_data_toggles(&usb_descriptor_set, interface, alt_setting);
  return true;
}

void handle_usb_get_interface(uint8_t interface) {
  EP0BUF[0] = usb_alt_setting[interface];
  SETUP_EP0_BUF(1);
}

// This monotonically increasing number ensures that we upload bitstream chunks
// strictly in order.
uint16_t bitstream_idx;

void handle_pending_usb_setup() {
  __xdata struct usb_req_setup *req = (__xdata struct usb_req_setup *)SETUPDAT;

  // EEPROM read/write requests
  if(req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_OUT &&
     req->bRequest == USB_REQ_LIBFX2_PAGE_SIZE) {
    pending_setup = false;

    // We have built-in knowledge of correct page sizes, ignore any supplied value.
    ACK_EP0();
    return;
  }

  if((req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_IN ||
      req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_OUT) &&
     (req->bRequest == USB_REQ_CYPRESS_EEPROM_DB ||
      req->bRequest == USB_REQ_EEPROM)) {
    bool     arg_read = (req->bmRequestType & USB_DIR_IN);
    uint8_t  arg_chip = 0;
    uint16_t arg_addr = req->wValue;
    uint16_t arg_len  = req->wLength;
    uint8_t  page_size = 0;
    uint8_t  timeout   = 255; // 5 ms
    if(req->bRequest == USB_REQ_CYPRESS_EEPROM_DB) {
      arg_chip = I2C_ADDR_FX2_MEM;
    } else /* req->bRequest == USB_REQ_EEPROM */ {
      switch(req->wIndex) {
        case 0:
          arg_chip  = I2C_ADDR_FX2_MEM;
          page_size = 6; // 64 bytes
          break;
        case 1:
          arg_chip  = I2C_ADDR_ICE_MEM;
          page_size = 8; // 256 bytes
          break;
        case 2:
          // Same chip, different I2C address for the top half.
          arg_chip  = I2C_ADDR_ICE_MEM + 1;
          page_size = 8;
          break;
      }
    }
    pending_setup = false;

    if(!arg_chip) {
      STALL_EP0();
      return;
    }

    while(arg_len > 0) {
      uint8_t chunk_len = arg_len < 64 ? arg_len : 64;

      if(arg_read) {
        while(EP0CS & _BUSY);
        if(!eeprom_read(arg_chip, arg_addr, EP0BUF, chunk_len, /*double_byte=*/true)) {
          STALL_EP0();
          break;
        }
        SETUP_EP0_BUF(chunk_len);
      } else {
        SETUP_EP0_BUF(0);
        while(EP0CS & _BUSY);
        if(!eeprom_write(arg_chip, arg_addr, EP0BUF, chunk_len, /*double_byte=*/true,
                         page_size, timeout)) {
          STALL_EP0();
          break;
        }
      }

      arg_len  -= chunk_len;
      arg_addr += chunk_len;
    }

    return;
  }

  // FPGA register read/write requests
  if((req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_IN ||
      req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_OUT) &&
     req->bRequest == USB_REQ_REGISTER) {
    bool     arg_read = (req->bmRequestType & USB_DIR_IN);
    uint8_t  arg_addr = req->wValue;
    uint16_t arg_len  = req->wLength;
    pending_setup = false;

    if(fpga_reg_select(arg_addr)) {
      if(arg_read) {
        while(EP0CS & _BUSY);
        if(fpga_reg_read(EP0BUF, arg_len)) {
          SETUP_EP0_BUF(arg_len);
          return;
        }
      } else {
        SETUP_EP0_BUF(0);
        while(EP0CS & _BUSY);
        fpga_reg_write(EP0BUF, arg_len);
        return;
      }
    }

    STALL_EP0();
    return;
  }

  // Device status request
  if((req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_IN) &&
     req->bRequest == USB_REQ_STATUS &&
     req->wLength == 1) {
    pending_setup = false;

    while(EP0CS & _BUSY);
    EP0BUF[0] = status;
    SETUP_EP0_BUF(1);

    reset_status_bit(ST_ERROR);

    return;
  }

  // Bitstream download request
  if(req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_OUT &&
     req->bRequest == USB_REQ_FPGA_CFG &&
     (req->wIndex == 0 || req->wIndex == bitstream_idx + 1)) {
    uint16_t arg_idx = req->wIndex;
    uint16_t arg_len = req->wLength;
    pending_setup = false;

    if(arg_idx == 0) {
      reset_status_bit(ST_FPGA_RDY);
      memset(glasgow_config.bitstream_id, 0, BITSTREAM_ID_SIZE);
      fpga_reset();
    }

    while(arg_len > 0) {
      uint8_t chunk_len = arg_len < 64 ? arg_len : 64;

      SETUP_EP0_BUF(0);
      while(EP0CS & _BUSY);
      fpga_load(EP0BUF, chunk_len);

      arg_len -= chunk_len;
    }

    bitstream_idx = arg_idx;
    return;
  }

  // Bitstream ID get/set request
  if((req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_IN ||
      req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_OUT) &&
     req->bRequest == USB_REQ_BITSTREAM_ID &&
     req->wLength == BITSTREAM_ID_SIZE) {
    bool arg_get = (req->bmRequestType & USB_DIR_IN);
    pending_setup = false;

    if(arg_get) {
      while(EP0CS & _BUSY);
      xmemcpy(EP0BUF, glasgow_config.bitstream_id, BITSTREAM_ID_SIZE);
      SETUP_EP0_BUF(BITSTREAM_ID_SIZE);
    } else {
      fpga_start();
      if(fpga_is_ready()) {
        latch_status_bit(ST_FPGA_RDY);

        SETUP_EP0_BUF(0);
        while(EP0CS & _BUSY);
        xmemcpy(glasgow_config.bitstream_id, EP0BUF, BITSTREAM_ID_SIZE);
      } else {
        STALL_EP0();
      }
    }

    return;
  }

  // I/O voltage get/set request
  if((req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_IN ||
      req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_OUT) &&
     req->bRequest == USB_REQ_IO_VOLT &&
     req->wLength == 2) {
    bool     arg_get = (req->bmRequestType & USB_DIR_IN);
    uint8_t  arg_mask = req->wIndex;
    pending_setup = false;

    if(arg_get) {
      while(EP0CS & _BUSY);
      if(!iobuf_get_voltage(arg_mask, (__xdata uint16_t *)EP0BUF)) {
        STALL_EP0();
      } else {
        SETUP_EP0_BUF(2);
      }
    } else {
      SETUP_EP0_BUF(2);
      while(EP0CS & _BUSY);
      if(!iobuf_set_voltage(arg_mask, (__xdata uint16_t *)EP0BUF)) {
        latch_status_bit(ST_ERROR);
      }
    }

    return;
  }

  // Voltage sense request
  if(req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_IN &&
     req->bRequest == USB_REQ_SENSE_VOLT &&
     req->wLength == 2) {
    uint8_t  arg_mask = req->wIndex;
    pending_setup = false;

    while(EP0CS & _BUSY);
    if(!iobuf_measure_voltage(arg_mask, (__xdata uint16_t *)EP0BUF)) {
      STALL_EP0();
    } else {
      SETUP_EP0_BUF(2);
    }

    return;
  }

  // Voltage alert get/set request
  if((req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_IN ||
      req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_OUT) &&
     req->bRequest == USB_REQ_ALERT_VOLT &&
     req->wLength == 4) {
    bool     arg_get = (req->bmRequestType & USB_DIR_IN);
    uint8_t  arg_mask = req->wIndex;
    pending_setup = false;

    if(arg_get) {
      while(EP0CS & _BUSY);
      if(!iobuf_get_alert(arg_mask, (__xdata uint16_t *)EP0BUF, (__xdata uint16_t *)EP0BUF + 1)) {
        STALL_EP0();
      } else {
        SETUP_EP0_BUF(4);
      }
    } else {
      SETUP_EP0_BUF(4);
      while(EP0CS & _BUSY);
      if(!iobuf_set_alert(arg_mask, (__xdata uint16_t *)EP0BUF, (__xdata uint16_t *)EP0BUF + 1)) {
        latch_status_bit(ST_ERROR);
      }
    }

    return;
  }

  // Alert poll request
  if((req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_IN) &&
     req->bRequest == USB_REQ_POLL_ALERT &&
     req->wLength == 1) {
    pending_setup = false;

    while(EP0CS & _BUSY);
    iobuf_poll_alert(EP0BUF, /*clear=*/true);
    SETUP_EP0_BUF(1);

    reset_status_bit(ST_ALERT);

    return;
  }

  // I/O buffer enable request
  if((req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_OUT) &&
     req->bRequest == USB_REQ_IOBUF_ENABLE &&
     req->wLength == 0) {
    bool arg_enable = req->wValue;
    pending_setup = false;

    iobuf_enable(arg_enable);
    ACK_EP0();

    return;
  }

  // I/O voltage limit get/set request
  if((req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_IN ||
      req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_OUT) &&
     req->bRequest == USB_REQ_LIMIT_VOLT &&
     req->wLength == 2) {
    bool     arg_get = (req->bmRequestType & USB_DIR_IN);
    uint8_t  arg_mask = req->wIndex;
    pending_setup = false;

    if(arg_get) {
      while(EP0CS & _BUSY);
      if(!iobuf_get_voltage_limit(arg_mask, (__xdata uint16_t *)EP0BUF)) {
        STALL_EP0();
      } else {
        if(!eeprom_write(I2C_ADDR_FX2_MEM,
                         8 + 4 + __builtin_offsetof(struct glasgow_config, voltage_limit),
                         (__xdata void *)&glasgow_config.voltage_limit,
                         sizeof(glasgow_config.voltage_limit),
                         /*double_byte=*/true, /*page_size=*/8, /*timeout=*/255)) {
          STALL_EP0();
        } else {
          SETUP_EP0_BUF(2);
        }
      }
    } else {
      SETUP_EP0_BUF(2);
      while(EP0CS & _BUSY);
      if(!iobuf_set_voltage_limit(arg_mask, (__xdata uint16_t *)EP0BUF)) {
        latch_status_bit(ST_ERROR);
      }
    }

    return;
  }

  // Microsoft descriptor requests
  if(req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_IN &&
     req->bRequest == USB_REQ_GET_MS_DESCRIPTOR) {
    enum usb_descriptor_microsoft arg_desc = req->wIndex;
    pending_setup = false;

    switch(arg_desc) {
      case USB_DESC_MS_EXTENDED_COMPAT_ID:
        xmemcpy(scratch, (__xdata void *)&usb_ms_ext_compat_id, usb_ms_ext_compat_id.dwLength);
        SETUP_EP0_IN_DESC(scratch);
        return;
    }

    STALL_EP0();
    return;
  }

  STALL_EP0();
}

volatile bool pending_alert;

void isr_IE0() __interrupt(_INT_IE0) {
  pending_alert = true;
}

void handle_pending_alert() {
  __xdata uint8_t mask;
  __xdata uint16_t millivolts = 0;

  pending_alert = false;

  latch_status_bit(ST_ALERT);
  iobuf_poll_alert(&mask, /*clear=*/false);
  iobuf_set_voltage(mask, &millivolts);
}

void isr_TF2() __interrupt(_INT_TF2) {
  // Inlined from led_act_set() for call-free interrupt code.
  IOD &= ~(1<<PIND_LED_ACT);
  TR2 = false;
  TF2 = false;
}

static void isr_EPn() __interrupt {
  // Inlined from led_act_set() for call-free interrupt code.
  IOD |= (1<<PIND_LED_ACT);
  // Just let it run, at the maximum reload value we get a pulse width of around 16ms.
  TR2 = true;
  // Clear all EPn IRQs, since we don't really need this IRQ to be fine-grained.
  CLEAR_USB_IRQ();
  EPIRQ = _EPI_EP0IN|_EPI_EP0OUT|_EPI_EP2|_EPI_EP4|_EPI_EP6|_EPI_EP8;
}

void isr_EP0IN()  __interrupt __naked { __asm ljmp _isr_EPn __endasm; }
void isr_EP0OUT() __interrupt __naked { __asm ljmp _isr_EPn __endasm; }
void isr_EP2()    __interrupt __naked { __asm ljmp _isr_EPn __endasm; }
void isr_EP4()    __interrupt __naked { __asm ljmp _isr_EPn __endasm; }
void isr_EP6()    __interrupt __naked { __asm ljmp _isr_EPn __endasm; }
void isr_EP8()    __interrupt __naked { __asm ljmp _isr_EPn __endasm; }

int main() {
  // Run at 48 MHz, drive CLKOUT.
  CPUCS = _CLKOE|_CLKSPD1;

  // All of our I2C devices can run at 400 kHz.
  I2CTL = _400KHZ;

  // Initialize subsystems.
  config_init();
  descriptors_init();
  leds_init();
  iobuf_init_dac_ldo();
  iobuf_init_adc();
  fifo_init();

  // Disable EP1IN/OUT
  SYNCDELAY;
  EP1INCFG = 0;
  SYNCDELAY;
  EP1OUTCFG = 0;

  // Use timer 2 in 16-bit timer mode for ACT LED.
  T2CON = _CPRL2;
  ET2 = true;

  // Set up endpoint interrupts for ACT LED.
  EPIE |= _EPI_EP0IN|_EPI_EP0OUT|_EPI_EP2|_EPI_EP4|_EPI_EP6|_EPI_EP8;

  // Set up interrupt for ADC ALERT.
  EX0 = true;

  // If there's a bitstream flashed, load it.
  if(glasgow_config.bitstream_size > 0) {
    uint32_t length = glasgow_config.bitstream_size;
    uint8_t  chip = I2C_ADDR_ICE_MEM;
    uint16_t addr = 0;

    // Loading the bitstream over I2C can take up to five seconds.
    led_act_set(true);

    fpga_reset();
    while(length > 0) {
      uint8_t chunk_len = 0x80;
      if(length < chunk_len)
        chunk_len = length;

      if(!eeprom_read(chip, addr, (uint8_t *)&scratch, chunk_len, /*double_byte=*/true))
        break;
      fpga_load((__xdata uint8_t *)scratch, chunk_len);

      length -= chunk_len;
      addr   += chunk_len;
      if(addr == 0)
        chip += 1; // address wraparound
    }
    if(length == 0)
      fpga_start();

    led_act_set(false);
  }

  // Latch initial status bits.
  // FPGA could be ready because we've loaded it above, or because the firmware was
  // reloaded live.
  if(fpga_is_ready())
    latch_status_bit(ST_FPGA_RDY);

  // Finally, enumerate.
  usb_init(/*reconnect=*/true);

  while(1) {
    if(pending_setup)
      handle_pending_usb_setup();
    if(pending_alert)
      handle_pending_alert();
  }
}
