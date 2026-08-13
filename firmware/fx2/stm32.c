// Ref: Application note — Introduction to system memory boot mode on STM32 MCUs, §47
// Document Number: AN2606
// Accession: G00128
// Ref: Application note — I2C protocol used in the STM32 bootloader
// Document Number: AN4221
// Accession: G00129

#include <stddef.h>
#include <stdlib.h>
#include <fx2delay.h>
#include <fx2regs.h>
#include <fx2i2c.h>
#include <fx2lib.h>
#include "glasgow.h"

enum stm32_command: uint8_t {
  STM32_GET_VERSION  = 0x01, // "Get Version"
  STM32_GET_CHIP_ID  = 0x02, // "Get ID"
  STM32_READ_MEMORY  = 0x11, // "Read Memory"
  STM32_WRITE_MEMORY = 0x31, // "Write Memory"
  STM32_RUN_FIRMWARE = 0x21, // "Go"
};

enum stm32_response: uint8_t {
  STM32_ACK  = 0x79,
  STM32_NACK = 0x1F,
};

enum write_flags: uint8_t {
  WRITE_SINGLE_BYTE = 0x01,
  WRITE_PREFIX_SIZE = 0x02,
};

// Either "Send Command frame", a byte-sized "Send Data frame" with arguments for certain
// commands, or a general "Send Data frame".
static bool stm32_write(__xdata uint8_t *data, uint8_t size_m1, uint8_t flags)
{
  __xdata uint8_t checksum = (flags & WRITE_SINGLE_BYTE) ? 0xff : 0x00;
  if (!i2c_start((I2C_ADDR_STM32_BOOT_REVD<<1)|0))
    goto fail;
  if (flags & WRITE_PREFIX_SIZE) {
    checksum ^= size_m1;
    if (!i2c_write(&size_m1, 1))
      goto fail;
  }
  for (__xdata uint8_t *byte = data; byte != &data[size_m1 + 1]; byte++)
    checksum ^= *byte;
  if (!i2c_write(data, size_m1 + 1))
    goto fail;
  if (!i2c_write(&checksum, 1))
    goto fail;
  if (!i2c_stop())
    return false;
  return true;

fail:
  i2c_stop();
  return false;
}

// "ACK/NACK" frame.
static bool stm32_ack()
{
  __xdata uint8_t packet[1];

  if (!i2c_start((I2C_ADDR_STM32_BOOT_REVD<<1)|1))
    goto fail;
  if (!i2c_read(packet, sizeof(packet)))
    goto fail;
  return packet[0] == STM32_ACK;

fail:
  i2c_stop();
  return false;
}

static __xdata uint8_t stm32_write_memory_cmd = STM32_WRITE_MEMORY;
static __xdata uint8_t stm32_run_firmware_cmd = STM32_RUN_FIRMWARE;
static __xdata uint32_t stm32_addr_20001000 = 0x00'10'00'20;
static __xdata uint32_t stm32_addr_20001100 = 0x00'11'00'20;
static __xdata uint8_t stm32_shellcode[1] = {0};

struct stm32_boot_step {
  __xdata uint8_t *data;
  uint8_t size_m1;
  uint8_t flags;
};

#define STM32_COMMAND(command)       {&command, sizeof(command)-1, WRITE_SINGLE_BYTE}
#define STM32_ADDRESS(address)       {&address, sizeof(address)-1,                 0}
#define STM32_WR_DATA(data, size_m1) {&data,    size_m1,           WRITE_PREFIX_SIZE}
#define STM32_FINISH()               {NULL}

static __xdata struct stm32_boot_step stm32_boot_steps[] = {
  STM32_COMMAND(stm32_write_memory_cmd),
  STM32_ADDRESS(stm32_addr_20001000),
  STM32_WR_DATA(scratch[0x0000], 0x100-1),

  STM32_COMMAND(stm32_write_memory_cmd),
  STM32_ADDRESS(stm32_addr_20001100),
  STM32_WR_DATA(scratch[0x0100], 0x100-1),

  STM32_COMMAND(stm32_run_firmware_cmd),
  STM32_ADDRESS(stm32_addr_20001000),
  STM32_FINISH(),
};

__bit mcu_ready = false;

bool mcu_bootload()
{
  mcu_ready = false;
  IO_LED_ACT = 1;

  // Reset the STM32 and enter the bootloader.
  // Note that the `MCU_BOOT0_REVD` pin is the same as `LED_FX2` pin.
  IO_MCU_nRESET_REVD = 0;
  IO_MCU_BOOT0_REVD = 1;
  delay_ms(1);
  IO_MCU_nRESET_REVD = 1;
  delay_ms(1);
  IO_MCU_BOOT0_REVD = 0;

  // Unfortunately, scratch space cannot be written by the FX2 bootloader.
#if 0
  // Load blinky.
  const __code uint8_t shellcode[] =
  {
    0x00, 0x12, 0x00, 0x20, 0x09, 0x10, 0x00, 0x20, 0x09, 0x48, 0x0a, 0x49, 0x01, 0x60, 0x0a, 0x48,
    0x0a, 0x49, 0x01, 0x60, 0x0a, 0x48, 0x0b, 0x49, 0x01, 0x60, 0x0b, 0x48, 0x0b, 0x49, 0x01, 0x60,
    0x0a, 0x4b, 0x59, 0x40, 0x01, 0x60, 0x0a, 0x4a, 0x01, 0x3a, 0x00, 0x2a, 0xfc, 0xd1, 0xf7, 0xe7,
    0x34, 0x12, 0x00, 0x20, 0xee, 0xff, 0x00, 0xcc, 0x34, 0x10, 0x02, 0x40, 0x07, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x50, 0xf7, 0xff, 0xff, 0xeb, 0x14, 0x00, 0x00, 0x50, 0x02, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x08, 0x00,
  };
  xmemcpy(scratch, (__xdata void *)shellcode, sizeof(shellcode));
#else
  // Load firmware.
  if (!eeprom_xfer(I2C_ADDR_FX2_MEM, 0x5000, scratch, 0x200, /*write=*/false))
    return false;
#endif

  // Load the firmware with a table-driven mechanism to save code size.
  for (__xdata struct stm32_boot_step *step = stm32_boot_steps; step->data; *step++) {
    if (!stm32_write(step->data, step->size_m1, step->flags))
      goto exit;
    if (!stm32_ack())
      goto exit;
  }

  // Check that the firmware is actually running. The bootloader only acknowledges transfer status.
  delay_ms(1);
  if (!i2c_start((I2C_ADDR_STM32_APP_REVD<<1)|0)) {
    i2c_stop();
    goto exit;
  }

  // Yay, it worked!
  mcu_ready = true;

exit:
  IO_LED_ACT = 0;
  return mcu_ready;
}
