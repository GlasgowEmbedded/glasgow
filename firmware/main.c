#include <fx2lib.h>
#include <fx2usb.h>
#include <fx2delay.h>
#include <fx2i2c.h>
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
  .idVendor             = VID_QIHW,
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
  "Glasgow Debug Tool",
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
  USB_REQ_EEPROM   = 0x10,
  USB_REQ_FPGA_CFG = 0x11,
  USB_REQ_STATUS   = 0x12,
  USB_REQ_REGISTER = 0x13,
  // Cypress requests
  USB_REQ_CYPRESS_EEPROM_DB = 0xA9,
};

enum {
  // Status bits
  ST_FPGA_RDY = 1<<0,
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
     (req->bRequest == USB_REQ_CYPRESS_EEPROM_DB ||
      req->bRequest == USB_REQ_EEPROM)) {
    bool     arg_read = (req->bmRequestType & USB_DIR_IN);
    uint8_t  arg_chip = 0;
    uint16_t arg_addr = req->wValue;
    uint16_t arg_len  = req->wLength;
    bool     double_byte;
    uint8_t  timeout  = 166;
    if(req->bRequest == USB_REQ_CYPRESS_EEPROM_DB) {
      double_byte = true;
      arg_chip = I2C_ADDR_CYP_MEM;
    } else /* req->bRequest == USB_REQ_EEPROM */ {
      double_byte = true;
      switch(req->wIndex) {
        case 0: arg_chip = I2C_ADDR_CYP_MEM;    break;
        case 1: arg_chip = I2C_ADDR_FPGA_MEM;   break;
        case 2: arg_chip = I2C_ADDR_FPGA_MEM+1; break;
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
        if(!eeprom_read(arg_chip, arg_addr, EP0BUF, chunk_len, double_byte)) {
          STALL_EP0();
          break;
        }
        SETUP_EP0_BUF(chunk_len);
      } else {
        SETUP_EP0_BUF(0);
        while(EP0CS & _BUSY);
        if(!eeprom_write(arg_chip, arg_addr, EP0BUF, chunk_len, double_byte, timeout)) {
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
    uint8_t status = 0;
    pending_setup = false;

    if(fpga_is_ready())
      status |= ST_FPGA_RDY;

    EP0BUF[0] = status;
    SETUP_EP0_BUF(1);
    return;
  }

  // Bitstream download request
  if(req->bmRequestType == USB_RECIP_DEVICE|USB_TYPE_VENDOR|USB_DIR_OUT &&
     req->bRequest == USB_REQ_FPGA_CFG &&
     (req->wIndex == 0 || req->wIndex == bitstream_idx + 1)) {
    uint16_t arg_idx = req->wIndex;
    uint16_t arg_len = req->wLength;
    pending_setup = false;

    if(arg_len > 0) {
      if(arg_idx == 0) {
        led_fpga_set(false);
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
    } else {
      fpga_start();
      if(fpga_is_ready()) {
        led_fpga_set(true);
        led_err_set(false);
      } else {
        led_err_set(true);
      }

      // We can't stall here (this would just result in a timeout),
      // so the host will explicitly read device status.
      ACK_EP0();
    }

    return;
  }

  STALL_EP0();
}

void isr_TF2() __interrupt(_INT_TF2) {
  led_act_set(false);
  TR2 = false;
  TF2 = false;
}

static void pulse_led_act() {
  led_act_set(true);
  // Just let it run, at the maximum reload value we get a pulse width of around 16ms
  TR2 = true;
}

void isr_EP0IN() __interrupt {
  pulse_led_act();
  CLEAR_USB_IRQ();
  EPIRQ = _EP0IN;
}

void isr_EP0OUT() __interrupt {
  pulse_led_act();
  CLEAR_USB_IRQ();
  EPIRQ = _EP0OUT;
}

int main() {
  // Run at 48 MHz, drive CLKOUT
  CPUCS = _CLKOE|_CLKSPD1;

  // Initialize subsystems
  usb_init(/*reconnect=*/true);
  leds_init();

  // Use timer 2 in 16-bit timer mode for ACT LED
  T2CON = _CPRL2;
  ET2 = true;

  // Set up endpoint interrupts for ACT LED
  EPIE |= _EP0IN|_EP0OUT;

  // Configure FIFOs
  EP2FIFOCFG = _ZEROLENIN;
  SYNCDELAY();
  EP4FIFOCFG = _ZEROLENIN;
  SYNCDELAY();
  EP6FIFOCFG = _ZEROLENIN;
  SYNCDELAY();
  EP8FIFOCFG = _ZEROLENIN;
  SYNCDELAY();

  // Drive 30 MHz IFCLK
  IFCONFIG = _IFCLKSRC|_IFCLKOE;

  while(1) {
    if(pending_setup)
      handle_pending_usb_setup();
  }
}
