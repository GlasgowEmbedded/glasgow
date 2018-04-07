#include <fx2lib.h>
#include <fx2usb.h>
#include <fx2delay.h>
#include <fx2eeprom.h>

const struct usb_desc_device
usb_device = {
  .bLength              = sizeof(struct usb_desc_device),
  .bDescriptorType      = USB_DESC_DEVICE,
  .bcdUSB               = 0x0200,
  .bDeviceClass         = 255,
  .bDeviceSubClass      = 255,
  .bDeviceProtocol      = 255,
  .bMaxPacketSize0      = 64,
  .idVendor             = 0x1d50,
  .idProduct            = 0x7777,
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
  USB_REQ_RW_EEPROM = 0x10,
  // Cypress requests
  USB_REQ_CYPRESS_RW_EEPROM_DB = 0xA9,
};

volatile enum {
  REQ_NONE = 0,
  REQ_EEPROM,
} request;

uint8_t  arg_eeprom_chip;
bool     arg_eeprom_read;
uint16_t arg_eeprom_addr;
uint16_t arg_eeprom_len;

bool handle_usb_request(__xdata struct usb_req_setup *req) {
  if((req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_IN ||
      req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_OUT) &&
     (req->bRequest == USB_REQ_RW_EEPROM ||
      req->bRequest == USB_REQ_CYPRESS_RW_EEPROM_DB)) {
    if(req->bRequest == USB_REQ_CYPRESS_RW_EEPROM_DB) {
      arg_eeprom_chip = 0b1010001;
    } else /* req->bRequest == USB_REQ_RW_EEPROM */ {
      switch(req->wIndex) {
        case 0: arg_eeprom_chip = 0b1010001;
        case 1: arg_eeprom_chip = 0b1010010;
        case 2: arg_eeprom_chip = 0b1010011;
        default: return false;
      }
    }
    arg_eeprom_read = (req->bmRequestType & USB_DIR_IN);
    arg_eeprom_addr = req->wValue;
    arg_eeprom_len  = req->wLength;
    request = REQ_EEPROM;
    return true;
  }

  return false;
}

int main() {
  CPUCS = _CLKOE|_CLKSPD1; // Run at 48 MHz, drive CLKOUT
  usb_init(/*reconnect=*/true);

  while(1) {
    switch(request) {
      case REQ_EEPROM:
        while(arg_eeprom_len > 0) {
          uint8_t len = arg_eeprom_len < 64 ? arg_eeprom_len : 64;

          if(arg_eeprom_read) {
            while(EP0CS & _BUSY);
            if(!eeprom_read(arg_eeprom_chip, arg_eeprom_addr, EP0BUF, len, /*dbyte=*/true))
              STALL_EP0();
            SETUP_EP0_BUF(len);
          } else {
            SETUP_EP0_BUF(0);
            while(EP0CS & _BUSY);
            if(!eeprom_write(arg_eeprom_chip, arg_eeprom_addr, EP0BUF, len, /*dbyte=*/true))
              STALL_EP0();
          }

          arg_eeprom_len  -= len;
          arg_eeprom_addr += len;
        }

        request = REQ_NONE;
        break;
    }
  }
}
