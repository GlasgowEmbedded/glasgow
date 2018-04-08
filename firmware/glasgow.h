#ifndef GLASGOW_H
#define GLASGOW_H

#define VID_OPENMOKO 0x1d50
#define PID_GLASGOW  0x7777

// PORTB pins
#define PINB_SCK      0
#define PINB_SI       1
#define PINB_SS_B     2
// PORTD pins
#define PIND_CRESET_B 0

void fpga_reset();
void fpga_load(__xdata uint8_t *data, uint8_t len);
void fpga_start();

#endif
