LIBFX2 = ../libfx2
include $(LIBFX2)/fx2fw.mk

PYTHONPATH = ../../software
export PYTHONPATH

all: glasgow.ihex

glasgow.ihex: build/main.rel
	$(SDCC) -o build/$@ $^
	@cp build/$@ $@

-include build/*.d
build/%.rel: %.c
	$(SDCC) -Wp,-MQ,$@,-MMD,build/$*.d -c -o $@ $<

clean:
	@rm -f build/* glasgow.ihex

load: glasgow.ihex
	python3 -m glasgow.fx2tool load $<

.PHONY: all clean load
