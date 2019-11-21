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
fn panic(_panic_info: &PanicInfo<'_>) -> ! {
    // if I include this code, the system hangs.
    /*
    let dbg = panic_info.payload().downcast_ref::<&str>();
    match dbg {
        None => unsafe{ DBGSTR[0] = 0xDEADBEEF; }
        _ => unsafe{ DBGSTR[0] = 0xFEEDFACE; }
        _ => unsafe{ DBGSTR[0] = dbg.unwrap().as_ptr() as u32; }  // this causes crashes????
    }
    */
    loop {}
}

#[alloc_error_handler]
fn alloc_error_handler(layout: alloc::alloc::Layout) -> ! {
    unsafe{ DBGSTR[0] = layout.size() as u32; }
    panic!()
}

use betrusted_hal::hal_i2c::*;
use betrusted_hal::hal_time::*;
use betrusted_hal::hal_lcd::*;
use betrusted_hal::hal_com::*;
use betrusted_hal::hal_kbd::*;
use embedded_graphics::prelude::*;
use embedded_graphics::egcircle;
use embedded_graphics::pixelcolor::BinaryColor;
use embedded_graphics::fonts::Font12x16;
use embedded_graphics::fonts::Font8x16;
use embedded_graphics::geometry::Point;
use embedded_graphics::primitives::Rectangle;
use embedded_graphics::primitives::Line;
use alloc::vec::Vec;
use alloc::string::String;

pub struct Bounce {
    vector: Point,
    radius: u32,
    bounds: Rectangle<BinaryColor>,
    rand: Vec<i32>,
    rand_index: usize,
    loc: Point,
}

impl Bounce {
    pub fn new(radius: u32, bounds: Rectangle<BinaryColor>) -> Bounce {
        Bounce {
            vector: Point::new(2,3),
            radius: radius,
            bounds: bounds,
            rand: vec![6, 2, 3, 5, 8, 3, 2, 4, 3, 8, 2],
            rand_index: 0,
            loc: Point::new((bounds.bottom_right.x - bounds.top_left.x)/2, (bounds.bottom_right.y - bounds.top_left.y)/2),
        }

    }

    pub fn update(&mut self) -> &mut Self {
        let mut x: i32;
        let mut y: i32;
        // update the new ball location
        x = self.loc.x + self.vector.x; y = self.loc.y + self.vector.y;

        let r: i32 = self.radius as i32;
        if (x >= (self.bounds.bottom_right().x as i32 - r)) || 
           (x <= (self.bounds.top_left().x + r)) ||   
           (y >= (self.bounds.bottom_right().y as i32 - r)) || 
           (y <= (self.bounds.top_left().y + r)) {
            if x >= (self.bounds.bottom_right().x as i32 - r) {
                self.vector.x = -self.rand[self.rand_index];
                x = self.bounds.bottom_right().x as i32 - r;
            }
            if x <= self.bounds.top_left().x + r {
                self.vector.x = self.rand[self.rand_index];
                x = self.bounds.top_left().x + r;
            }
            if y >= (self.bounds.bottom_right().y as i32 - r) {
                self.vector.y = -self.rand[self.rand_index];
                y = self.bounds.bottom_right().y as i32 - r;
            }
            if y <= (self.bounds.top_left().y + r) {
                self.vector.y = self.rand[self.rand_index];
                y = self.bounds.top_left().y + r;
            }
            self.rand_index += 1;
            self.rand_index = self.rand_index % self.rand.len();
        }

        self.loc.x = x;
        self.loc.y = y;

        self
    }
}

pub struct Repl {
    /// PAC access for commands
    p: betrusted_pac::Peripherals,
    /// current line being typed in
    input: String,
    /// last fully-formed line
    cmd: String,
    /// output response
    output: String,
    /// power state variable
    power: bool,
}

const PROMPT: &str = "bt> ";

impl Repl {
    pub fn new() -> Self {
        unsafe {
            Repl {
                p: betrusted_pac::Peripherals::steal(),
                input: String::from(PROMPT),
                cmd: String::from(" "),
                output: String::from("Awaiting input."),
                power: true,
            }
        }
    }

    pub fn input_char(&mut self, c: char) {
        if c.is_ascii() && !c.is_control() {
            self.input.push(c);
        } else if c == 0x8_u8.into() { // backspace
            if self.input.len() > PROMPT.len() {
                self.input.pop();
            }
        } else if c == 0xd_u8.into() { // carriage return
            self.cmd = self.input.clone();
            self.cmd.drain(..PROMPT.len());
            self.input = String::from(PROMPT);

            self.parse_cmd(); // now try parsing the command
        }
    }

    pub fn get_cmd(&self) -> String {
        self.cmd.clone()
    }

    pub fn get_input(&self) -> String {
        self.input.clone()
    }

    pub fn get_powerstate(self) -> bool {
        self.power
    }

    pub fn force_poweroff(&mut self) {
        self.power = false;
    }

    pub fn parse_cmd(&mut self) {
        if self.cmd.len() == 0 {
            return;
        } else {
            if self.cmd.trim() == "shutdown" {
                self.output = String::from("Shutting down system");
                self.power = false; // the main UI loop needs to pick this up and render the display accordingly
            } else if self.cmd.trim() == "buzz" {
                self.output = String::from("Making a buzz");
                unsafe{ self.p.GPIO.drive.write(|w| w.bits(4)); }
                unsafe{ self.p.GPIO.output.write(|w| w.bits(4)); }
                let time: u32 = get_time_ms(&self.p);
                while get_time_ms(&self.p) - time < 250 { }
                unsafe{ self.p.GPIO.output.write(|w| w.bits(4)); }
            } else {
                self.output = String::from(self.cmd.trim());
                self.output.push_str(": not recognized.");
            }
        }
    }

    pub fn get_output(&self )-> String {
        self.output.clone()
    }
}

#[entry]
fn main() -> ! {
    let p = betrusted_pac::Peripherals::take().unwrap();
    com_txrx(&p, 0x9003 as u16);  // 0x90cc specifies power set command. bit 0 set means EC stays on; bit 1 means power SoC on
    unsafe{ p.POWER.power.write(|w| w.self_().bit(true).state().bits(3)); }

    p.SRAM_EXT.read_config.write( |w| w.trigger().bit(true) );  // check SRAM config
    i2c_init(&p, CONFIG_CLOCK_FREQUENCY / 1_000_000);
    time_init(&p);

    let cr = p.SRAM_EXT.config_status0.read().bits(); // pull out config params for debug
    unsafe {
        let heap_start = &_sheap as *const u8 as usize;
        let heap_size = &_heap_size as *const u8 as usize;
        ALLOCATOR.init(heap_start, heap_size);
        DBGSTR[4] = heap_start as u32;  // some debug visibility on heap initial parameters
        DBGSTR[6] = heap_size as u32;
        DBGSTR[2] = cr;
    }

    let display: LockedBtDisplay = LockedBtDisplay::new();
    display.lock().init(CONFIG_CLOCK_FREQUENCY);

    let mut keyboard: KeyManager = KeyManager::new();

    // initialize vibe motor patch
    unsafe{ p.GPIO.drive.write(|w| w.bits(4)); }
    unsafe{ p.GPIO.output.write(|w| w.bits(0)); }
    //let mut elapsed: u32 = get_time_ms(&p);
    //let mut vibetime: u32 = 1000;

    let radius: u32 = 14;
    let size: Size = display.lock().size();
    let mut cur_time: u32 = get_time_ms(&p);
    let mut stat_array: [u16; 10] = [0; 10];
    let mut line_height: i32 = 18;
    let left_margin: i32 = 10;
    let mut bouncy_ball: Bounce = Bounce::new(radius, Rectangle::new(Point::new(0, line_height * 13), Point::new(size.width as i32, size.height as i32)));
    let mut tx_index: usize = 0;
    let mut repl: Repl = Repl::new();

    let mut nd: u8 = 0;
    let mut d1: char = ' ';
    let mut d2: char = ' ';
    let mut nu: u8 = 0;
    let mut u1: char = ' ';
    let mut u2: char = ' ';
    loop {
        display.lock().clear();
        if repl.power == false {
            Font12x16::render_str("Betrusted in Standby")
            .stroke_color(Some(BinaryColor::On))
            .translate(Point::new(50, 250))
            .draw(&mut *display.lock());

            Font12x16::render_str("Press '0' to power on")
            .stroke_color(Some(BinaryColor::On))
            .translate(Point::new(40, 270))
            .draw(&mut *display.lock());

            display.lock().blocking_flush();

            unsafe{p.POWER.power.write(|w| w.self_().bit(false).state().bits(1));} // FIXME: figure out how to float the state bit while system is running...
            com_txrx(&p, 0x9005 as u16);  // 0x90cc specifies power set command. bit 0 set means EC stays on; bit 2 set means fast discharge of FPGA domain

            continue; // this creates the illusion of being powered off even if we're plugged in
        }
        let mut cur_line: i32 = 5;

        let uptime = format!{"Uptime {}s", (get_time_ms(&p) / 1000) as u32};
        line_height = 18;
        Font12x16::render_str(&uptime)
        .stroke_color(Some(BinaryColor::On))
        .translate(Point::new(left_margin,cur_line))
        .draw(&mut *display.lock());
        cur_line += line_height;

        // power state testing ONLY - force a power off in 5 seconds
        /*
        if get_time_ms(&p) > 5000 {
            repl.force_poweroff();
        }
        */
        /*
        // pulse the motor once every second
        if get_time_ms(&p) - elapsed > vibetime {
            if vibetime > 500 {
                unsafe{ p.GPIO.output.write(|w| w.bits(4)); }
                vibetime = 250;
            } else {
                unsafe{ p.GPIO.output.write(|w| w.bits(0)); }
                vibetime = 1000;
            }
            elapsed = get_time_ms(&p);
        }*/

        bouncy_ball.update();
        let circle = egcircle!(bouncy_ball.loc, bouncy_ball.radius, 
                               stroke_color = Some(BinaryColor::Off), fill_color = Some(BinaryColor::On));
        circle.draw(&mut *display.lock());
        
        // ping the EC and update various records over time
        if get_time_ms(&p) - cur_time > 100 {
            cur_time = get_time_ms(&p);
            if tx_index == 0 {
                com_txrx(&p, 0x8000 as u16); // send the pointer reset command
            } else if tx_index < stat_array.len() + 1 {
                stat_array[tx_index - 1] = com_txrx(&p, 0xDEAD) as u16; // the transmit is a dummy byte
            }
            tx_index += 1;
            tx_index = tx_index % (stat_array.len() + 2);
        }

        for i in 0..4 {
            // but update the result every loop iteration
            let dbg = format!{"s{}: 0x{:04x}  s{}: 0x{:04x}", i*2, stat_array[i*2], i*2+1, stat_array[i*2+1]};
            Font12x16::render_str(&dbg)
            .stroke_color(Some(BinaryColor::On))
            .translate(Point::new(left_margin, cur_line))
            .draw(&mut *display.lock());
            cur_line += line_height;
        }
        let dbg = format!{"voltage: {}mV", stat_array[7]};
        Font12x16::render_str(&dbg)
        .stroke_color(Some(BinaryColor::On))
        .translate(Point::new(left_margin, cur_line))
        .draw(&mut *display.lock());

        cur_line += line_height;
        let dbg = format!{"avg current: {}mA", (stat_array[9] as i16)};
        Font12x16::render_str(&dbg)
        .stroke_color(Some(BinaryColor::On))
        .translate(Point::new(left_margin, cur_line))
        .draw(&mut *display.lock());

        cur_line += line_height;
        let dbg = format!{"sby current: {}mA", (stat_array[8] as i16)};
        Font12x16::render_str(&dbg)
        .stroke_color(Some(BinaryColor::On))
        .translate(Point::new(left_margin, cur_line))
        .draw(&mut *display.lock());

        let (keydown, keyup) = keyboard.update();
        if keydown.is_some() { 
            let mut keyvect = keydown.unwrap();
            nd = keyvect.len() as u8;
            
            if nd >= 1 {
                let (r, c) = keyvect.pop().unwrap();
                let scancode = map_dvorak((r,c));
                let c: char;
                match scancode.key {
                    None => c = ' ',
                    _ => c = scancode.key.unwrap(),
                }
                d1 = c;
                repl.input_char(c);
            }
            if nd >= 2 {
                let (r, c) = keyvect.pop().unwrap();
                let scancode = map_dvorak((r,c));
                let c: char;
                match scancode.key {
                    None => c = ' ',
                    _ => c = scancode.key.unwrap(),
                }
                d2 = c;
            }
        }

        if keyup.is_some() { 
            let mut keyvect = keyup.unwrap();
            nu = keyvect.len() as u8;
            
            if nu >= 1 {
                let (r, c) = keyvect.pop().unwrap();
                let scancode = map_dvorak((r,c));
                let c: char;
                match scancode.key {
                    None => c = ' ',
                    _ => c = scancode.key.unwrap(),
                }
                u1 = c;
            }
            if nu >= 2 {
                let (r, c) = keyvect.pop().unwrap();
                let scancode = map_dvorak((r,c));
                let c: char;
                match scancode.key {
                    None => c = ' ',
                    _ => c = scancode.key.unwrap(),
                }
                u2 = c;
            }
        }

        cur_line += line_height;
        let dbg = format!{"nd:{} d1:{} d2:{}", nd, d1, d2};
        Font12x16::render_str(&dbg)
        .stroke_color(Some(BinaryColor::On))
        .translate(Point::new(left_margin, cur_line))
        .draw(&mut *display.lock());

        cur_line += line_height;
        let dbg = format!{"nu:{} u1:{} u2:{}", nu, u1, u2};
        Font12x16::render_str(&dbg)
        .stroke_color(Some(BinaryColor::On))
        .translate(Point::new(left_margin, cur_line))
        .draw(&mut *display.lock());
        
        // draw a demarcation line
        cur_line += line_height + 2;
        Line::<BinaryColor>::new(Point::new(left_margin, cur_line), 
        Point::new(size.width as i32 - left_margin, cur_line))
        .stroke_color(Some(BinaryColor::On))
        .draw(&mut *display.lock());

        cur_line += 4;
        line_height = 15; // shorter line, smaller font
        let out = repl.get_output();
        Font8x16::render_str(&out)
        .stroke_color(Some(BinaryColor::On))
        .translate(Point::new(left_margin, cur_line))
        .draw(&mut *display.lock());

        cur_line += line_height;
        let cmd = repl.get_cmd();
        Font8x16::render_str(&cmd)
        .stroke_color(Some(BinaryColor::On))
        .translate(Point::new(left_margin, cur_line))
        .draw(&mut *display.lock());

        cur_line += line_height;
        let mut input = repl.get_input();
        if (get_time_ms(&p) / 500) % 2 == 0 {
            input.push('_'); // add an insertion carat
        }
        Font8x16::render_str(&input)
        .stroke_color(Some(BinaryColor::On))
        .translate(Point::new(left_margin, cur_line))
        .draw(&mut *display.lock());

        display.lock().flush().unwrap();
    }
}
