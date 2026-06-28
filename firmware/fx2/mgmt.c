#include <fx2regs.h>
#include <fx2delay.h>
#include <fx2lib.h>
#include "glasgow.h"

__data uint8_t mgmt_req_len, mgmt_rsp_len;

enum mgmt_result nvmem_mgmt_write_eeprom();
enum mgmt_result nvmem_mgmt_read_eeprom();
enum mgmt_result fpga_mgmt_load_cfg();
enum mgmt_result fpga_mgmt_load_nvm();
enum mgmt_result fpga_mgmt_status();
enum mgmt_result fpga_mgmt_set_reg();
enum mgmt_result fpga_mgmt_get_reg();
enum mgmt_result port_mgmt_get_vsupply();
enum mgmt_result port_mgmt_set_vsupply();
enum mgmt_result port_mgmt_set_vlimit();
enum mgmt_result port_mgmt_get_vlimit();
enum mgmt_result port_mgmt_set_valert();
enum mgmt_result port_mgmt_get_valert();
enum mgmt_result port_mgmt_set_ialert();
enum mgmt_result port_mgmt_get_ialert();
enum mgmt_result port_mgmt_get_vsense();
enum mgmt_result port_mgmt_get_isense();
enum mgmt_result port_mgmt_set_pulls();
enum mgmt_result port_mgmt_get_pulls();
enum mgmt_result port_mgmt_get_state();
enum mgmt_result mgmt_get_alerts();
enum mgmt_result mgmt_clr_alerts();
enum mgmt_result leds_mgmt_test();
enum mgmt_result smbus_mgmt_write_word();
enum mgmt_result smbus_mgmt_read_word();
enum mgmt_result mgmt_debug();

typedef __xdata struct {
  enum mgmt_request type;
  uint8_t req_len;
  uint8_t rsp_len;
  enum mgmt_result (*handler)();
} mgmt_command;

static const mgmt_command commands[] = {
  {
    .type    = REQ_SET_VSUPPLY,
    .req_len = sizeof(mgmt_req.vsupply),
    .handler = port_mgmt_set_vsupply,
  },
  {
    .type    = REQ_GET_VSUPPLY,
    .rsp_len = sizeof(mgmt_rsp.vsupply),
    .handler = port_mgmt_get_vsupply,
  },
  {
    .type    = REQ_SET_VLIMIT,
    .req_len = sizeof(mgmt_req.vlimit),
    .handler = port_mgmt_set_vlimit,
  },
  {
    .type    = REQ_GET_VLIMIT,
    .rsp_len = sizeof(mgmt_rsp.vlimit),
    .handler = port_mgmt_get_vlimit,
  },
  {
    .type    = REQ_SET_VALERT,
    .req_len = sizeof(mgmt_req.valert),
    .handler = port_mgmt_set_valert,
  },
  {
    .type    = REQ_GET_VALERT,
    .rsp_len = sizeof(mgmt_rsp.valert),
    .handler = port_mgmt_get_valert,
  },
  {
    .type    = REQ_SET_IALERT,
    .req_len = sizeof(mgmt_req.ialert),
    .handler = port_mgmt_set_ialert,
  },
  {
    .type    = REQ_GET_IALERT,
    .rsp_len = sizeof(mgmt_rsp.ialert),
    .handler = port_mgmt_get_ialert,
  },
  {
    .type    = REQ_GET_VSENSE,
    .rsp_len = sizeof(mgmt_rsp.vsense),
    .handler = port_mgmt_get_vsense,
  },
  {
    .type    = REQ_GET_ISUPPLY,
    .rsp_len = sizeof(mgmt_rsp.isense),
    .handler = port_mgmt_get_isense,
  },
  {
    .type    = REQ_SET_PULLS,
    .req_len = sizeof(mgmt_req.pulls),
    .handler = port_mgmt_set_pulls,
  },
  {
    .type    = REQ_GET_PULLS,
    .rsp_len = sizeof(mgmt_rsp.pulls),
    .handler = port_mgmt_get_pulls,
  },
  {
    .type    = REQ_GET_STATE,
    .rsp_len = sizeof(mgmt_rsp.state),
    .handler = port_mgmt_get_state,
  },
  {
    .type    = REQ_FPGA_LOAD_CFG,
    .req_len = sizeof(mgmt_rsp.bitstream),
    .handler = fpga_mgmt_load_cfg,
  },
  {
    .type    = REQ_FPGA_LOAD_NVM,
    .req_len = sizeof(mgmt_rsp.bitstream),
    .rsp_len = sizeof(mgmt_rsp.load_progress),
    .handler = fpga_mgmt_load_nvm,
  },
  {
    .type    = REQ_FPGA_STATUS,
    .rsp_len = sizeof(mgmt_rsp.bitstream),
    .handler = fpga_mgmt_status,
  },
  {
    .type    = REQ_FPGA_SET_REG,
    .req_len = MGMT_LEN_VARY,
    .handler = fpga_mgmt_set_reg,
  },
  {
    .type    = REQ_FPGA_GET_REG,
    .req_len = sizeof(mgmt_req.fpga_get),
    .rsp_len = MGMT_LEN_VARY,
    .handler = fpga_mgmt_get_reg,
  },
  {
    .type    = REQ_WRITE_EEPROM,
    .req_len = MGMT_LEN_VARY,
    .handler = nvmem_mgmt_write_eeprom,
  },
  {
    .type    = REQ_READ_EEPROM,
    .req_len = sizeof(mgmt_req.eeprom_read),
    .rsp_len = MGMT_LEN_VARY,
    .handler = nvmem_mgmt_read_eeprom,
  },
  {
    .type    = REQ_GET_ALERTS,
    .rsp_len = sizeof(mgmt_rsp.alert),
    .handler = mgmt_get_alerts,
  },
  {
    .type    = REQ_CLR_ALERTS,
    .req_len = sizeof(mgmt_req.alert),
    .handler = mgmt_clr_alerts,
  },
  {
    .type    = REQ_TEST_LEDS,
    .req_len = sizeof(mgmt_req.test_leds),
    .handler = leds_mgmt_test,
  },
  {
    .type    = REQ_WRITE_SMBUS,
    .req_len = sizeof(mgmt_req.smbus_write),
    .handler = smbus_mgmt_write_word,
  },
  {
    .type    = REQ_READ_SMBUS,
    .req_len = sizeof(mgmt_req.smbus_read),
    .rsp_len = sizeof(mgmt_rsp.smbus_read_data),
    .handler = smbus_mgmt_read_word,
  },
  {
    .type    = REQ_DEBUG,
    .req_len = sizeof(mgmt_req.debug_addr),
    .rsp_len = sizeof(mgmt_rsp.debug),
    .handler = mgmt_debug,
  },
  { /*terminator*/ },
};

void mgmt_init() {
  SYNCDELAY;
  EP1OUTCFG = _VALID|_TYPE1; // EP1OUT BULK
  SYNCDELAY;
  EP1INCFG  = _VALID|_TYPE1; // EP1IN  BULK
  SYNCDELAY;
  EP1OUTBC  = 0;             // arm EP1OUT
  SYNCDELAY;
  EP1INCS   = _BUSY;         // force disarm EP1IN
}

void mgmt_poll()
{
  if (EP01STAT & _EP1INBSY)
    return; // EP1IN still full

  // Sending unsolicited alert packets takes priority over command processing.
  if (alert_pending) {
    alert_pending = false;

    mgmt_rsp.serial = 0x00;
    mgmt_rsp.result = RES_ALERT;
    mgmt_get_alerts();
    mgmt_rsp_len = sizeof(mgmt_rsp.alert);
    goto enqueue;
  }

  if (EP01STAT & _EP1OUTBSY)
    return; // EP1OUT empty
  if (EP1OUTBC < 2)
    goto error_pkt; // too small for a header
  if (mgmt_req.serial == 0)
    goto error_pkt; // reserved for notifications

  xmemclr(&mgmt_rsp, sizeof(mgmt_rsp));

  mgmt_req_len = EP1OUTBC - 2;
  mgmt_rsp_len = 0;

  const mgmt_command *command = commands;
  while (command->handler) {
    if (command->type != mgmt_req.request) {
      command++;
      continue;
    }
    if (command->req_len != MGMT_LEN_VARY && command->req_len != mgmt_req_len)
      goto error_pkt;
    if (command->rsp_len != MGMT_LEN_VARY)
      mgmt_rsp_len = command->rsp_len;
    mgmt_rsp.result = command->handler();
    goto send_pkt;
  }
  // if not found: fallthrough to error_pkt

error_pkt:
  mgmt_rsp.result = RES_ERROR;
send_pkt:
  mgmt_rsp.serial = mgmt_req.serial;
  SYNCDELAY;
  EP1OUTBC = 0; // rearm
enqueue:
  SYNCDELAY;
  EP1INBC  = 2 + mgmt_rsp_len;
}

// ================================================================================================

__xdata struct mgmt_alert alert;
__bit alert_pending;

enum mgmt_result mgmt_get_alerts()
{
  xmemcpy(&mgmt_rsp.alert, &alert, sizeof(alert));
  return RES_ACK;
}

enum mgmt_result mgmt_clr_alerts()
{
  bool any_ports = false;
  for (uint8_t chan = 0; chan < 4; chan++) {
    alert.ports[chan] &= ~mgmt_req.alert.ports[chan];
    if (alert.ports[chan])
      any_ports = true;
  }
  if (!test_leds && !any_ports)
    IO_LED_ERR = 0;
  alert.fpga &= ~mgmt_req.alert.fpga;
  return RES_ACK;
}

enum mgmt_result mgmt_debug()
{
  xmemcpy((__xdata void *)mgmt_rsp.debug, (__xdata void *)mgmt_req.debug_addr,
          sizeof(mgmt_rsp.debug));
  return RES_ACK;
}
