SDCC = sdcc -mmcs51 -Iinclude
SDAS = sdas8051 -plo
SDAR = sdar rc

# core interrupts
DEFISRS  = \
	IE0 TF0 IE1 TF1 RI_TI_0 TF2 RESUME RI_TI_1 I2C IE5 IE6
# USB autovectored interrupts
DEFAUTOISRS += \
	SUDAV SOF SUTOK SUSPEND USBRESET HISPEED \
	EP0ACK EP0IN EP0OUT EP1IN EP1OUT EP2 EP4 EP6 EP8 \
	IBN EP0PING EP1PING EP2PING EP4PING EP6PING EP8PING \
	ERRLIMIT EP2ISOERR EP4ISOERR EP6ISOERR EP8ISOERR
# GPIF autovectored interrupts
DEFAUTOISRS += \
	EP2PF EP4PF EP6PF EP8PF \
	EP2EF EP4EF EP6EF EP8EF \
	EP2FF EP4FF EP6FF EP8FF GPIFDONE GPIFWF

OBJECTS = \
	autovec.rel \
	$(patsubst %,defisr_%.rel,$(DEFISRS)) \
	$(patsubst %,defautoisr_%.rel,$(DEFAUTOISRS))

fx2.lib: $(addprefix build/,$(OBJECTS))
	$(SDAR) $@ $^

build/%.rel: %.c
	$(SDCC) -c -o $@ $<

build/%.rel: %.asm
	$(SDAS) $@ $<

build/defisr_%.rel: defisr.c
	$(SDCC) -c -o $@ $< -DISRNAME=isr_$* -DINTNAME=_INT_$*

build/defautoisr_%.rel: defautoisr.c
	$(SDCC) -c -o $@ $< -DISRNAME=isr_$*

all: fx2.lib

clean:
	@rm -f build/* fx2.lib

.PHONY: all clean
