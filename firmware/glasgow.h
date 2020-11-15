#ifndef GLASGOW_H
#define GLASGOW_H

#include <stdbool.h>

#define VID_CYPRESS   0x04b4
#define PID_FX2       0x8613

#define VID_QIHW      0x20b7
#define PID_GLASGOW   0x9db1

enum {
  // Board revisions
  GLASGOW_REV_A  = 0x10,
  GLASGOW_REV_B  = 0x20,
  GLASGOW_REV_C0 = 0x30,
  GLASGOW_REV_C1 = 0x31,

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
#define PIND_LED_CY           2
#define PIND_LED_FPGA         3
#define PIND_LED_ACT          4
#define PIND_LED_ERR          5
#define PIND_ENVB             6
#define PIND_OEQ_N_REVAB      7

enum {
  // I2C addresses (unshifted)
  I2C_ADDR_FPGA     = 0b0001000,
  I2C_ADDR_FX2_MEM  = 0b1010001,
  I2C_ADDR_ICE_MEM  = 0b1010010,
  I2C_ADDR_IOA_DAC  = 0b0001100,
  I2C_ADDR_IOB_DAC  = 0b0001101,
  I2C_ADDR_ALL_DAC  = 0b1001000,
  I2C_ADDR_IOA_ADC  = 0b1010100,
  I2C_ADDR_IOB_ADC  = 0b1010101,
  I2C_ADDR_IOA_PULL = 0b0100000,
  I2C_ADDR_IOB_PULL = 0b0100001,
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

// LED API
void leds_init();
void led_fpga_set(bool on);
void led_act_set(bool on);
void led_err_set(bool on);

// FPGA API
void fpga_reset();
void fpga_load(__xdata uint8_t *data, uint8_t len);
void fpga_start();
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

// ADC API
void iobuf_init_adc();
bool iobuf_measure_voltage(uint8_t selector, __xdata uint16_t *millivolts);
bool iobuf_set_alert(uint8_t mask,
                     __xdata const uint16_t *low_millivolts,
                     __xdata const uint16_t *high_millivolts);
bool iobuf_get_alert(uint8_t selector,
                     __xdata uint16_t *low_millivolts,
                     __xdata uint16_t *high_millivolts);
bool iobuf_is_alerted();
bool iobuf_poll_alert(__xdata uint8_t *mask, bool clear);

// Pull API
bool iobuf_set_pull(uint8_t selector, uint8_t enable, uint8_t level);
bool iobuf_get_pull(uint8_t selector, __xdata uint8_t *enable, __xdata uint8_t *level);

// FIFO API
void fifo_init();
void fifo_configure(bool two_ep);
void fifo_reset(bool two_ep, uint8_t interfaces);

#endif
