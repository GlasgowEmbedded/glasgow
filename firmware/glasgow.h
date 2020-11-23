#ifndef GLASGOW_H
#define GLASGOW_H

#include <stdbool.h>

#define VID_CYPRESS   0x04b4
#define PID_FX2       0x8613

#define VID_QIHW      0x20b7
#define PID_GLASGOW   0x9db1

enum {
  // Board revisions
  //
  // The revision byte encodes the letter X and digit N in "revXN" in the high and low nibble
  // respectively. The high nibble is the letter (1 means 'A') and the low nibble is the digit.
  // This means that host software can always decode a revision to be human-readable, even if
  // the hardware is newer than the software.
  GLASGOW_REV_A  = 0x10,
  GLASGOW_REV_B  = 0x20,
  GLASGOW_REV_C0 = 0x30,
  GLASGOW_REV_C1 = 0x31,
  GLASGOW_REV_C2 = 0x32,

  GLASGOW_REV_NA = 0xF9,
};

enum {
  // API compatibility level
  CUR_API_LEVEL  = 0x01,
};

// PORTA pins
#define PINA_ALERT_N          0
#define PINA_CDONE            3
#define PINA_CRESET_N_REVC    1
// PORTB pins
#define PINB_SI               2
#define PINB_SS_N             3
#define PINB_SCK              4
// PORTD pins
#define PIND_ENVA             0
#define PIND_CRESET_N_REVAB   1
#define PIND_LED_FX2          2
#define PIND_LED_ICE          3
#define PIND_LED_ACT          4
#define PIND_LED_ERR          5
#define PIND_ENVB             6
#define PIND_OEQ_N_REVAB      7

enum {
  // I2C addresses (unshifted)
  I2C_ADDR_FPGA            = 0b0001000,
  I2C_ADDR_FX2_MEM         = 0b1010001,
  I2C_ADDR_ICE_MEM         = 0b1010010,
  I2C_ADDR_IOA_DAC         = 0b0001100,
  I2C_ADDR_IOB_DAC         = 0b0001101,
  I2C_ADDR_ALL_DAC         = 0b1001000,
  I2C_ADDR_IOA_ADC_ADC081C = 0b1010100,
  I2C_ADDR_IOB_ADC_ADC081C = 0b1010101,
  I2C_ADDR_IOA_ADC_INA233  = 0b1000000,
  I2C_ADDR_IOB_ADC_INA233  = 0b1000001,
  I2C_ADDR_IOA_PULL        = 0b0100000,
  I2C_ADDR_IOB_PULL        = 0b0100001,
};

enum {
  // I/O buffer selectors
  IO_BUF_A      = (1<<0),
  IO_BUF_B      = (1<<1),
  IO_BUF_ALL    = IO_BUF_A|IO_BUF_B,
};

// I/O buffer parameters
#define MIN_VOLTAGE 1650 // mV
#define MAX_VOLTAGE 5500 // mV

// Config API
#define BITSTREAM_ID_SIZE 16

__xdata __at(0x4000 - CONF_SIZE) struct glasgow_config {
  uint8_t   revision;
  char      serial[16];
  uint32_t  bitstream_size;
  char      bitstream_id[BITSTREAM_ID_SIZE];
  uint16_t  voltage_limit[2];
} glasgow_config;

// FPGA API
void fpga_init();
void fpga_reset();
void fpga_load(__xdata uint8_t *data, uint8_t len);
bool fpga_start();
bool fpga_is_ready();
bool fpga_reg_select(uint8_t addr);
bool fpga_reg_read(__xdata uint8_t *value, uint8_t length);
bool fpga_reg_write(__xdata const uint8_t *value, uint8_t length);

// DAC/LDO API
void iobuf_init_dac_ldo();
void iobuf_enable(bool on);
bool iobuf_set_voltage(uint8_t mask, __xdata const uint16_t *millivolts);
bool iobuf_get_voltage(uint8_t selector, __xdata uint16_t *millivolts);
bool iobuf_set_voltage_limit(uint8_t mask, __xdata const uint16_t *millivolts);
bool iobuf_get_voltage_limit(uint8_t selector, __xdata uint16_t *millivolts);

// ADC API (TI ADC081C)
void iobuf_init_adc_adc081c();
bool iobuf_measure_voltage_adc081c(uint8_t selector, __xdata uint16_t *millivolts);
bool iobuf_set_alert_adc081c(uint8_t mask,
                     __xdata const uint16_t *low_millivolts,
                     __xdata const uint16_t *high_millivolts);
bool iobuf_get_alert_adc081c(uint8_t selector,
                     __xdata uint16_t *low_millivolts,
                     __xdata uint16_t *high_millivolts);
bool iobuf_is_alerted_adc081c();
bool iobuf_poll_alert_adc081c(__xdata uint8_t *mask, bool clear);

// ADC API (TI INA233)
bool iobuf_init_adc_ina233();
bool iobuf_measure_voltage_ina233(uint8_t selector, __xdata uint16_t *millivolts);
bool iobuf_get_alert_ina233(uint8_t selector,
                     __xdata uint16_t *low_millivolts,
                     __xdata uint16_t *high_millivolts);

// Pull API
bool iobuf_set_pull(uint8_t selector, uint8_t enable, uint8_t level);
bool iobuf_get_pull(uint8_t selector, __xdata uint8_t *enable, __xdata uint8_t *level);

// FIFO API
void fifo_init();
void fifo_configure(bool two_ep);
void fifo_reset(bool two_ep, uint8_t interfaces);

// Util functions
bool i2c_reg8_read(uint8_t addr, uint8_t reg,
                         __pdata uint8_t *value, uint8_t length);
bool i2c_reg8_write(uint8_t addr, uint8_t reg,
                          __pdata const uint8_t *value, uint8_t length);

#endif
