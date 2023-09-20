VID      ?= 20b7
PID      ?= 9db1

CODE_SIZE = 0x3e00
XRAM_SIZE = 0x01c0
CONF_SIZE = 0x0040
MODEL     = medium

TARGET    = glasgow
SOURCES   = main fpga dac_ldo adc_adc081c adc_ina233 pull fifo util
LIBRARIES = fx2 fx2isrs fx2usb
CFLAGS    = -DSYNCDELAYLEN=16 -DCONF_SIZE=$(CONF_SIZE)

LIBFX2    = ../vendor/libfx2/firmware/library
include $(LIBFX2)/fx2rules.mk

# Make executes makefiles in two stages: first it builds a dependency graph and determines freshness, and then it
# starts to actually build the targets. By the time it starts to build, any updates to the freshness of files on
# disk will be ignored; therefore we need to build the `version.h` target during the first stage. In practical
# terms this is accomplished by building it as a part of an immediate assignment.
#
# Yes, this is awful. I am so proud of it =^_^=
GIT_REV_SHORT   = $(shell git log -1 --abbrev=8 --pretty=%h HEAD .)
ifneq ($(shell git diff-index --exit-code HEAD -- .),)
GIT_TREE_DIRTY  = .dirty
endif
VERSION_H_RULE := $(shell \
	echo "#define GIT_REVISION \"$(GIT_REV_SHORT)$(GIT_TREE_DIRTY)\"" >.version.h && \
	if ! diff -q .version.h version.h 2>/dev/null ; then mv .version.h version.h; else rm -f .version.h; fi \
)
