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
use betrusted_hal::hal_xadc::*;
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

use jtag::*;
use efuse_api::*;

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
            if x >= (self.bounds.bottom_right().x as i32 - r - 1) {
                self.vector.x = -self.rand[self.rand_index];
                x = self.bounds.bottom_right().x as i32 - r;
            }
            if x <= self.bounds.top_left().x + r + 1 {
                self.vector.x = self.rand[self.rand_index];
                x = self.bounds.top_left().x + r;
            }
            if y >= (self.bounds.bottom_right().y as i32 - r - 1) {
                self.vector.y = -self.rand[self.rand_index];
                y = self.bounds.bottom_right().y as i32 - r;
            }
            if y <= (self.bounds.top_left().y + r + 1) {
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
    text: TextArea,
    /// power state variable
    power: bool,
    /// JTAG state variable
    jtag: JtagMach,
    /// JTAG phy
    jtagphy: JtagUartPhy,
    /// efuse API
    efuse: EfuseApi,
    /// xadc object
    xadc: BtXadc,
    /// noise arrays
    noise0: [u16; 300],
    noise1: [u16; 300],
    update_noise: bool,
}

const PROMPT: &str = "bt> ";
const NUM_LINES: usize = 6;

impl Repl {
    pub fn new() -> Self {
        let mut r: Repl = 
        unsafe {
            Repl {
                p: betrusted_pac::Peripherals::steal(),
                input: String::from(PROMPT),
                cmd: String::from(" "),
                text: TextArea::new(NUM_LINES),
                power: true,
                jtag: JtagMach::new(),
                jtagphy: JtagUartPhy::new(),
                efuse: EfuseApi::new(),
                xadc: BtXadc::new(),
                noise0: [0; 300],
                noise1: [0; 300],
                update_noise: false,
            }
        };
        r.text.add_text(&mut String::from("Awaiting input."));

        r
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

    pub fn get_noise0(&self) -> [u16; 300] { self.noise0 }
    pub fn get_noise1(&self) -> [u16; 300] { self.noise1 }
    pub fn get_update_noise(&self) -> bool {self.update_noise}
    pub fn sample_noise(&mut self) {
        for i in 0..300 {
            self.xadc.wait_update();
            self.noise0[i] = self.xadc.noise0();
            self.noise1[i] = self.xadc.noise1();
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
                self.text.add_text(&mut String::from("Shutting down system"));
                self.power = false; // the main UI loop needs to pick this up and render the display accordingly
            } else if self.cmd.trim() == "buzz" {
                self.text.add_text(&mut String::from("Making a buzz"));
                unsafe{ self.p.GPIO.drive.write(|w| w.bits(4)); }
                unsafe{ self.p.GPIO.output.write(|w| w.bits(4)); }
                let time: u32 = get_time_ms(&self.p);
                while get_time_ms(&self.p) - time < 250 { }
                unsafe{ self.p.GPIO.output.write(|w| w.bits(0)); }
            } else if self.cmd.trim() == "blon" {
                self.text.add_text(&mut String::from("Turning backlight on"));
                com_txrx(&self.p, 0x6007); // turn on the keyboard backlight LEDs
                com_txrx(&self.p, 0x681F); // turn on the backlight to full brightness (31)
            } else if self.cmd.trim() == "bloff" {
                self.text.add_text(&mut String::from("Turning backlight off"));
                com_txrx(&self.p, 0x6000);
                com_txrx(&self.p, 0x6800);
            } else if self.cmd.trim() == "step" {
                self.jtag.step(&mut self.jtagphy);
            } else if self.cmd.trim() == "id" {
                self.jtag.reset(&mut self.jtagphy);
                let mut id_leg: JtagLeg = JtagLeg::new(JtagChain::IR, "idcode");
                id_leg.push_u32(0b001001, 6, JtagEndian::Little);
                self.jtag.add(id_leg);
                self.jtag.next(&mut self.jtagphy);
                // NOW: - check the return data on .get() before using it
                if self.jtag.get().is_none() { // discard ID code but check that there's something
                   self.text.add_text(&mut format!("ID instruction not in get queue!"));
                   return;
                }

                let mut data_leg: JtagLeg = JtagLeg::new(JtagChain::DR, "iddata");
                data_leg.push_u32(0, 32, JtagEndian::Little);
                self.jtag.add(data_leg);
                self.jtag.dbg_reset();
                self.jtag.next(&mut self.jtagphy);
                let d: u32 = self.jtag.dbg_get();
                if let Some(mut iddata) = self.jtag.get() { // this contains the actual idcode data
                    self.text.add_text(&mut format!("tag: {}, code: 0x{:08x}, d:{}", iddata.tag(), iddata.pop_u32(32, JtagEndian::Little).unwrap(), d));
                } else {
                    self.text.add_text(&mut format!("ID data not in get queue!"));
                }
            } else if self.cmd.trim() == "fk" { // crypto fuse
                self.efuse.fetch(&mut self.jtag, &mut self.jtagphy);
                let key: [u8; 32] = self.efuse.phy_key();
                self.text.add_text(&mut String::from("Key, in hex:"));
                let mut line = String::from("");
                for i in (16..32).rev() {
                    line = line + &format!("{:02x}", key[i]);
                }
                self.text.add_text(&mut line);
                line = String::from("");
                for i in (0..16).rev() {
                    line = line + &format!("{:02x}", key[i]);
                }
                self.text.add_text(&mut line);
            } else if self.cmd.trim() == "fu" {
                self.efuse.fetch(&mut self.jtag, &mut self.jtagphy);
                self.text.add_text(&mut format!("user: 0x{:08x}", self.efuse.phy_user()));
            } else if self.cmd.trim() == "fc" {
                self.efuse.fetch(&mut self.jtag, &mut self.jtagphy);
                self.text.add_text(&mut format!("cntl: 0x{:02x}", self.efuse.phy_cntl()));
            }  else if self.cmd.trim() == "test1" {
                self.efuse.fetch(&mut self.jtag, &mut self.jtagphy);
                let mut key: [u8; 32] = self.efuse.phy_key();
                key[26] = 0xA0;
                key[25] = 0x03;
                key[24] = 0x81;
                self.efuse.set_key(key);
                if self.efuse.is_valid() {
                    self.text.add_text(&mut format!("Patch is valid."));
                } else {
                    self.text.add_text(&mut format!("Patch is not valid."));
                }
                self.efuse.burn(&mut self.jtag, &mut self.jtagphy);
            }  else if self.cmd.trim() == "dna" { // dna
                self.jtag.reset(&mut self.jtagphy);
                let mut ir_leg: JtagLeg = JtagLeg::new(JtagChain::IR, "cmd");
                ir_leg.push_u32(0b110010, 6, JtagEndian::Little);
                self.jtag.add(ir_leg);
                self.jtag.next(&mut self.jtagphy);
                if self.jtag.get().is_none() { // discard ID code but check that there's something
                   self.text.add_text(&mut format!("cmd instruction not in get queue!"));
                   return;
                }

                let mut data_leg: JtagLeg = JtagLeg::new(JtagChain::DR, "dna");
                data_leg.push_u128(0, 64, JtagEndian::Little);
                self.jtag.add(data_leg);
                self.jtag.next(&mut self.jtagphy);
                if let Some(mut data) = self.jtag.get() {
                    let dna: u128 = data.pop_u128(64, JtagEndian::Little).unwrap();
                    self.text.add_text(&mut format!("{}/0x{:16x}", data.tag(), dna));
                } else {
                    self.text.add_text(&mut format!("dna data not in queue!"));
                }
            } else if self.cmd.trim() == "loop" {
                unsafe { self.p.UART.ev_pending.write(|w| w.bits(self.p.UART.ev_pending.read().bits())); }
                unsafe { self.p.UART.ev_enable.write(|w| w.bits(3)); }
                
                // send 0-9 as a test
                for _ in 0..10 {
                    for i in 0..10 {
                        while self.p.UART.txfull.read().bits() != 0 {}
                        unsafe { self.p.UART.rxtx.write(|w| w.bits(0x30 + i as u32)); }
                        unsafe { self.p.UART.ev_pending.write(|w| w.bits(1)); }
                    }
                    // crlf
                    unsafe { self.p.UART.rxtx.write(|w| w.bits(0xa as u32)); }
                    unsafe { self.p.UART.rxtx.write(|w| w.bits(0xd as u32)); }
                }
            } else if self.cmd.trim() == "xadc" {
                let vccint: u32 = self.p.INFO.xadc_vccint0.read().bits() as u32 | ((self.p.INFO.xadc_vccint1.read().bits() as u32) << 8);
                let vccaux: u32 = self.p.INFO.xadc_vccaux0.read().bits() as u32 | ((self.p.INFO.xadc_vccaux1.read().bits() as u32) << 8);
                let vccbram: u32 = self.p.INFO.xadc_vccbram0.read().bits() as u32 | ((self.p.INFO.xadc_vccbram1.read().bits() as u32) << 8);
                let temp: u32 = self.p.INFO.xadc_temperature0.read().bits() as u32 | ((self.p.INFO.xadc_temperature1.read().bits() as u32) << 8);

                self.text.add_text(&mut format!("vccint: {:.3}V", (vccint as f64) / 1365.0));
                self.text.add_text(&mut format!("vccaux: {:.3}V", (vccaux as f64) / 1365.0));
                self.text.add_text(&mut format!("vccbram: {:.3}V", (vccbram as f64) / 1365.0));
                self.text.add_text(&mut format!("temp: {:.2}C", ((temp as f64) * 0.12304) - 273.15));
            } else if self.cmd.trim() == "sense" {
                self.xadc.wait_update();
                self.text.add_text(&mut format!("int:  {:.3}V  aux: {:.3}V", (self.xadc.vccint() as f64) / 1365.0, (self.xadc.vccaux() as f64) / 1365.0));
                self.text.add_text(&mut format!("bram: {:.3}V temp: {:.2}C", 
                                                (self.xadc.vccbram() as f64) / 1365.0, 
                                                ((self.xadc.temp() as f64) * 0.12304) - 273.15 ));
                self.text.add_text(&mut format!("vbus: {:4}mV cc1: {:4}mV cc2: {:4}mV", 
                                                self.xadc.vbus_mv(),
                                                self.xadc.cc1_mv(),
                                                self.xadc.cc2_mv()  ));
                self.text.add_text(&mut format!("noise0: {:4} noise1: {:4}", self.xadc.noise0(), self.xadc.noise1()));
                self.text.add_text(&mut format!("audio: 0x{:04x}", self.xadc.audio_sample() ));
            } else if self.cmd.trim() == "non" {
                unsafe{ self.p.POWER.power.write(|w| w.noisebias().bit(true).noise().bits(3).self_().bit(true).state().bits(3) ); }
                self.update_noise = true;
            } else if self.cmd.trim() == "noff" {
                unsafe{ self.p.POWER.power.write(|w| w.noisebias().bit(false).noise().bits(0).self_().bit(true).state().bits(3) ); }
                self.update_noise = false;
            } else {
                self.text.add_text(&mut format!("{}: not recognized.", self.cmd.trim()));
            }
        }
    }

    pub fn get_line(&self, line: usize)-> String {
        self.text.get_line(line)
    }
}

pub struct TextArea {
    height_lines: usize,
    text: Vec<String>,
}

impl TextArea {
    pub fn new(lines: usize) -> Self {
        TextArea {
            height_lines: lines,
            text: Vec::new(),
        }
    }

    pub fn get_height(&self) -> usize { self.height_lines }
    pub fn get_width(&self) -> usize { 38 as usize }

    pub fn get_line(&self, line: usize) -> String {
        if line > self.height_lines {
            String::from("")
        } else {
            if let Some(line) = self.text.get(line) {
                line.clone()
            } else {
                String::from("")   
            }
        }
    }

    pub fn add_text(&mut self, text: &mut String) {
        // add the new text
        let strbytes = text.as_bytes();
        for chunk in strbytes.chunks(self.get_width()) {
            self.text.insert(0, String::from_utf8(chunk.to_vec()).unwrap());
        }

        // trim the old text
        while self.text.len() > self.height_lines {
            self.text.pop();
        }
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

    let radius: u32 = 14;
    let size: Size = display.lock().size();
    let mut cur_time: u32 = get_time_ms(&p);
    let mut _stat_array: [u16; 10] = [0; 10];
    let mut gg_array: [u16; 4] = [0; 4];
    let mut line_height: i32 = 18;
    let left_margin: i32 = 10;
    let mut bouncy_ball: Bounce = Bounce::new(radius, Rectangle::new(Point::new(0, line_height * 21), Point::new(size.width as i32, size.height as i32 - 1)));
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

        bouncy_ball.update();
        let circle = egcircle!(bouncy_ball.loc, bouncy_ball.radius, 
                               stroke_color = Some(BinaryColor::Off), fill_color = Some(BinaryColor::On));
        circle.draw(&mut *display.lock());
        
        // ping the EC and update various records over time
        if get_time_ms(&p) - cur_time > 250 {
            cur_time = get_time_ms(&p);
            if tx_index == 0 {
                com_txrx(&p, 0x7000 as u16); // send the pointer reset command
            } else if tx_index < gg_array.len() + 1 {
                gg_array[tx_index - 1] = com_txrx(&p, 0xDEAD) as u16; // the transmit is a dummy byte
            }
            tx_index += 1;
            tx_index = tx_index % (gg_array.len() + 2);
        }
        /*
        for i in 0..4 {
            // but update the result every loop iteration
            let dbg = format!{"s{}: 0x{:04x}  s{}: 0x{:04x}", i*2, stat_array[i*2], i*2+1, stat_array[i*2+1]};
            Font12x16::render_str(&dbg)
            .stroke_color(Some(BinaryColor::On))
            .translate(Point::new(left_margin, cur_line))
            .draw(&mut *display.lock());
            cur_line += line_height;
        }*/
        let dbg = format!{"voltage: {}mV", gg_array[2]};
        Font12x16::render_str(&dbg)
        .stroke_color(Some(BinaryColor::On))
        .translate(Point::new(left_margin, cur_line))
        .draw(&mut *display.lock());

        cur_line += line_height;
        let dbg = format!{"avg current: {}mA", (gg_array[0] as i16)};
        Font12x16::render_str(&dbg)
        .stroke_color(Some(BinaryColor::On))
        .translate(Point::new(left_margin, cur_line))
        .draw(&mut *display.lock());

        cur_line += line_height;
        let dbg = format!{"sby current: {}mA", (gg_array[1] as i16)};
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

        // split string into 4 lines and render
        cur_line += 4;
        line_height = 15; // shorter line, smaller font

        for line in (0..NUM_LINES).rev() {
            let out = repl.get_line(line);
            Font8x16::render_str(&out)
            .stroke_color(Some(BinaryColor::On))
            .translate(Point::new(left_margin, cur_line))
            .draw(&mut *display.lock());
            cur_line += line_height;
        }

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

        cur_line += line_height;
        const GRAPH_MARGIN: i32 = 18;
        Line::<BinaryColor>::new(Point::new(GRAPH_MARGIN, cur_line + 128),
        Point::new(size.width as i32 - GRAPH_MARGIN, cur_line + 128))
        .stroke_color(Some(BinaryColor::On))
        .draw(&mut *display.lock());
        Line::<BinaryColor>::new(Point::new(GRAPH_MARGIN, cur_line),
        Point::new(GRAPH_MARGIN, cur_line + 128))
        .stroke_color(Some(BinaryColor::On))
        .draw(&mut *display.lock());
        if repl.get_update_noise() {
            repl.sample_noise();
            let noise0: [u16; 300] = repl.get_noise0();
            let noise1: [u16; 300] = repl.get_noise1();
            let mut x = GRAPH_MARGIN;
            for index in 0..299 {
                Line::<BinaryColor>::new(Point::new(x, cur_line + 64 - noise0[index] as i32 / 32),
                Point::new(x+1, cur_line + 64 - noise0[index+1] as i32 / 32))
                .stroke_color(Some(BinaryColor::On))
                .draw(&mut *display.lock());
                x = x + 1;
            }
            x = GRAPH_MARGIN;
            for index in 0..299 {
                Line::<BinaryColor>::new(Point::new(x, cur_line + 128 - noise1[index] as i32 / 32),
                Point::new(x+1, cur_line + 128 - noise1[index+1] as i32 / 32))
                .stroke_color(Some(BinaryColor::On))
                .draw(&mut *display.lock());
                x = x + 1;
            }
        }

        display.lock().flush().unwrap();
    }
}
