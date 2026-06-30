#pragma once

// Set up aliases for all of the GPIO pins accessible by `setb` and `clr`
// to reduce code size.
#define IO_CONCAT(a, b) a ## b
#define IO_A(number) IO_CONCAT(PA, number)
#define IO_B(number) IO_CONCAT(PB, number)
#define IO_D(number) IO_CONCAT(PD, number)

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

extern __bit test_leds;

void gpio_init();
void leds_init();
