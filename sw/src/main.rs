#![no_main]
#![no_std]

use core::panic::PanicInfo;
use riscv_rt::entry;
//use riscv_semihosting::hprintln;

extern crate betrusted_hal;

const CONFIG_CLOCK_FREQUENCY: u32 = 100_000_000;

// allocate a global, unsafe static string for debug output
#[used] // This is necessary to keep DBGSTR from being optimized out
static mut DBGSTR: [u32; 4] = [0, 0, 0, 0];

#[panic_handler]
fn panic(_panic: &PanicInfo<'_>) -> ! {
    loop {}
}

#[entry]
fn main() -> ! {
    use betrusted_hal::hal_i2c::hal_i2c::*;
    use betrusted_hal::hal_time::hal_time::*;
    use betrusted_hal::hal_lcd::hal_lcd::*;

    let p = betrusted_pac::Peripherals::take().unwrap();

    i2c_init(&p, CONFIG_CLOCK_FREQUENCY / 1_000_000);
    time_init(&p);

    lcd_init(&p, CONFIG_CLOCK_FREQUENCY);
    lcd_clear(&p);

    let mut i : u32 = 0;
    loop {
        // hprintln!("Hello world!").unwrap();

        lcd_pattern(&p, !(1 << i));
        i += 1;
        if i >= 32 {
            i = 0;
        }
        /*
        delay_ms(&p, 500);
        unsafe{ DBGSTR[0] = 4; }

        delay_ms(&p, 500);
        unsafe{ DBGSTR[0] = 8; }
        */
    }
}
