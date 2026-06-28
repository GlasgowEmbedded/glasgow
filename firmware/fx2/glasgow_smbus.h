#pragma once

// SMBus engine
enum smbus_opcode {
  SMBUS_OP_DONE       = 0x00,
  SMBUS_OP_ADDR       = 0x01,
  SMBUS_OP_XFRM_WORD  = 0x02,
  SMBUS_OP_SEND_BYTE  = 0x10,
  SMBUS_OP_SEND_WORD  = 0x12,
  SMBUS_OP_RECV_BYTE  = 0x11,
  SMBUS_OP_RECV_WORD  = 0x13,
  SMBUS_OP_WRITE_BYTE = 0x20,
  SMBUS_OP_WRITE_WORD = 0x22,
  SMBUS_OP_READ_BYTE  = 0x21,
  SMBUS_OP_READ_WORD  = 0x23,
};

typedef uint16_t (* smbus_xfrm_t)(uint16_t);

// This type has to be a `__xdata void *` because sdcc doesn't let you cast a function pointer
// to an `uint16_t` in a constant initializer.
typedef __xdata void *smbus_sequence;

#define SM_DONE()                  (__xdata void*)((SMBUS_OP_DONE<<8)) // aka NULL
#define SM_ADDR(addr)              (__xdata void*)((SMBUS_OP_ADDR<<8)|(uint8_t)(addr<<1))
#define SM_XFRM_WORD(func)         (__xdata void*)((SMBUS_OP_XFRM_WORD<<8)), (__xdata void*)&func
#define SM_SEND_BYTE(data)         (__xdata void*)((SMBUS_OP_SEND_BYTE<<8)), &data
#define SM_SEND_WORD(data)         (__xdata void*)((SMBUS_OP_SEND_WORD<<8)), &data
#define SM_RECV_BYTE(data)         (__xdata void*)((SMBUS_OP_RECV_BYTE<<8)), &data
#define SM_RECV_WORD(data)         (__xdata void*)((SMBUS_OP_RECV_WORD<<8)), &data
#define SM_WRITE_BYTE(cmd, data)   (__xdata void*)((SMBUS_OP_WRITE_BYTE<<8)|(uint8_t)cmd), &data
#define SM_WRITE_WORD(cmd, data)   (__xdata void*)((SMBUS_OP_WRITE_WORD<<8)|(uint8_t)cmd), &data
#define SM_READ_BYTE(cmd, data)    (__xdata void*)((SMBUS_OP_READ_BYTE<<8)|(uint8_t)cmd), &data
#define SM_READ_WORD(cmd, data)    (__xdata void*)((SMBUS_OP_READ_WORD<<8)|(uint8_t)cmd), &data

bool smbus_run(smbus_sequence *seq, uint8_t addr);
