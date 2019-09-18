#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <irq.h>
#include <uart.h>
#include <time.h>
#include <generated/csr.h>
#include <generated/mem.h>
#include <console.h>
#include <system.h>

void * __stack_chk_guard = (void *) (0xDEADBEEF);
void __stack_chk_fail(void) {
  printf( "stack fail\n" );
}

int main(void)
{
	irq_setmask(0);
	irq_setie(1);
	uart_init();

	puts("\nbetrusted.io software built "__DATE__" "__TIME__);

	while(1) {
	  printf( "hello world\n" );
	}

	return 0;
}
