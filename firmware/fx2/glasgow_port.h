#pragma once

enum port_alerts: uint8_t {
  // These match INA233 alert bits.
  PORT_FAULT_UNDERVOLTAGE = 1<<0,
  PORT_FAULT_OVERVOLTAGE  = 1<<1,
  PORT_FAULT_OVERCURRENT  = 1<<2,
};

// For some reason the enumeration is 16-bit on sdcc 4.5.0.
typedef uint8_t port_alerts_t;

void port_init();
void port_poll_alert();
