#include <fx2regs.h>
#include <fx2i2c.h>
#include <fx2lib.h>
#include <fx2delay.h>
#include "glasgow.h"

static uint16_t nop(uint16_t value) { return value; }

bool smbus_run(smbus_sequence *seq, uint8_t addr)
{
  bool success = true;
  smbus_xfrm_t xfrm = nop;
  addr <<= 1;
  while (success) {
    uint16_t insn = *(__xdata uint16_t*)seq++;
    uint8_t op = insn>>8, arg = insn;
    if (op == SMBUS_OP_DONE) {
      break;
    } else if (op == SMBUS_OP_ADDR) {
      addr = arg;
    } else if (op == SMBUS_OP_XFRM_WORD) {
      xfrm = *(smbus_xfrm_t __xdata *)seq++;
    } else {
      __xdata uint8_t *ptr = *(__xdata uint8_t* __xdata*)seq++;
      if ((op&0xf0) == 0x20) { // {WRITE,READ}_{BYTE,WORD}
        success = i2c_start(addr);
        success = success && i2c_write(&arg, 1);
      } else if (!(op&1)) { // {SEND,RECV}_{BYTE,WORD}
        success = i2c_start(addr);
      }
      if (op&1) { // {READ,RECV}
        success = success && i2c_start(addr|1);
        success = success && i2c_read(ptr, (op&2)?2:1);
        *(__xdata uint16_t*)ptr = xfrm(*(__xdata uint16_t*)ptr);
      } else { // {WRITE,SEND}
        *(__xdata uint16_t*)ptr = xfrm(*(__xdata uint16_t*)ptr);
        success = success && i2c_write(ptr, (op&2)?2:1);
        success = success && i2c_stop();
      }
      xfrm = nop;
    }
  }
  if (!success)
    i2c_stop();
  return success;
}

static smbus_sequence write_word_seq[] = {
  SM_WRITE_WORD(0, mgmt_req.smbus_write.data),
  SM_DONE(),
};

enum mgmt_result smbus_mgmt_write_word()
{
  *(__xdata uint8_t *)write_word_seq = mgmt_req.smbus_write.cmd;
  if (!smbus_run(write_word_seq, mgmt_req.smbus_write.addr))
    return RES_ERROR;
  return RES_ACK;
}

static smbus_sequence read_word_seq[] = {
  SM_READ_WORD(0, mgmt_rsp.smbus_read_data),
  SM_DONE(),
};

enum mgmt_result smbus_mgmt_read_word()
{
  *(__xdata uint8_t *)read_word_seq = mgmt_req.smbus_read.cmd;
  if (!smbus_run(read_word_seq, mgmt_req.smbus_read.addr))
    return RES_ERROR;
  return RES_ACK;
}
