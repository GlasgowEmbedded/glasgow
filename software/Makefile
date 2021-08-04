all:
	$(MAKE) -C ../vendor/libfx2/firmware/library all
	$(MAKE) -C ../firmware all
	cp ../firmware/glasgow.ihex glasgow/device/firmware.ihex

clean:
	$(MAKE) -C ../vendor/libfx2/firmware/library clean
	$(MAKE) -C ../firmware clean
	rm glasgow/device/firmware.ihex

.PHONY: all clean
