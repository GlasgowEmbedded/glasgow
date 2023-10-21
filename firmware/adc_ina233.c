#include <fx2regs.h>
#include <fx2i2c.h>
#include "glasgow.h"

enum {
  // ADC registers
  INA233_REG_CLEAR_FAULTS        = 0x03,
  INA233_REG_RESTORE_DEFAULT_ALL = 0x12,
  INA233_REG_VIN_OV_WARN_LIMIT   = 0x57,
  INA233_REG_VIN_UV_WARN_LIMIT   = 0x58,
  INA233_REG_STATUS_MFR_SPECIFIC = 0x80,
  INA233_REG_READ_VIN            = 0x88,
  INA233_REG_READ_IIN            = 0x89,
  INA233_REG_MFR_ALERT_MASK      = 0xD2,
  INA233_REG_MFR_CALIBRATION     = 0xD4,
  INA233_REG_MFR_DEVICE_CONFIG   = 0xD5,
  // MFR_ALERT_MASK and STATUS_MFR_SPECIFIC bits
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
  __xdata uint8_t* status_cache_ptr;
  uint8_t address;
};

// see iobuf_clear_alert_ina233() for details about status_cache
static __xdata uint8_t ina233_status_cache[2];

static const struct buffer_desc buffers[] = {
  { IO_BUF_A, &ina233_status_cache[0], I2C_ADDR_IOA_ADC_INA233 },
  { IO_BUF_B, &ina233_status_cache[1], I2C_ADDR_IOB_ADC_INA233 },
  { 0, 0 }
};

static bool iobuf_reset_ina233(uint8_t i2c_addr) {
  __pdata uint8_t regval;

  // Bring the INA233 to a known state, even if there was no reset (e.g. firmware reload)

  // This command is the only known way to free an asserted ~ALERT line when not using the
  // SMBus ALERT response command.

  // Just send register/command code, no data, to execute the RESTORE_DEFAULT_ALL command
  if(!i2c_reg8_write(i2c_addr, INA233_REG_RESTORE_DEFAULT_ALL, &regval, 0))
    return false;

  // mask all events from triggering an alert (=would switch off our port power)
  // they will be unmasked selectively when the alerts are configured
  regval = 0xFF;
  if(!i2c_reg8_write(i2c_addr, INA233_REG_MFR_ALERT_MASK, &regval, 1))
    return false;

  // TODO: write cal register to allow current measurement

  return true;
}

bool iobuf_init_adc_ina233() {
  __code const struct buffer_desc *buffer;
  for(buffer = buffers; buffer->selector; buffer++) {
    // clear cache
    *(buffer->status_cache_ptr) = 0;

    if (!iobuf_reset_ina233(buffer->address))
      return false;
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

static void millivolts_to_code_bytes_ina233(uint16_t millivolts, __pdata uint8_t *code_bytes) {
  // See explanation above.
  uint32_t code_word = (millivolts * 4) / 5;
  code_bytes[0] = code_word & 0xff;
  code_bytes[1] = code_word >> 8;
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

bool iobuf_set_alert_ina233(uint8_t mask,
                     __xdata const uint16_t *low_millivolts,
                     __xdata const uint16_t *high_millivolts) {
  __code const struct buffer_desc *buffer;
  __pdata uint8_t low_code_bytes[2] = { 0x00, 0x00 };
  __pdata uint8_t high_code_bytes[2] = { 0xf8, 0x7f };
  __pdata uint8_t mask_reg = 0xFF;

  // TODO: we probably want to allow more than MAX_VOLTAGE for the INA233

  if(*low_millivolts > MAX_VOLTAGE || *high_millivolts > MAX_VOLTAGE)
    return false;

  if(*low_millivolts != 0) {
    // Alert enabled, unmask the alert
    millivolts_to_code_bytes_ina233(*low_millivolts, low_code_bytes);
    mask_reg &= ~(INA233_BIT_IN_UV_WARNING);
  }

  if(*high_millivolts != MAX_VOLTAGE) {
    // Alert enabled, unmask the alert
    millivolts_to_code_bytes_ina233(*high_millivolts, high_code_bytes);
    mask_reg &= ~(INA233_BIT_IN_OV_WARNING);
  }

  for(buffer = buffers; buffer->selector; buffer++) {
    if(mask & buffer->selector) {

      if(!i2c_reg8_write(buffer->address, INA233_REG_VIN_UV_WARN_LIMIT, low_code_bytes, 2))
        return false;

      if(!i2c_reg8_write(buffer->address, INA233_REG_VIN_OV_WARN_LIMIT, high_code_bytes, 2))
        return false;

      if(!i2c_reg8_write(buffer->address, INA233_REG_MFR_ALERT_MASK, &mask_reg, 1))
        return false;

      // a CLEAR_FAULTS seems to be necessary after changing the alert mask.
      // Experimentation shows that the alert mask is only evaluated when a fault occurs
      // When a currently masked fault occured, a later change in the alert mask does not
      // cause the fault to trigger ~ALERT. A change in the limit vaules also doesn't cause
      // a fault to be reevaluated.
      if(!i2c_reg8_write(buffer->address, INA233_REG_CLEAR_FAULTS, &mask_reg, 0))
        return false;
    }
  }

  return true;
}


bool iobuf_get_alert_ina233(uint8_t selector,
                     __xdata uint16_t *low_millivolts,
                     __xdata uint16_t *high_millivolts) {
  __code const struct buffer_desc *buffer;
  for(buffer = buffers; buffer->selector; buffer++) {
    if(selector == buffer->selector) {
      __pdata uint8_t code_bytes[2];

      if(!i2c_reg8_read(buffer->address, INA233_REG_VIN_UV_WARN_LIMIT, code_bytes, 2))
        return false;

      if (code_bytes[0] == 0 && code_bytes[1] == 0)
        *low_millivolts = 0;
      else
        *low_millivolts = code_bytes_to_millivolts_ina233(code_bytes);

      if(!i2c_reg8_read(buffer->address, INA233_REG_VIN_OV_WARN_LIMIT, code_bytes, 2))
        return false;

      if (code_bytes[0] == 0xf8 && code_bytes[1] == 0x7f)
        *high_millivolts = MAX_VOLTAGE;
      else
        *high_millivolts = code_bytes_to_millivolts_ina233(code_bytes);

      return true;
    }
  }

  return false;
}

// This just polls the INA233 for alerts and updates the status cache
// It does not clear the ~ALERT line
bool iobuf_poll_alert_ina233(__xdata uint8_t *mask) {
  __code const struct buffer_desc *buffer;
  for(*mask = 0, buffer = buffers; buffer->selector; buffer++) {
    __pdata uint8_t status_byte;
    if(!i2c_reg8_read(buffer->address, INA233_REG_STATUS_MFR_SPECIFIC, &status_byte, 1))
      return false;

    // just check the actual limit alert bits, ignoring the others
    if(status_byte &
        (INA233_BIT_IN_UV_WARNING | INA233_BIT_IN_OV_WARNING | INA233_BIT_IN_OC_WARNING | INA233_BIT_IN_OP_WARNING))
    {
      // we got some kind of limit alert, return the port in the bitmask
      *mask |= buffer->selector;

      // store the full status byte in the status cache
      *(buffer->status_cache_ptr) = status_byte;
    }
  }

  return true;
}

// Just read out and optionally clear the status/alert cache
// This function does not talk to the INA233 at all
void iobuf_read_alert_cache_ina233(__xdata uint8_t *mask, bool clear) {
  __code const struct buffer_desc *buffer;
  for(*mask = 0, buffer = buffers; buffer->selector; buffer++) {
    uint8_t status_byte = *(buffer->status_cache_ptr);

    // just check the actual limit alert bits, ignoring the others
    if(status_byte &
        (INA233_BIT_IN_UV_WARNING | INA233_BIT_IN_OV_WARNING | INA233_BIT_IN_OC_WARNING | INA233_BIT_IN_OP_WARNING))
    {
      // we got some kind of limit alert, return the port in the bitmask
      *mask |= buffer->selector;

      if (clear)
        *(buffer->status_cache_ptr) = 0;
    }
  }
}


bool iobuf_clear_alert_ina233(uint8_t mask) {
  __code const struct buffer_desc *buffer;
  __pdata uint8_t low_code_bytes[2];
  __pdata uint8_t high_code_bytes[2];
  for(buffer = buffers; buffer->selector; buffer++) {
    if (mask & buffer->selector) {
      // The INA233 seems to expect that you clear the ~ALERT line by reading the
      // SMBus Alert Response Address (ARA) at 0001100.
      // Unfortunately this clashes with the address of DAC A on revC2
      // Experimentation showed only RESTORE_DEFAULT_ALL (aka software reset)
      // as alternative way to clear ~ALERT. Especially CLEAR_FAULTS does not
      // affect the ~ALERT line, despite the datasheet claiming otherwise

      // So first read out the currently set limit values, reset, and write them back
      if(!i2c_reg8_read(buffer->address, INA233_REG_VIN_UV_WARN_LIMIT, low_code_bytes, 2))
        return false;

      if(!i2c_reg8_read(buffer->address, INA233_REG_VIN_OV_WARN_LIMIT, high_code_bytes, 2))
        return false;

      if(!iobuf_reset_ina233(buffer->address))
        return false;

      // After the reset, the ~ALERT line is cleared. But so is any trace in the INA233 itself
      // that an alert has happened at all. To allow finding out about the alert, the status_cache
      // in firmware is necessary. iobuf_poll_alert_ina233() stored the alert details in the cache.
      // It has to be called before iobuf_clear_alert_ina233().

      // we masked all alerts after the reset, so the alert will not trigger again instantly

      if(!i2c_reg8_write(buffer->address, INA233_REG_VIN_UV_WARN_LIMIT, low_code_bytes, 2))
        return false;

      if(!i2c_reg8_write(buffer->address, INA233_REG_VIN_OV_WARN_LIMIT, high_code_bytes, 2))
        return false;
    }
  }

  return true;
}
