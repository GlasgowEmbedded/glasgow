//! This module implements the SMBus microcode engine.
//!
//! Glasgow heavily uses I2C, and most I2C devices are SMBus-compliant (see [glasgow_i2c.h] for
//! details). Most management tasks using these devices can be expressed as an SMBus operation
//! sequence with minimal setup/teardown code. "Microcoding" these operation sequences (i.e.
//! expressing them as ROM tables of specialized instructions rather than C functions) allows
//! dramatic decreases of code size; without using this technique, it would not be possible to fit
//! revABCD firmwares in the same 16K RAM block and maintain a unified firmware image.
//!
//! A few of the defined operations are not present in the SMBus specification and are
//! straightforward extensions of the defined protocols. These are called out as nonstandard.

#pragma once

/// SMBus operation codes. These codes are a private implementation detail of the SMBus engine
/// and are only defined in this header because they have to be referenced in the ROM tables.
///
/// Note that `0x1?` and `0x2?` opcodes are implemented by decomposing them into a bit mask that
/// is not explicitly defined anywhere here.
enum {
  _SMBUS_OP_DONE       = 0x00,
  _SMBUS_OP_ADDR       = 0x01,
  _SMBUS_OP_XFRM_WORD  = 0x02,
  _SMBUS_OP_SEND_BYTE  = 0x10,
  _SMBUS_OP_SEND_WORD  = 0x12,
  _SMBUS_OP_RECV_BYTE  = 0x11,
  _SMBUS_OP_RECV_WORD  = 0x13,
  _SMBUS_OP_WRITE_BYTE = 0x20,
  _SMBUS_OP_WRITE_WORD = 0x22,
  _SMBUS_OP_READ_BYTE  = 0x21,
  _SMBUS_OP_READ_WORD  = 0x23,
};

/// Pointer to a transformation function. See [SM_XFRM_WORD].
typedef uint16_t (* smbus_xfrm_t)(uint16_t);

/// Pointer to an SMBus microcoded operation sequence.
///
/// This type has to be a `__xdata void *` because sdcc doesn't let you cast a function pointer
/// to an `uint16_t` in a constant initializer. It cannot be a discriminated union because sdcc
/// will attempt to initialize every field of a union, erasing the values of all but the last field
/// (with zero if no initializer is explicitly specified). It cannot be a constant because in some
/// cases, the sequence itself must be modified before execution (in cases where the microcode
/// engine does not offer enough parameterizability as-is.)
///
/// The first `__xdata` refers to the location of `&data` pointers. The second `__xdata` refers to
/// the location of the variable of type `smbus_sequence` itself. Both of these pointers never
/// have to point anywhere but XRAM, and using `movx` directly greatly decreases code size.
typedef __xdata void *__xdata smbus_sequence;

/// Exit sequence. This operation must be the last in every sequence.
#define SM_DONE()                  (__xdata void*)((_SMBUS_OP_DONE<<8)) // aka NULL

/// Set address. Configures engine to communicate with SMBus device `addr` (an unshifted I2C
/// address as an integer literal) from this point onwards.
#define SM_ADDR(addr)              (__xdata void*)((_SMBUS_OP_ADDR<<8)|(uint8_t)(addr<<1))

/// Set transformation function. Configures engine to transform the payload of the next operation
/// using `func` (name of a function with signature [smbus_xfrm_t]). This happens before a write
/// operation, or after a read operation. The subsequent operations do not use `func`, and
/// `SM_XFRM_WORD(func)` has to be used again if this is desired.
///
/// Note: while [smbus_xfrm_t] accepts a 16-bit argument, it can also be used for `BYTE` variants.
/// In this case, the high byte of the argument **must be preserved** by `func`. No separate 8-bit
/// and 16-bit variants are provided to reduce code size.
#define SM_XFRM_WORD(func)         (__xdata void*)((_SMBUS_OP_XFRM_WORD<<8)), (__xdata void*)&func

/// Perform SMBus "Send Byte" protocol with `data` (name of an `__xdata uint8_t` object).
#define SM_SEND_BYTE(data)         (__xdata void*)((_SMBUS_OP_SEND_BYTE<<8)), &data

/// Perform SMBus "Receive Byte" protocol with `data` (name of an `__xdata uint8_t` object).
#define SM_RECV_BYTE(data)         (__xdata void*)((_SMBUS_OP_RECV_BYTE<<8)), &data

/// Perform non-standard "Send Word" protocol (an extension of "Send Byte" protocol with
/// 16-bit, little endian payloda) with `data` (name of an `__xdata uint16_t` object).
#define SM_SEND_WORD(data)         (__xdata void*)((_SMBUS_OP_SEND_WORD<<8)), &data

/// Perform non-standard "Receive Word" protocol (an extension of "Receive Byte" protocol with
/// 16-bit, little endian payloda) with `data` (name of an `__xdata uint16_t` object).
#define SM_RECV_WORD(data)         (__xdata void*)((_SMBUS_OP_RECV_WORD<<8)), &data

/// Perform SMBus "Write Byte" protocol with `data` (name of an `__xdata uint8_t` object).
#define SM_WRITE_BYTE(cmd, data)   (__xdata void*)((_SMBUS_OP_WRITE_BYTE<<8)|(uint8_t)cmd), &data

/// Perform SMBus "Write Word" protocol with `data` (name of an `__xdata uint16_t` object).
#define SM_WRITE_WORD(cmd, data)   (__xdata void*)((_SMBUS_OP_WRITE_WORD<<8)|(uint8_t)cmd), &data

/// Perform SMBus "Read Byte" protocol with `data` (name of an `__xdata uint8_t` object).
#define SM_READ_BYTE(cmd, data)    (__xdata void*)((_SMBUS_OP_READ_BYTE<<8)|(uint8_t)cmd), &data

/// Perform SMBus "Read Word" protocol with `data` (name of an `__xdata uint16_t` object).
#define SM_READ_WORD(cmd, data)    (__xdata void*)((_SMBUS_OP_READ_WORD<<8)|(uint8_t)cmd), &data

/// Execute SMBus operation sequence `seq`, and return whether the operation succeeded. Failure
/// is normally detected only if the I2C address write or I2C data write are not acknowledged.
/// While the I2C start and stop conditions may return errors architecturally, this is not expected
/// to actually happen in Glasgow.
///
/// On failure, all subsequent operations are skipped, the bus transaction is terminated with
/// a stop condition, if applicable, and `false` is returned; `true` is returned otherwise.
///
/// Be very careful with pointers in SMBus operation sequences. An unsound address space cast can
/// result in unintentional writes to a difficult-to-predict memory area and corrupt executable
/// code or important data. Make sure all referenced data is declared as `__xdata type var;`.
bool smbus_run(smbus_sequence *seq, uint8_t addr);
