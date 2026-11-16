// The STM32 firmware is written in a rather idiosyncratic manner. This is because of the harsh
// size requirements: in order to simplify the bootstrapping process, the firmware is written to
// the STM32's RAM every time the FX2 boots. This limits the size of the firmware to 0x1000 bytes.
//
// The linker script doesn't clear .bss, so globals must be initialized explicitly in `_reset()`.

#include <stdint.h>
#include <stddef.h>

#define RCC_BASE   0x4002'1000
#define GPIOA_BASE 0x5000'0000
#define GPIOB_BASE 0x5000'0400
#define GPIOC_BASE 0x5000'0800
#define I2C1_BASE  0x4000'5400
#define SPI1_BASE  0x4001'3000

#define RCC_CFGR    (RCC_BASE+0x8)
#define RCC_CFGR_PPRE(v)   (((v)&0b111)<<12)

#define RCC_IOPENR  (RCC_BASE+0x34)
#define RCC_IOPENR_GPIOAEN (1<<0)
#define RCC_IOPENR_GPIOBEN (1<<1)
#define RCC_IOPENR_GPIOCEN (1<<2)

#define RCC_APBENR1 (RCC_BASE+0x3C)
#define RCC_APBENR1_I2C1EN (1<<21)

#define RCC_APBENR2 (RCC_BASE+0x40)
#define RCC_APBENR2_SPI1EN (1<<12)

#define GPIO_MODER(b)    ((b)+0x00)
#define GPIO_OTYPER(b)   ((b)+0x04)
#define GPIO_OSPEEDR(b)  ((b)+0x08)
#define GPIO_IDR(b)      ((b)+0x10)
#define GPIO_ODR(b)      ((b)+0x14)
#define GPIO_BSRR(b)     ((b)+0x18)
#define GPIO_AFRL(b)     ((b)+0x20)
#define GPIO_AFRH(b)     ((b)+0x24)

#define GPIO_MODE(n,v)   (((v)&0b11)<<(n*2))
#define GPIO_MODE_INPUT  0b00
#define GPIO_MODE_OUTPUT 0b01
#define GPIO_MODE_ALTERN 0b10
#define GPIO_MODE_ANALOG 0b11

#define GPIO_OTYPE(n,v)  (((v)&0b1)<<(n))
#define GPIO_OTYPE_PP    0b0
#define GPIO_OTYPE_OD    0b1

#define GPIO_OSPEED(n,v) (((v)&0b11)<<(n))
#define GPIO_OSPEED_VL   0b00
#define GPIO_OSPEED_L    0b01
#define GPIO_OSPEED_H    0b10
#define GPIO_OSPEED_VH   0b11

#define GPIO_AFSEL(n,v)  (((v)&0b1111)<<(n*4))
#define GPIO_AF(n)       (n)

#define GPIO_SET_RST(n,v) ((1<<(n))<<((v)?0:16))

#define I2C_CR1(b)       ((b)+0x00)
#define I2C_CR2(b)       ((b)+0x04)
#define I2C_OAR1(b)      ((b)+0x08)
#define I2C_TIMEOUTR(b)  ((b)+0x14)
#define I2C_ISR(b)       ((b)+0x18)
#define I2C_ICR(b)       ((b)+0x1C)
#define I2C_RXDR(b)      ((b)+0x24)
#define I2C_TXDR(b)      ((b)+0x28)

#define I2C_CR1_PE       (1<<0)

#define I2C_CR2_NACK     (1<<15)

#define I2C_OAR1_7BIT(v) ((1<<15)|((v&0b111'1111)<<1))

#define I2C_TIMEOUTR_TEXTEN         (1<<31)
#define I2C_TIMEOUTR_TIMEOUTEN      (1<<15)
#define I2C_TIMEOUTR_TIDLE          (1<<12)
#define I2C_TIMEOUTR_TIMEOUTA(v)    ((v&0xFFF)<<0)
#define I2C_TIMEOUTR_TIMEOUTB(v)    ((v&0xFFF)<<16)

#define I2C_ISR_DIR     (1<<16)
#define I2C_ISR_BUSY    (1<<15)
#define I2C_ISR_TIMEOUT (1<<12)
#define I2C_ISR_BERR    (1<<8)
#define I2C_ISR_STOPF   (1<<5)
#define I2C_ISR_NACKF   (1<<4)
#define I2C_ISR_ADDR    (1<<3)
#define I2C_ISR_RXNE    (1<<2)
#define I2C_ISR_TXIS    (1<<1)
#define I2C_ISR_TXE     (1<<0)

#define I2C_ICR_TIMEOUTF (1<<12)
#define I2C_ICR_BERRCF  (1<<8)
#define I2C_ICR_STOPCF  (1<<5)
#define I2C_ICR_NACKCF  (1<<4)
#define I2C_ICR_ADDRCF  (1<<3)

#define SPI_CR1(b)      ((b)+0x00)
#define SPI_CR2(b)      ((b)+0x04)
#define SPI_SR(b)       ((b)+0x08)
#define SPI_DR(b)       ((b)+0x0C)

#define SPI_CR1_SSM     (1<<9)
#define SPI_CR1_SSI     (1<<8)
#define SPI_CR1_SPE     (1<<6)
#define SPI_CR1_BR(n)   (((n)&0b111)<<3)
#define SPI_CR1_MSTR    (1<<2)
#define SPI_CR1_CPOL(n) (((n)&1)<<1)
#define SPI_CR1_CPHA(n) (((n)&1)<<0)

#define SPI_CR2_FRXTH   (1<<12)
#define SPI_CR2_DS(v)   ((((v)-1)&0b1111)<<8)

#define SPI_SR_FTLVL(v) (((v)>>11)&0b11)
#define SPI_SR_FRLVL(v) (((v)>>9)&0b11)
#define SPI_SR_BSY      (1<<7)
#define SPI_SR_TXE      (1<<1)
#define SPI_SR_RXNE     (1<<0)

#define R32(a) *((volatile uint32_t*)(a))
#define W32(a,v) do{*((volatile uint32_t*)(a))=(v);}while(0)

#define R16(a) *((volatile uint16_t*)(a))
#define W16(a,v) do{*((volatile uint16_t*)(a))=(v);}while(0)

#define R8(a) *((volatile uint8_t*)(a))
#define W8(a,v) do{*((volatile uint8_t*)(a))=(v);}while(0)

#define MCU_PROTOCOL_ONLY
#include "../fx2/glasgow_mcu.h"

static uint8_t spi_xfer(uint8_t data)
{
    W8(SPI_DR(SPI1_BASE), data);
    while (!(R16(SPI_SR(SPI1_BASE)) & SPI_SR_RXNE));
    return R8(SPI_DR(SPI1_BASE));
}

void main()
{
    static const struct reg_init {
        uint32_t addr;
        uint32_t value;
    } init_seq[] = {
        // RCC
        {RCC_CFGR,    RCC_CFGR_PPRE(0b100)}, // PCLK = HCLK/2
        {RCC_IOPENR,  RCC_IOPENR_GPIOAEN|RCC_IOPENR_GPIOBEN|RCC_IOPENR_GPIOCEN},
        {RCC_APBENR1, RCC_APBENR1_I2C1EN},
        {RCC_APBENR2, RCC_APBENR2_SPI1EN},

        // GPIOA
        {GPIO_OSPEEDR(GPIOA_BASE), (
            GPIO_OSPEED(5,  GPIO_OSPEED_VH) | // SCLK
            GPIO_OSPEED(6,  GPIO_OSPEED_VH) | // CIPO
            GPIO_OSPEED(7,  GPIO_OSPEED_VH) | // COPI
            GPIO_OSPEED(13, GPIO_OSPEED_H)  | // SWDIO
            GPIO_OSPEED(14, GPIO_OSPEED_H)  | // SWCLK
            0
        )},
        {GPIO_BSRR(GPIOA_BASE),
            GPIO_SET_RST(1,  1)             | // nLED=1
            GPIO_SET_RST(10, 1)             | // ADC_nRST=1
            0
        },
        {GPIO_MODER(GPIOA_BASE), 0xFFFF'FFFF & (
            GPIO_MODE(1,  GPIO_MODE_OUTPUT) | // nLED
            GPIO_MODE(2,  GPIO_MODE_INPUT)  | // DRDY
            GPIO_MODE(5,  GPIO_MODE_ALTERN) | // SCLK   (AF0)
            GPIO_MODE(6,  GPIO_MODE_ALTERN) | // CIPO   (AF0)
            GPIO_MODE(7,  GPIO_MODE_ALTERN) | // COPI   (AF0)
            GPIO_MODE(8,  GPIO_MODE_OUTPUT) | // nCS    (not AF!)
            GPIO_MODE(9,  GPIO_MODE_OUTPUT) | // SYNC
            GPIO_MODE(10, GPIO_MODE_OUTPUT) | // ADC_nRST
            GPIO_MODE(13, GPIO_MODE_ALTERN) | // SWDIO  (AF0)
            GPIO_MODE(14, GPIO_MODE_ALTERN) | // SWCLK  (AF0)
            0
        )},

        // GPIOB
        {GPIO_OTYPER(GPIOB_BASE), (
            GPIO_OTYPE(6, GPIO_OTYPE_OD)    | // SCL
            GPIO_OTYPE(7, GPIO_OTYPE_OD)    | // SDA
            0
        )},
        {GPIO_AFRL(GPIOB_BASE),
            GPIO_AFSEL(6, GPIO_AF(6))       | // SCL
            GPIO_AFSEL(7, GPIO_AF(6))       | // SDA
            0
        },
        {GPIO_BSRR(GPIOB_BASE),
            GPIO_SET_RST(0,  1)             | // CFG0=1
            GPIO_SET_RST(1,  1)             | // CFG2=1
            GPIO_SET_RST(3,  0)             | // FLASH_nHOLD=0
            0
        },
        {GPIO_MODER(GPIOB_BASE), 0xFFFF'FFFF & (
            GPIO_MODE(0,  GPIO_MODE_OUTPUT) | // CFG0
            GPIO_MODE(1,  GPIO_MODE_OUTPUT) | // CFG2
            GPIO_MODE(3,  GPIO_MODE_OUTPUT) | // FLASH_nHOLD
            GPIO_MODE(6,  GPIO_MODE_ALTERN) | // SCL    (AF6)
            GPIO_MODE(7,  GPIO_MODE_ALTERN) | // SDA    (AF6)
            0
        )},

        // GPIOC
        {GPIO_MODER(GPIOC_BASE), 0xFFFF'FFFF & (
            GPIO_MODE(6,  GPIO_MODE_INPUT)  | // nADC_INT
            0
        )},

        // I2C1
        {I2C_OAR1(I2C1_BASE), I2C_OAR1_7BIT(0b000'1010)},
        {I2C_TIMEOUTR(I2C1_BASE),
            // These timeouts are sized for a triple measurement at max oversampling ratio.
            // (Specifically, the FX2 firmware uses this MCMR command for auto-gain.)
            I2C_TIMEOUTR_TIMEOUTEN | I2C_TIMEOUTR_TIMEOUTA(0xFFF) | // 1048 ms @ 8 MHz I2C_CLK
            I2C_TIMEOUTR_TEXTEN    | I2C_TIMEOUTR_TIMEOUTB(0xFFF)   // 1048 ms @ 8 MHz (PCLK)
        },
        {I2C_CR1(I2C1_BASE), I2C_CR1_PE},

        // End
        {},
    };

    // Write all 32-bit registers using a table to reduce code size.
    for (const struct reg_init *init = init_seq; init->addr; init++)
        W32(init->addr, init->value);

    // SPI1
    W16(SPI_CR2(SPI1_BASE), SPI_CR2_FRXTH|SPI_CR2_DS(8));
    W16(SPI_CR1(SPI1_BASE),
        SPI_CR1_CPOL(0)|SPI_CR1_CPHA(1)|SPI_CR1_BR(0)|
        SPI_CR1_MSTR|SPI_CR1_SSM|SPI_CR1_SSI|SPI_CR1_SPE
    );

    enum state {
        STATE_IDLE = 0u,
        STATE_COMMAND,
        STATE_LED_DATA,
        STATE_SPI_DATA,
        STATE_SPI_DRDY,
        STATE_CFG_DATA,
    } state = STATE_IDLE;

    while (1) {
        uint32_t isr = R32(I2C_ISR(I2C1_BASE));
        if (isr & (I2C_ISR_STOPF|I2C_ISR_TIMEOUT)) {
            W32(I2C_ICR(I2C1_BASE), I2C_ICR_STOPCF|I2C_ICR_TIMEOUTF);
            W32(GPIO_BSRR(GPIOA_BASE), GPIO_SET_RST(8, 1)); // nCS
        } else if (isr & I2C_ISR_ADDR) {
            W32(I2C_ICR(I2C1_BASE), I2C_ICR_ADDRCF);
            // Clear transmit buffer. In STATE_IDLE (among others), we place the error marker into
            // the FIFO whenever TXIS fires, to avoid locking up the bus on a sequencing error in
            // the way that the STM32 bootloader likes to do. But this leaves the stray byte in
            // the FIFO, which in turn creates an off-by-one frame shift.
            W32(I2C_ISR(I2C1_BASE), I2C_ISR_TXE);
            // First byte after a write address determines the function.
            if (!(isr & I2C_ISR_DIR)) {
                W32(GPIO_BSRR(GPIOA_BASE), GPIO_SET_RST(8, 1)); // nCS
                state = STATE_COMMAND;
            }
        } else if (isr & I2C_ISR_RXNE) {
            uint8_t rxd = R32(I2C_RXDR(I2C1_BASE));
            if (state == STATE_COMMAND && rxd == MCU_CMD_LED) {
                state = STATE_LED_DATA;
            } else if (state == STATE_COMMAND && (rxd == MCU_CMD_NAFE || rxd == MCU_CMD_MEAS)) {
                W32(GPIO_BSRR(GPIOA_BASE), GPIO_SET_RST(8, 0)); // nCS
                state = (rxd == MCU_CMD_MEAS) ? STATE_SPI_DRDY : STATE_SPI_DATA;
            } else if (state == STATE_COMMAND && rxd == MCU_CMD_FPGA) {
                state = STATE_CFG_DATA;
            } else if (state == STATE_LED_DATA) {
                bool is_lit = rxd;
                W32(GPIO_BSRR(GPIOA_BASE),
                    GPIO_SET_RST(1, !is_lit) | // nLED
                    0
                );
                state = STATE_IDLE;
            } else if (state == STATE_SPI_DATA || state == STATE_SPI_DRDY) {
                spi_xfer(rxd);
            } else if (state == STATE_CFG_DATA) {
                bool is_sram = rxd;
                W32(GPIO_BSRR(GPIOB_BASE),
                    GPIO_SET_RST(0,  is_sram) | // CFG0=is_sram
                    GPIO_SET_RST(1,  is_sram) | // CFG2=is_sram
                    GPIO_SET_RST(3, !is_sram) | // FLASH_nHOLD=!is_sram
                    0
                );
            } else {
                // Strictly speaking we should be using SBC/NBYTES here, but reception completes
                // so fast in case of an error that this will just waste code size.
                W32(I2C_CR2(I2C1_BASE), I2C_CR2_NACK);
                state = STATE_IDLE;
            }
        } else if (isr & I2C_ISR_TXIS) {
            if (state == STATE_SPI_DRDY) {
                // Wait until a DRDY pulse or a new command. Otherwise, if the NAFE is misconfigured,
                // this will hang the STM32 and require a hardware reset.
                state = STATE_SPI_DATA;
                while (
                    !(R32(GPIO_IDR(GPIOA_BASE)) & (1<<2)) && // DRDY
                    !(R32(I2C_ISR(I2C1_BASE)) & I2C_ISR_TIMEOUT)
                );
            } else if (state == STATE_SPI_DATA) {
                W32(I2C_TXDR(I2C1_BASE), spi_xfer(0));
            } else {
                // Do nothing. The I2C peripheral will stretch the clock until eventually the SMBus
                // timeout will fire and release the bus.
            }
        }
    }
}
