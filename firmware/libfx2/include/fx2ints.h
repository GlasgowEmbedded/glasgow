#ifndef FX2INTS_H
#define FX2INTS_H

enum {
  _INT_IE0       =  0, //< Pin PA0 / INT0#
  _INT_TF0       =  1, //< Internal, Timer 0
  _INT_IE1       =  2, //< Pin PA1 / INT1#
  _INT_TF1       =  3, //< Internal, Timer 1
  _INT_RI_TI_0   =  4, //< Internal, USART0
  _INT_TF2       =  5, //< Internal, Timer 2
  _INT_RESUME    =  6, //< Pin WAKEUP or Pin PA3/WU2
  _INT_RI_TI_1   =  7, //< Internal, USART1
  _INT_USB       =  8, //< Internal, USB
  _INT_I2C       =  9, //< Internal, I2C Bus Controller
  _INT_GPIF_IE4  = 10, //< Internal, GPIF/FIFOs or Pin INT4 (100 and 128 pin only)
  _INT_IE5       = 11, //< Pin INT5# (100 and 128 pin only)
  _INT_IE6       = 12, //< Pin INT6 (100 and 128 pin only)
};

// 8051 core interrupts

void isr_IE0() __interrupt(_INT_IE0);
void isr_TF0() __interrupt(_INT_TF0);
void isr_IE1() __interrupt(_INT_IE1);
void isr_TF1() __interrupt(_INT_TF1);
void isr_RI_TI_0() __interrupt(_INT_RI_TI_0);
void isr_TF2() __interrupt(_INT_TF2);
void isr_RESUME() __interrupt(_INT_RESUME);
void isr_RI_TI_1() __interrupt(_INT_RI_TI_1);
void isr_USB() __interrupt(_INT_USB);
void isr_I2C() __interrupt(_INT_I2C);
void isr_GPIF_IE4() __interrupt(_INT_GPIF_IE4);
void isr_IE5() __interrupt(_INT_IE5);
void isr_IE6() __interrupt(_INT_IE6);

// Autovectored USB interrupts

/**
 * Enables the autovectored USB interrupt and the corresponding jump table.
 */
#define ENABLE_USB_AUTOVEC() \
  do { EUSB = 1; INTSETUP |= _AV2EN; } while(0)

/**
 * Clears the main USB interrupt request.
 * This must be done before clearing the individual USB interrupt request latch.
 */
#define CLEAR_USBINT_IRQ() \
  do { EXIF &= ~0x10; } while(0)

void isr_SUDAV() __interrupt;
void isr_SOF() __interrupt;
void isr_SUTOK() __interrupt;
void isr_SUSPEND() __interrupt;
void isr_USBRESET() __interrupt;
void isr_HISPEED() __interrupt;
void isr_EP0ACK() __interrupt;
void isr_EP0IN() __interrupt;
void isr_EP0OUT() __interrupt;
void isr_EP1IN() __interrupt;
void isr_EP1OUT() __interrupt;
void isr_EP2() __interrupt;
void isr_EP4() __interrupt;
void isr_EP6() __interrupt;
void isr_EP8() __interrupt;
void isr_IBN() __interrupt;
void isr_EP0PING() __interrupt;
void isr_EP1PING() __interrupt;
void isr_EP2PING() __interrupt;
void isr_EP4PING() __interrupt;
void isr_EP6PING() __interrupt;
void isr_EP8PING() __interrupt;
void isr_ERRLIMIT() __interrupt;
void isr_EP2ISOERR() __interrupt;
void isr_EP4ISOERR() __interrupt;
void isr_EP6ISOERR() __interrupt;
void isr_EP8ISOERR() __interrupt;

// GPIF autovectored interrupts

/**
 * Enables the autovectored GPIF interrupt and the corresponding jump table.
 * Note that this makes it impossible to provide an INT4 handler.
 */
#define ENABLE_GPIF_AUTOVEC() \
  do { EX4 = 1; INTSETUP |= AV4EN; } while(0)

/**
 * Clears the main GPIF interrupt request.
 * This must be done before clearing the individual GPIF interrupt request latch.
 */
#define CLEAR_GPIF_IRQ() \
  do { EXIF &= ~0x40; } while(0)

void isr_EP2PF() __interrupt;
void isr_EP4PF() __interrupt;
void isr_EP6PF() __interrupt;
void isr_EP8PF() __interrupt;
void isr_EP2EF() __interrupt;
void isr_EP4EF() __interrupt;
void isr_EP6EF() __interrupt;
void isr_EP8EF() __interrupt;
void isr_EP2FF() __interrupt;
void isr_EP4FF() __interrupt;
void isr_EP6FF() __interrupt;
void isr_EP8FF() __interrupt;
void isr_GPIFDONE() __interrupt;
void isr_GPIFWF() __interrupt;

#endif
