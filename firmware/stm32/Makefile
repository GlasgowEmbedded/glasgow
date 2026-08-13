CFLAGS  = --std=c23 -mcpu=cortex-m0 -ffreestanding -nostdlib -fno-builtin
CFLAGS += -Os -ffunction-sections -Wall -Wextra

firmware.elf firmware.bin: reset.s stdlib.c main.c stm32g031g6.x
	mkdir -p build
	arm-none-eabi-gcc $(CFLAGS) $(filter-out %.x,$^) -T$(filter %.x,$^) -o firmware.elf
	arm-none-eabi-size firmware.elf
	arm-none-eabi-objcopy -O binary firmware.elf firmware.bin

all: firmware.bin

clean:
	rm -f firmware.elf firmware.bin

.PHONY: clean all
