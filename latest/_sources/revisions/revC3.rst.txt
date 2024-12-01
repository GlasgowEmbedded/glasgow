Technical description (revC3)
=============================

This document provides a technical description of the Glasgow revC3 hardware.


.. _revC3-power:

Power
-----

Glasgow is powered by its USB-C connection. The input voltage is 5.0 V and the typical operating current is 500 mA or less. For reliable and safe operation we recommend that you power Glasgow from a standard USB port capable of providing at least 1.0 A at 5.0 V.

Some non-standards-compliant USB ports, such as those found on certain powered USB hubs, may provide more than 3.0 A of current at 5.0 V on their ports without active negotiation. While powering Glasgow from these ports is absolutely fine under all but the rarest circumstances, such non-compliant high-current USB power sources may not implement proper overcurrent protection. Such supplies carry a greater risk of damage to the board and its components in the rare event that the USB-C connector on Glasgow becomes damaged and a short develops between VBUS and GND. Shorts anywhere elsewhere on the board should be protected by overcurrent detection and protection features built into Glasgow's design. These protection features are discussed elsewhere in this document.

Since Glasgow draws less than 1.0 A of current at all times, it does not benefit from non-standards-compliant high-current USB ports.

The USB-C connector shield is connected to ground via a 100 nF capacitor and 100 kΩ resistor in parallel. The plated mounting holes in the four corners of the board are grounded.


.. _revC3-5v-rail:

+5V rail
~~~~~~~~

The +5V rail is the input power rail for Glasgow. You can measure this rail using the 5V test points on the front and rear of the board.

The +5V rail is derived from VUSB without additional regulation - as such, you should expect some variance in the +5V rail voltage depending on the power source and USB cable that you are using.

A BLM15PX601SZ1 ferrite bead (FB1) is inserted in series with VUSB with the intention of reducing conducted emissions onto the USB cable. Its maximum DC series resistance is 230 mΩ and its impedance at 100 MHz is 600 Ω. This ferrite bead also acts as a makeshift fuse in the event that either U15 or C8 fail short and the upstream USB supply does not implement proper overcurrent protection.

A TPD3S014 current limit switch IC (U15) is inserted between VUSB and the +5V rail, and enforces a maximum current of 850 mA. There is a 150 uF aluminium electrolytic capacitor on the +5V rail for bulk decoupling and brownout protection. As such, you should expect up to 850 mA of inrush current for a brief period when you plug Glasgow in. Continuous operating current should not exceed 500 mA under normal circumstances.

The +5V rail is monitored by an APX811-40UG-7 supervisor IC. The supervisor has a nominal undervoltage threshold of 4.0 V. If the +5V rail drops below this threshold, the +3.3V regulator is disabled and ``CY_RESET`` is asserted to hold the Cypress FX2 USB controller IC (U1) in a reset state.

The +5V rail is used to power the following devices:

+------------+----------------+--------------------------------------------------------------+
| Designator | Part           | Function / Notes                                             |
+============+================+==============================================================+
| U7         | APX811-40UG-7  | +5V rail supervisor and reset (triggered by reset button)    |
+------------+----------------+--------------------------------------------------------------+
| U8         | TLV75533PDRVR  | 3.3 V, 500 mA linear regulator for generating +3.3V rail     |
+------------+----------------+--------------------------------------------------------------+
| U36        | TLV73312PQDRVR | 1.2 V, 300 mA linear regulator for generating +1.2V rail     |
+------------+----------------+--------------------------------------------------------------+
| U31        | TPS73101DBV    | Adjustable linear regulator for generating VIO on port A     |
+------------+----------------+--------------------------------------------------------------+
| U14        | TPS73101DBV    | Adjustable linear regulator for generating VIO on port B     |
+------------+----------------+--------------------------------------------------------------+


.. _revC3-3v3-rail:

+3.3V rail
~~~~~~~~~~

The +3.3V rail is used to power most ICs on the board. You can measure this rail using the 3V3 test points on the front and rear of the board. The green PWR LED on the front of the board is powered by the +3.3V rail.

The +3.3V rail is derived from the +5V rail using a TLV75533PDRVR linear voltage regulator (U8). The regulator has a maximum output current of 500 mA. The regulator's EN pin is driven by an APX811-40UG-7 supervisor IC (U7) which monitors the +5V rail for stability; in the event that the +5V rail does not meet the required threshold, U7's reset signal will disable the +3.3V regulator.

The +3.3V rail is used to power the following devices:

+----------------------------------------+------------------+-------------------------------------------------------------------------------------------------+
| Designator                             | Part             | Function / Notes                                                                                |
+========================================+==================+=================================================================================================+
| D1                                     | NCD0603G1        | Green "PWR" LED on front of board                                                               |
+----------------------------------------+------------------+-------------------------------------------------------------------------------------------------+
| U1                                     | CY7C68013A-56LTX | Cypress FX2 HS USB controller. +3.3V rail powers VCC, AVCC                                      |
+----------------------------------------+------------------+-------------------------------------------------------------------------------------------------+
| U2                                     | CAT24M01X        | I2C 1Mbit serial EEPROM for iCE40                                                               |
+----------------------------------------+------------------+-------------------------------------------------------------------------------------------------+
| U3                                     | BL24C256A-SFRC   | I2C 256Kbit serial EEPROM for FX2                                                               |
+----------------------------------------+------------------+-------------------------------------------------------------------------------------------------+
| U5                                     | PCA6408APW       | I2C I/O expander for programmable pullup/pulldown resistors on port B. +3.3V powers I2C supply  |
+----------------------------------------+------------------+-------------------------------------------------------------------------------------------------+
| U4, U6, U9, U10, U11, U16, U17, U18    | SN74LVC1T45DCKR  | Logic level translators for port A. +3.3V powers internal side (VCCA)                           |
+----------------------------------------+------------------+-------------------------------------------------------------------------------------------------+
| U12                                    | INA233           | Voltage/current measurement IC for port B.                                                      |
+----------------------------------------+------------------+-------------------------------------------------------------------------------------------------+
| U13                                    | DAC081C081CIMK   | I2C DAC for programming VIO voltage on port B.                                                  |
+----------------------------------------+------------------+-------------------------------------------------------------------------------------------------+
| U19                                    | PCA6408APW       | I2C I/O expander for programmable pullup/pulldown resistors on port A. +3.3V powers I2C supply  |
+----------------------------------------+------------------+-------------------------------------------------------------------------------------------------+
| U20                                    | DAC081C081CIMK   | I2C DAC for programming VIO voltage on port A                                                   |
+----------------------------------------+------------------+-------------------------------------------------------------------------------------------------+
| U21                                    | INA233           | Voltage/current measurement IC for port A.                                                      |
+----------------------------------------+------------------+-------------------------------------------------------------------------------------------------+
| U22, U23, U24, U25, U26, U27, U28, U29 | SN74LVC1T45DCKR  | Logic level translators for port B. +3.3V powers internal side (VCCA)                           |
+----------------------------------------+------------------+-------------------------------------------------------------------------------------------------+
| U30                                    | ICE40HX8K-BG121  | iCE40 FPGA. +3.3V rail powers VCCIO_x, VPP_2V5, VCC_SPI                                         |
+----------------------------------------+------------------+-------------------------------------------------------------------------------------------------+
| U32                                    | SN74LVC1T45DCKR  | Logic level translator for SYNC input/output connector. +3.3V powers internal side (VCCA)       |
+----------------------------------------+------------------+-------------------------------------------------------------------------------------------------+


.. _revC3-1v2-rail:

+1.2V rail
~~~~~~~~~~

The +1.2V rail is used to power the iCE40 FPGA (VCC and VCCPLL0/1). You can measure this rail using the 1V2 test points on the front and back of the board.

The +1.2V rail is derived from the +5V rail using a TLV73312PQDRVR linear voltage regulator (U36). The regulator has a maximum output current of 300 mA. The regulator's EN pin is tied directly to the +5V rail. The regulator enters dropout mode when the +5V rail reaches approximately 1.3 V, and enters normal operation once the +5V rail reaches approximately 1.65 V.

The VCCPLL0 and VCCPLL1 supplies are low-pass filtered using a 100 Ω resistor and 4.7 uF capacitor, resulting in a -3 dB cutoff frequency of approximately 340 Hz.


.. _revC3-vio-rails:

VIO rails
~~~~~~~~~

There are two main independent VIO rails - one for port A, and one for port B. These rails are adjustable and set the IO voltage levels for the ports. Each VIO rail voltage can be independently configured, which allows you to work with different logic levels on ports A and B simultaneously. The VIOA and VIOB rails are exposed as pins on the port A and port B connectors.

Each VIO rail is derived from the +5V rail using a TPS73101DBV linear regulator (U31, U14). These regulators have an ultra-low dropout voltage of just 30 mV, which allows the VIO voltages to be programmed anywhere between 1.8 V and the +5V rail voltage (which is essentially equal to VUSB) minus 30 mV.

The TPS73101DBV regulators feature reverse current blocking which prevents current from being sunk into the regulator instead of sourced from it. They also have a unique foldback current limit characteristic which provides excellent protection against short circuits on the VIO rails - see the "Internal Current Limit" section and Figure 12 in the datasheet.

Each VIO regulator has a feedback network which incorporates the output of a DAC081C081CIMK DAC IC. These DACs (U20, U13) are programmed over I2C to adjust the feedback voltage by injecting current into the feedback resistor network, which in turn adjusts the VIO voltage, thus providing runtime VIO voltage adjustment. The DAC output voltages can be measured using the VDAC A and B test points on the rear of the board. The FX2 firmware `calculates the correct DAC voltage <https://github.com/GlasgowEmbedded/glasgow/blob/1f5691a4b516f4ac083e7fa4fc32abcc659e608d/firmware/dac_ldo.c#L76-L83>`__ for the target output voltage. Some examples are:

+--------------+-------------+
| VIO Voltage  | DAC Output  |
+==============+=============+
| 5.0 V        | 0.45 V      |
+--------------+-------------+
| 3.3 V        | 1.88 V      |
+--------------+-------------+
| 2.8 V        | 2.31 V      |
+--------------+-------------+
| 2.5 V        | 2.56 V      |
+--------------+-------------+
| 1.8 V        | 3.15 V      |
+--------------+-------------+

On power-on or reset, both VIO regulators are disabled and the voltage adjustment DACs are reset to 0.0 V. The DAC voltages are programmed over I2C, after which the regulators may be enabled by the FX2 asserting the ``ENVA`` and ``ENVB`` signals (pins 45 and 51 on the FX2 respectively). The VIO A and VIO B LEDs on the front of the board light up when the regulators are enabled.

The VIO rail currents are measured by INA233 voltage and current monitoring ADC ICs (U21, U12) using 150 mΩ shunt resistors (R49, R48) in series with the regulator outputs. This allows the VIO currents for each port to be measured over I2C. The voltage sense pin on each INA233 is exposed on the port connector (VA_SENS, VB_SENS), allowing for two useful configurations:

-  The sense input may be connected directly to the VIO rail for that port (e.g. VA_SENSE to VIOA), enabling you to monitor the VIO rail voltage precisely and utilise the INA233's inbuilt power calculation feature to measure total power consumption for that VIO rail.
-  The sense input may be connected to any arbitrary voltage in the range 0.0 V to 36.0 V, essentially using the INA233's voltage sensing input as a generic 16-bit ADC input. In this configuration the VIO rail current can still be measured but the inbuilt VIO rail power calculation feature will not be available.

Additional 330 mΩ resistors (R56, R7) in series with the regulator outputs ensure recovery in the event that a VIO rail is shorted to ground - see `GitHub issue #135 <https://github.com/GlasgowEmbedded/glasgow/issues/135>`__ for details.

Each VIO rail is protected against overvoltage and ESD by two parallel elements of a SP3012-06UTG diode array. VIOA is protected by D22 and VIOB is protected by D20. These diode arrays also feature a 6.0 V zener diode clamp.

The VIOA rail is used to power the following devices:

+-------------------------------------+-----------------+----------------------------------------------------------------------------------------------+
| Designator                          | Part            | Function / Notes                                                                             |
+=====================================+=================+==============================================================================================+
| U4, U6, U9, U10, U11, U16, U17, U18 | SN74LVC1T45DCKR | Logic level translators for port A. VIOA powers external side (VCCB)                         |
+-------------------------------------+-----------------+----------------------------------------------------------------------------------------------+
| U19                                 | PCA6408APW      | I2C I/O expander for programmable pullup/pulldown resistors on port A. VIOA powers IO ports. |
+-------------------------------------+-----------------+----------------------------------------------------------------------------------------------+


The VIOB rail is used to power the following devices:

+----------------------------------------+-----------------+----------------------------------------------------------------------------------------------+
| Designator                             | Part            | Function / Notes                                                                             |
+========================================+=================+==============================================================================================+
| U22, U23, U24, U25, U26, U27, U28, U29 | SN74LVC1T45DCKR | Logic level translators for port B. VIOB powers external side (VCCB)                         |
+----------------------------------------+-----------------+----------------------------------------------------------------------------------------------+
| U5                                     | PCA6408APW      | I2C I/O expander for programmable pullup/pulldown resistors on port A. VIOB powers IO ports. |
+----------------------------------------+-----------------+----------------------------------------------------------------------------------------------+


.. _revC3-vio-aux:

VIO_AUX
~~~~~~~

Ports A and B are the primary connectors which are expected to be used with Glasgow. The LVDS connector is a secondary connector that can be used for special addons that require additional IOs. While the IOs on ports A and B are well-protected against ESD and utilise separate logic level translation with their own VIO rails, the LVDS connector is directly connected to the iCE40 FPGA without any logic level translation or discrete protection, and without a programmable IO voltage. The supply for the IOs exposed on the LVDS connector must be externally provided via VIO_AUX on pin 44. This voltage is directly fed to ``VCCIO_3`` on the FPGA. Voltages between 1.8 V and 3.3 V are supported. See the iCE40HX8K-BG121 datasheet for more information.


.. _revC3-decoupling-capacitors:

Decoupling capacitors
~~~~~~~~~~~~~~~~~~~~~

Two values of MLCC decoupling capacitor are used across the Glasgow
design.

4.7 uF capacitors are `Taiyo Yuden LMK107BJ475KAHT <https://ds.yuden.co.jp/TYCOMPAS/eu/detail?pn=MBASL168SB5475KTNA01&u=M>`__, with the following DC bias characteristics:

+-----------------+-----------------------+
| DC bias voltage | Effective Capacitance |
+=================+=======================+
| 5.0 V           | 1.93 uF               |
+-----------------+-----------------------+
| 3.3 V           | 2.82 uF               |
+-----------------+-----------------------+
| 2.5 V           | 3.39 uF               |
+-----------------+-----------------------+
| 1.8 V           | 3.92 uF               |
+-----------------+-----------------------+
| 1.2 V           | 4.37 uF               |
+-----------------+-----------------------+

100 nF capacitors are `Taiyo Yuden TMK105BJ104KV-F <https://ds.yuden.co.jp/TYCOMPAS/eu/detail?pn=MSAST105SB5104KFNA01&u=M>`__ (now renamed to MSAST105SB5104KFNA01), with the following DC bias characteristics:

+-----------------+-----------------------+
| DC bias voltage | Effective Capacitance |
+=================+=======================+
| 5.0 V           | 93 nF                 |
+-----------------+-----------------------+
| 3.3 V           | 98 nF                 |
+-----------------+-----------------------+
| 2.5 V           | 99 nF                 |
+-----------------+-----------------------+
| 1.8 V           | 100 nF                |
+-----------------+-----------------------+
| 1.2 V           | 100 nF                |
+-----------------+-----------------------+


.. _revC3-power-on-sequencing:

Power-on sequencing
~~~~~~~~~~~~~~~~~~~

The power-on sequence is as follows:

1. 5.0 V becomes present on the VUSB pin of the USB-C connector.
2. After VUSB exceeds the enable threshold (nominally 1.45 V) of the TPD3S014 current limit switch (U15) for approximately 1.0 ms to 2.2 ms (nominally 1.6 ms) the switch turns on and the +5V rail begins to rise.
3. TPD3S014 performs soft-start and inrush limiting while charging the 150 uF bulk capacitor (C87) on the +5V rail. Charging takes around 2 ms, during which up to 850 mA is drawn.
4. When the +5V rail reaches approximately 1.3 V, the TLV73312PQDRVR linear regulator (U36) leaves disabled mode and enters dropout mode. During this time the +1.2V rail will have a voltage equal to the +5V rail minus the 450 mV dropout voltage of the regulator. When the +5V rail exceeds 1.65 V, the regulator enters normal mode and the +1.2V rail voltage becomes stable at 1.2 V.
5. APX811-40UG-7 (U7) monitors the +5V rail and asserts a reset signal (active low) while the +5V rail is below 4.0 V nominal.
6. Once the +5V rail exceeds this threshold for at least 240 ms, U7's reset signal is no longer asserted. As a result, the TLV75533PDRVR linear regulator (U8) switches on and powers the +3.3V rail.
7. The +3.3V rail and reset signal from U7 are connected to a common-anode dual-Schottky diode package (D24) in such a way that ``CY_RESET`` is asserted (active low) if U7 is outputting a reset state or the +3.3V rail is not present. The `CY_RESET` signal is low-pass filtered using R4, R5, and C88 to ensure that ``CY_RESET`` remains asserted for 5 ms after the +3.3V rail turns on.
8. All rails are now at nominal and ``CY_RESET`` is de-asserted, allowing the FX2 USB controller to start operating. The FX2 de-asserts ``FPGA_RESET``, allowing the iCE40 FPGA (U30) to operate.
9. During power-on, ``ENVA`` and ``ENVB`` are pulled down, disabling the TPS73101DBV adjustable linear regulators (U31, U14) which provide the VIO voltages for ports A and B. The DAC081C081CIMK DACs (U20, U13) provide an adjustable feedback voltage to the regulators. These are programmed over I2C as required to adjust the voltage of the VIO regulators, after which the FX2 can assert ``ENVA`` and/or ``ENVB`` to enable the regulators which, in turn, power the VIO outputs.


.. _revC3-connectors:

Connectors
----------


.. _revC3-port-a-layout:

Port A Connector Layout
~~~~~~~~~~~~~~~~~~~~~~~

+-------------+------------+------------+------------+------------+------------+------------+------------+------------+--------+
| **VIOA**    | **GND**    | **GND**    | **GND**    | **GND**    | **GND**    | **GND**    | **GND**    | **GND**    | **NC** |
+=============+============+============+============+============+============+============+============+============+========+
| **VA_SENS** | **PA_IO0** | **PA_IO1** | **PA_IO2** | **PA_IO3** | **PA_IO4** | **PA_IO5** | **PA_IO6** | **PA_IO7** | **NC** |
+-------------+------------+------------+------------+------------+------------+------------+------------+------------+--------+


.. _revC3-port-b-layout:

Port B Connector Layout
~~~~~~~~~~~~~~~~~~~~~~~

+--------+------------+------------+------------+------------+------------+------------+------------+------------+-------------+
| **NC** | **PB_IO7** | **PB_IO6** | **PB_IO5** | **PB_IO4** | **PB_IO3** | **PB_IO2** | **PB_IO1** | **PB_IO0** | **VIOB**    |
+========+============+============+============+============+============+============+============+============+=============+
| **NC** | **GND**    | **GND**    | **GND**    | **GND**    | **GND**    | **GND**    | **GND**    | **GND**    | **VB_SENS** |
+--------+------------+------------+------------+------------+------------+------------+------------+------------+-------------+


.. _revC3-ports-a-b-pinout:

Ports A/B Pinout
~~~~~~~~~~~~~~~~

+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| Number | Name  | Wire Colour | Description                                                                                                                                          |
+========+=======+=============+======================================================================================================================================================+
| 1      | SENSE | Red         | Voltage sense, connected to VBUS pin of INA233. Tie to pin 2 to enable VIO power measurement feature, or use as an arbitrary 0-36V 16-bit ADC input. |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 2      | VIO   | Blue        | Logic level voltage output. Generated by TPS73101DBV linear regulator, voltage level configured at runtime by DAC081C081CIMK DAC.                    |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 3      | IO0   | Orange      | IO pin 0.                                                                                                                                            |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 4      | GND   | Black       | Ground.                                                                                                                                              |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 5      | IO1   | Green       | IO pin 1.                                                                                                                                            |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 6      | GND   | Black       | Ground.                                                                                                                                              |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 7      | IO2   | Grey        | IO pin 2.                                                                                                                                            |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 8      | GND   | Black       | Ground.                                                                                                                                              |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 9      | IO3   | Brown       | IO pin 3.                                                                                                                                            |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 10     | GND   | Black       | Ground.                                                                                                                                              |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 11     | IO4   | Pink        | IO pin 4.                                                                                                                                            |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 12     | GND   | Black       | Ground.                                                                                                                                              |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 13     | IO5   | Yellow      | IO pin 5.                                                                                                                                            |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 14     | GND   | Black       | Ground.                                                                                                                                              |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 15     | IO6   | White       | IO pin 6.                                                                                                                                            |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 16     | GND   | Black       | Ground.                                                                                                                                              |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 17     | IO7   | Purple      | IO pin 7.                                                                                                                                            |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 18     | GND   | Black       | Ground.                                                                                                                                              |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 19     | NC    | N/A         | Not connected.                                                                                                                                       |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+
| 20     | NC    | N/A         | Not connected.                                                                                                                                       |
+--------+-------+-------------+------------------------------------------------------------------------------------------------------------------------------------------------------+

Wire colours described here are correct for the 1BitSquared wiring looms and are not innate to Glasgow itself.

Note that each of the IOs has a GND pin opposite. This provides a ground reference plane for return currents, which helps improve signal integrity and reduces crosstalk in higher speed signals. Where possible, connect each ground wire to GND on the target device, physically close to the signal connection.

Each IO is driven by an SN74LVC1T45DCKR bus transceiver, which converts between the port's logic voltage (VIO) and the 3.3 V used by the FPGA IO ports. Each IO can be independently configured as an input or output. Each IO pin can source or sink up to 4 mA at 1.8 V, 8 mA at 2.5 V, 24 mA at 3.3 V, or 32 mA at 5.0 V.

The SN74LVC1T45DCKR itself provides limited isolation between the FPGA and the IO pins, and a modicum of ESD protection. Additional ESD and overvoltage protection is provided by an SP3012-06UTG diode array and a 33Ω series termination resistor.

The VSENSE pin is protected by a CDSOD323-T36S unidirectional TVS diode which helps protect the INA233 ICs against overvoltage.


.. _revC3-sync-connector:

SYNC Connector
~~~~~~~~~~~~~~

The SYNC connector is used to synchronise multiple Glasgows together. As of March 2024 this has not been used for much, but we expect folks will come up with interesting ways to use it.

The SYNC pin is weakly pulled up to the +3.3V rail and is buffered by a SN74LVC1T45DCKR bus transceiver. The input-low threshold is 0.8 V and the input-high threshold is 2.0 V, making it directly compatible with 2.5 V, 3.3 V, and 5.0 V logic.

The SYNC pin is protected by a ESD5Z5.0T1G ESD protection diode with a standoff voltage of 5.0 V and a breakdown of 6.2 V, and a 47 Ω series resistor.


.. _revC3-lvds-connector:

LVDS Connector
~~~~~~~~~~~~~~

The LVDS port is a secondary connector used for specially designed addons. It is directly wired to the FPGA rather than using bus transceivers, and has limited ESD protection, so you should be careful when plugging things into it and only do so when the device is fully powered off.

The LVDS port will be replaced with different connectors in future hardware revisions of Glasgow, so its use is not preferred for addon boards.

+--------+-------+--------+---------+
| Number | Name  | Number | Name    |
+========+=======+========+=========+
| 1      | GND   | 2      | +3.3V   |
+--------+-------+--------+---------+
| 3      | Z11_N | 4      | GND     |
+--------+-------+--------+---------+
| 5      | Z11_P | 6      | GND     |
+--------+-------+--------+---------+
| 7      | GND   | 8      | Z12_P   |
+--------+-------+--------+---------+
| 9      | Z10_P | 10     | Z12_N   |
+--------+-------+--------+---------+
| 11     | Z10_N | 12     | GND     |
+--------+-------+--------+---------+
| 13     | GND   | 14     | Z9_N    |
+--------+-------+--------+---------+
| 15     | Z8_P  | 16     | Z9_P    |
+--------+-------+--------+---------+
| 17     | Z8_N  | 18     | GND     |
+--------+-------+--------+---------+
| 19     | GND   | 20     | Z7_N    |
+--------+-------+--------+---------+
| 21     | Z6_P  | 22     | Z7_P    |
+--------+-------+--------+---------+
| 23     | Z6_N  | 24     | GND     |
+--------+-------+--------+---------+
| 25     | GND   | 26     | Z5_N    |
+--------+-------+--------+---------+
| 27     | Z3_P  | 28     | Z5_P    |
+--------+-------+--------+---------+
| 29     | Z3_N  | 30     | GND     |
+--------+-------+--------+---------+
| 31     | GND   | 32     | Z4_P    |
+--------+-------+--------+---------+
| 33     | Z2_N  | 34     | Z4_N    |
+--------+-------+--------+---------+
| 35     | Z2_P  | 36     | GND     |
+--------+-------+--------+---------+
| 37     | GND   | 38     | Z1_N    |
+--------+-------+--------+---------+
| 39     | Z0_P  | 40     | Z1_P    |
+--------+-------+--------+---------+
| 41     | Z0_N  | 42     | GND     |
+--------+-------+--------+---------+
| 43     | GND   | 44     | VIO_AUX |
+--------+-------+--------+---------+


The +3.3V pin provides 3.3 V power from the onboard +3.3V rail.

To use the LVDS connector you must provide ``VIO_AUX``, an IO voltage between 1.8 V and 3.3 V, on pin 44. This pin is tied directly to ``VCCIO_3`` on the FPGA. See the iCE40HX8K-BG121 datasheet for more information about the power requirements.

The pins can be used in differential mode (N/P pairs) or in single-ended mode (independent signals on N and P).

No termination resistors are included. You should include termination resistors on your board if you use the LVDS connector. See the Lattice document `FPGA-TN-02213 "Using Differential I/O (LVDS, Sub-LVDS) in iCE40 LP/HX Devices" <https://www.latticesemi.com/view_document?document_id=47960>`__ for details.


.. _revC3-leds:

LEDs
----

+-------+--------+------------+-------------+---------------------------------------------------------------------------------------------------------------------+
| Name  | Colour | Designator | Part        | Description                                                                                                         |
+=======+========+============+=============+=====================================================================================================================+
| PWR   | Green  | D1         | NCD0603G1   | Powered by +3.3V rail                                                                                               |
+-------+--------+------------+-------------+---------------------------------------------------------------------------------------------------------------------+
| FX2   | White  | D2         | NCD0603W1   | Connected to pin 47 (PD2/FD10) of Cypress FX2 (U1). Pulses during enumeration. Lights when the FX2 has initialised. |
+-------+--------+------------+-------------+---------------------------------------------------------------------------------------------------------------------+
| ICE   | Blue   | D3         | ORH-B36G    | Connected to pin 48 (PD3/FD11) of Cypress FX2 (U1). Lights when the FPGA is ready.                                  |
+-------+--------+------------+-------------+---------------------------------------------------------------------------------------------------------------------+
| ACT   | Orange | D4         | NCD0603O1   | Connected to pin 49 (PD4/FD12) of Cypress FX2 (U1). Lights when activity is occurring.                              |
+-------+--------+------------+-------------+---------------------------------------------------------------------------------------------------------------------+
| ERR   | Red    | D5         | NCD0603R1   | Connected to pin 50 (PD5/FD13) of Cypress FX2 (U1). Lights when an error occurs.                                    |
+-------+--------+------------+-------------+---------------------------------------------------------------------------------------------------------------------+
| U1    | Blue   | D6         | ORH-B36G    | Connected to ball G9 (IOR_128) of iCE40 FPGA (U30)                                                                  |
+-------+--------+------------+-------------+---------------------------------------------------------------------------------------------------------------------+
| U2    | Pink   | D7         | OSK40603C1E | Connected to ball G8 (IOR_118) of iCE40 FPGA (U30)                                                                  |
+-------+--------+------------+-------------+---------------------------------------------------------------------------------------------------------------------+
| U3    | White  | D8         | NCD0603W1   | Connected to ball E9 (IOR_144) of iCE40 FPGA (U30)                                                                  |
+-------+--------+------------+-------------+---------------------------------------------------------------------------------------------------------------------+
| U4    | Pink   | D9         | OSK40603C1E | Connected to ball D9 (IOR_147) of iCE40 FPGA (U30)                                                                  |
+-------+--------+------------+-------------+---------------------------------------------------------------------------------------------------------------------+
| U5    | Blue   | D10        | ORH-B36G    | Connected to ball E8 (IOR_146) of iCE40 FPGA (U30)                                                                  |
+-------+--------+------------+-------------+---------------------------------------------------------------------------------------------------------------------+
| VIO A | Green  | D15        | NCD0603G1   | Lights when VIO A regulator (U31) is enabled                                                                        |
+-------+--------+------------+-------------+---------------------------------------------------------------------------------------------------------------------+
| VIO B | Green  | D14        | NCD0603G1   | Lights when VIO B regulator (U14) is enabled                                                                        |
+-------+--------+------------+-------------+---------------------------------------------------------------------------------------------------------------------+

The system LEDs (FX2, ICE, ACT, ERR) are under control of the FX2 firmware, which is responsible for producing the behaviour described above. In the event that the FX2 firmware does not run (e.g. no firmware is present), the LED IO pins default to a high-impedance input state and will all be off.

The user LEDs (U1-U5) are under control of the gateware. In most cases they go unused and the FPGA defaults the pins to be inputs with weak pullups, which results in the user LEDs lighting dimly.


.. _revC3-i2c-bus:

I²C bus
-------

Glasgow uses I2C internally for controlling the VIO voltages, measuring VIO current and voltage (or an external voltage input), and for communicating with the FX2 and iCE40 EEPROMs. The SDA and SCL signals can be accessed via test points on the front and rear of the board.


.. _revC3-i2c-bus-addresses:

I²C bus addresses
~~~~~~~~~~~~~~~~~

+--------------+------------+----------------+----------------------------------------------------------+
| Address      | Designator | Part           | Function                                                 |
+==============+============+================+==========================================================+
| 101001X [1]_ | U2         | CAT24M01X      | 1 Mbit [4]_ flash memory for ICE40 FPGA                  |
+--------------+------------+----------------+----------------------------------------------------------+
| 1010001      | U3         | BL24C256A-SFRC | Flash memory for FX2 USB controller                      |
+--------------+------------+----------------+----------------------------------------------------------+
| 0001110      | U20        | DAC081C081CIMK | DAC for setting VIO voltage on port A                    |
+--------------+------------+----------------+----------------------------------------------------------+
| 1000000      | U21        | INA233         | Voltage/current measurement ADC for port A               |
+--------------+------------+----------------+----------------------------------------------------------+
| 0100000 [2]_ | U19        | PCA6408APW     | I/O expander for programmable pullup/pulldowns on port A |
+--------------+------------+----------------+----------------------------------------------------------+
| 0001101      | U13        | DAC081C081CIMK | DAC for setting VIO voltage on port B                    |
+--------------+------------+----------------+----------------------------------------------------------+
| 1000001      | U12        | INA233         | Voltage/current measurement ADC for port B               |
+--------------+------------+----------------+----------------------------------------------------------+
| 0100001 [3]_ | U5         | PCA6408APW     | I/O expander for programmable pullup/pulldowns on port B |
+--------------+------------+----------------+----------------------------------------------------------+

.. [1]
   The X in this address indicates that the device responds to two addresses (0 or 1 in the last bit position). In this case each address acts as a 512 Kbit flash device, providing 1 Mbit in total. Refer to the product datasheet for more information.

.. [2]
   PCA6408APW is an SMBus device. The SMBus Alert Response Address (ARA) is 0001100 for both U19 (port A) and U5 (port B).

.. [3]
   PCA6408APW is an SMBus device. The SMBus Alert Response Address (ARA) is 0001100 for both U19 (port A) and U5 (port B).

.. [4]
   The iCE40HX8K bitstream is actually about 3 KB bigger than 1 Mbit, so the tail end of the bitstream lives in U3 as a workaround.


.. _revC3-recovery:

Recovery
--------

Two pads can be found on the board marked "RECOVER", next to the FX2 EEPROM (U2). This footprint is R40 in the schematic. To initiate recovery, short these pads together and press the reset button, then remove the short. This temporarily changes the I2C address of the FX2 EEPROM so that it boots without firmware, placing it into a recovery mode where it enumerates with the default FX2 device descriptor. The ``fx2tool`` utility can then be used to make a backup copy of the FX2 EEPROM, and the ``glasgow factory`` command can be used to re-provision the device configuration block and the firmware
