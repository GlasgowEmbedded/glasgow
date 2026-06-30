#include <stddef.h>
#include <fx2regs.h>
#include <fx2delay.h>
#include <fx2lib.h>
#include <fx2i2c.h>
#include <fx2spi.h>
#include "glasgow.h"

static __bit nvmem_fail;

// ===== Platform-specific code ===================================================================

static uint32_t load_bytes;

static void fpga_reset(bool assert) __reentrant
{
  if (glasgow_config.revision < GLASGOW_REV_C0) {
    IO_FPGA_nRESET_REVAB = !assert;
  } else {
    IO_FPGA_nRESET_REVCD = !assert;
  }
}

static void load_reset_revabc() __reentrant
{
  // Disable voltage output.
  // This is necessary because iCE40 FPGAs have pull-ups enabled by default (when unconfigured
  // and on unused pins), and on revC, a high logic level on the OE pin configures the respective
  // level shifter as an output. On revAB, the FXMA level shifter could start oscillating.
  IO_EN_VA = 0;
  IO_EN_VB = 0;

  // We don't have feedback from the Vio output to know when it has actually discharged.
  // The revC device itself has 6 µF of capacitance and a load of 1 kΩ(min), for a t_RC = 6 ms.
  // A reasonable starting point is 3×t_RC = 18 ms. However, external circuitry powered by
  // the device can and likely will add some bulk capacitance. 250 ms of delay would be safe
  // in the worst case of 5 V, 40 uF, no added load. It is also not long enough to become
  // an annoyance.
  delay_ms(250);

  // Reset the FPGA now that it's safe to do so.
  fpga_reset(true);
  delay_us(1);
  fpga_reset(false);

  // Assert nCS. This puts the FPGA into SPI device mode once it initializes.
  IO_nCS_REVABC = 0;
  IO_SCK_REVABC = 1;

  // Wait for FPGA to initialize. This is specified as 800 us for the UP5K FPGA on revAB, and
  // 1200 us for the HX8K FPGA on revC.
  delay_us(1200);
}

static void load_reset_revd() __reentrant
{
  // Reset the FPGA.
  fpga_reset(true);
  // tPRGM = 110ns(min)

  // Connect EP2OUT to parallel bus via GPIF.
  SYNCDELAY;
  IFCONFIG = _3048MHZ|_IFCLKSRC|_IFCLKOE|_IFCFG1; // 48 MHz, IFCLK output, GPIF mode

  // Take the FPGA out of reset.
  fpga_reset(false);
  // tINITL = 55ns(max)

  // For reasons that aren't entirely clear, unless the ECP5's SPCM interface is clocked
  // at least once after reset here, it will never configure until it is power-cycled, even
  // after toggling PROGRAMN later.
  GPIFIDLECTL = 0b00;
  GPIFIDLECTL = 0b10;
}

static void load_start_revabc() __reentrant
{
  // On iCE40, after the bitstream is uploaded, it is required to toggle SCK at least 49
  // more times for the configuration to activate. (This advances the configuration state
  // machine of the FPGA until it enables I/O.)
  for (uint8_t cycles = 0; cycles < 49; cycles++) {
    IO_SCK_REVABC = 0;
    IO_SCK_REVABC = 1;
  }
}

// Both revABC and revD have FPGA configuration data uploaded via EP2OUT.
static void load_begin(bool nvmem) __reentrant
{
  load_bytes = 0;
  nvmem_fail = false;

  // NAK all transfers.
  SYNCDELAY;
  FIFORESET = _NAKALL;

  // Abort any pending GPIF transfer.
  SYNCDELAY;
  GPIFABORT = 0xFF;

  // Disable parallel bus, keep IFCLK running to access FX2 FIFO registers.
  SYNCDELAY;
  IFCONFIG = _3048MHZ|_IFCLKSRC;

  // Configure EP2 as double buffered bulk OUT.
  SYNCDELAY;
  EP2CFG = _VALID|_TYPE1|_BUF1;

  // Prime EP2 FIFO.
  SYNCDELAY;
  EP2FIFOCFG = 0;
  SYNCDELAY;
  FIFORESET = 2;
  SYNCDELAY;
  OUTPKTEND = _SKIP|2;
  SYNCDELAY;
  OUTPKTEND = _SKIP|2;

  // FIFO configuration done.
  SYNCDELAY;
  FIFORESET = 0;

  if (nvmem) {
    // Just put the FPGA in reset. On revD, the bus is shared between the FPGA and SPI flash.
    // On revC and earlier, this isn't really necessary but it's a lot simpler to keep the process
    // outwardly identical between revisions.
    fpga_reset(true);
    return;
  }

  if (glasgow_config.revision < GLASGOW_REV_D0) {
    load_reset_revabc();
  } else {
    load_reset_revd();
  }
}

DEFINE_SPI_WR_FN(load_sram_revabc, IO_SCK_REVABC, IO_COPI_REVABC)

static void load_poll_revabc(bool nvmem)
{
  if (!(EP2468STAT & _EP2E)) {
    uint16_t length = (EP2BCH << 8) | EP2BCL;

    if (!nvmem) {
      // Write configuration data to FPGA.
      load_sram_revabc(EP2FIFOBUF, length);
    } else {
      if (!nvmem_xfer_bitstream_revabc(EP2FIFOBUF, load_bytes, length, /*write=*/true))
        nvmem_fail = true;
    }

    // Dequeue the FIFO packet.
    SYNCDELAY;
    OUTPKTEND = _SKIP|2;

    // Done with this packet!
    load_bytes += length;
  }
}

static void load_poll_revd(bool nvmem)
{
  if (!(EP2468STAT & _EP2E)) {
    uint16_t length = (EP2BCH << 8) | EP2BCL;

    if (!nvmem) {
      // Start the GPIF transfer.
      SYNCDELAY;
      GPIFTCB1 = length >> 8;
      SYNCDELAY;
      GPIFTCB0 = length;
      SYNCDELAY;
      GPIFTRIG = 0;

      // Commit the FIFO packet to GPIF.
      SYNCDELAY;
      OUTPKTEND = 2;

      // Wait until GPIF transfer ends.
      while (!(GPIFTRIG & _GPIFIDLE));
    } else {
      if (!nvmem_write_bitstream_revd(EP2FIFOBUF, load_bytes, length))
        nvmem_fail = true;

      // Dequeue the FIFO packet.
      SYNCDELAY;
      OUTPKTEND = _SKIP|2;
    }

    // Done with this packet!
    load_bytes += length;
  }
}

static void load_end()
{
  // Take the FPGA out of reset. (Does nothing after SRAM configuration. See `load_begin()` for
  // an explanation of why this is necessary.)
  fpga_reset(false);

  // Abort any pending GPIF transfer. (Does nothing on revABC.)
  SYNCDELAY;
  GPIFABORT = 0xFF;

  // Configure parallel bus for FIFO. revAB FPGA is slower than revCD FPGAs.
  SYNCDELAY;
  if (glasgow_config.revision < GLASGOW_REV_C0) {
    IFCONFIG =          _IFCLKSRC|_IFCLKOE|_IFCFG0|_IFCFG1; // 30 MHz, IFCLK output, FIFO mode
  } else {
    IFCONFIG = _3048MHZ|_IFCLKSRC|_IFCLKOE|_IFCFG0|_IFCFG1; // 48 MHz, IFCLK output, FIFO mode
  }
}

// ===== Generic code =============================================================================

// intf[0]: EP1IN/OUT: off/mgmt
// intf[1]: EP2OUT:    off/2x/4x/cfg/nvm
// intf[2]: EP4OUT:    off/2x
// intf[3]: EP6IN:     off/2x/4x
// intf[4]: EP8IN:     off/2x
extern __idata uint8_t usb_alt_setting[5];

static __bit fpga_ready = false;
static __xdata uint8_t fpga_pipe_rst = 0xf;

void fpga_init()
{
  // Disable parallel bus, keep IFCLK running to access FX2 FIFO registers.
  SYNCDELAY;
  IFCONFIG = _3048MHZ|_IFCLKSRC;

  // Suspend all FIFOs.
  SYNCDELAY;
  FIFORESET = _NAKALL;

  // Disable all main endpoints.
  SYNCDELAY;
  EP2CFG = 0;
  SYNCDELAY;
  EP4CFG = 0;
  SYNCDELAY;
  EP6CFG = 0;
  SYNCDELAY;
  EP8CFG = 0;

  // Use 8-bit parallel bus. If any of EPnFIFOCFG have _WORDWIDE set, PORTD is used as the high
  // half of the parallel bus, so clear it.
  SYNCDELAY;
  EP2FIFOCFG = 0;
  SYNCDELAY;
  EP4FIFOCFG = 0;
  SYNCDELAY;
  EP6FIFOCFG = 0;
  SYNCDELAY;
  EP8FIFOCFG = 0;

  // Configure strobes and flags.
  SYNCDELAY;
  FIFOPINPOLAR = 0;
  SYNCDELAY;
  PINFLAGSAB = 0b10011000; // FLAGA = EP2 ~EF, FLAGB = EP4 ~EF
  SYNCDELAY;
  PINFLAGSCD = 0b11111110; // FLAGC = EP6 ~FF, FLAGD = EP8 ~FF
  SYNCDELAY;
  PORTACFG = _FLAGD; // PA7 is FLAGD

  // Configure GPIF waveforms for ECP5 configuration.
  SYNCDELAY;
  EP2GPIFFLGSEL = _FS0; // FLG=EF
  // STATE 0: Write word / Low half-period
  WAVEDATA[0x20+0x00+0] = 0x01;          // LENGTH = 1
  WAVEDATA[0x20+0x08+0] = 0b00'000010;   // OPCODE = DATA
  WAVEDATA[0x20+0x10+0] = 0b00000'000;   // OUTPUT = CLK(CTL1)=L
  // STATE 1: Dequeue word / High half-period
  WAVEDATA[0x20+0x00+1] = 0b0'0'111'111; // BRANCH = IDLE
  WAVEDATA[0x20+0x08+1] = 0b00'000111;   // OPCODE = NEXT|DATA|DP
  WAVEDATA[0x20+0x10+1] = 0b00000'010;   // OUTPUT = CLK(CTL1)=H

  // Unsuspend EP1IN/OUT FIFOs.
  SYNCDELAY;
  FIFORESET = 0;
}

// This function implements "interlocks" that use alt-settings to achieve what configurations
// would normally be used for. On Windows, it is impossible to use non-first device configuration,
// which would otherwise result in ~halving of achievable bulk bandwidth.
static bool fpga_check_mode(enum interface iface, enum ep_mode alt_setting)
{
  if (alt_setting == EP_MODE_OFF) {
    // The kernel will set alt-setting to 0 whenever the iface is released.
    // We could return in principle an error here, but it wouldn't be useful most of the time.
    return true;
  } else if (alt_setting == EP_MODE_CFG || alt_setting == EP_MODE_NVM) {
    if (iface == IFACE_EP2OUT) {
      // This also ensures that all pipes are held in reset whenever the FPGA is reconfigured.
      // OSes will assume that a single endpoint can only belong to one interface, therefore EP2
      // has to be shared between bitstream loading and data transfer.
      return usb_alt_setting[IFACE_EP4OUT] == EP_MODE_OFF &&
             usb_alt_setting[IFACE_EP6IN]  == EP_MODE_OFF &&
             usb_alt_setting[IFACE_EP8IN]  == EP_MODE_OFF;
    }
  } else if (fpga_ready) {
    if (alt_setting == EP_MODE_4X) {
      if (iface == IFACE_EP2OUT) {
        return usb_alt_setting[IFACE_EP4OUT] == EP_MODE_OFF;
      } else if (iface == IFACE_EP6IN) {
        return usb_alt_setting[IFACE_EP8IN]  == EP_MODE_OFF;
      }
    } else if (alt_setting == EP_MODE_2X) {
      if (iface == IFACE_EP4OUT) {
        return usb_alt_setting[IFACE_EP2OUT] != EP_MODE_4X;
      } else if (iface == IFACE_EP8IN) {
        return usb_alt_setting[IFACE_EP6IN]  != EP_MODE_4X;
      } else if (iface == IFACE_EP2OUT || iface == IFACE_EP6IN) {
        return true;
      }
    }
  }
  return false;
}

static smbus_sequence set_fpga_pipe_rst_seq[] = {
  SM_WRITE_BYTE(FPGA_REG_PIPE_RST, fpga_pipe_rst),
  SM_DONE(),
};

static __xdata __at(0xe612) volatile uint8_t EPnCFG[4];
static __xdata __at(0xe618) volatile uint8_t EPnFIFOCFG[4];

bool fpga_configure(enum interface iface, enum ep_mode mode)
{
  if (!fpga_check_mode(iface, mode))
    return false;

  // Begin or end FPGA bitstream loading.
  if (iface == IFACE_EP2OUT) {
    uint8_t prev_mode = usb_alt_setting[IFACE_EP2OUT];
    if (mode == EP_MODE_CFG || mode == EP_MODE_NVM) {
      fpga_ready = false;
      fpga_pipe_rst = 0xf;
      load_begin(/*nvmem=*/mode == EP_MODE_NVM);
      return true;
    } else if (prev_mode == EP_MODE_CFG || prev_mode == EP_MODE_NVM) {
      load_end();
      return true;
    } /* else fallthrough */
  }

  // Compute pipe and endpoint indices.
  uint8_t pipe_index = iface - 1; // intf[1] -> EPnCFG[0], intf[3] -> EPnCFG[1], ...
  uint8_t ep_index = iface << 1;  // intf[1] -> 2, intf[2] -> 4, ...

  // Reset FPGA pipe.
  if (fpga_ready) {
    fpga_pipe_rst |= nibble_mask[pipe_index];
    if (!smbus_run(set_fpga_pipe_rst_seq, I2C_ADDR_FPGA))
      return false;
  }

  // Compute endpoint configuration.
  uint8_t ep_type = _TYPE1;
  if (mode == EP_MODE_4X) {
    ep_type |= _VALID;
  } else if (mode == EP_MODE_2X) {
    ep_type |= _VALID|_BUF1;
  }
  if (pipe_index & 0b10) { // EP6IN, EP8IN
    ep_type |= _DIR;
  }

  // Suspend all FIFOs.
  SYNCDELAY;
  FIFORESET = _NAKALL;

  // Configure endpoint type.
  SYNCDELAY;
  EPnCFG[pipe_index] = ep_type;

  if (ep_type & _VALID) {
    // Clear endpoint FIFO configuration, otherwise FIFORESET and OUTPKTEND do nothing.
    SYNCDELAY;
    EPnFIFOCFG[pipe_index] = 0;

    // Clear endpoint FIFO.
    SYNCDELAY;
    FIFORESET = ep_index;

    if (!(ep_type & _DIR)) {
      // Prime OUT endpoint FIFO.
      SYNCDELAY;
      OUTPKTEND = _SKIP|ep_index;
      SYNCDELAY;
      OUTPKTEND = _SKIP|ep_index;
      if (!(ep_type & _BUF1)) {
        SYNCDELAY;
        OUTPKTEND = _SKIP|ep_index;
        SYNCDELAY;
        OUTPKTEND = _SKIP|ep_index;
      }
      // Enable OUT endpoint.
      SYNCDELAY;
      EPnFIFOCFG[pipe_index] = _AUTOOUT;
    } else {
      // Enable IN endpoint.
      SYNCDELAY;
      EPnFIFOCFG[pipe_index] = _ZEROLENIN;
    }

    // Start FPGA pipe.
    fpga_pipe_rst &= ~nibble_mask[pipe_index];
    if (!smbus_run(set_fpga_pipe_rst_seq, I2C_ADDR_FPGA))
      return false;
  }

  // Unsuspend (valid) FIFOs.
  SYNCDELAY;
  FIFORESET = 0;

  return true;
}

bool fpga_reset_pipes()
{
  fpga_pipe_rst = 0xf;
  if (fpga_ready) {
    return smbus_run(set_fpga_pipe_rst_seq, I2C_ADDR_FPGA);
  } else {
    return true;
  }
}

void fpga_poll_cfg()
{
  bool nvmem = (usb_alt_setting[IFACE_EP2OUT] == EP_MODE_NVM);
  if (glasgow_config.revision < GLASGOW_REV_D0) {
    load_poll_revabc(nvmem);
  } else {
    load_poll_revd(nvmem);
  }
}

enum mgmt_result fpga_mgmt_load_cfg()
{
  if (usb_alt_setting[IFACE_EP2OUT] != EP_MODE_CFG)
    return RES_ERROR; // not in configuration mode
  if (fpga_ready)
    return RES_ERROR; // already launched

  mgmt_rsp.load_progress = load_bytes;
  if (load_bytes < mgmt_req.bitstream.size) {
    // Not all configuration data consumed yet.
    return RES_WAIT;
  } else if (IO_FPGA_DONE) {
    if (glasgow_config.revision < GLASGOW_REV_D0)
      load_start_revabc();
    // Bitstream is now active! Enable FIFO alt-settings.
    xmemcpy(&glasgow_config.bitstream_size, &mgmt_req.bitstream, sizeof(mgmt_req.bitstream));
    fpga_ready = true;
    return RES_ACK;
  } else {
    return RES_ERROR;
  }
}

enum mgmt_result fpga_mgmt_load_nvm()
{
  if (mgmt_req.bitstream.size == 0) {
    // We're removing the bitstream. (This doesn't need to touch the FPGA, unlike the rest.)
    xmemclr(&glasgow_config.bitstream_size, sizeof(mgmt_req.bitstream));
  } else {
    mgmt_rsp.load_progress = load_bytes;
    if (usb_alt_setting[IFACE_EP2OUT] != EP_MODE_NVM) {
      // Need to be in NVM configuration mode to write a bitstream.
      return RES_ERROR;
    } else if (nvmem_fail) {
      // A write operation has failed.
      return RES_ERROR;
    } else if (load_bytes < mgmt_req.bitstream.size) {
      // Not all configuration data consumed yet.
      return RES_WAIT;
    } else {
      // Bitstream has been flashed!
      xmemcpy(&glasgow_config.bitstream_size, &mgmt_req.bitstream, sizeof(mgmt_req.bitstream));
    }
  }
  // Now persist the new configuration.
  if (!config_save(offsetof(struct glasgow_config, bitstream_size), sizeof(mgmt_req.bitstream)))
    return RES_ERROR;
  return RES_ACK;
}

enum mgmt_result fpga_mgmt_status()
{
  if (fpga_ready) {
    xmemcpy(&mgmt_rsp.bitstream, &glasgow_config.bitstream_size, sizeof(mgmt_req.bitstream));
  }
  return RES_ACK;
}

bool fpga_load_nvmem()
{
  if (glasgow_config.revision < GLASGOW_REV_D0) {
    load_reset_revabc();
    while (load_bytes < glasgow_config.bitstream_size) {
      IO_LED_ACT = !!(load_bytes & 0x800);
      nvmem_xfer_bitstream_revabc(scratch, load_bytes, 512, /*write=*/false);
      load_sram_revabc(scratch, 512);
      load_bytes += 512;
    }
    load_start_revabc();
  } else {
    // TODO: implement revD NVM load
  }
  load_end();
  fpga_ready = IO_FPGA_DONE;
  return fpga_ready;
}

// ===== FPGA I2C registers =======================================================================

static bool fpga_reg_select(uint8_t addr)
{
  if (!i2c_start((I2C_ADDR_FPGA<<1)|0))
    goto fail;
  if (!i2c_write(&addr, 1))
    goto fail;
  return true;

fail:
  i2c_stop();
  return false;
}

enum mgmt_result fpga_mgmt_set_reg()
{
  if (mgmt_req_len < sizeof(mgmt_req.fpga_set.addr))
    return RES_ERROR;
  if (mgmt_req_len > sizeof(mgmt_req.fpga_set.addr) + sizeof(mgmt_req.fpga_set.data))
    return RES_ERROR;
  if (mgmt_req.fpga_set.addr <= FPGA_REG_PRIVATE_LAST)
    return RES_ERROR;

  if (!fpga_reg_select(mgmt_req.fpga_set.addr))
    return RES_ERROR;
  if (!i2c_write(mgmt_req.fpga_set.data, mgmt_req_len - sizeof(mgmt_req.fpga_set.addr)))
    goto fail;
  if (!i2c_stop())
    return RES_ERROR;
  return RES_ACK;

fail:
  i2c_stop();
  return RES_ERROR;
}

enum mgmt_result fpga_mgmt_get_reg()
{
  if (mgmt_req.fpga_get.len > sizeof(mgmt_req.fpga_reg_data))
    return RES_ERROR;
  mgmt_rsp_len = mgmt_req.fpga_get.len;

  if (!fpga_reg_select(mgmt_req.fpga_get.addr))
    return RES_ERROR;
  if (!i2c_start((I2C_ADDR_FPGA<<1)|1))
    goto fail;
  if (!i2c_read(mgmt_rsp.fpga_reg_data, mgmt_req.fpga_get.len))
    goto fail;
  return RES_ACK;

fail:
  i2c_stop();
  return RES_ERROR;
}

// ===== FPGA alerts =============================================================================

static __xdata uint8_t fpga_new_alerts;

static smbus_sequence fpga_poll_alert_seq[] = {
  SM_READ_BYTE(FPGA_REG_ALERTS, fpga_new_alerts),
  SM_DONE(),
};

void fpga_poll_alert()
{
  if (!fpga_ready)
    return;
  if (!smbus_run(fpga_poll_alert_seq, I2C_ADDR_FPGA))
    return;
  if (fpga_new_alerts & ~alert.fpga) {
    alert.fpga |= fpga_new_alerts;
    alert_pending = true;
    // Do not light ERR LED; FPGA alerts are more likely to be used as interrupts rather than
    // to highlight faults per se.
  }
}
