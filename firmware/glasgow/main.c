#include <fx2.h>

void isr_TF0() __interrupt(_INT_TF0) {
  static int i;
  if(i++ % 64 == 0) PA0 = !PA0;
}

int main() {
  OEA = 0b1;
  PA0 = 1;

  TCON = _M0_0;
  TR0 = 1;
  ET0 = 1;
  EA  = 1;
  while(1);
}
