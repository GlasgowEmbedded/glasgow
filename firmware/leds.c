#include <fx2regs.h>
#include "glasgow.h"

void leds_init() {
  IOD |=   (1<<PIND_LED_CY);
  IOD &= ~(                 (1<<PIND_LED_FPGA)|(1<<PIND_LED_ACT)|(1<<PIND_LED_ERR));
  OED |=   (1<<PIND_LED_CY)|(1<<PIND_LED_FPGA)|(1<<PIND_LED_ACT)|(1<<PIND_LED_ERR);
}

void led_fpga_set(bool on) {
  if(on) IOD |=  (1<<PIND_LED_FPGA);
  else   IOD &= ~(1<<PIND_LED_FPGA);
}

void led_act_set(bool on) {
  if(on) IOD |=  (1<<PIND_LED_ACT);
  else   IOD &= ~(1<<PIND_LED_ACT);
}

void led_err_set(bool on) {
  if(on) IOD |=  (1<<PIND_LED_ERR);
  else   IOD &= ~(1<<PIND_LED_ERR);
}
