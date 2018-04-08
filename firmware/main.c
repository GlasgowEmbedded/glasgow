#include <fx2lib.h>
#include <fx2usb.h>
#include <fx2delay.h>
#include <fx2eeprom.h>
#include "glasgow.h"

const struct usb_desc_device
usb_device = {
  .bLength              = sizeof(struct usb_desc_device),
  .bDescriptorType      = USB_DESC_DEVICE,
  .bcdUSB               = 0x0200,
  .bDeviceClass         = 255,
  .bDeviceSubClass      = 255,
  .bDeviceProtocol      = 255,
  .bMaxPacketSize0      = 64,
  .idVendor             = VID_OPENMOKO,
  .idProduct            = PID_GLASGOW,
  .bcdDevice            = 0x0001,
  .iManufacturer        = 1,
  .iProduct             = 2,
  .iSerialNumber        = 0,
  .bNumConfigurations   = 1,
};

const struct usb_desc_configuration
usb_configs[] = {
  {
    .bLength              = sizeof(struct usb_desc_configuration),
    .bDescriptorType      = USB_DESC_CONFIGURATION,
    .wTotalLength         = sizeof(struct usb_desc_configuration) +
                            sizeof(struct usb_desc_interface),
    .bNumInterfaces       = 1,
    .bConfigurationValue  = 0,
    .iConfiguration       = 0,
    .bmAttributes         = USB_ATTR_RESERVED_1,
    .bMaxPower            = 50,
  }
};

const struct usb_desc_interface
usb_interfaces[] = {
  {
    .bLength              = sizeof(struct usb_desc_interface),
    .bDescriptorType      = USB_DESC_INTERFACE,
    .bInterfaceNumber     = 0,
    .bAlternateSetting    = 0,
    .bNumEndpoints        = 0,
    .bInterfaceClass      = 255,
    .bInterfaceSubClass   = 255,
    .bInterfaceProtocol   = 255,
    .iInterface           = 0,
  }
};

const char *
usb_strings[] = {
  "whitequark research",
  "Glasgow Debug Peripheral",
};

const struct usb_descriptor_set
usb_descriptor_set = {
  .device          = &usb_device,
  .config_count    = ARRAYSIZE(usb_configs),
  .configs         = usb_configs,
  .interface_count = ARRAYSIZE(usb_interfaces),
  .interfaces      = usb_interfaces,
  .string_count    = ARRAYSIZE(usb_strings),
  .strings         = usb_strings,
};

enum {
  // Glasgow requests
  USB_REQ_EEPROM = 0x10,
  USB_REQ_FPGA   = 0x11,
  // Cypress requests
  USB_REQ_CYPRESS_EEPROM_DB = 0xA9,
};

// We perform lengthy operations in the main loop to avoid hogging the interrupt.
// This flag is used for synchronization between the main loop and the ISR;
// to allow new SETUP requests to arrive while the previous one is still being
// handled (with all data received), the flag should be reset as soon as
// the entire SETUP request is parsed.
volatile bool pending_setup;

void handle_usb_setup(__xdata struct usb_req_setup *req) {
  req;
  if(pending_setup) {
    STALL_EP0();
  } else {
    pending_setup = true;
  }
}

// This monotonically increasing number ensures that we upload bitstream chunks
// strictly in order.
uint16_t bitstream_idx;

void handle_pending_usb_setup() {
  __xdata struct usb_req_setup *req = (__xdata struct usb_req_setup *)SETUPDAT;

  // EEPROM read/write requests
  if((req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_IN ||
      req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_OUT) &&
     (req->bRequest == USB_REQ_EEPROM ||
      req->bRequest == USB_REQ_CYPRESS_EEPROM_DB)) {
    bool     arg_read = (req->bmRequestType & USB_DIR_IN);
    uint8_t  arg_chip;
    uint16_t arg_addr = req->wValue;
    uint16_t arg_len  = req->wLength;
    if(req->bRequest == USB_REQ_CYPRESS_EEPROM_DB) {
      arg_chip = 0b1010001;
    } else /* req->bRequest == USB_REQ_RW_EEPROM */ {
      switch(req->wIndex) {
        case 0:  arg_chip = 0b1010001;
        case 1:  arg_chip = 0b1010010;
        case 2:  arg_chip = 0b1010011;
        default: STALL_EP0(); return;
      }
    }
    pending_setup = false;

    while(arg_len > 0) {
      uint8_t chunk_len = arg_len < 64 ? arg_len : 64;

      if(arg_read) {
        while(EP0CS & _BUSY);
        if(!eeprom_read(arg_chip, arg_addr, EP0BUF, chunk_len, /*double_byte=*/2)) {
          STALL_EP0();
          break;
        }
        SETUP_EP0_BUF(chunk_len);
      } else {
        SETUP_EP0_BUF(0);
        while(EP0CS & _BUSY);
        if(!eeprom_write(arg_chip, arg_addr, EP0BUF, chunk_len, /*double_byte=*/2)) {
          STALL_EP0();
          break;
        }
      }

      arg_len  -= chunk_len;
      arg_addr += chunk_len;
    }

    return;
  }

  // Bitstream download request
  if(req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_OUT &&
     req->bRequest == USB_REQ_FPGA &&
     (req->wIndex == 0 || req->wIndex == bitstream_idx + 1)) {
    uint16_t arg_idx = req->wIndex;
    uint16_t arg_len = req->wLength;
    pending_setup = false;

    if(arg_len > 0) {
      if(arg_idx == 0)
        fpga_reset();

      while(arg_len > 0) {
        uint8_t chunk_len = arg_len < 64 ? arg_len : 64;

        SETUP_EP0_BUF(0);
        while(EP0CS & _BUSY);
        fpga_load(EP0BUF, chunk_len);

        arg_len -= chunk_len;
      }

      bitstream_idx = arg_idx;
    } else {
      // TODO: check CDONE here
      fpga_start();
      ACK_EP0();
    }

    return;
  }

  STALL_EP0();
}

int main() {
  CPUCS = _CLKOE|_CLKSPD1; // Run at 48 MHz, drive CLKOUT
  usb_init(/*reconnect=*/true);

  while(1) {
    if(pending_setup)
      handle_pending_usb_setup();
  }
}
