//! This module contains FX2 GPIO related functionality. Mainly, it defines the FX2 GPIO
//! functions; to reduce code size by a significant margin, GPIO manipulation is done inline
//! in the functions that implement associated functionality.
//!
//! Where possible, Glasgow revisions use the same GPIO pin to implement the same function.
//! In some cases this was not possible, and the related constants are suffixed with `_REV*`,
//! which indicates the revision this function belongs to. In one additional exceptional case,
//! a pin had to be shared between two functions, which is called out in the pinout table.

#pragma once

// Set up aliases for all of the GPIO pins accessible by `setb` and `clr`.
#define IO_CONCAT(a, b) a ## b
#define IO_A(number) IO_CONCAT(PA, number)
#define IO_B(number) IO_CONCAT(PB, number)
#define IO_D(number) IO_CONCAT(PD, number)

/// Pin definition table. These definitions use pin numbers (not masks!).
// PORTA pins
#define PINA_nALERT             0
#define PINA_FPGA_nRESET_REVCD  1
#define PINA_FPGA_DONE          3
// PORTB pins
#define PINB_COPI_REVABC        2
#define PINB_nCS_REVABC         3
#define PINB_SCK_REVABC         4
// PORTD pins (all outputs)
#define PIND_EN_VA              0
#define PIND_FPGA_nRESET_REVAB  1
#define PIND_EN_VC_REVD         1
#define PIND_LED_FX2            2 // shared with PIND_MCU_BOOT0_REVD
#define PIND_MCU_BOOT0_REVD     2 // shared with PIND_LED_FX2
#define PIND_LED_ICE_REVABC     3
#define PIND_MCU_nRESET_REVD    3
#define PIND_LED_ACT            4
#define PIND_LED_ERR            5
#define PIND_EN_VB              6
#define PIND_nOEQ_REVAB         7
#define PIND_EN_VD_REVD         7

/// IO SFR bit definitions, exactly mirroring the table above.
// PORTA bits
#define IO_nALERT               IO_A(PINA_nALERT)
#define IO_FPGA_nRESET_REVCD    IO_A(PINA_FPGA_nRESET_REVCD)
#define IO_FPGA_DONE            IO_A(PINA_FPGA_DONE)
// PORTB bits
#define IO_COPI_REVABC          IO_B(PINB_COPI_REVABC)
#define IO_nCS_REVABC           IO_B(PINB_nCS_REVABC)
#define IO_SCK_REVABC           IO_B(PINB_SCK_REVABC)
// PORTC bits
#define IO_EN_VA                IO_D(PIND_EN_VA)
#define IO_FPGA_nRESET_REVAB    IO_D(PIND_FPGA_nRESET_REVAB)
#define IO_EN_VC_REVD           IO_D(PIND_EN_VC_REVD)
#define IO_LED_FX2              IO_D(PIND_LED_FX2)
#define IO_MCU_BOOT0_REVD       IO_D(PIND_MCU_BOOT0_REVD)
#define IO_LED_ICE_REVABC       IO_D(PIND_LED_ICE_REVABC)
#define IO_MCU_nRESET_REVD      IO_D(PIND_MCU_nRESET_REVD)
#define IO_LED_ACT              IO_D(PIND_LED_ACT)
#define IO_LED_ERR              IO_D(PIND_LED_ERR)
#define IO_EN_VB                IO_D(PIND_EN_VB)
#define IO_nOEQ_REVAB           IO_D(PIND_nOEQ_REVAB)
#define IO_EN_VD_REVD           IO_D(PIND_EN_VD_REVD)

/// LED test mode. If `true`, LED manipulation is skipped. This is only used during factory
/// testing, for a visually check of LED function, but has to be referenced throughout the firmware
/// because LED manipulation isn't abstracted out.
extern __bit test_leds;

/// Initialize the GPIO interface. Configures all OE/IO registers, EX0 interrupt, and parallel bus
/// (in GPIO mode).
///
/// Should be called after CPU reset.
void gpio_init();

/// Initialize the LED interface. Configures ACT LED behavior.
///
/// Should be called after CPU reset.
void leds_init();
