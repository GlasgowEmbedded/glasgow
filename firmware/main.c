#include <fx2lib.h>
#include <fx2regs.h>
#include <fx2ints.h>
#include <fx2usb.h>
#include <fx2delay.h>
#include <fx2i2c.h>
#include <fx2eeprom.h>
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
  .bcdDevice            = 0x0001,
  .iManufacturer        = 1,
  .iProduct             = 2,
  .iSerialNumber        = 0,
  .bNumConfigurations   = 1,
};

usb_desc_configuration_c usb_configs[] = {
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

usb_desc_interface_c usb_interfaces[] = {
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

usb_ascii_string_c usb_strings[] = {
  "whitequark research",
  "Glasgow Debug Tool",
};

usb_descriptor_set_c usb_descriptor_set = {
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
  USB_REQ_EEPROM     = 0x10,
  USB_REQ_FPGA_CFG   = 0x11,
  USB_REQ_STATUS     = 0x12,
  USB_REQ_REGISTER   = 0x13,
  USB_REQ_IO_VOLT    = 0x14,
  USB_REQ_SENSE_VOLT = 0x15,
  USB_REQ_ALERT_VOLT = 0x16,
  USB_REQ_POLL_ALERT = 0x17,
  // Cypress requests
  USB_REQ_CYPRESS_EEPROM_DB = 0xA9,
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

    if(arg_len > 0) {
      if(arg_idx == 0) {
        reset_status_bit(ST_FPGA_RDY);
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
        latch_status_bit(ST_FPGA_RDY);
      } else {
        latch_status_bit(ST_ERROR);
      }

      ACK_EP0();
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
      if(!iobuf_get_voltage(arg_mask, (uint16_t *)EP0BUF)) {
        STALL_EP0();
      } else {
        SETUP_EP0_BUF(2);
      }
    } else {
      SETUP_EP0_BUF(2);
      while(EP0CS & _BUSY);
      if(!iobuf_set_voltage(arg_mask, (uint16_t *)EP0BUF)) {
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
    if(!iobuf_measure_voltage(arg_mask, (uint16_t *)EP0BUF)) {
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
      if(!iobuf_get_alert(arg_mask, (uint16_t *)EP0BUF, (uint16_t *)EP0BUF + 1)) {
        STALL_EP0();
      } else {
        SETUP_EP0_BUF(4);
      }
    } else {
      SETUP_EP0_BUF(4);
      while(EP0CS & _BUSY);
      if(!iobuf_set_alert(arg_mask, (uint16_t *)EP0BUF, (uint16_t *)EP0BUF + 1)) {
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
  // Run at 48 MHz, drive CLKOUT.
  CPUCS = _CLKOE|_CLKSPD1;

  // Initialize subsystems.
  leds_init();
  led_fpga_set(fpga_is_ready());
  iobuf_init_dac_ldo();
  iobuf_init_adc();

  // Use timer 2 in 16-bit timer mode for ACT LED.
  T2CON = _CPRL2;
  ET2 = true;

  // Set up endpoint interrupts for ACT LED.
  EPIE |= _EP0IN|_EP0OUT;

  // Set up interrupt for ADC ALERT.
  EX0 = true;

  // Configure FIFOs
  SYNCDELAY();
  REVCTL = _ENH_PKT|_DYN_OUT;
  SYNCDELAY();
  EP2FIFOCFG = _ZEROLENIN;
  SYNCDELAY();
  EP4FIFOCFG = _ZEROLENIN;
  SYNCDELAY();
  EP6FIFOCFG = _ZEROLENIN;
  SYNCDELAY();
  EP8FIFOCFG = _ZEROLENIN;

  // Drive 30 MHz IFCLK
  SYNCDELAY();
  IFCONFIG = _IFCLKSRC|_IFCLKOE;

  // Finally, enumerate.
  usb_init(/*reconnect=*/true);

  while(1) {
    if(pending_setup)
      handle_pending_usb_setup();
    if(pending_alert)
      handle_pending_alert();
  }
}
