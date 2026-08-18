//! This module implements the USB EP1 management protocol. This is the protocol used for all
//! device configuration except where standard USB methods (or Microsoft extensions) must be used
//! instead. The protocol is designed to be easy to tunnel over 64-byte EP1 buffers, as well as
//! encapsulate in a TCP/IP tunnel in the future.
//!
//! Many other modules contain functions with the signature of `enum mgmt_result ..._mgmt_...()`.
//! These functions are called by [mgmt_poll]. They implicitly take four parameters: `mgmt_req`,
//! `mgmt_req_len`, `mgmt_rsp`, `mgmt_rsp_len`. These parameters are passed via global variables
//! or predefined memory areas to significantly reduce code size.
//!
//! The management protocol framing (placeholders represent hex digits) is:
//!
//!     Host>Device: nn QQ [dd...]
//!     Device>Host: nn SS [ee...]
//!
//! Field definitions:
//! - `nn`: packet serial, an arbitrary number echoed back by the device
//!   - requests with serial `00` are rejected
//!   - response with serial `00` is unsolicited (here, `SS` is always `RES_ALERT`, at the moment)
//! - `QQ`: request code from `enum mgmt_request`
//! - `dd`: request data (opcode-specific)
//! - `SS`: result code from `enum mgmt_result`
//! - `ee`: result data (opcode-specific)
//!
//! Every request receives exactly one reply. Whenever possible, the reply always has the exact
//! same size regardless of the result code; this simplifies decoding. Error packets have everything
//! but the result code zeroed out. (For packets with variable length replies, if the request does
//! not include the length field, the returned error packet is sent as if length was 0.)
//!
//! Requests are processed in order, which is a part of the API contract. At the moment, they are
//! not pipelined (EP1IN buffer must be full and EP1OUT buffer must be empty for processing to
//! start), which is an implementation detail. The serial is provided mainly for convenience of
//! implementation of upper layers since requests are never reordered.
//!
//! The protocol specified here is a public interface. Within a single API level (high byte of
//! `bcdDevice` in the USB device descriptor), the protocol will never change. Between API levels,
//! the protocol may change in arbitrarily incompatible ways.

#pragma once

/// Request codes.
enum mgmt_request {
  REQ_DEBUG         = 0x01,
  // Board management
  REQ_WRITE_EEPROM  = 0x10,
  REQ_READ_EEPROM   = 0x11,
  // FPGA management
  REQ_FPGA_LOAD_CFG = 0x20,
  REQ_FPGA_LOAD_NVM = 0x21,
  REQ_FPGA_STATUS   = 0x22,
  REQ_FPGA_SET_REG  = 0x28,
  REQ_FPGA_GET_REG  = 0x29,
  // Port management
  REQ_SET_VSUPPLY   = 0x30,
  REQ_GET_VSUPPLY   = 0x31,
  REQ_SET_VLIMIT    = 0x32,
  REQ_GET_VLIMIT    = 0x33,
  REQ_SET_VALERT    = 0x34,
  REQ_GET_VALERT    = 0x35,
  REQ_SET_IALERT    = 0x36,
  REQ_GET_IALERT    = 0x37,
  REQ_GET_VSENSE    = 0x38,
  REQ_GET_ISUPPLY   = 0x39,
  REQ_SET_PULLS     = 0x3A,
  REQ_GET_PULLS     = 0x3B,
  REQ_GET_STATE     = 0x3C,
  // Analog measurements
  REQ_NAFE_SINGLE   = 0x40,
  // Alert handling
  REQ_GET_ALERTS    = 0xA0,
  REQ_CLR_ALERTS    = 0xA1,
  // Internal use only
  REQ_TEST_LEDS     = 0xF0,
  REQ_WRITE_SMBUS   = 0xF1,
  REQ_READ_SMBUS    = 0xF2,
};

/// Result codes.
enum mgmt_result {
  /// Indicates that an operation has failed. Currently, there is no way to retrieve the cause
  /// of the error; it could span anything from "parameter error" to "invalid state" to "hardware
  /// failure". Because of this information scarcity, request parameters should be validated before
  /// a request is issued (in most cases this can be done fully statically).
  RES_ERROR         = 0xff,

  /// Indicates that an operation has succeeded.
  RES_ACK           = 0x00,

  /// Indicates that an operation needs more time to complete. The **exact same** request **must**
  /// be repeated until either `RES_ERROR` or `RES_ACK` is returned, otherwise the behavior is
  /// unspecified (but side effects are constrained to foreseeable faults of the operation being
  /// executed).
  RES_WAIT          = 0x01,

  /// Indicates an unsolicited response. The payload has format [struct mgmt_alert].
  RES_ALERT         = 0x02, // unsolicited
};

struct mgmt_packet {
  uint8_t serial;
  union {
    enum mgmt_request request;
    enum mgmt_result  result;
  };
  union {
    // REQ_DEBUG
    uint16_t debug_addr;
    struct {
      char data[32];
    } debug;
    // REQ_WRITE_EEPROM
    struct {
      // request must be covered by one 32-byte aligned block
      uint16_t addr;
      uint8_t  data[32];
    } eeprom_write;
    // REQ_READ_EEPROM
    struct {
      uint16_t addr;
      uint8_t  len;
    } eeprom_read;
    uint8_t eeprom_read_data[32];
    // REQ_FPGA_LOAD_CFG
    // REQ_FPGA_LOAD_NVM
    // REQ_FPGA_STATUS
    struct {
      uint32_t size;
      uint8_t  id[CONFIG_SIZE_BITSTREAM_ID];
    } bitstream;
    // REQ_FPGA_LOAD_NVM (response)
    uint32_t load_progress;
    // REQ_FPGA_SET_REG
    struct {
      uint8_t addr;
      uint8_t data[32];
    } fpga_set;
    // REQ_FPGA_GET_REG
    struct {
      uint8_t addr;
      uint8_t len;
    } fpga_get;
    uint8_t fpga_reg_data[32];
    // REQ_SET_VSUPPLY
    // REQ_GET_VSUPPLY
    // REQ_SET_VLIMIT
    // REQ_GET_VLIMIT
    // REQ_SET_IALERT
    // REQ_GET_IALERT
    // REQ_GET_VSENSE
    // REQ_GET_ISUPPLY
    struct {
      uint8_t mask;
      // in millivolts, 0 means disabled
      uint16_t value[4];
    } vsupply, vlimit, ialert, vsense, isense;
    // REQ_SET_VALERT
    // REQ_GET_VALERT
    struct {
      uint8_t mask;
      // range in millivolts, 0 means disabled
      struct {
        uint16_t low;
        uint16_t high;
      } value[4];
    } valert;
    // REQ_SET_PULLS
    // REQ_GET_PULLS
    struct {
      uint8_t mask;
      // down=1 up=1 means "preserve" in SET_PULLS, never appears in GET_PULLS
      struct {
        uint8_t down;
        uint8_t up;
      } value[4];
    } pulls;
    // REQ_GET_STATE
    struct {
      uint8_t mask;
      uint8_t value[4];
    } state;
    // REQ_NAFE_SINGLE
    struct {
      enum nafe_input {
        NAFE_INPUT_GND = 0,
        NAFE_INPUT_AI1 = 1,
        NAFE_INPUT_AI2 = 2,
        NAFE_INPUT_AI3 = 3,
        NAFE_INPUT_AI4 = 4,
        NAFE_INPUT_REFH = 5,
        NAFE_INPUT_REFL = 6,
        NAFE_INPUT_AICOM = 7,
      } in_pos, in_neg;
      uint8_t rate_filt;
    } nafe_single;
    struct {
      int32_t value;
      enum nafe_gain {
        NAFE_GAIN_0_2X = 0,
        NAFE_GAIN_0_4X = 1,
        NAFE_GAIN_0_8X = 2,
      } gain;
    } nafe_single_data;
    // REQ_GET_ALERTS
    // REQ_CLR_ALERTS
    struct mgmt_alert {
      uint8_t realtime; // actually [bool]
      uint8_t ports[4]; // actually [enum port_alerts]
      uint8_t fpga;
    } alert;
    // REQ_TEST_LEDS
    struct {
      uint8_t enabled;
      uint8_t state;
    } test_leds;
    // REQ_WRITE_SMBUS
    struct {
      uint8_t  addr;
      uint8_t  cmd;
      uint16_t data;
    } smbus_write;
    // REQ_READ_SMBUS
    struct {
      uint8_t  addr;
      uint8_t  cmd;
    } smbus_read;
    uint16_t smbus_read_data;
  };
};

/// Request and response packet buffers. To reduce code size, the packet buffers are overlaid
/// with the EP1IN and EP1OUT MMIO areas, as this allows most pointers into these buffers to be
/// compile-time constant. Note that these areas can only be accessed while owned by the CPU,
/// otherwise the behavior is undefined. (In practice I think this can at worst corrupt packets.)
///
/// These objects are implicit arguments for all management handlers.
__xdata __at(/*EP1OUTBUF*/0xe780) struct mgmt_packet mgmt_req;
__xdata __at(/*EP1INBUF */0xe7c0) struct mgmt_packet mgmt_rsp;

/// Request and response packet lengths.
///
/// These variables are implicit arguments for all management handlers.
extern __data uint8_t mgmt_req_len, mgmt_rsp_len;

/// Alert status. When handling the nALERT assertion, relevant alert bits in this structure are set
/// and [alert_pending] is set as well. On the next [mgmt_poll] call, a [RES_ALERT] unsolicited
/// result will be sent, and [alert_pending] is cleared.
extern __xdata struct mgmt_alert alert;
extern __bit alert_pending;

/// Initialize the management interface. Configures EP1IN/OUT and aborts any ongoing transaction.
///
/// Should be called after CPU reset, or when the management interface is reset via
/// "Set Configuration" or "Set Interface" standard USB requests.
void mgmt_init();

/// Handle deferred tasks for the management interface.
///
/// Precondition: `IFACE_MGMT` has mode `EP_MODE_ON`.
void mgmt_poll();
