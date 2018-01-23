CODE_SIZE ?= 0x3e00
XRAM_SIZE ?= 0x0200

SDCCFLAGS  = \
	--iram-size 0x100 \
	--code-size $(CODE_SIZE) \
	--xram-loc  $(CODE_SIZE) \
	--xram-size $(XRAM_SIZE) \
	--std-sdcc99 \
	-I$(LIBFX2)/include \
	-L$(LIBFX2) -lfx2
ifeq ($(V),1)
SDCCFLAGS += -V
endif
SDCC       = sdcc -mmcs51 $(SDCCFLAGS)
