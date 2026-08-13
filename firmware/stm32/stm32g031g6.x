OUTPUT_FORMAT(elf32-littlearm)

MEMORY
{
	/* Low half of the RAM is used by the bootloader and not writable via I2C. */
	RAM (RWX) : ORIGIN = 0x20001000, LENGTH = 0x1000
}

SECTIONS {
	.ram : {
		*(.init)
		. = ALIGN(4);

		*(.text .text.*)
		. = ALIGN(4);

		*(.rodata .rodata.*)
		. = ALIGN(4);

		*(.data .data.*)
		. = ALIGN(4);

		*(.bss .bss.*)
		*(COMMON)
		. = ALIGN(4);

		__stack_end = ORIGIN(RAM) + LENGTH(RAM) - 4;
	}

	/DISCARD/ : {
		*(.comment)
		*(.ARM.attributes)
	}
}
