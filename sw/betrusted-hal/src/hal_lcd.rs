#[allow(dead_code)]

pub mod hal_lcd {
    extern crate embedded_graphics;
    use embedded_graphics::drawable::Pixel;
    use embedded_graphics::geometry::Size;
    use embedded_graphics::pixelcolor::{BinaryColor};
    use embedded_graphics::DrawTarget;
    use spin::Mutex;
    use core::ops::Deref;

    /// FIXME: figure out a way to get LCD_FB mapped to the _lcdfb symbol without crashing RLS
    const LCD_FB: *mut [u32; FB_SIZE] = 0xB000_0000 as *mut [u32; FB_SIZE];
    const FB_WIDTH_WORDS: usize = 11;
    const FB_WIDTH_PIXELS: usize = 336;
    const FB_LINES: usize = 536;
    const FB_SIZE: usize = FB_WIDTH_WORDS * FB_LINES; // 44 bytes by 536 lines
        
    /// BetrustedDisplay abstraction for embedded-graphics library
    pub struct BetrustedDisplay {
            interface: betrusted_pac::Peripherals,
    }
    
    impl BetrustedDisplay {
        pub fn new() -> Self {
            unsafe{ BetrustedDisplay{ interface: betrusted_pac::Peripherals::steal(), } }
        }

        pub fn init(&self, clk_mhz: u32) {
            lcd_init(&self.interface, clk_mhz);
        }

        pub fn flush(&self) -> Result<(), ()> {
            lcd_update_dirty(&self.interface);
            while lcd_busy(&self.interface) {} // should this be blocking??

            // clear all the dirty bits, under the theory that it's time-wise cheaper on average
            // to visit every line and clear the dirty bits than it is to do an update_all()
            for lines in 0..FB_LINES {
                unsafe{
                    (*LCD_FB)[lines * FB_WIDTH_WORDS + (FB_WIDTH_WORDS - 1)] &= 0x0000_FFFF;
                }
            }
            Ok(())
        }
        
        pub fn clear(&self) {
            let mut line_dirty: bool = false;
            for words in 0..FB_SIZE {
                if words % FB_WIDTH_WORDS != 10 {
                    unsafe{ 
                        if (*LCD_FB)[words] != 0xFFFF_FFFF {
                            (*LCD_FB)[words] = 0xFFFF_FFFF;
                            line_dirty = true;
                        }
                    }
                } else {
                    unsafe{ 
                        if (*LCD_FB)[words] & 0xFFFF != 0xFFFF || line_dirty {
                            (*LCD_FB)[words] = 0x0001_FFFF;
                        }
                        line_dirty = false;
                    }
                }
            }
        }
    }

    pub struct LockedBetrustedDisplay(Mutex<BetrustedDisplay>);

    impl LockedBetrustedDisplay {
        pub fn empty() -> LockedBetrustedDisplay {
            LockedBetrustedDisplay(Mutex::new(BetrustedDisplay::new()))
        }

        pub fn new() -> LockedBetrustedDisplay {
            LockedBetrustedDisplay(Mutex::new(BetrustedDisplay::new()))
        }
    }

    impl Deref for LockedBetrustedDisplay {
        type Target = Mutex<BetrustedDisplay>;

        fn deref(&self) -> &Mutex<BetrustedDisplay> {
            &self.0
        }
    }

    impl DrawTarget<BinaryColor> for BetrustedDisplay {
        fn size(&self) -> Size {
            Size::new(FB_WIDTH_PIXELS as u32, FB_LINES as u32)
        }

        fn draw_pixel(&mut self, pixel:Pixel<BinaryColor>) {
            let Pixel(coord, color) = pixel;
            match color {
                BinaryColor::Off => 
                   unsafe{ 
                       (*LCD_FB)[ (coord.x / 32 + coord.y * FB_WIDTH_WORDS as i32) as usize] |= 
                          1 << (coord.x % 32); },
                BinaryColor::On =>
                   unsafe{ 
                       (*LCD_FB)[ (coord.x / 32 + coord.y * FB_WIDTH_WORDS as i32) as usize] &= 
                          !(1 << (coord.x % 32)); },
            }
            // set the dirty bit on the line
            unsafe{
                (*LCD_FB)[(coord.y * FB_WIDTH_WORDS as i32 + (FB_WIDTH_WORDS as i32 - 1)) as usize] |= 0x0001_0000;
            }
        }
    }
    
    /// LCD hardware abstraction layer
    /// 
    /// The API for the betrusted LCD needs to be security-aware. Untrusted content
    /// cannot be rendered into areas reserved for system messages, and untrusted images
    /// should be rendered with a distinct border. As a result, the API will model
    /// the display as a series of objects that are rendered by the system into a
    /// framebuffer. This is less computationally efficient than just handing 
    /// processes a "bag of bits" frame buffer, but allows for fine-grained tuning of
    /// how the OS manages and displays trusted and untrusted information as we learn
    /// more about how the system is used. 
    /// 
    /// On the other side of the API is the HAL. The system exposes the LCD as a 
    /// distinct memory region, along with some CSRs that control the automatic
    /// rastering of the memory to the LCD. The LCD itself has the unique property
    /// in that it will persistently display the last image sent to it, unless 
    /// it is explicitly powered down or cleared.
    /// 
    
    pub fn lcd_clear(p: &betrusted_pac::Peripherals) {
        for words in 0..FB_SIZE {
            if words % FB_WIDTH_WORDS != 10 {
                unsafe{ (*LCD_FB)[words] = 0xFFFF_FFFF; }
            } else {
                unsafe{ (*LCD_FB)[words] = 0x0000_FFFF; } // don't set the dirty bit
            }
        }
        lcd_update_all(p); // because we force an all update here
        while lcd_busy(p) {}
    }

    pub fn lcd_test_pattern(p: &betrusted_pac::Peripherals, pattern: u32) {
        for words in 0..FB_SIZE / 2 {
            if words % FB_WIDTH_WORDS != 10 {
                unsafe{ (*LCD_FB)[words] = pattern; }
            } else {
                unsafe{ (*LCD_FB)[words] = (pattern & 0xFFFF) | 0x1_0000; }
            }
        }
        lcd_update_dirty(p);
        while lcd_busy(p) {}
    }

    pub fn lcd_update_all(p: &betrusted_pac::Peripherals) {
        p.MEMLCD.command.write( |w| w.update_all().bit(true));
    }

    pub fn lcd_update_dirty(p: &betrusted_pac::Peripherals) {
        p.MEMLCD.command.write( |w| w.update_dirty().bit(true));
    }

    pub fn lcd_init(p: &betrusted_pac::Peripherals, clk_mhz: u32) {
        unsafe{ p.MEMLCD.prescaler.write( |w| w.bits( (clk_mhz / 2_000_000) - 1) ); }
    }

    pub fn lcd_busy(p: &betrusted_pac::Peripherals) -> bool {
        if p.MEMLCD.busy.read().bits() == 1 {
            true
        } else {
            false
        }
    }

    pub fn lcd_lines() -> u32 {
        FB_LINES as u32
    }
}