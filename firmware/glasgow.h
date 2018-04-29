#ifndef GLASGOW_H
#define GLASGOW_H

#include <stdbool.h>

#define VID_OPENMOKO 0x1d50
#define PID_GLASGOW  0x7777

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

void leds_init();
void led_fpga_set(bool on);
void led_act_set(bool on);
void led_err_set(bool on);

void fpga_reset();
void fpga_load(__xdata uint8_t *data, uint8_t len);
bool fpga_start();

#endif
