# Glasgow = Bus Pirate + Bus Blaster + Logic Sniffer

**Want one? [Subscribe here](https://mailchi.mp/44980ff6f0ab/glasgow-announcements)**

**Let's chat! [Our IRC channel is #glasgow at freenode.net](https://webchat.freenode.net/?channels=glasgow)**.

**Important note: if you are looking to assemble boards yourself, do NOT pick revA or revB unless you have a COMPLETE understanding of pitfalls associated with the FXMA level shifter.**

**Important note: if you are looking to assemble boards yourself, consider that revC0 has a serious issue related to configurable pull resistors, see [revC1 ECNs](https://github.com/GlasgowEmbedded/Glasgow/wiki/ECNs#revc1).**

The project is in an early stage. The description below is a 1-year-old design overview provided for reference. Some details have changed in the meantime, some things aren't yet implemented; once we have hardware that can be mass-produced I'll put more effort into coherent documentation--promise!

## Overview

Glasgow is a 50 MHz 1V8/2V5/3V3/3V6/5V0 bus multitool,
think [Bus Pirate](http://dangerousprototypes.com/docs/Bus_Pirate) + [Bus Blaster](http://dangerousprototypes.com/docs/Bus_Blaster) + [Logic Sniffer](http://dangerousprototypes.com/docs/Open_Bench_Logic_Sniffer)
all in one reconfigurable package.

You have 16 pins; put any of {JTAG,SWD,SPI,I2C,USART,…} on any of them, or even use your own protocol core on the FPGA!

The 16 pins are split among two fully independent ESD protected I/O banks with a DAC+LDO to set the I/O standard and/or power the target,
an ADC to sense the target voltage, an alert function to detect faults, and an intrinsic 100 mA current limit for added safety.

The PC interface has peak throughput of ~360 Mbps (bulk endpoints), so you can sample 16 channels at 22.5 Msps, 8 channels at 45 Msps, 4 channels at 90 Msps, and so on.
You can also download stuff via JTAG -really fast-; instead of bus turnarounds, just use a custom JTAG core.

The somewhat low sampling rate is compensated (for synchronous interfaces) by the fact that the FPGA is able to sample at a defined phase with respect to the interface clock;
so while normally you would need 200 Msps for a bus running at 50 MHz, with Glasgow mere 50 Msps are enough.

if you want one, once the hardware is proven I'll be selling these at an estimated $70 plus shipping.

in case you're wondering, this is basically a scaled down version of [azonenberg's](https://github.com/azonenberg) [STARSHIPRAIDER](https://github.com/azonenberg/starshipraider),
which does 32 channels at 500 MHz, has a 10 GbE host interface, and costs around $1K in BOM+PCB.
I didn't set out to do that but it turns out this design space is really narrow.

This project is a collaboration with [awygle](https://github.com/awygle), who has given invaluable advice on overall design, made all the symbols and footprints and is upstreaming them in KiCAD (the goal is using 100% upstream libraries).

~I think this is about as far as you can go while using only FOSS tool chains for firmware/gateware;
if I ever make a sequel for this board it'll be after [oe1cxw](https://github.com/cliffordwolf) finishes Series 7 bitstream reverse-engineering :)~ Glasgow revE will use an ECP5-5G FPGA, but this is a few years away.

(This README file transcribed from this twitter thread: https://twitter.com/whitequark/status/985040607864176640)

## Contributors

  * [@whitequark](https://github.com/whitequark) came up with the design, coordinates the project and implements most of gateware and software;
  * [@awygle](https://github.com/awygle) designed the power/analog port circuitry and helped with layout of revB;
  * [@marcan](https://github.com/marcan) improved almost every aspect of hardware for revC;
  * [@esden](https://github.com/esden) is handling batch manufacturing;
  * [@smunaut](https://github.com/smunaut) provided advice crucial for stability and performance of USB communication;
  * ... and many [other people](https://github.com/GlasgowEmbedded/Glasgow/graphs/contributors).

## License

_Glasgow_ is distributed under the terms of both 0-clause BSD license as well as Apache 2.0 license.

See [LICENSE-0BSD](LICENSE-0BSD.txt) and [LICENSE-Apache-2.0.txt](LICENSE-Apache-2.0.txt) for details.
