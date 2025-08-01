VID      ?= 20b7
PID      ?= 9db1

CODE_SIZE = 0x3e00
XRAM_SIZE = 0x01c0
CONF_SIZE = 0x0040
MODEL     = medium

TARGET    = glasgow
SOURCES   = main fpga dac_ldo adc_adc081c adc_ina233 pull fifo util
LIBRARIES = fx2 fx2isrs fx2usb
CFLAGS    = --std=c23 -DSYNCDELAYLEN=16 -DCONF_SIZE=$(CONF_SIZE)

LIBFX2    = ../vendor/libfx2/firmware/library
include $(LIBFX2)/fx2rules.mk

# Embed the git revision of the last change to the firmware directory (not the repository as a whole!) into
# the firmware. This helps tracking down firmware issues since you can correlate `lsusb` output to git commit.
# If you are packaging the Glasgow software for distribution, you MUST ensure that the firmware you build is
# bit-for-bit identical with the firmware checked into the source tree as `software/glasgow/hardware/firmware.ihex`.
# To do so, you can run `make -C firmware GIT_REV_SHORT=<abbrev>` when building in an isolated environment.
#
# Make executes makefiles in two stages: first it builds a dependency graph and determines freshness, and then it
# starts to actually build the targets. By the time it starts to build, any updates to the freshness of files on
# disk will be ignored; therefore we need to build the `version.h` target during the first stage. In practical
# terms this is accomplished by building it as a part of an immediate assignment.
#
# Yes, this is awful. I am so proud of it =^_^=
GIT_REV_SHORT  ?= $(shell git log -1 --abbrev=8 --pretty=%h HEAD .)
$(if $(GIT_REV_SHORT),,$(error Failed to determine git revision))
ifneq ($(shell git diff-index --exit-code HEAD -- .),)
GIT_TREE_DIRTY  = .dirty
endif
VERSION_H_RULE := $(shell \
	echo "#define GIT_REVISION \"$(GIT_REV_SHORT)$(GIT_TREE_DIRTY)\"" >.version.h && \
	if ! diff -q .version.h version.h 2>/dev/null ; then mv .version.h version.h; else rm -f .version.h; fi \
)
