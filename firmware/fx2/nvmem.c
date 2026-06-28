// Ref: CAT24C256 EEPROM Serial 256-Kb I2C CAT24C256
// Accession: G00124
// Ref: BL24C256A 256Kbits (32768×8)
// Accession: G00125
// Ref: CAT24M01 EEPROM Serial 1-Mb I2C
// Accession: G00061
// Ref: Winbond W25Q32JV-DTR 3V 32M-BIT SERIAL FLASH MEMORY WITH DUAL/QUAD SPI & QPI & DTR
// Accession: G00108

// FX2 NVM layout (addresses in hex):
// - 0000..0008: FX2 header
// - 0008..0050: Glasgow header; see [struct glasgow_config]
// - 0050..5000: firmware code/data (~16K)
// - 5000..7000: unused (~8K)
// - 7000..8000: (revC only) tail end of FPGA bitstream

#include <fx2i2c.h>
#include "glasgow.h"

// Simpler and smaller than the one in <fx2eeprom.h>.
bool eeprom_xfer(uint8_t chip, uint16_t addr, __xdata uint8_t *buf, uint16_t len, bool write)
{
  uint8_t addr_bytes[2];
  addr_bytes[0] = addr >> 8;
  addr_bytes[1] = addr & 0xff;

  if (!i2c_start((chip<<1)|0))
    goto stop;
  if (!i2c_write(addr_bytes, 2))
    goto stop;
  if (write) {
    if (!i2c_write(buf, len))
      goto stop;
    if (!i2c_stop())
      return false;
    // At this point, the EEPROM falls off the bus until it finishes the write cycle.
    // This polling loop is empirically sufficient for the part used on revABCD.
    for (uint8_t attempt = 0; attempt < 128; attempt++) {
      if (i2c_start((chip<<1)|0)) {
        i2c_stop();
        return true;
      }
    }
    return false;
  } else {
    if (!i2c_start((chip<<1)|1))
      goto stop;
    if (!i2c_read(buf, len))
      return false;
    return true;
  }

stop:
  i2c_stop();
  return false;
}

enum mgmt_result nvmem_mgmt_write_eeprom()
{
  if (mgmt_req_len < sizeof(mgmt_req.eeprom_write.addr))
    return RES_ERROR;
  uint8_t eeprom_write_len = mgmt_req_len - sizeof(mgmt_req.eeprom_write.addr);
  if (eeprom_write_len > sizeof(mgmt_req.eeprom_write.data))
    return RES_ERROR;

  if (!eeprom_xfer(I2C_ADDR_FX2_MEM, mgmt_req.eeprom_write.addr, mgmt_req.eeprom_write.data,
                   eeprom_write_len, /*write=*/true))
    return RES_ERROR;
  return RES_ACK;
}

enum mgmt_result nvmem_mgmt_read_eeprom()
{
  if (mgmt_req.eeprom_read.len > sizeof(mgmt_req.eeprom_read_data))
    return RES_ERROR;
  mgmt_rsp_len = mgmt_req.eeprom_read.len;

  if (!eeprom_xfer(I2C_ADDR_FX2_MEM, mgmt_req.eeprom_read.addr, mgmt_rsp.eeprom_read_data,
                   mgmt_req.eeprom_read.len, /*write=*/false))
    return RES_ERROR;
  return RES_ACK;
}

bool nvmem_xfer_bitstream_revabc(__xdata uint8_t *buffer, uint32_t addr, uint16_t length, bool write)
{
  // Layout of bitstream in EEPROMs:
  // - 00000..10000: 64K at I2C_ADDR_ICE_MEM_REVABC+0 @ 0000
  // - 10000..20000: 64K at I2C_ADDR_ICE_MEM_REVABC+1 @ 0000
  // - 20000..21000:  4K at I2C_ADDR_FX2_MEM          @ 7000
  // (The layout is awkward because bitstream on revAB could fit into ICE_MEM, but on revC
  // it is slightly too big, and the issue was not noticed during the design phase.)
  uint8_t chip;
  uint16_t offset = addr;
  switch (addr >> 16) {
    case 0: // CAT24M01
      chip = I2C_ADDR_ICE_MEM_REVABC + 0;
      break;
    case 1: // CAT24M01
      chip = I2C_ADDR_ICE_MEM_REVABC + 1;
      break;
    case 2: // BL64C256
      chip = I2C_ADDR_FX2_MEM;
      offset += 0x7000;
      break;
    default:
      return false;
  }

  while (length > 0) {
    // Avoid crossing page boundaries. CAT24M01 has 256-bytepages, BL64C256 has 64-byte pages.
    uint16_t chunk = ((offset | 63) + 1) - offset;
    if (chunk > length || !write)
      chunk = length;
    // Write the chunk and advance.
    if (!eeprom_xfer(chip, offset, buffer, chunk, write))
      return false;
    offset += chunk;
    buffer += chunk;
    length -= chunk;
  }
  return true;
}

bool nvmem_write_bitstream_revd(__xdata uint8_t *buffer, uint32_t addr, uint16_t length)
{
  // TODO: implement revD bitstream write
  (void)buffer;
  (void)addr;
  (void)length;
  return false;
}
