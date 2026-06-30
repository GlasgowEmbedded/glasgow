#include <stddef.h>
#include <fx2regs.h>
#include <fx2i2c.h>
#include <fx2lib.h>
#include <fx2delay.h>
#include "glasgow.h"

// The SMBus engine uses constant islands.
static __xdata const uint8_t zero = 0x00;
static __xdata const uint8_t ones = 0xFF;

// Due to code size and ABI constraints, these values are stored as global variables instead of
// being arguments or local variables as they would be in a normal codebase.
static __xdata uint8_t config;
static __xdata uint16_t data0, data1;

// ===== revABC DAC081C ===========================================================================

static __idata uint8_t dac_addr_revabc[] = {
  I2C_ADDR_IOA_DAC_REVC3, // or I2C_ADDR_IOA_DAC_REVABC012
  I2C_ADDR_IOB_DAC,
};

static uint16_t dac081c_encode(uint16_t value)
{
  // Offset 1650, slope -15.2, 0x1000/15.2 = 269;
  // the DAC has a 12-bit code word, so we only shift back by 8
  return bswap16((254 << 4) - ((((value - 1650) >> 4) * 269) >> 4));
}

static uint16_t dac081c_decode(uint16_t value)
{
  return 1650 + (255 - (bswap16(value) >> 4)) * 152 / 10;
}

static smbus_sequence set_vsupply_revabc_seq[] = {
  SM_XFRM_WORD(dac081c_encode),
  SM_SEND_WORD(data0),
  SM_DONE(),
};

bool set_vsupply_revabc(uint8_t chan) __reentrant
{
  return smbus_run(set_vsupply_revabc_seq, dac_addr_revabc[chan]);
}

static smbus_sequence get_vsupply_revabc_seq[] = {
  SM_XFRM_WORD(dac081c_decode),
  SM_RECV_WORD(data0),
  SM_DONE(),
};

static bool get_vsupply_revabc(uint8_t chan) __reentrant
{
  return smbus_run(get_vsupply_revabc_seq, dac_addr_revabc[chan]);
}

// ===== revABC01 ADC081C =========================================================================

static __idata const uint8_t adc_addr_revabc01[] = {
  I2C_ADDR_IOA_ADC_REVABC01,
  I2C_ADDR_IOB_ADC_REVABC01,
};

enum {
  // ADC081C registers
  ADC081_REG_CONV_RESULT   = 0x0,
  ADC081_REG_ALERT_STATUS  = 0x1,
  ADC081_REG_CONFIGURATION = 0x2,
  ADC081_REG_LOW_LIMIT     = 0x3,
  ADC081_REG_HIGH_LIMIT    = 0x4,
  ADC081_REG_HYSTERESIS    = 0x5,
  ADC081_REG_LOWEST_CONV   = 0x6,
  ADC081_REG_HIGHEST_CONV  = 0x7,
  // ADC081C Conversion Result register bits
  ADC081_BIT_ALERT_FLAG    = 1<<15,
  // ADC081C Alert Status register bits
  ADC081_BIT_UNDER_RANGE   = 1<<0,
  ADC081_BIT_OVER_RANGE    = 1<<1,
  // ADC081C Configuration register bits
  ADC081_BIT_POLARITY      = 1<<0,
  ADC081_BIT_ALERT_PIN_EN  = 1<<2,
  ADC081_BIT_ALERT_FLAG_EN = 1<<3,
  ADC081_BIT_ALERT_HOLD    = 1<<4,
};

static uint16_t adc081c_decode(uint16_t value)
{
  // 0x000 = 0 mV, 0xff0 = 6600 mV, 16 LSB = 25.9 mV;
  // highest code word achievable is 0xd50 = 5500 mV, so the following doesn't overflow.
  return (bswap16(value) >> 4) * 259 / 10;
}

static uint16_t adc081c_encode(uint16_t value)
{
  return bswap16((value * 10 / 259) << 4);
}

// Reset

static smbus_sequence reset_adc_revabc01_seq[] = {
  SM_WRITE_BYTE(ADC081_REG_CONFIGURATION, zero),
  SM_DONE(),
};

static bool reset_adc_revabc01(uint8_t chan) __reentrant
{
  return smbus_run(reset_adc_revabc01_seq, adc_addr_revabc01[chan]);
}

// During testing done in preparation for upgrading the firmware for revC it was discovered
// that the ADC081C021 IC has an issue where, when the internal oscillator is enabled, under
// certain conditions it is possible to induce a faulty state by issuing I2C reads. This state
// can sometimes prevent the I2C bus from functioning by holding SDA low, and can also prevent
// normal device operation (with all-zeros/all-ones being read out of limit registers) until
// power cycling. Due to this problem, the feature is disabled. (Polling the alert has not been
// implemented in the upgraded firmware for the same reason.)
//
// It is not clear why this issue hasn't been discovered earlier. If you figure out what goes
// wrong this code can be re-enabled.
#if 0
// Valert

static __xdata const uint8_t set_valert_revabc01_const_0 =
  ADC081_BIT_UNDER_RANGE|ADC081_BIT_OVER_RANGE;
static __xdata const uint8_t set_valert_revabc01_const_1 =
  ADC081_BIT_ALERT_PIN_EN|ADC081_BIT_ALERT_HOLD|/*1 ksps*/(0b110u<<5);
static smbus_sequence set_valert_revabc01_seq[] = {
  SM_WRITE_BYTE(ADC081_REG_CONFIGURATION, zero),
  SM_XFRM_WORD(adc081c_encode),
  SM_WRITE_WORD(ADC081_REG_LOW_LIMIT, data0),
  SM_XFRM_WORD(adc081c_encode),
  SM_WRITE_WORD(ADC081_REG_HIGH_LIMIT, data1),
  SM_WRITE_BYTE(ADC081_REG_ALERT_STATUS, set_valert_revabc01_const_0),
  SM_WRITE_BYTE(ADC081_REG_CONFIGURATION, set_valert_revabc01_const_1),
  SM_DONE(),
};

static bool set_valert_revabc01(uint8_t chan) __reentrant
{
  return smbus_run(set_valert_revabc01_seq, adc_addr_revabc01[chan]);
}

static smbus_sequence get_valert_revabc01_seq[] = {
  SM_READ_BYTE(ADC081_REG_CONFIGURATION, config),
  SM_XFRM_WORD(adc081c_decode),
  SM_READ_WORD(ADC081_REG_LOW_LIMIT, data0),
  SM_XFRM_WORD(adc081c_decode),
  SM_READ_WORD(ADC081_REG_HIGH_LIMIT, data1),
  SM_DONE(),
};

static bool get_valert_revabc01(uint8_t chan) __reentrant
{
  if (!smbus_run(get_valert_revabc01_seq, adc_addr_revabc01[chan]))
    return false;
  if (config == 0) {
    data0 = 0;
    data1 = 0;
  }
  return true;
}
#else
static bool set_valert_revabc01(uint8_t chan) __reentrant
{
  (void)chan;
  return false;
}

static bool get_valert_revabc01(uint8_t chan) __reentrant
{
  (void)chan;
  data0 = 0;
  data1 = 0;
  return true;
}
#endif

// Vsense

static smbus_sequence get_vsense_revabc01_seq[] = {
  SM_XFRM_WORD(adc081c_decode),
  SM_READ_WORD(ADC081_REG_CONV_RESULT, data0),
  SM_DONE(),
};

static bool get_vsense_revabc01(uint8_t chan) __reentrant
{
  return smbus_run(get_vsense_revabc01_seq, adc_addr_revabc01[chan]);
}

// ===== revCD INA233 =============================================================================

static __idata uint8_t adc_addr_revc23d[] = {
  I2C_ADDR_IOA_ADC_REVD, // or I2C_ADDR_IOA_ADC_REVC23
  I2C_ADDR_IOB_ADC_REVD, // or I2C_ADDR_IOB_ADC_REVC23
  I2C_ADDR_IOC_ADC_REVD,
  I2C_ADDR_IOD_ADC_REVD,
};

enum {
  // ADC registers
  INA233_CMD_CLEAR_FAULTS        = 0x03,
  INA233_CMD_RESTORE_DEFAULT_ALL = 0x12,
  INA233_CMD_IOUT_OC_WARN_LIMIT  = 0x4A,
  INA233_CMD_VIN_OV_WARN_LIMIT   = 0x57,
  INA233_CMD_VIN_UV_WARN_LIMIT   = 0x58,
  INA233_CMD_STATUS_MFR_SPECIFIC = 0x80,
  INA233_CMD_READ_VIN            = 0x88,
  INA233_CMD_READ_IOUT           = 0x8C,
  INA233_CMD_MFR_ALERT_MASK      = 0xD2,
  INA233_CMD_MFR_CALIBRATION     = 0xD4,
  INA233_CMD_MFR_DEVICE_CONFIG   = 0xD5,
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

static __xdata const uint8_t ina233_cmd_restore_default_all_const =
  INA233_CMD_RESTORE_DEFAULT_ALL;
static __xdata const uint8_t ina233_cmd_clear_faults_const =
  INA233_CMD_CLEAR_FAULTS;

// See `port_init()`.
static __xdata uint16_t adc_calib_revc23d;

static uint16_t ina233_decode_voltage(uint16_t value)
{
  // 0x0000 = 0 mV, 0x7fff (max code value) = 40960 mV, 16 bit LSB = 1.25 mV
  return ((uint32_t)value) * 5 / 4;
}

static uint16_t ina233_encode_voltage(uint16_t value)
{
  return ((uint32_t)value) * 4 / 5;
}

// Reset

static smbus_sequence reset_adc_revc23d_seq[] = {
  // This command is the only known way to free an asserted ~ALERT line when not using the
  // SMBus ALERT response command.
  SM_SEND_BYTE(ina233_cmd_restore_default_all_const),
  // Write calibration register to enable current measurement.
  SM_WRITE_WORD(INA233_CMD_MFR_CALIBRATION, adc_calib_revc23d),
  // Mask all alerts; they will be selectively unmasked when configured.
  SM_WRITE_BYTE(INA233_CMD_MFR_ALERT_MASK, ones),
  SM_DONE(),
};

static bool reset_adc_revc23d(uint8_t chan) __reentrant
{
  return smbus_run(reset_adc_revc23d_seq, adc_addr_revc23d[chan]);
}

// Valert/Ialert shared

static smbus_sequence get_alert_mask_revc23d_seq[] = {
  SM_READ_BYTE(INA233_CMD_MFR_ALERT_MASK, config),
  SM_DONE(),
};

// Valert

static smbus_sequence set_valert_revc23d_seq[] = {
  SM_XFRM_WORD(ina233_encode_voltage),
  SM_WRITE_WORD(INA233_CMD_VIN_OV_WARN_LIMIT, data1),
  SM_XFRM_WORD(ina233_encode_voltage),
  SM_WRITE_WORD(INA233_CMD_VIN_UV_WARN_LIMIT, data0),
  SM_WRITE_BYTE(INA233_CMD_MFR_ALERT_MASK, config),
  // a CLEAR_FAULTS seems to be necessary after changing the alert mask.
  // Experimentation shows that the alert mask is only evaluated when a fault occurs
  // When a currently masked fault occured, a later change in the alert mask does not
  // cause the fault to trigger ~ALERT. A change in the limit vaules also doesn't cause
  // a fault to be reevaluated.
  SM_SEND_BYTE(ina233_cmd_clear_faults_const),
  SM_DONE(),
};

static bool set_valert_revc23d(uint8_t chan) __reentrant
{
  uint8_t addr = adc_addr_revc23d[chan];
  if (!smbus_run(get_alert_mask_revc23d_seq, addr))
    return false;
  config |= INA233_BIT_IN_UV_WARNING|INA233_BIT_IN_OV_WARNING;
  if (data0 != 0) config &= ~INA233_BIT_IN_UV_WARNING;
  if (data1 != 0) config &= ~INA233_BIT_IN_OV_WARNING;
  return smbus_run(set_valert_revc23d_seq, addr);
}

static smbus_sequence get_valert_revc23d_seq[] = {
  SM_READ_BYTE(INA233_CMD_MFR_ALERT_MASK, config),
  SM_XFRM_WORD(ina233_decode_voltage),
  SM_READ_WORD(INA233_CMD_VIN_OV_WARN_LIMIT, data1),
  SM_XFRM_WORD(ina233_decode_voltage),
  SM_READ_WORD(INA233_CMD_VIN_UV_WARN_LIMIT, data0),
  SM_DONE(),
};

static bool get_valert_revc23d(uint8_t chan) __reentrant
{
  if (!smbus_run(get_valert_revc23d_seq, adc_addr_revc23d[chan]))
    return false;
  if (config & INA233_BIT_IN_UV_WARNING) data0 = 0;
  if (config & INA233_BIT_IN_OV_WARNING) data1 = 0;
  return true;
}

// Ialert

static smbus_sequence set_ialert_revc23d_seq[] = {
  SM_WRITE_WORD(INA233_CMD_IOUT_OC_WARN_LIMIT, data0),
  SM_WRITE_BYTE(INA233_CMD_MFR_ALERT_MASK, config),
  // see note in set_valert_revc23d_seq
  SM_SEND_BYTE(ina233_cmd_clear_faults_const),
  SM_DONE(),
};

static bool set_ialert_revc23d(uint8_t chan) __reentrant
{
  uint8_t addr = adc_addr_revc23d[chan];
  if (!smbus_run(get_alert_mask_revc23d_seq, addr))
    return false;
  config |= INA233_BIT_IN_OC_WARNING;
  if (data0 != 0) config &= ~INA233_BIT_IN_OC_WARNING;
  return smbus_run(set_ialert_revc23d_seq, addr);
}

static smbus_sequence get_ialert_revc23d_seq[] = {
  SM_READ_BYTE(INA233_CMD_MFR_ALERT_MASK, config),
  SM_READ_WORD(INA233_CMD_IOUT_OC_WARN_LIMIT, data0),
  SM_DONE(),
};

static bool get_ialert_revc23d(uint8_t chan) __reentrant
{
  if (!smbus_run(get_ialert_revc23d_seq, adc_addr_revc23d[chan]))
    return false;
  if (config & INA233_BIT_IN_OC_WARNING) data0 = 0;
  return true;
}

// Vsense

static smbus_sequence get_vsense_revc23d_seq[] = {
  SM_XFRM_WORD(ina233_decode_voltage),
  SM_READ_WORD(INA233_CMD_READ_VIN, data0),
  SM_DONE(),
};

static bool get_vsense_revc23d(uint8_t chan) __reentrant
{
  return smbus_run(get_vsense_revc23d_seq, adc_addr_revc23d[chan]);
}

// Isense

static smbus_sequence get_isense_revc23d_seq[] = {
  SM_READ_WORD(INA233_CMD_READ_IOUT, data0),
  SM_DONE(),
};

static bool get_isense_revc23d(uint8_t chan) __reentrant
{
  return smbus_run(get_isense_revc23d_seq, adc_addr_revc23d[chan]);
}

static smbus_sequence poll_alert_revc23d_seq[] = {
  SM_READ_BYTE(INA233_CMD_STATUS_MFR_SPECIFIC, config),
  SM_DONE(),
};

static bool poll_alert_revc23d(uint8_t chan) __reentrant
{
  if (!smbus_run(poll_alert_revc23d_seq, adc_addr_revc23d[chan]))
    return false;
  config &= INA233_BIT_IN_OC_WARNING|INA233_BIT_IN_UV_WARNING|INA233_BIT_IN_OV_WARNING;
  return true;
}

// The INA233 seems to expect that you clear the ~ALERT line by reading the SMBus Alert Response
// Address (ARA) at 0b0001100. Unfortunately this clashes with the address of DAC A on revC2.
// Experimentation showed only `RESTORE_DEFAULT_ALL` command (aka software reset) is an alternate
// way to clear ~ALERT. Especially `CLEAR_FAULTS` does not affect the ~ALERT line, despite
// the datasheet claiming otherwise.
//
// Clear the alert by reading out the entire configuration (the parts that we are using at least),
// resetting the chip, then restoring the configuration back. This must be done after supply
// voltage has already been disabled, else the alert will just trigger again.
static smbus_sequence clear_alert_revc23d_seq[] = {
  SM_READ_WORD(INA233_CMD_IOUT_OC_WARN_LIMIT, data0),
  SM_SEND_BYTE(ina233_cmd_restore_default_all_const),
  SM_WRITE_WORD(INA233_CMD_MFR_CALIBRATION, adc_calib_revc23d),
  SM_WRITE_WORD(INA233_CMD_IOUT_OC_WARN_LIMIT, data0),
  SM_WRITE_BYTE(INA233_CMD_MFR_ALERT_MASK, config),
  SM_DONE(),
};

static bool clear_alert_revc23d(uint8_t chan) __reentrant
{
  uint8_t addr = adc_addr_revc23d[chan];
  if (!smbus_run(get_alert_mask_revc23d_seq, addr))
    return false;
  // Over-current alert remains enabled after clearing since it will always stop firing after
  // Vsupply is disabled. Over/under-voltage alerts are disabled since Vsense is external and
  // there is no guarantee that it has any relationship to Vsupply.
  config |= ~INA233_BIT_IN_OC_WARNING;
  return smbus_run(clear_alert_revc23d_seq, addr);
}

// ===== revD DAC43204 ============================================================================

// This device can work in either I2C or PMBus mode (a non-sequitur). The same registers are
// laid out in different ways (big vs little endian, global vs per-channel) with different access
// methods. This code is parameterized per-channel and uses little endian, so we switch to PMBus
// mode on reset.
static __xdata uint8_t dac43204_page;

enum {
  // I2C mode (PMBus mode address differs)
  DAC43204_REG_INTERFACE_CONFIG = 0x26,
  // any PMBus page
  DAC43204_CMD_PMBUS_PAGE = 0x00,
  // PMBus page FFh
  DAC43204_CMD_COMMON_CONFIG = 0xE3,
  DAC43204_CMD_DAC_0_IOUT_MISC_CONFIG = 0xD2,
  DAC43204_CMD_DAC_1_IOUT_MISC_CONFIG = 0xD6,
  DAC43204_CMD_DAC_2_IOUT_MISC_CONFIG = 0xDA,
  DAC43204_CMD_DAC_3_IOUT_MISC_CONFIG = 0xDE,
  // PMBus page 00h, 01h, 02h, 03h
  DAC43204_CMD_DAC_X_DATA = 0x21,
};

static uint16_t dac43204_encode(uint16_t value)
{
  // code 0x1A00 for 5.0 V, code 0xB400 for 0.9 V: slope 26.5 mV/256 LSB
  // multiplication split across division to avoid overflow
  return (((5690 - value) * 8) / 53) * 64;
}

static uint16_t dac43204_decode(uint16_t value)
{
  return 5690 - (((value / 64) * 53) / 8);
}

static __xdata const uint16_t reset_dac_revd_const_0 =
  /*INTERFACE-CONFIG={EN-PMBUS=1}*/0x0101; // byte-reversed because of mode mismatch
static __xdata const uint16_t reset_dac_revd_const_1 =
  /*COMMON-CONFIG={EN-INT-REF=1,VOUT-PDN-X=11,IOUT-PDN-X=0}*/0b0001'110'110'110'110;
static __xdata const uint16_t reset_dac_revd_const_2 =
  /*DAC-X-IOUT-MISC-CONFIG={IOUT-RANGE-X±50uV}=*/0b000'1001'0'00000000;
static smbus_sequence reset_dac_revd_seq[] = {
  // NOP in I2C mode, PMBUS-PAGE=FFh in PMBus mode
  SM_WRITE_BYTE(DAC43204_CMD_PMBUS_PAGE, ones),
  // EN-PMBUS=1 in I2C mode, NOP in PMBus mode (no register 22h on page FFh)
  SM_WRITE_WORD(DAC43204_REG_INTERFACE_CONFIG, reset_dac_revd_const_0),
  // now set PMBUS-PAGE=FFh to do actual configuration
  SM_WRITE_BYTE(DAC43204_CMD_PMBUS_PAGE, ones),
  SM_WRITE_WORD(DAC43204_CMD_COMMON_CONFIG, reset_dac_revd_const_1),
  SM_WRITE_WORD(DAC43204_CMD_DAC_0_IOUT_MISC_CONFIG, reset_dac_revd_const_2),
  SM_WRITE_WORD(DAC43204_CMD_DAC_1_IOUT_MISC_CONFIG, reset_dac_revd_const_2),
  SM_WRITE_WORD(DAC43204_CMD_DAC_2_IOUT_MISC_CONFIG, reset_dac_revd_const_2),
  SM_WRITE_WORD(DAC43204_CMD_DAC_3_IOUT_MISC_CONFIG, reset_dac_revd_const_2),
  SM_DONE(),
};

static bool reset_dac_revd(uint8_t chan) __reentrant
{
  if (chan == 0)
    return smbus_run(reset_dac_revd_seq, I2C_ADDR_ALL_DAC_REVD);
  return true;
}

static smbus_sequence set_vsupply_revd_seq[] = {
  SM_WRITE_BYTE(DAC43204_CMD_PMBUS_PAGE, dac43204_page),
  SM_XFRM_WORD(dac43204_encode),
  SM_WRITE_WORD(DAC43204_CMD_DAC_X_DATA, data0),
  SM_DONE(),
};

static bool set_vsupply_revd(uint8_t chan) __reentrant
{
  dac43204_page = chan;
  return smbus_run(set_vsupply_revd_seq, I2C_ADDR_ALL_DAC_REVD);
}

static smbus_sequence get_vsupply_revd_seq[] = {
  SM_WRITE_BYTE(DAC43204_CMD_PMBUS_PAGE, dac43204_page),
  SM_XFRM_WORD(dac43204_decode),
  SM_READ_WORD(DAC43204_CMD_DAC_X_DATA, data0),
  SM_DONE(),
};

static bool get_vsupply_revd(uint8_t chan) __reentrant
{
  dac43204_page = chan;
  return smbus_run(get_vsupply_revd_seq, I2C_ADDR_ALL_DAC_REVD);
}

// ===== revC PCA6408A ============================================================================

static __idata uint8_t pull_addr_revc[] = {
  I2C_ADDR_IOA_PULL_REVC,
  I2C_ADDR_IOB_PULL_REVC,
};

enum {
  PCA6408A_CMD_INPUT_PORT         = 0x00,
  PCA6408A_CMD_OUTPUT_PORT        = 0x01,
  PCA6408A_CMD_POLARITY_INVERSION = 0x02,
  PCA6408A_CMD_CONFIGURATION      = 0x03,
};

static smbus_sequence set_pulls_revc_seq[] = {
  SM_WRITE_BYTE(PCA6408A_CMD_OUTPUT_PORT, data0),
  SM_WRITE_BYTE(PCA6408A_CMD_CONFIGURATION, data1),
  SM_DONE(),
};

static bool set_pulls_revc(uint8_t chan) __reentrant
{
  return smbus_run(set_pulls_revc_seq, pull_addr_revc[chan]);
}

static smbus_sequence get_pulls_revc_seq[] = {
  SM_READ_BYTE(PCA6408A_CMD_OUTPUT_PORT, data0),
  SM_READ_BYTE(PCA6408A_CMD_CONFIGURATION, data1),
  SM_DONE(),
};

static bool get_pulls_revc(uint8_t chan) __reentrant
{
  return smbus_run(get_pulls_revc_seq, pull_addr_revc[chan]);
}

static smbus_sequence get_state_revc_seq[] = {
  SM_READ_BYTE(PCA6408A_CMD_INPUT_PORT, data0),
  SM_DONE(),
};

static bool get_state_revc(uint8_t chan) __reentrant
{
  return smbus_run(get_state_revc_seq, pull_addr_revc[chan]);
}

// ===== revD PCA6416A ============================================================================

static __idata uint8_t pull_addr_revd[] = {
  I2C_ADDR_IOAC_PULL_REVD,
  I2C_ADDR_IOBD_PULL_REVD,
  I2C_ADDR_IOAC_PULL_REVD,
  I2C_ADDR_IOBD_PULL_REVD,
};

enum {
  PCA6416A_CMD_INPUT_PORT_0         = 0x00,
  PCA6416A_CMD_INPUT_PORT_1         = 0x01,
  PCA6416A_CMD_OUTPUT_PORT_0        = 0x02,
  PCA6416A_CMD_OUTPUT_PORT_1        = 0x03,
  PCA6416A_CMD_POLARITY_INVERSION_0 = 0x04,
  PCA6416A_CMD_POLARITY_INVERSION_1 = 0x05,
  PCA6416A_CMD_CONFIGURATION_0      = 0x06,
  PCA6416A_CMD_CONFIGURATION_1      = 0x07,
};

static smbus_sequence set_pulls_revd_seq0[] = {
  SM_WRITE_BYTE(PCA6416A_CMD_OUTPUT_PORT_0, data0),
  SM_WRITE_BYTE(PCA6416A_CMD_CONFIGURATION_0, data1),
  SM_DONE(),
};

static smbus_sequence set_pulls_revd_seq1[] = {
  SM_WRITE_BYTE(PCA6416A_CMD_OUTPUT_PORT_1, data0),
  SM_WRITE_BYTE(PCA6416A_CMD_CONFIGURATION_1, data1),
  SM_DONE(),
};

static bool set_pulls_revd(uint8_t chan) __reentrant
{
  return smbus_run(chan&1 ? set_pulls_revd_seq1 : set_pulls_revd_seq0, pull_addr_revd[chan]);
}

static smbus_sequence get_pulls_revd_seq0[] = {
  SM_READ_BYTE(PCA6416A_CMD_OUTPUT_PORT_0, data0),
  SM_READ_BYTE(PCA6416A_CMD_CONFIGURATION_0, data1),
  SM_DONE(),
};

static smbus_sequence get_pulls_revd_seq1[] = {
  SM_READ_BYTE(PCA6416A_CMD_OUTPUT_PORT_1, data0),
  SM_READ_BYTE(PCA6416A_CMD_CONFIGURATION_1, data1),
  SM_DONE(),
};

static bool get_pulls_revd(uint8_t chan) __reentrant
{
  return smbus_run(chan&1 ? get_pulls_revd_seq1 : get_pulls_revd_seq0, pull_addr_revd[chan]);
}

static smbus_sequence get_state_revd_seq0[] = {
  SM_READ_BYTE(PCA6416A_CMD_INPUT_PORT_0, data0),
  SM_DONE(),
};

static smbus_sequence get_state_revd_seq1[] = {
  SM_READ_BYTE(PCA6416A_CMD_INPUT_PORT_1, data0),
  SM_DONE(),
};

static bool get_state_revd(uint8_t chan) __reentrant
{
  return smbus_run(chan&1 ? get_state_revd_seq1 : get_state_revd_seq0, pull_addr_revd[chan]);
}

// ===== Generic code =============================================================================

static bool always_succeeds(uint8_t chan)
{
  (void)chan;
  return true;
}

static bool always_fails(uint8_t chan)
{
  (void)chan;
  return false;
}

const __idata uint8_t port_en_bit[] = {
  1u<<PIND_EN_VA,
  1u<<PIND_EN_VB,
  1u<<PIND_EN_VC_REVD,
  1u<<PIND_EN_VD_REVD,
};

struct port_params {
  uint8_t valid_mask;
  uint16_t vsupply_min;
  uint16_t vsupply_max;
  bool (*reset_dac)(uint8_t chan) __reentrant;
  bool (*set_vsupply)(uint8_t chan) __reentrant;
  bool (*get_vsupply)(uint8_t chan) __reentrant;
  bool (*reset_adc)(uint8_t chan) __reentrant;
  bool (*set_valert)(uint8_t chan) __reentrant;
  bool (*get_valert)(uint8_t chan) __reentrant;
  bool (*set_ialert)(uint8_t chan) __reentrant;
  bool (*get_ialert)(uint8_t chan) __reentrant;
  bool (*get_vsense)(uint8_t chan) __reentrant;
  bool (*get_isense)(uint8_t chan) __reentrant;
  bool (*poll_alert)(uint8_t chan) __reentrant;
  bool (*clear_alert)(uint8_t chan) __reentrant;
  bool (*set_pulls)(uint8_t chan) __reentrant;
  bool (*get_pulls)(uint8_t chan) __reentrant;
  bool (*get_state)(uint8_t chan) __reentrant;
};

static const __xdata struct port_params port_params_revabc01 = {
  .valid_mask     = 0b0011,
  .vsupply_min    = 1650,
  .vsupply_max    = 5500,
  .reset_dac      = always_succeeds,
  .set_vsupply    = set_vsupply_revabc,
  .get_vsupply    = get_vsupply_revabc,
  .reset_adc      = reset_adc_revabc01,
  .set_valert     = set_valert_revabc01,
  .get_valert     = get_valert_revabc01,
  .set_ialert     = always_fails,
  .get_ialert     = always_fails,
  .get_vsense     = get_vsense_revabc01,
  .get_isense     = always_fails,
  .poll_alert     = always_succeeds,
  .clear_alert    = always_fails,
  // will always fail on revAB; revAB+revC01 handling unified to reduce code size
  .set_pulls      = set_pulls_revc,
  .get_pulls      = get_pulls_revc,
  .get_state      = get_state_revc,
};

static const __xdata struct port_params port_params_revc23 = {
  .valid_mask     = 0b0011,
  .vsupply_min    = 1650,
  .vsupply_max    = 5500,
  .reset_dac      = always_succeeds,
  .set_vsupply    = set_vsupply_revabc,
  .get_vsupply    = get_vsupply_revabc,
  .reset_adc      = reset_adc_revc23d,
  .set_valert     = set_valert_revc23d,
  .get_valert     = get_valert_revc23d,
  .set_ialert     = set_ialert_revc23d,
  .get_ialert     = get_ialert_revc23d,
  .get_vsense     = get_vsense_revc23d,
  .get_isense     = get_isense_revc23d,
  .poll_alert     = poll_alert_revc23d,
  .clear_alert    = clear_alert_revc23d,
  .set_pulls      = set_pulls_revc,
  .get_pulls      = get_pulls_revc,
  .get_state      = get_state_revc,
};

static const __xdata struct port_params port_params_revd = {
  .valid_mask     = 0b1111,
  .vsupply_min    =  900,
  .vsupply_max    = 5500,
  .reset_dac      = reset_dac_revd,
  .set_vsupply    = set_vsupply_revd,
  .get_vsupply    = get_vsupply_revd,
  .reset_adc      = reset_adc_revc23d,
  .set_valert     = set_valert_revc23d,
  .get_valert     = get_valert_revc23d,
  .set_ialert     = set_ialert_revc23d,
  .get_ialert     = get_ialert_revc23d,
  .get_vsense     = get_vsense_revc23d,
  .get_isense     = get_isense_revc23d,
  .poll_alert     = poll_alert_revc23d,
  .clear_alert    = clear_alert_revc23d,
  .set_pulls      = set_pulls_revd,
  .get_pulls      = get_pulls_revd,
  .get_state      = get_state_revd,
};

static const __xdata struct port_params *port_params;

void port_init()
{
  IO_EN_VA = 0;
  IO_EN_VB = 0;
  if (glasgow_config.revision == GLASGOW_REV_D0) {
    IO_EN_VC_REVD = 0;
    IO_EN_VD_REVD = 0;
    port_params = &port_params_revd;
    // R_shunt = 0.05 ohm, Current_LSB = 10 uA/LSB (round number to save 59 bytes XRAM)
    // I_max = Current_LSB * 2**15 = 327.68 mA (TPS629203 current limit is 300 mA)
    // CAL = 0.00512 / (R_shunt * Current_LSB)
    adc_calib_revc23d = 10240;
  } else {
    if (glasgow_config.revision >= GLASGOW_REV_C2) {
      port_params = &port_params_revc23;
      // R_shunt = 0.15 ohm, Current_LSB = 10 uA/LSB (round number to save 59 bytes XRAM)
      // I_max = Current_LSB * 2**15 = 327.68 mA (typ. foldback current limit is 360 mA)
      // CAL = 0.00512 / (R_shunt * Current_LSB)
      adc_calib_revc23d = 3413;
    } else {
      port_params = &port_params_revabc01;
    }
  }
  if (glasgow_config.revision < GLASGOW_REV_C3) {
    // revC3 and later has the port A DAC strapped to a different address because
    // the address on previous revisions conflicts with SMBus Alert Response address.
    dac_addr_revabc[0] = I2C_ADDR_IOA_DAC_REVABC012;
  }
  if (glasgow_config.revision < GLASGOW_REV_D0) {
    // revD0 and later use a different address for port A and B INA233s, with addresses
    // adjacent to the ones for ports C and D.
    adc_addr_revc23d[0] = I2C_ADDR_IOA_ADC_REVC23;
    adc_addr_revc23d[1] = I2C_ADDR_IOB_ADC_REVC23;
  }
  for (uint8_t chan = 0; chan < 4; chan++) {
    if (port_params->valid_mask & nibble_mask[chan]) {
      port_params->reset_dac(chan);
      port_params->reset_adc(chan);
      data0 = data1 = 0;
      port_params->set_pulls(chan);
    }
  }
}

static bool port_valid_voltage(uint16_t millivolts)
{
  return millivolts == 0 ||
         millivolts >= port_params->vsupply_min &&
         millivolts <= port_params->vsupply_max;
}

enum mgmt_result port_mgmt_set_vsupply()
{
  // Validate request.
  if (mgmt_req.vsupply.mask & ~port_params->valid_mask)
    return RES_ERROR;
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.vsupply.value); chan++) {
    if (mgmt_req.vsupply.mask & nibble_mask[chan]) {
      uint16_t supply_millivolts = mgmt_req.vsupply.value[chan];
      // Check against physical limits.
      if (!port_valid_voltage(supply_millivolts))
        return RES_ERROR;
      // Check against programmed limit.
      uint16_t limit_millivolts = glasgow_config.voltage_limit[chan];
      if (limit_millivolts != 0 && supply_millivolts > limit_millivolts)
        return RES_ERROR;
    }
  }
  // Apply request.
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.vsupply.value); chan++) {
    if (mgmt_req.vsupply.mask & nibble_mask[chan]) {
      uint16_t millivolts = mgmt_req.vsupply.value[chan];
      if (millivolts == 0)
        IOD &= ~port_en_bit[chan];
      data0 = millivolts;
      if (!port_params->set_vsupply(chan))
        return RES_ERROR;
      if (millivolts != 0)
        IOD |= port_en_bit[chan];
    }
  }
  return RES_ACK;
}

enum mgmt_result port_mgmt_get_vsupply()
{
  mgmt_rsp.vsupply.mask = port_params->valid_mask;
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.vsupply.value); chan++) {
    if (mgmt_rsp.vsupply.mask & nibble_mask[chan]) {
      if (IOD & port_en_bit[chan]) {
        if (!port_params->get_vsupply(chan))
          return RES_ERROR;
        mgmt_rsp.vsupply.value[chan] = data0;
      } else {
        mgmt_rsp.vsupply.value[chan] = 0;
      }
    }
  }
  return RES_ACK;
}

enum mgmt_result port_mgmt_set_vlimit()
{
  // Validate request.
  if (mgmt_req.vlimit.mask & ~port_params->valid_mask)
    return RES_ERROR;
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.vlimit.value); chan++) {
    if (mgmt_req.vlimit.mask & nibble_mask[chan]) {
      uint16_t millivolts = mgmt_req.vlimit.value[chan];
      // Check against physical limits.
      if (!port_valid_voltage(millivolts))
        return RES_ERROR;
    }
  }
  // Apply request.
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.vlimit.value); chan++) {
    if (mgmt_req.vlimit.mask & nibble_mask[chan]) {
      uint16_t millivolts = mgmt_req.vlimit.value[chan];
      if (!port_params->get_vsupply(chan))
        return RES_ERROR;
      if (data0 > millivolts) {
        data0 = millivolts;
        if (!port_params->set_vsupply(chan))
          return RES_ERROR;
      }
      glasgow_config.voltage_limit[chan] = millivolts;
      if (!config_save(offsetof(struct glasgow_config, voltage_limit[chan]), sizeof(uint16_t)))
        return RES_ERROR;
    }
  }
  return RES_ACK;
}

enum mgmt_result port_mgmt_get_vlimit()
{
  mgmt_rsp.vlimit.mask = port_params->valid_mask;
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.vlimit.value); chan++) {
    if (mgmt_rsp.vlimit.mask & nibble_mask[chan]) {
      mgmt_rsp.vlimit.value[chan] = glasgow_config.voltage_limit[chan];
    }
  }
  return RES_ACK;
}

enum mgmt_result port_mgmt_set_valert()
{
  // Validate request.
  if (mgmt_req.valert.mask & ~port_params->valid_mask)
    return RES_ERROR;
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.valert.value); chan++) {
    if (mgmt_req.valert.mask & nibble_mask[chan]) {
      uint16_t low_millivolts  = mgmt_req.valert.value[chan].low;
      uint16_t high_millivolts = mgmt_req.valert.value[chan].high;
      // Check against physical limits.
      if (!port_valid_voltage(low_millivolts) ||
          !port_valid_voltage(high_millivolts))
        return RES_ERROR;
    }
  }
  // Apply request.
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.valert.value); chan++) {
    if (mgmt_req.valert.mask & nibble_mask[chan]) {
      data0 = mgmt_req.valert.value[chan].low;
      data1 = mgmt_req.valert.value[chan].high;
      if (!port_params->set_valert(chan))
        return RES_ERROR;
    }
  }
  return RES_ACK;
}

enum mgmt_result port_mgmt_get_valert()
{
  mgmt_rsp.valert.mask = port_params->valid_mask;
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.valert.value); chan++) {
    if (mgmt_rsp.valert.mask & nibble_mask[chan]) {
      if (!port_params->get_valert(chan))
        return RES_ERROR;
      mgmt_rsp.valert.value[chan].low  = data0;
      mgmt_rsp.valert.value[chan].high = data1;
    }
  }
  return RES_ACK;
}

enum mgmt_result port_mgmt_set_ialert()
{
  // Apply request.
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.ialert.value); chan++) {
    if (mgmt_req.ialert.mask & nibble_mask[chan]) {
      data0 = mgmt_req.ialert.value[chan];
      if (!port_params->set_ialert(chan))
        return RES_ERROR;
    }
  }
  return RES_ACK;
}

enum mgmt_result port_mgmt_get_ialert()
{
  mgmt_rsp.ialert.mask = port_params->valid_mask;
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.ialert.value); chan++) {
    if (mgmt_rsp.ialert.mask & nibble_mask[chan]) {
      if (!port_params->get_ialert(chan))
        return RES_ERROR;
      mgmt_rsp.ialert.value[chan] = data0;
    }
  }
  return RES_ACK;
}

enum mgmt_result port_mgmt_get_vsense()
{
  mgmt_rsp.vsense.mask = port_params->valid_mask;
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.vsense.value); chan++) {
    if (mgmt_rsp.vsense.mask & nibble_mask[chan]) {
      if (!port_params->get_vsense(chan))
        return RES_ERROR;
      mgmt_rsp.vsense.value[chan] = data0;
    }
  }
  return RES_ACK;
}

enum mgmt_result port_mgmt_get_isense()
{
  mgmt_rsp.isense.mask = port_params->valid_mask;
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.isense.value); chan++) {
    if (mgmt_rsp.isense.mask & nibble_mask[chan]) {
      if (!port_params->get_isense(chan))
        return RES_ERROR;
      mgmt_rsp.isense.value[chan] = data0;
    }
  }
  return RES_ACK;
}

void port_poll_alert()
{
  for (uint8_t chan = 0; chan < 4; chan++) {
    if (port_params->valid_mask & nibble_mask[chan]) {
      if (!port_params->poll_alert(chan))
        continue; // not much we can do about it
      if (config) {
        IOD &= ~port_en_bit[chan];
        alert.ports[chan] |= config; // `enum port_alerts` matches INA233 alert mask bit layout
        port_params->clear_alert(chan);
        alert_pending = true;
      }
    }
  }
}

enum mgmt_result port_mgmt_set_pulls()
{
  if (mgmt_req.pulls.mask & ~port_params->valid_mask)
    return RES_ERROR;
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.pulls.value); chan++) {
    if (mgmt_req.pulls.mask & nibble_mask[chan]) {
      uint8_t up   = mgmt_req.pulls.value[chan].up;
      uint8_t down = mgmt_req.pulls.value[chan].down;
      uint8_t keep = up & down;
      uint8_t ena  = up | down;
      if (!port_params->get_pulls(chan))
        return RES_ERROR;
      /*out*/data0 = (data0 & keep) | ( up  & ~keep);
      /*tri*/data1 = (data1 & keep) | (~ena & ~keep);
      if (!port_params->set_pulls(chan))
        return RES_ERROR;
    }
  }
  return RES_ACK;
}

enum mgmt_result port_mgmt_get_pulls()
{
  mgmt_rsp.pulls.mask = port_params->valid_mask;
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.pulls.value); chan++) {
    if (mgmt_rsp.pulls.mask & nibble_mask[chan]) {
      data1 = 0;
      if (IOD & port_en_bit[chan]) {
        if (!port_params->get_pulls(chan))
          return RES_ERROR;
      }
      mgmt_rsp.pulls.value[chan].up   = /*tri*/~data1 &  /*out*/data0;
      mgmt_rsp.pulls.value[chan].down = /*tri*/~data1 & ~/*out*/data0;
    }
  }
  return RES_ACK;
}

enum mgmt_result port_mgmt_get_state()
{
  mgmt_rsp.state.mask = port_params->valid_mask;
  for (uint8_t chan = 0; chan < ARRAYSIZE(mgmt_req.state.value); chan++) {
    if (mgmt_rsp.state.mask & nibble_mask[chan]) {
      data0 = 0;
      if (IOD & port_en_bit[chan]) {
        if (!port_params->get_state(chan))
          return RES_ERROR;
      }
      mgmt_rsp.state.value[chan] = data0;
    }
  }
  return RES_ACK;
}
