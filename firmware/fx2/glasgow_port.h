//! This module implements analog IO port features (Vsupply/Ialert/Vsense(alert) configuration,
//! Isupply measurement/Vsense measurement, pull resistor configuration, port alert handling).
//! These functions are exposed via the EP1 management protocol only (there is no API).

#pragma once

/// Per-port alert bit mask. See [struct mgmt_alert].
///
/// The specific bit masks happen to match INA233 alert bits, but are a stable part of the EP1
/// management protocol and will not change if we switch to a different ADC.
///
/// Note: sdcc 4.5.0 infers the underlying type for this enum as uint16_t despite the explicit
/// annotation and the C specification. uint8_t is used in protocol structures instead.
enum port_alerts: uint8_t {
  PORT_FAULT_UNDERVOLTAGE = 1<<0,
  PORT_FAULT_OVERVOLTAGE  = 1<<1,
  PORT_FAULT_OVERCURRENT  = 1<<2,
};

/// Initialize analog IO port features. Turns off Vsupply, resets ADCs, DACs, and disables outputs
/// of pull resistor GPIO expanders. The latter three actions involve I2C requests and may fail,
/// but these failures are ignored.
///
/// Should be called after CPU reset.
void port_init();

/// Handle deferred tasks for nALERT low event.
void port_poll_alert();
