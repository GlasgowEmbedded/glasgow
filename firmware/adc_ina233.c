#include <fx2regs.h>
#include <fx2i2c.h>
#include "glasgow.h"

enum {
  // ADC registers
  INA233_REG_CLEAR_FAULTS        = 0x03,
  INA233_REG_VIN_OV_WARN_LIMIT   = 0x57,
  INA233_REG_VIN_UV_WARN_LIMIT   = 0x58,
  INA233_REG_STATUS_MFR_SPECIFIC = 0x80,
  INA233_REG_READ_VIN            = 0x88,
  INA233_REG_READ_IIN            = 0x89,
  INA233_REG_MFR_ALERT_MASK      = 0xD2,
  INA233_REG_MFR_CALIBRATION     = 0xD4,
  // MFR_ALERT_MASK bits
  INA233_BIT_IN_UV_WARNING       = 1<<0,
  INA233_BIT_IN_OV_WARNING       = 1<<1,
  INA233_BIT_IN_OC_WARNING       = 1<<2,
  INA233_BIT_IN_OP_WARNING       = 1<<3,
  INA233_BIT_COMM_ERR            = 1<<4,
  INA233_BIT_POR_EVENT           = 1<<5,
  INA233_BIT_ADC_OVERFLOW        = 1<<6,
  INA233_BIT_CONV_READY          = 1<<7,
  
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
  __code const struct buffer_desc *buffer;
  for(buffer = buffers; buffer->selector; buffer++) {
    // mask all events from triggering an alert (=would switch off our port power)
    // they will be unmasked selectively when configured
      __pdata uint8_t regval = 0xFF;
    if(!i2c_reg8_write(buffer->address, INA233_REG_MFR_ALERT_MASK, &regval, 1))
      return false;

    // TODO: write cal register
  }
  
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

bool iobuf_get_alert_ina233(uint8_t selector,
                     __xdata uint16_t *low_millivolts,
                     __xdata uint16_t *high_millivolts) {
  __code const struct buffer_desc *buffer;
  for(buffer = buffers; buffer->selector; buffer++) {
    if(selector == buffer->selector) {
      __pdata uint8_t code_bytes[2];
      __pdata uint8_t mask_reg;

      // check which kind of alerts are activated
      if(!i2c_reg8_read(buffer->address, INA233_REG_MFR_ALERT_MASK, &mask_reg, 1))
        return false;

      if (mask_reg & INA233_BIT_IN_UV_WARNING) {
        // undervoltage inactive
        *low_millivolts = 0;
      } else {
        if(!i2c_reg8_read(buffer->address, INA233_REG_VIN_UV_WARN_LIMIT, code_bytes, 2))
            return false;
        *low_millivolts = code_bytes_to_millivolts_ina233(code_bytes);
      }

      if (mask_reg & INA233_BIT_IN_OV_WARNING) {
        // overvoltage inactive
        // TODO: MAX_VOLTAGE is a bad choice for the INA233, as it can measure up to 40V
        // this suggests a small API change
        *high_millivolts = MAX_VOLTAGE;
      } else {
        if(!i2c_reg8_read(buffer->address, INA233_REG_VIN_OV_WARN_LIMIT, code_bytes, 2))
            return false;
        *high_millivolts = code_bytes_to_millivolts_ina233(code_bytes);
      }

      return true;
    }
  }

  return false;
}
