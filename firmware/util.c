#include <fx2regs.h>
#include <fx2i2c.h>
#include "glasgow.h"

bool i2c_reg8_read(uint8_t addr, uint8_t reg,
                         __pdata uint8_t *value, uint8_t length) {
  if(!i2c_start(addr<<1))
    goto fail;
  if(!i2c_write(&reg, 1))
    goto fail;
  if(!i2c_start((addr<<1)|1))
    goto fail;
  if(!i2c_read(value, length))
    goto fail;
  return true;

fail:
  i2c_stop();
  return false;
}

bool i2c_reg8_write(uint8_t addr, uint8_t reg,
                          __pdata const uint8_t *value, uint8_t length) {
  if(!i2c_start(addr<<1))
    goto fail;
  if(!i2c_write(&reg, 1))
    goto fail;
  if(!i2c_write(value, length))
    goto fail;
  if(!i2c_stop())
    return false;
  return true;

fail:
  i2c_stop();
  return false;
}
