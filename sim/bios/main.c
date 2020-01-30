// This file is Copyright (c) 2013-2014 Sebastien Bourdeauducq <sb@m-labs.hk>
// This file is Copyright (c) 2014-2019 Florent Kermarrec <florent@enjoy-digital.fr>
// This file is Copyright (c) 2015 Yann Sionneau <ys@m-labs.hk>
// This file is Copyright (c) 2015 whitequark <whitequark@whitequark.org>
// This file is Copyright (c) 2019 Ambroz Bizjak <ambrop7@gmail.com>
// This file is Copyright (c) 2019 Caleb Jamison <cbjamo@gmail.com>
// This file is Copyright (c) 2018 Dolu1990 <charles.papon.90@gmail.com>
// This file is Copyright (c) 2018 Felix Held <felix-github@felixheld.de>
// This file is Copyright (c) 2019 Gabriel L. Somlo <gsomlo@gmail.com>
// This file is Copyright (c) 2018 Jean-François Nguyen <jf@lambdaconcept.fr>
// This file is Copyright (c) 2018 Sergiusz Bazanski <q3k@q3k.org>
// This file is Copyright (c) 2016 Tim 'mithro' Ansell <mithro@mithis.com>

// License: BSD

#include <stdio.h>
#include <stdlib.h>
#include <console.h>
#include <string.h>
#include <uart.h>
#include <system.h>
#include <id.h>
#include <irq.h>
#include <crc.h>

#include <generated/csr.h>
#include <generated/mem.h>
#include <generated/git.h>

#ifdef CSR_ETHMAC_BASE
#include <net/microudp.h>
#endif

#ifdef CSR_SPIFLASH_BASE
#include <spiflash.h>
#endif

#ifdef CSR_ETHPHY_MDIO_W_ADDR
#include <mdio.h>
#endif

#include "sdram.h"
#include "boot.h"

/* General address space functions */
void lcd_clear(void);
void lcd_animate(void);
extern void boot_helper(unsigned long r1, unsigned long r2, unsigned long r3, unsigned long addr);
extern void __attribute__((noreturn)) boot(unsigned long r1, unsigned long r2, unsigned long r3, unsigned long addr);

#define NUMBER_OF_BYTES_ON_A_LINE 16
static void dump_bytes(unsigned int *ptr, int count, unsigned long addr)
{
	char *data = (char *)ptr;
	int line_bytes = 0, i = 0;

	putsnonl("Memory dump:");
	while(count > 0){
		line_bytes =
			(count > NUMBER_OF_BYTES_ON_A_LINE)?
				NUMBER_OF_BYTES_ON_A_LINE : count;

		printf("\n0x%08x  ", addr);
		for(i=0;i<line_bytes;i++)
			printf("%02x ", *(unsigned char *)(data+i));

		for(;i<NUMBER_OF_BYTES_ON_A_LINE;i++)
			printf("   ");

		printf(" ");

		for(i=0;i<line_bytes;i++) {
			if((*(data+i) < 0x20) || (*(data+i) > 0x7e))
				printf(".");
			else
				printf("%c", *(data+i));
		}

		for(;i<NUMBER_OF_BYTES_ON_A_LINE;i++)
			printf(" ");

		data += (char)line_bytes;
		count -= line_bytes;
		addr += line_bytes;
	}
	printf("\n");
}

static void mr(char *startaddr, char *len)
{
	char *c;
	unsigned int *addr;
	unsigned int length;

	if(*startaddr == 0) {
		printf("mr <address> [length]\n");
		return;
	}
	addr = (unsigned *)strtoul(startaddr, &c, 0);
	if(*c != 0) {
		printf("incorrect address\n");
		return;
	}
	if(*len == 0) {
		length = 4;
	} else {
		length = strtoul(len, &c, 0);
		if(*c != 0) {
			printf("incorrect length\n");
			return;
		}
	}

	dump_bytes(addr, length, (unsigned long)addr);
}

static void mw(char *addr, char *value, char *count)
{
	char *c;
	unsigned int *addr2;
	unsigned int value2;
	unsigned int count2;
	unsigned int i;

	if((*addr == 0) || (*value == 0)) {
		printf("mw <address> <value> [count]\n");
		return;
	}
	addr2 = (unsigned int *)strtoul(addr, &c, 0);
	if(*c != 0) {
		printf("incorrect address\n");
		return;
	}
	value2 = strtoul(value, &c, 0);
	if(*c != 0) {
		printf("incorrect value\n");
		return;
	}
	if(*count == 0) {
		count2 = 1;
	} else {
		count2 = strtoul(count, &c, 0);
		if(*c != 0) {
			printf("incorrect count\n");
			return;
		}
	}
	for (i=0;i<count2;i++) *addr2++ = value2;
}

static void mwi(char *addr, char *value, char *count)
{
	char *c;
	unsigned int *addr2;
	unsigned int value2;
	unsigned int count2;
	unsigned int i;

	if((*addr == 0) || (*value == 0)) {
		printf("mwi <address> <value> [count]\n");
		return;
	}
	addr2 = (unsigned int *)strtoul(addr, &c, 0);
	if(*c != 0) {
		printf("incorrect address\n");
		return;
	}
	value2 = strtoul(value, &c, 0);
	if(*c != 0) {
		printf("incorrect value\n");
		return;
	}
	if(*count == 0) {
		count2 = 1;
	} else {
		count2 = strtoul(count, &c, 0);
		if(*c != 0) {
			printf("incorrect count\n");
			return;
		}
	}
	for (i=0;i<count2;i++) *addr2++ = value2 + i;
}

static void mwa(char *addr, char *value, char *count)
{
	char *c;
	unsigned int *addr2;
	unsigned int value2;
	unsigned int count2;
	unsigned int i;

	if((*addr == 0) || (*value == 0)) {
		printf("mwa <address> <value> [count]\n");
		return;
	}
	addr2 = (unsigned int *)strtoul(addr, &c, 0);
	if(*c != 0) {
		printf("incorrect address\n");
		return;
	}
	value2 = strtoul(value, &c, 0);
	if(*c != 0) {
		printf("incorrect value\n");
		return;
	}
	if(*count == 0) {
		count2 = 1;
	} else {
		count2 = strtoul(count, &c, 0);
		if(*c != 0) {
			printf("incorrect count\n");
			return;
		}
	}
	for (i=0;i<count2;i++) {
	  *addr2 = value2 + (unsigned int) addr2;
	  addr2++;
	}
}

static void mmi(char *addr, char *value, char *count)
{
	char *c;
	unsigned int *addr2;
	unsigned int value2;
	unsigned int count2;
	unsigned int i;

	if((*addr == 0) || (*value == 0)) {
		printf("mmi <address> <value> [count]\n");
		return;
	}
	addr2 = (unsigned int *)strtoul(addr, &c, 0);
	if(*c != 0) {
		printf("incorrect address\n");
		return;
	}
	value2 = strtoul(value, &c, 0);
	if(*c != 0) {
		printf("incorrect value\n");
		return;
	}
	if(*count == 0) {
		count2 = 1;
	} else {
		count2 = strtoul(count, &c, 0);
		if(*c != 0) {
			printf("incorrect count\n");
			return;
		}
	}
	for (i=0;i<count2;i++) {
	  *addr2 = (*addr2 << 16) + value2 + i;
	  addr2++;
	}
}

static void mm(char *addr, char *value, char *count)
{
	char *c;
	unsigned int *addr2;
	unsigned int value2;
	unsigned int count2;
	unsigned int i;

	if((*addr == 0) || (*value == 0)) {
		printf("mm <address> <value> [count]\n");
		return;
	}
	addr2 = (unsigned int *)strtoul(addr, &c, 0);
	if(*c != 0) {
		printf("incorrect address\n");
		return;
	}
	value2 = strtoul(value, &c, 0);
	if(*c != 0) {
		printf("incorrect value\n");
		return;
	}
	if(*count == 0) {
		count2 = 1;
	} else {
		count2 = strtoul(count, &c, 0);
		if(*c != 0) {
			printf("incorrect count\n");
			return;
		}
	}
	for (i=0;i<count2;i++) {
	  *addr2 = *addr2 + value2;
	  addr2++;
	}
}

static void mc(char *dstaddr, char *srcaddr, char *count)
{
	char *c;
	unsigned int *dstaddr2;
	unsigned int *srcaddr2;
	unsigned int count2;
	unsigned int i;

	if((*dstaddr == 0) || (*srcaddr == 0)) {
		printf("mc <dst> <src> [count]\n");
		return;
	}
	dstaddr2 = (unsigned int *)strtoul(dstaddr, &c, 0);
	if(*c != 0) {
		printf("incorrect destination address\n");
		return;
	}
	srcaddr2 = (unsigned int *)strtoul(srcaddr, &c, 0);
	if(*c != 0) {
		printf("incorrect source address\n");
		return;
	}
	if(*count == 0) {
		count2 = 1;
	} else {
		count2 = strtoul(count, &c, 0);
		if(*c != 0) {
			printf("incorrect count\n");
			return;
		}
	}
	for (i=0;i<count2;i++) *dstaddr2++ = *srcaddr2++;
}

#if (defined CSR_SPIFLASH_BASE && defined SPIFLASH_PAGE_SIZE)
static void fw(char *addr, char *value, char *count)
{
	char *c;
	unsigned int addr2;
	unsigned int value2;
	unsigned int count2;
	unsigned int i;

	if((*addr == 0) || (*value == 0)) {
		printf("fw <offset> <value> [count]\n");
		return;
	}
	addr2 = strtoul(addr, &c, 0);
	if(*c != 0) {
		printf("incorrect offset\n");
		return;
	}
	value2 = strtoul(value, &c, 0);
	if(*c != 0) {
		printf("incorrect value\n");
		return;
	}
	if(*count == 0) {
		count2 = 1;
	} else {
		count2 = strtoul(count, &c, 0);
		if(*c != 0) {
			printf("incorrect count\n");
			return;
		}
	}
	for (i=0;i<count2;i++) write_to_flash(addr2 + i * 4, (unsigned char *)&value2, 4);
}

static void fe(void)
{
	erase_flash();
	printf("flash erased\n");
}
#endif

#ifdef CSR_ETHPHY_MDIO_W_ADDR
static void mdiow(char *phyadr, char *reg, char *val)
{
	char *c;
	unsigned int phyadr2;
	unsigned int reg2;
	unsigned int val2;

	if((*phyadr == 0) || (*reg == 0) || (*val == 0)) {
		printf("mdiow <phyadr> <reg> <value>\n");
		return;
	}
	phyadr2 = strtoul(phyadr, &c, 0);
	if(*c != 0) {
		printf("incorrect phyadr\n");
		return;
	}
	reg2 = strtoul(reg, &c, 0);
	if(*c != 0) {
		printf("incorrect reg\n");
		return;
	}
	val2 = strtoul(val, &c, 0);
	if(*c != 0) {
		printf("incorrect val\n");
		return;
	}
	mdio_write(phyadr2, reg2, val2);
}

static void mdior(char *phyadr, char *reg)
{
	char *c;
	unsigned int phyadr2;
	unsigned int reg2;
	unsigned int val;

	if((*phyadr == 0) || (*reg == 0)) {
		printf("mdior <phyadr> <reg>\n");
		return;
	}
	phyadr2 = strtoul(phyadr, &c, 0);
	if(*c != 0) {
		printf("incorrect phyadr\n");
		return;
	}
	reg2 = strtoul(reg, &c, 0);
	if(*c != 0) {
		printf("incorrect reg\n");
		return;
	}
	val = mdio_read(phyadr2, reg2);
	printf("reg %d: 0x%04x\n", reg2, val);
}

static void mdiod(char *phyadr, char *count)
{
	char *c;
	unsigned int phyadr2;
	unsigned int count2;
	unsigned int val;
	int i;

	if((*phyadr == 0) || (*count == 0)) {
		printf("mdiod <phyadr> <count>\n");
		return;
	}
	phyadr2 = strtoul(phyadr, &c, 0);
	if(*c != 0) {
		printf("incorrect phyadr\n");
		return;
	}
	count2 = strtoul(count, &c, 0);
	if(*c != 0) {
		printf("incorrect count\n");
		return;
	}
	printf("MDIO dump @0x%x:\n", phyadr2);
	for (i=0; i<count2; i++) {
		val = mdio_read(phyadr2, i);
		printf("reg %d: 0x%04x\n", i, val);
	}
}
#endif

static void crc(char *startaddr, char *len)
{
	char *c;
	char *addr;
	unsigned int length;

	if((*startaddr == 0)||(*len == 0)) {
		printf("crc <address> <length>\n");
		return;
	}
	addr = (char *)strtoul(startaddr, &c, 0);
	if(*c != 0) {
		printf("incorrect address\n");
		return;
	}
	length = strtoul(len, &c, 0);
	if(*c != 0) {
		printf("incorrect length\n");
		return;
	}

	printf("CRC32: %08x\n", crc32((unsigned char *)addr, length));
}

static void ident(void)
{
	char buffer[IDENT_SIZE];

	get_ident(buffer);
	printf("Ident: %s\n", buffer);
}

static unsigned int seed_to_data_32(unsigned int seed, int random)
{
	if (random)
		return 1664525*seed + 1013904223;
	else
		return seed + 1;
}

static unsigned short seed_to_data_16(unsigned short seed, int random)
{
	if (random)
		return 25173*seed + 13849;
	else
		return seed + 1;
}

#ifndef MEMTEST_DATA_SIZE
#define MEMTEST_DATA_SIZE (16*1024*1024)
#endif
#define MEMTEST_DATA_RANDOM 1

//#define MEMTEST_DATA_DEBUG

static unsigned int seed = 0;
static int memtest_data(void)
{
	volatile unsigned int *array = (unsigned int *)SRAM_EXT_BASE;
	int i, errors;
	unsigned int seed_32;
	unsigned int rdata;

	errors = 0;
	seed_32 = seed;

	for(i=0;i<MEMTEST_DATA_SIZE/4;i++) {
		seed_32 = seed_to_data_32(seed_32, MEMTEST_DATA_RANDOM);
		array[i] = seed_32;
		if( i % (1024 * 512) == 0 )
		  putchar('.');
	}
	putchar('\n');

	seed_32 = seed++;
	flush_cpu_dcache();
#ifdef CONFIG_L2_SIZE
	flush_l2_cache();
#endif
	for(i=0;i<MEMTEST_DATA_SIZE/4;i++) {
		seed_32 = seed_to_data_32(seed_32, MEMTEST_DATA_RANDOM);
		rdata = array[i];
		if( i % (1024 * 512) == 0 )
		  putchar('*');
		if(rdata != seed_32) {
			errors++;
#ifdef MEMTEST_DATA_DEBUG
			printf("[data 0x%0x]: 0x%08x vs 0x%08x\n", i, rdata, seed_32);
#endif
		}
	}
	putchar('\n');

	return errors;
}

#ifndef MEMTEST_ADDR_SIZE
#define MEMTEST_ADDR_SIZE (32*1024)
#endif
#define MEMTEST_ADDR_RANDOM 0

//#define MEMTEST_ADDR_DEBUG

static int memtest_addr(void)
{
	volatile unsigned int *array = (unsigned int *)SRAM_EXT_BASE;
	int i, errors;
	unsigned short seed_16;
	unsigned short rdata;

	errors = 0;
	seed_16 = (unsigned short) seed;

	for(i=0;i<MEMTEST_ADDR_SIZE/4;i++) {
		seed_16 = seed_to_data_16(seed_16, MEMTEST_ADDR_RANDOM);
		array[(unsigned int) seed_16] = i;
	}
	
	seed_16 = (unsigned short) seed++;
	flush_cpu_dcache();
#ifdef CONFIG_L2_SIZE
	flush_l2_cache();
#endif
	for(i=0;i<MEMTEST_ADDR_SIZE/4;i++) {
		seed_16 = seed_to_data_16(seed_16, MEMTEST_ADDR_RANDOM);
		rdata = array[(unsigned int) seed_16];
		if(rdata != i) {
			errors++;
#ifdef MEMTEST_ADDR_DEBUG
			printf("[addr 0x%0x]: 0x%08x vs 0x%08x\n", i, rdata, i);
#endif
		}
	}

	return errors;
}

static int smemtest(char *iter)
{
	int data_errors, addr_errors;
	int total_errors = 0;
	uint32_t iterations;
	char *c;

	if(*iter == 0)
	  iterations = 1;
	else
	  iterations = strtoul(iter, &c, 0);

	for( int i = 0; i < iterations; i++ ) {
	  data_errors = memtest_data();
	  if(data_errors != 0)
	    printf("Memtest data failed: %d/%d errors\n", data_errors, MEMTEST_DATA_SIZE/4);

	  addr_errors = memtest_addr();
	  if(addr_errors != 0)
	    printf("Memtest addr failed: %d/%d errors\n", addr_errors, MEMTEST_ADDR_SIZE/4);

	  total_errors += data_errors;
	  total_errors += addr_errors;
	}
	
	if(total_errors != 0)
	  return 0;
	else {
	  printf("Memtest OK\n");
	  return 1;
	}
}

/* Init + command line */

static void help(void)
{
	puts("LiteX BIOS, available commands:");
	puts("mr         - read address space");
	puts("mw         - write address space");
	puts("mwi        - write address space incrementing");
	puts("mwa        - write address space with address");
	puts("mmi        - modify memory with add and increment");
	puts("mm         - modify memory with add");
	puts("mc         - copy address space");
	puts("smemtest    - test sram memory");
#if (defined CSR_SPIFLASH_BASE && defined SPIFLASH_PAGE_SIZE)
	puts("fe         - erase whole flash");
	puts("fw         - write to flash");

#endif
#ifdef CSR_ETHPHY_MDIO_W_ADDR
	puts("mdiow      - write MDIO register");
	puts("mdior      - read MDIO register");
	puts("mdiod      - dump MDIO registers");
#endif
	puts("");
	puts("crc        - compute CRC32 of a part of the address space");
	puts("ident      - display identifier");
	puts("");
#ifdef CSR_CTRL_BASE
	puts("reboot     - reset processor");
#endif
#ifdef CSR_ETHMAC_BASE
	puts("netboot    - boot via TFTP");
#endif
	puts("serialboot - boot via SFL");
#ifdef FLASH_BOOT_ADDRESS
	puts("flashboot  - boot from flash");
#endif
#ifdef ROM_BOOT_ADDRESS
	puts("romboot    - boot from embedded rom");
#endif
	puts("");
#ifdef CSR_SDRAM_BASE
	puts("memtest    - run a memory test");
#endif
}

static char *get_token(char **str)
{
	char *c, *d;

	c = (char *)strchr(*str, ' ');
	if(c == NULL) {
		d = *str;
		*str = *str+strlen(*str);
		return d;
	}
	*c = 0;
	d = *str;
	*str = c+1;
	return d;
}

#ifdef CSR_CTRL_BASE
static void reboot(void)
{
	ctrl_reset_write(1);
}
#endif

static void do_command(char *c)
{
	char *token;

	token = get_token(&c);

	if(strcmp(token, "mr") == 0) mr(get_token(&c), get_token(&c));
	else if(strcmp(token, "mw") == 0) mw(get_token(&c), get_token(&c), get_token(&c));
	else if(strcmp(token, "mwi") == 0) mwi(get_token(&c), get_token(&c), get_token(&c));
	else if(strcmp(token, "mwa") == 0) mwa(get_token(&c), get_token(&c), get_token(&c));
	else if(strcmp(token, "mmi") == 0) mmi(get_token(&c), get_token(&c), get_token(&c));
	else if(strcmp(token, "mm") == 0) mm(get_token(&c), get_token(&c), get_token(&c));
	else if(strcmp(token, "mc") == 0) mc(get_token(&c), get_token(&c), get_token(&c));
#if (defined CSR_SPIFLASH_BASE && defined SPIFLASH_PAGE_SIZE)
	else if(strcmp(token, "fw") == 0) fw(get_token(&c), get_token(&c), get_token(&c));
	else if(strcmp(token, "fe") == 0) fe();
#endif
#ifdef CSR_ETHPHY_MDIO_W_ADDR
	else if(strcmp(token, "mdiow") == 0) mdiow(get_token(&c), get_token(&c), get_token(&c));
	else if(strcmp(token, "mdior") == 0) mdior(get_token(&c), get_token(&c));
	else if(strcmp(token, "mdiod") == 0) mdiod(get_token(&c), get_token(&c));
#endif
	else if(strcmp(token, "crc") == 0) crc(get_token(&c), get_token(&c));
	else if(strcmp(token, "ident") == 0) ident();

#ifdef CONFIG_L2_SIZE
	else if(strcmp(token, "flushl2") == 0) flush_l2_cache();
#endif
#ifdef CSR_CTRL_BASE
	else if(strcmp(token, "reboot") == 0) reboot();
#endif
#ifdef FLASH_BOOT_ADDRESS
	else if(strcmp(token, "flashboot") == 0) flashboot();
#endif
#ifdef ROM_BOOT_ADDRESS
	else if(strcmp(token, "romboot") == 0) romboot();
#endif
	else if(strcmp(token, "serialboot") == 0) serialboot();
#ifdef CSR_ETHMAC_BASE
	else if(strcmp(token, "netboot") == 0) netboot();
#endif

	else if(strcmp(token, "help") == 0) help();

#ifdef CSR_SDRAM_BASE
	else if(strcmp(token, "sdrrow") == 0) sdrrow(get_token(&c));
	else if(strcmp(token, "sdrsw") == 0) sdrsw();
	else if(strcmp(token, "sdrhw") == 0) sdrhw();
	else if(strcmp(token, "sdrrdbuf") == 0) sdrrdbuf(-1);
	else if(strcmp(token, "sdrrd") == 0) sdrrd(get_token(&c), get_token(&c));
	else if(strcmp(token, "sdrrderr") == 0) sdrrderr(get_token(&c));
	else if(strcmp(token, "sdrwr") == 0) sdrwr(get_token(&c));
#ifdef CSR_DDRPHY_BASE
	else if(strcmp(token, "sdrinit") == 0) sdrinit();
#ifdef CSR_DDRPHY_WLEVEL_EN_ADDR
	else if(strcmp(token, "sdrwlon") == 0) sdrwlon();
	else if(strcmp(token, "sdrwloff") == 0) sdrwloff();
#endif
	else if(strcmp(token, "sdrlevel") == 0) sdrlevel();
#endif
	else if(strcmp(token, "memtest") == 0) memtest();
#endif
	else if(strcmp(token, "smemtest") == 0) smemtest(get_token(&c));

	else if(strcmp(token, "lcdclear") == 0) lcd_clear();
	else if(strcmp(token, "lcdanimate") == 0) lcd_animate();
	else if(strcmp(token, "testboot") == 0) boot_helper(0, 0, 0, 0x20000000);
	//	else if(strcmp(token, "testboot2") == 0) boot(0, 0, 0, strtoul(get_token(&c), NULL, 0));


	else if(strcmp(token, "") != 0)
		printf("Command not found\n");
}

extern unsigned int _ftext, _edata;

static void crcbios(void)
{
	unsigned long offset_bios;
	unsigned long length;
	unsigned int expected_crc;
	unsigned int actual_crc;

	/*
	 * _edata is located right after the end of the flat
	 * binary image. The CRC tool writes the 32-bit CRC here.
	 * We also use the address of _edata to know the length
	 * of our code.
	 */
	offset_bios = (unsigned long)&_ftext;
	expected_crc = _edata;
	length = (unsigned long)&_edata - offset_bios;
	actual_crc = crc32((unsigned char *)offset_bios, length);
	if(expected_crc == actual_crc)
		printf(" BIOS CRC passed (%08x)\n", actual_crc);
	else {
		printf(" BIOS CRC failed (expected %08x, got %08x)\n", expected_crc, actual_crc);
		printf(" The system will continue, but expect problems.\n");
	}
}

static void readstr(char *s, int size)
{
	static char skip = 0;
	char c[2];
	int ptr;

	c[1] = 0;
	ptr = 0;
	while(1) {
		c[0] = readchar();
		if (c[0] == skip)
			continue;
		skip = 0;
		switch(c[0]) {
			case 0x7f:
			case 0x08:
				if(ptr > 0) {
					ptr--;
					putsnonl("\x08 \x08");
				}
				break;
			case 0x07:
				break;
			case '\r':
				skip = '\n';
				s[ptr] = 0x00;
				putsnonl("\n");
				return;
			case '\n':
				skip = '\r';
				s[ptr] = 0x00;
				putsnonl("\n");
				return;
			default:
				putsnonl(c);
				s[ptr] = c[0];
				ptr++;
				break;
		}
	}
}

static void boot_sequence(void)
{
	if(serialboot()) {
#ifdef FLASH_BOOT_ADDRESS
		flashboot();
#endif
#ifdef ROM_BOOT_ADDRESS
		romboot();
#endif
#ifdef CSR_ETHMAC_BASE
#ifdef CSR_ETHPHY_MODE_DETECTION_MODE_ADDR
		eth_mode();
#endif
		netboot();
#endif
		printf("No boot medium found\n");
	}
}

void lcd_clear(void) {
#ifndef SIMULATION
  
  int row, col;
  volatile unsigned int *lcd = (volatile unsigned int *)MEMLCD_BASE;

  memlcd_prescaler_write(49);
  for( row = 0; row < 536; row++ ) {
    for( col = 0; col < 11; col++ ) {
      lcd[ row * 11 + col ] = 0xffffffff;
    }
  }
  memlcd_command_write(1 << CSR_MEMLCD_COMMAND_UPDATEDIRTY_OFFSET);
  col++;
  while(memlcd_Busy_read())
    ;

  // clear all the dirty bits
  for( row = 0; row < 536; row++ ) {
      lcd[ row * 11 + 10 ] = 0xffff;
  }
  printf( "cleared: %d\n", col );
#endif  
}

void lcd_animate(void) {
#ifndef SIMULATION
  int row, col, offset;
  volatile unsigned int *lcd = (volatile unsigned int *)MEMLCD_BASE;

  offset = 0;
  while(1) {
    for( row = 100; row < 400; row++ ) {
      for( col = 0; col < 11; col++ ) {
	switch (offset % 4) {
	  case 0:
	    lcd[ row * 11 + col ] = 0xc003c003;
	    break;
	  case 1:
	    lcd[ row * 11 + col ] = 0x3c003c00;
	    break;
	  case 2:
	    lcd[ row * 11 + col ] = 0x03c003c0;
	    break;
	  case 3:
	    lcd[ row * 11 + col ] = 0x003c003c;
	    break;
	}
      }
    }
    memlcd_command_write(1 << CSR_MEMLCD_COMMAND_UPDATEDIRTY_OFFSET);
    offset ++;
    while(memlcd_Busy_read())
      ;
    printf("%d", offset);
  }
#endif
}

uint16_t lfsr(uint16_t in) {
	/* taps: 16 14 13 11; feedback polynomial: x^16 + x^14 + x^13 + x^11 + 1 */
	unsigned bit  = ((in >> 0) ^ (in >> 2) ^ (in >> 3) ^ (in >> 5) ) & 1;
	return (in >> 1) | (bit << 15);
};

int main(int i, char **c)
{
	char buffer[64];
	int sdr_ok;

#if BOOT_SIMULATION
	volatile unsigned int *mem;
	volatile unsigned char *mem_c;
	volatile unsigned char *foo = (unsigned char *) SRAM_BASE;

	sram_ext_read_config_write(1 << CSR_SRAM_EXT_READ_CONFIG_TRIGGER_OFFSET);
	int j;
	for( j = 0; j < 20; j++ ) { // delay while this runs
	  *foo = j;
	}
	
	mem = (volatile unsigned int *) 0x40000100;
	mem[0x4] = mem[0x20] + mem[0x31] + 0xfeedface;
	mem[0x50] = mem[0x64] + mem[0x75] + 0xdeadbeef;
	mem_c = (volatile unsigned char *) mem;
	mem_c[0x00] = mem_c[0x180] + mem_c[0x1a1] + 0xaa;
	mem_c[0x11] = mem_c[0x1b2] + mem_c[0x1c3] + 0x55;
	mem_c[0x22] = mem_c[0x1d4] + mem_c[0x1e5] + 0x33;
	mem_c[0x33] = mem_c[0x1f6] + mem_c[0x207] + 0xcc;
#endif
#if LCD_SIMULATION
	volatile unsigned int *lcd = (volatile unsigned int *)MEMLCD_BASE;

	lcd_clear();
	lcd_animate();

	memlcd_prescaler_write(49); // set to 2MHz clock (top speed allowed)
	lcd[535*11 + 10] = 0x10001;  // set a dirty bit on the last line
	lcd[535*11] = 0x1111face; // put data at the beginning of the last line

	lcd[10] = 0x07006006;
	lcd[0] = 0x80000001;
	lcd[1] = 0x40000002;
	memlcd_command_write(1 << CSR_MEMLCD_COMMAND_UPDATEDIRTY_OFFSET);
	while(memlcd_Busy_read())
	  ;
#endif
#if COM_SIMULATION
	volatile unsigned int *mem;
	mem = (volatile unsigned int *) 0x40000000;
	
	spislave_control_write(1 << CSR_SPISLAVE_CONTROL_INTENA_OFFSET);
	
	spislave_tx_write(0x0F0F);
	spimaster_tx_write(0xf055);
	spimaster_control_write(1 << CSR_SPIMASTER_CONTROL_GO_OFFSET |
				1 << CSR_SPIMASTER_CONTROL_INTENA_OFFSET);
	// note: if spiclk > cpuclock, the below line should be commented out on all transactons
	while( !(spimaster_status_read() & (1 << CSR_SPIMASTER_STATUS_TIP_OFFSET)) )
	  ;
	while( spimaster_status_read() & (1 << CSR_SPIMASTER_STATUS_TIP_OFFSET) )
	  ;
	spimaster_control_write(0);
	mem[0] = spimaster_rx_read();
	mem[1] = spislave_rx_read();
	
	spislave_tx_write(0x1234);
	spimaster_tx_write(0x90F1);
	spimaster_control_write(1 << CSR_SPIMASTER_CONTROL_GO_OFFSET |
				1 << CSR_SPIMASTER_CONTROL_INTENA_OFFSET);
	while( !(spimaster_status_read() & (1 << CSR_SPIMASTER_STATUS_TIP_OFFSET)) )
	  ;
	while( spimaster_status_read() & (1 << CSR_SPIMASTER_STATUS_TIP_OFFSET) )
	  ;
	spimaster_control_write(0);
	mem[2] = spimaster_rx_read();
	// mem[3] = spislave_rx_read();  // test overrun flag

	
	spislave_tx_write(0x89ab);
	spimaster_tx_write(0xbabe);
	spimaster_control_write(1 << CSR_SPIMASTER_CONTROL_GO_OFFSET |
				1 << CSR_SPIMASTER_CONTROL_INTENA_OFFSET);
	while( !(spimaster_status_read() & (1 << CSR_SPIMASTER_STATUS_TIP_OFFSET)) )
	  ;
	while( spimaster_status_read() & (1 << CSR_SPIMASTER_STATUS_TIP_OFFSET) )
	  ;
	spimaster_control_write(0);
	mem[4] = spimaster_rx_read();
	mem[5] = spislave_rx_read();

	
	spislave_tx_write(0xcdef);
	spimaster_tx_write(0x3c06);
	spimaster_control_write(1 << CSR_SPIMASTER_CONTROL_GO_OFFSET |
				1 << CSR_SPIMASTER_CONTROL_INTENA_OFFSET);
	while( !(spimaster_status_read() & (1 << CSR_SPIMASTER_STATUS_TIP_OFFSET)) )
	  ;
	while( spimaster_status_read() & (1 << CSR_SPIMASTER_STATUS_TIP_OFFSET) )
	  ;
	spimaster_control_write(0);
	mem[6] = spimaster_rx_read();
	mem[7] = spislave_rx_read();

	spislave_control_write(1 << CSR_SPISLAVE_CONTROL_CLRERR_OFFSET);

	spislave_tx_write(0xff00);
	spimaster_tx_write(0x5a5a);
	spimaster_control_write(1 << CSR_SPIMASTER_CONTROL_GO_OFFSET |
				1 << CSR_SPIMASTER_CONTROL_INTENA_OFFSET);
	while( !(spimaster_status_read() & (1 << CSR_SPIMASTER_STATUS_TIP_OFFSET)) )
	  ;
	while( spimaster_status_read() & (1 << CSR_SPIMASTER_STATUS_TIP_OFFSET) )
	  ;
	spimaster_control_write(0);
	mem[8] = spimaster_rx_read();
	mem[9] = spislave_rx_read();

	// write performance benchmark
	for(i = 0; i < 16; i++ ) {
	  spimaster_tx_write(i + 0x4c00);
	  spimaster_control_write(1 << CSR_SPIMASTER_CONTROL_GO_OFFSET);
	  // simulations show the below is critical in poll loops for sysclk=100MHz, spclk=25MHz
	  while( !(spimaster_status_read() & (1 << CSR_SPIMASTER_STATUS_TIP_OFFSET)) )
	    ;
	  while( spimaster_status_read() & (1 << CSR_SPIMASTER_STATUS_TIP_OFFSET) )
	    ;
	  spimaster_control_write(0);
	  mem[i+10] = spislave_rx_read();
	}
	
#endif
#if 0 // deprecated com simulation
	int j;
	for( j = 0; j < 8; j ++ ) {
	  spimaster_control_write(1 << CSR_SPIMASTER_CONTROL_CLRDONE_OFFSET);
	  while( spimaster_status_read() & (1 << CSR_SPIMASTER_STATUS_DONE_OFFSET) )
	    ;
	  spimaster_tx_write(0xa500 + i);
	  spimaster_control_write(1 << CSR_SPIMASTER_CONTROL_GO_OFFSET);
	  while( !(spimaster_status_read() & (1 << CSR_SPIMASTER_STATUS_DONE_OFFSET)) )
	    ;
	}
	
#endif
#if KBD_SIMULATION
	while( !keyboard_ev_pending_read() )
	  ;
	keyboard_ev_pending_write(1);
	
#endif
#if SPIFLASH_SIMULATION
    volatile unsigned int dest[1024];
    int j;
    volatile unsigned int *rom = (volatile unsigned int *)SPIFLASH_BASE;

    // sequential read of 64 words starting at 0; this should be 8 cache lines (8 x 32-bit words cache line)
    for( j = 0; j < 64; j ++ ) {
      dest[j] = rom[j];
    }
    // do a simple read
    uint16_t r = 0xF0AA;
    for( j = 0; j < 32; j ++ ) {
      dest[j] = rom[r & (1024-1)];
      r = lfsr(r);
    }

    r = 1;
    for( j = 0; j < 32; j++ ) {
      r = lfsr(r);
      dest[r & (1024-1)] = 0xBEEF0000 + j;
    }
#endif
	sram_ext_read_config_write(1 << CSR_SRAM_EXT_READ_CONFIG_TRIGGER_OFFSET);
	
	irq_setmask(0);
	irq_setie(1);
	uart_init();

	printf("\n");
	printf("\e[1m        __   _ __      _  __\e[0m\n");
	printf("\e[1m       / /  (_) /____ | |/_/\e[0m\n");
	printf("\e[1m      / /__/ / __/ -_)>  <\e[0m\n");
	printf("\e[1m     /____/_/\\__/\\__/_/|_|\e[0m\n");
	printf("\n");
	printf(" (c) Copyright 2012-2019 Enjoy-Digital\n");
	printf("\n");
	printf(" BIOS built on "__DATE__" "__TIME__"\n");
	crcbios();
	printf("\n");
	printf(" Migen git sha1: "MIGEN_GIT_SHA1"\n");
	printf(" LiteX git sha1: "LITEX_GIT_SHA1"\n");
	printf("\n");
	printf("--=============== \e[1mSoC\e[0m ==================--\n");
	printf("\e[1mCPU\e[0m:       ");
#ifdef __lm32__
	printf("LM32");
#elif __or1k__
	printf("MOR1KX");
#elif __picorv32__
	printf("PicoRV32");
#elif __vexriscv__
	printf("VexRiscv");
#elif __minerva__
	printf("Minerva");
#elif __rocket__
	printf("RocketRV64[imac]");
#else
	printf("Unknown");
#endif
	printf(" @ %dMHz\n", CONFIG_CLOCK_FREQUENCY/1000000);
	printf("\e[1mROM\e[0m:       %dKB\n", ROM_SIZE/1024);
	printf("\e[1mSRAM\e[0m:      %dKB\n", SRAM_SIZE/1024);
#ifdef CONFIG_L2_SIZE
	printf("\e[1mL2\e[0m:        %dKB\n", CONFIG_L2_SIZE/1024);
#endif
#ifdef MAIN_RAM_SIZE
	printf("\e[1mMAIN-RAM\e[0m:  %dKB\n", MAIN_RAM_SIZE/1024);
#endif
	printf("\n");

	printf("--========= \e[1mPeripherals init\e[0m ===========--\n");
	printf("EXT SRAM config: 0x%08x\n", sram_ext_config_status_read());
	/*
	lcd_clear();
	printf("LCD cleared\n");

	printf("Now animating LCD\n");
	lcd_animate();
	*/

	sdr_ok = 1;
#if defined(CSR_ETHMAC_BASE) || defined(CSR_SDRAM_BASE)
	printf("--========== \e[1mInitialization\e[0m ============--\n");
#ifdef CSR_ETHMAC_BASE
	eth_init();
#endif
#ifdef CSR_SDRAM_BASE
	sdr_ok = sdrinit();
#else
#ifdef MAIN_RAM_TEST
	sdr_ok = memtest();
#endif
#endif
	if (sdr_ok !=1)
		printf("Memory initialization failed\n");
	printf("\n");
#endif

	if(sdr_ok) {
		printf("--============== \e[1mBoot\e[0m ==================--\n");
		boot_sequence();
		printf("\n");
	}

	printf("--============= \e[1mConsole\e[0m ================--\n");
	while(1) {
		putsnonl("\e[92;1mlitex\e[0m> ");
		readstr(buffer, 64);
		do_command(buffer);
	}
	return 0;
}
