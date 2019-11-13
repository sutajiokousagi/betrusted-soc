#![no_main]

#![feature(lang_items)]
#![feature(alloc_error_handler)]

#![no_std]

use core::panic::PanicInfo;
use riscv_rt::entry;

extern "C" {
    static _sheap: u8;
    static _heap_size: u8;
}

// Plug in the allocator crate
extern crate alloc;
extern crate alloc_riscv;

use alloc_riscv::RiscvHeap;

#[global_allocator]
static ALLOCATOR: RiscvHeap = RiscvHeap::empty();

extern crate betrusted_hal;

const CONFIG_CLOCK_FREQUENCY: u32 = 100_000_000;

// allocate a global, unsafe static string for debug output
#[used] // This is necessary to keep DBGSTR from being optimized out
static mut DBGSTR: [u32; 4] = [0, 0, 0, 0];

#[panic_handler]
fn panic(_panic: &PanicInfo<'_>) -> ! {
    loop {}
}

#[alloc_error_handler]
fn alloc_error_handler(layout: alloc::alloc::Layout) -> ! {
    unsafe{ DBGSTR[3] = layout.size() as u32; }
    panic!()
}

#[entry]
fn main() -> ! {
    use betrusted_hal::hal_i2c::hal_i2c::*;
    use betrusted_hal::hal_time::hal_time::*;
    use betrusted_hal::hal_lcd::hal_lcd::*;
    use alloc::vec::Vec;

    let p = betrusted_pac::Peripherals::take().unwrap();

    i2c_init(&p, CONFIG_CLOCK_FREQUENCY / 1_000_000);
    time_init(&p);

    lcd_init(&p, CONFIG_CLOCK_FREQUENCY);
    lcd_clear(&p);

    unsafe {
        let heap_start = &_sheap as *const u8 as usize;
        let heap_size = &_heap_size as *const u8 as usize;
        ALLOCATOR.init(heap_start, heap_size)
    }

    let mut v: Vec <u32> = Vec::new();
    v.push(!1);
    v.push(!2);
    v.push(!4);
    v.push(!8);
    v.push(8);
    v.push(4);
    v.push(2);
    v.push(1);

    loop {

        for pattern in v.iter() {
            lcd_pattern(&p, *pattern);
        }
        /*
        lcd_pattern(&p, !(1 << i));
        i += 1;
        if i >= 32 {
            i = 0;
        }
        */
        /*
        delay_ms(&p, 500);
        unsafe{ DBGSTR[0] = 4; }

        delay_ms(&p, 500);
        unsafe{ DBGSTR[0] = 8; }
        */
    }
}
