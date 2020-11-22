#include <fx2regs.h>
#include <fx2i2c.h>
#include "glasgow.h"

enum {
  // ADC registers
  INA233_REG_READ_VIN        = 0x88,
  INA233_REG_READ_IIN        = 0x89,
  INA233_REG_MFR_CALIBRATION = 0xD4,
};

struct buffer_desc {
  uint8_t selector;
  uint8_t address;
};

static const struct buffer_desc buffers[] = {
  { IO_BUF_A, I2C_ADDR_IOA_ADC_INA233 },
  { IO_BUF_B, I2C_ADDR_IOB_ADC_INA233 },
  { 0, 0 }
};

bool iobuf_init_adc_ina233() {
    // TODO: write cal register
    
    return true;
}

static uint16_t code_bytes_to_millivolts_ina233(__pdata const uint8_t *code_bytes) {
  // 0x0000 = 0 mV, 0x7fff (max code value) = 40960 mV, 16 bit LSB = 1.25 mV
  // the INA233 sends LSB first, this is described contradictory in the datasheet
  // uint32_t is necessary as the value could overflow during multiplication with just 16 bits
  uint32_t code_dword = (((uint32_t)code_bytes[1]) << 8) | code_bytes[0];
  uint16_t millivolts = (code_dword * 5) / 4;
  return millivolts;
}

bool iobuf_measure_voltage_ina233(uint8_t selector, __xdata uint16_t *millivolts) {
  __code const struct buffer_desc *buffer;
  for(buffer = buffers; buffer->selector; buffer++) {
    if(selector == buffer->selector) {
      __pdata uint8_t code_bytes[2];
      if(!i2c_reg8_read(buffer->address, INA233_REG_READ_VIN, code_bytes, 2))
        return false;

      *millivolts = code_bytes_to_millivolts_ina233(code_bytes);
      return true;
    }
  }

  return false;
}

