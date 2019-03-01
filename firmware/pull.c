#include <fx2regs.h>
#include <fx2i2c.h>
#include "glasgow.h"

enum {
  TCA9534_CMD_INPUT_PORT          = 0x00,
  TCA9534_CMD_OUTPUT_PORT         = 0x01,
  TCA9534_CMD_POLARITY_INVERSION  = 0x02,
  TCA9534_CMD_CONFIGURATION       = 0x03,
};

static bool pull_start(uint8_t selector, bool read) {
  uint8_t addr = 0;
  switch(selector) {
    case IO_BUF_A: addr = I2C_ADDR_IOA_PULL; break;
    case IO_BUF_B: addr = I2C_ADDR_IOB_PULL; break;
  }
  if(!addr)
    return false;

  if(!i2c_start((addr<<1)|read))
    return false;

  return true;
}

static bool pull_write(uint8_t selector, uint8_t command, uint8_t value) {
  if(!pull_start(selector, /*read=*/false))
    goto fail;
  if(!i2c_write(&command, 1))
    goto fail;
  if(!i2c_write(&value, 1))
    goto fail;
  if(!i2c_stop())
    return false;
  return true;

fail:
  i2c_stop();
  return false;
}

static bool pull_read(uint8_t selector, uint8_t command, __xdata uint8_t *value) {
  if(!pull_start(selector, /*read=*/false))
    goto fail;
  if(!i2c_write(&command, 1))
    goto fail;
  if(!pull_start(selector, /*read=*/true))
    goto fail;
  if(!i2c_read(value, 1))
    goto fail;
  return true;

fail:
  i2c_stop();
  return false;
}

bool iobuf_set_pull(uint8_t selector, uint8_t enable, uint8_t level) {
  if(!pull_write(selector, TCA9534_CMD_OUTPUT_PORT, level))
    return false;
  enable = ~enable;
  if(!pull_write(selector, TCA9534_CMD_CONFIGURATION, enable))
    return false;
  return true;
}

bool iobuf_get_pull(uint8_t selector, __xdata uint8_t *enable, __xdata uint8_t *level) {
  if(!pull_read(selector, TCA9534_CMD_OUTPUT_PORT, level))
    return false;
  if(!pull_read(selector, TCA9534_CMD_CONFIGURATION, enable))
    return false;
  *enable = ~*enable;
  return true;
}
