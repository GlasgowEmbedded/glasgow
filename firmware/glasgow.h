#ifndef GLASGOW_H
#define GLASGOW_H

#include <stdbool.h>

#define VID_OPENMOKO 0x1d50
#define PID_GLASGOW  0x7777

// PORTA pins
#define PINA_CDONE    3
// PORTB pins
#define PINB_SS_B     3
#define PINB_SCK      4
#define PINB_SI       2
// PORTD pins
#define PIND_CRESET_B 1

void fpga_reset();
void fpga_load(__xdata uint8_t *data, uint8_t len);
bool fpga_start();

#endif
