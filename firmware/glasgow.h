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
  GLASGOW_REV_C3 = 0x33,

  GLASGOW_REV_NA = 0xF9,
};

enum {
  // API compatibility level
  CUR_API_LEVEL  = 0x04,
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

// Set up aliases for all of the GPIO pins accessible by `setb` and `clr`
// to reduce code size.
#define CONCAT(a, b) a ## b
#define IO_A(number) CONCAT(PA, number)
#define IO_B(number) CONCAT(PB, number)
#define IO_D(number) CONCAT(PD, number)

#define IO_ALERT_N        IO_A(PINA_ALERT_N)
#define IO_CDONE          IO_A(PINA_CDONE)
#define IO_CRESET_N_REVC  IO_A(PINA_CRESET_N_REVC)

#define IO_SI             IO_B(PINB_SI)
#define IO_SS_N           IO_B(PINB_SS_N)
#define IO_SCK            IO_B(PINB_SCK)

#define IO_ENVA           IO_D(PIND_ENVA)
#define IO_CRESET_N_REVAB IO_D(PIND_CRESET_N_REVAB)
#define IO_LED_FX2        IO_D(PIND_LED_FX2)
#define IO_LED_ICE        IO_D(PIND_LED_ICE)
#define IO_LED_ACT        IO_D(PIND_LED_ACT)
#define IO_LED_ERR        IO_D(PIND_LED_ERR)
#define IO_ENVB           IO_D(PIND_ENVB)
#define IO_OEQ_N_REVAB    IO_D(PIND_OEQ_N_REVAB)

enum {
  // I2C addresses (unshifted)
  I2C_ADDR_FPGA            = 0b0001000,
  I2C_ADDR_FX2_MEM         = 0b1010001,
  I2C_ADDR_ICE_MEM         = 0b1010010,
  I2C_ADDR_IOA_DAC_REVBC12 = 0b0001100,
  I2C_ADDR_IOA_DAC_REVC3   = 0b0001110,
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

// FPGA registers
enum {
  FPGA_REG_HEALTH   = 0x00,
  FPGA_REG_PIPE_RST = 0x01,
};

// Config API
enum {
  /// Size of the bitstream ID field.
  CONFIG_SIZE_BITSTREAM_ID      = 16,

  /// Size of the manufacturer name field.
  CONFIG_SIZE_MANUFACTURER      = 22,

  /// Modified from the original design files. This flag must be set if the PCBA has been modified
  /// from the design files published in https://github.com/GlasgowEmbedded/glasgow/ in any way
  /// except those exempted in https://glasgow-embedded.org/latest/build.html. It will be set when
  /// running `glasgow factory --using-modified-design-files=yes`.
  CONFIG_FLAG_MODIFIED_DESIGN   = 0b00000001,
};

__xdata __at(0x4000 - CONF_SIZE) struct glasgow_config {
  uint8_t   revision;
  char      serial[16];
  uint32_t  bitstream_size;
  char      bitstream_id[CONFIG_SIZE_BITSTREAM_ID];
  uint16_t  voltage_limit[2];
  char      manufacturer[CONFIG_SIZE_MANUFACTURER];
  uint8_t   flags; // last field in a 64-byte configuration block
} glasgow_config;

// Test mode API
extern __bit test_leds;

// FPGA API
void fpga_init();
void fpga_reset();
void fpga_load(__xdata uint8_t *data, uint8_t len);
bool fpga_start();
bool fpga_is_ready();
bool fpga_reg_select(uint8_t addr);
bool fpga_reg_read(__xdata uint8_t *value, uint8_t length);
bool fpga_reg_write(__xdata const uint8_t *value, uint8_t length);
bool fpga_pipe_rst(uint8_t set, uint8_t clr);

// FIFO API
void fifo_init();
void fifo_configure(bool two_ep);
void fifo_reset(bool two_ep, uint8_t ep_mask);

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
bool iobuf_set_alert_ina233(uint8_t mask,
                     __xdata const uint16_t *low_millivolts,
                     __xdata const uint16_t *high_millivolts);
bool iobuf_get_alert_ina233(uint8_t selector,
                     __xdata uint16_t *low_millivolts,
                     __xdata uint16_t *high_millivolts);
bool iobuf_poll_alert_ina233(__xdata uint8_t *mask);
bool iobuf_clear_alert_ina233(uint8_t mask);
void iobuf_read_alert_cache_ina233(__xdata uint8_t *mask, bool clear);

// Pull API
bool iobuf_set_pull(uint8_t selector, uint8_t enable, uint8_t level);
bool iobuf_get_pull(uint8_t selector, __xdata uint8_t *enable, __xdata uint8_t *level);

// Util functions
bool i2c_reg8_read(uint8_t addr, uint8_t reg, __pdata uint8_t *value, uint8_t length);
bool i2c_reg8_write(uint8_t addr, uint8_t reg, __pdata const uint8_t *value, uint8_t length);

#endif
