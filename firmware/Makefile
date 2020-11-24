VID      ?= 20b7
PID      ?= 9db1

CODE_SIZE = 0x3e00
XRAM_SIZE = 0x01c0
CONF_SIZE = 0x0040
MODEL     = medium

TARGET    = glasgow
SOURCES   = main fpga dac_ldo adc pull fifo
LIBRARIES = fx2 fx2isrs fx2usb
CFLAGS    = -DSYNCDELAYLEN=16 -DCONF_SIZE=$(CONF_SIZE)

LIBFX2    = ../vendor/libfx2/firmware/library
include $(LIBFX2)/fx2rules.mk
