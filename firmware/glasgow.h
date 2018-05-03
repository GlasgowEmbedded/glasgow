#ifndef GLASGOW_H
#define GLASGOW_H

#include <stdbool.h>

#define VID_QIHW      0x20b7
#define PID_GLASGOW   0x9db1

// PORTA pins
#define PINA_ALERT_N  0
#define PINA_CDONE    3
// PORTB pins
#define PINB_SI       2
#define PINB_SS_N     3
#define PINB_SCK      4
// PORTD pins
#define PIND_ENVA_N   0
#define PIND_CRESET_N 1
#define PIND_LED_CY   2
#define PIND_LED_FPGA 3
#define PIND_LED_ACT  4
#define PIND_LED_ERR  5
#define PIND_ENVB_N   6
#define PIND_OEQ_N    7

// I2C addresses (unshifted)
#define I2C_ADDR_FPGA     0b0001000
#define I2C_ADDR_CYP_MEM  0b1010001
#define I2C_ADDR_FPGA_MEM 0b1010010
#define I2C_ADDR_IOA_DAC  0b0011000
#define I2c_ADDR_IOA_ADC  0b1010100
#define I2C_ADDR_IOB_DAC  0b0011001
#define I2c_ADDR_IOB_ADC  0b1010101

// LED API
void leds_init();
void led_fpga_set(bool on);
void led_act_set(bool on);
void led_err_set(bool on);

// FPGA API
void fpga_reset();
void fpga_load(__xdata uint8_t *data, uint8_t len);
bool fpga_is_ready();
bool fpga_reg_select(uint8_t addr);
bool fpga_reg_read(uint8_t *value, uint8_t length);
bool fpga_reg_write(uint8_t *value, uint8_t length);

#endif
