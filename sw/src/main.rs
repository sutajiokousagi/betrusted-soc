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

    let display: LockedBetrustedDisplay = LockedBetrustedDisplay::new();
    display.lock().init(CONFIG_CLOCK_FREQUENCY);
    display.lock().clear();

    let radius: i32 = 14;
    let mut x: i32 = 12;
    let mut y: i32 = 30;
    let mut vector: Point = Point::new(2,3);
    let rand: Vec<i32> = vec![6, 2, 3, 5, 8, 3, 2, 4, 3, 8, 2];
    let mut index: usize = 0;
    loop {
        display.lock().clear();
        Font12x16::render_str("Hello World!")
        .stroke_color(Some(BinaryColor::On))
        .translate(Point::new(25,10))
        .draw(&mut display.lock() as &mut BetrustedDisplay);

        let circle = egcircle!((x, y), radius as u32, 
                               stroke_color = Some(BinaryColor::Off), fill_color = Some(BinaryColor::On));
        circle.draw(&mut display.lock() as &mut BetrustedDisplay);
        
        x = x + vector.x; y = y + vector.y;
        let size: Size = display.lock().size();
        if (x >= (size.width as i32 - radius)) || (x <= radius) ||   
           (y >= (size.height as i32 - radius)) || (y <= radius) {
            if x >= (size.width as i32 - radius) {
                vector.x = -rand[index];
                x = size.width as i32 - radius;
            }
            if x <= radius {
                vector.x = rand[index];
                x = radius;
            }
            if y >= (size.height as i32 - radius) {
                vector.y = -rand[index];
                y = size.height as i32 - radius;
            }
            if y <= radius {
                vector.y = rand[index];
                y = radius;
            }
            index += 1;
            index = index % rand.len();
        }
        display.lock().flush().unwrap();
    }
}
