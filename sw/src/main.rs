#![no_main]

#![feature(lang_items)]
#![feature(alloc_error_handler)]

#![no_std]

use core::panic::PanicInfo;
use riscv_rt::entry;

// pull in external symbols to define heap start and stop
// defined in memory.x
extern "C" {
    static _sheap: u8;
    static _heap_size: u8;
}

// Plug in the allocator crate
#[macro_use]
extern crate alloc;
extern crate alloc_riscv;

use alloc_riscv::RiscvHeap;

#[global_allocator]
static ALLOCATOR: RiscvHeap = RiscvHeap::empty();

extern crate betrusted_hal;

const CONFIG_CLOCK_FREQUENCY: u32 = 100_000_000;

// allocate a global, unsafe static string for debug output
#[used] // This is necessary to keep DBGSTR from being optimized out
static mut DBGSTR: [u32; 8] = [0, 0, 0, 0, 0, 0, 0, 0];

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
    use embedded_graphics::prelude::*;
    use embedded_graphics::egcircle;
    use embedded_graphics::pixelcolor::BinaryColor;
    use embedded_graphics::fonts::Font12x16;
    use alloc::vec::Vec;

    let p = betrusted_pac::Peripherals::take().unwrap();

    i2c_init(&p, CONFIG_CLOCK_FREQUENCY / 1_000_000);
    time_init(&p);

    unsafe {
        let heap_start = &_sheap as *const u8 as usize;
        let heap_size = &_heap_size as *const u8 as usize;
        ALLOCATOR.init(heap_start, heap_size);
        DBGSTR[4] = heap_start as u32;  // some debug visibility on heap initial parameters
        DBGSTR[6] = heap_size as u32;
    }

    let display: BetrustedDisplay = BetrustedDisplay::new();
    display.init(CONFIG_CLOCK_FREQUENCY);
    display.clear();

    let radius: i32 = 14;
    let mut x: i32 = 12;
    let mut y: i32 = 30;
    let mut vector: Point = Point::new(2,3);
    let rand: Vec<i32> = vec![2, 1, 3, 5, 2, 3, 2, 4, 1, 2, 2];
    let mut index: usize = 0;
    loop {
        let mut display: BetrustedDisplay = BetrustedDisplay::new();
        display.clear();
        Font12x16::render_str("Hello World!")
        .stroke_color(Some(BinaryColor::On))
        .translate(Point::new(25,10))
        .draw(&mut display);

        let circle = egcircle!((x, y), radius as u32, 
                               stroke_color = Some(BinaryColor::Off), fill_color = Some(BinaryColor::On));
        circle.draw(&mut display);

        x = x + vector.x; y = y + vector.y;
        if (x >= (display.size().width as i32 - radius)) || (x <= radius) ||   
           (y >= (display.size().height as i32 - radius)) || (y <= radius) {
            if x >= (display.size().width as i32 - radius) {
                vector.x = -rand[index];
            }
            if x <= radius {
                vector.x = rand[index];
            }
            if y >= (display.size().height as i32 - radius) {
                vector.y = -rand[index];
            }
            if y <= radius {
                vector.y = rand[index];
            }
            index += 1;
            index = index % rand.len();
        }
        display.flush().unwrap();
    }
    /*
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
    } */
}
