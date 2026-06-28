#pragma once

enum fpga_reg {
  // Registers present in every bitstream.
  FPGA_REG_HEALTH   = 0x00, // should read as A5
  FPGA_REG_PIPE_RST = 0x01,
  FPGA_REG_ALERTS   = 0x02,

  FPGA_REG_PRIVATE_LAST = FPGA_REG_ALERTS
};

void fpga_init();
bool fpga_load_nvmem();
bool fpga_configure(enum interface iface, enum ep_mode mode);
bool fpga_reset_pipes();
void fpga_poll_cfg();
void fpga_poll_alert();

bool nvmem_xfer_bitstream_revabc(__xdata uint8_t *buffer, uint32_t addr, uint16_t length, bool write);
bool nvmem_write_bitstream_revd(__xdata uint8_t *buffer, uint32_t addr, uint16_t length);
