.syntax unified

.section .init, "xa", %progbits
.word __stack_end
.word main
