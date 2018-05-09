VID      ?= 20b7
PID      ?= 9db1

TARGET    = glasgow
SOURCES   = main leds fpga dac_ldo adc fifo
LIBRARIES = fx2 fx2isrs fx2usb
CFLAGS    = -DSYNCDELAYLEN=16

LIBFX2    = ../vendor/libfx2/firmware/library
include $(LIBFX2)/fx2rules.mk
