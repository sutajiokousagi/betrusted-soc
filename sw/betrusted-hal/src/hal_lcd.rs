#[allow(dead_code)]

pub mod hal_lcd {
    const FB_WIDTH_WORDS: usize = 11;
    const FB_LINES: usize = 536;
    const FB_SIZE: usize = FB_WIDTH_WORDS * FB_LINES; // 44 bytes by 536 lines

    extern "C" {
        static mut _lcdfb: [u32; FB_SIZE];
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
                unsafe { _lcdfb[words] = 0xFFFF_FFFF; } // 1 is white
            } else {
                unsafe { _lcdfb[words] = 0x0000_FFFF; } // don't set the dirty bit
            }
        }
        lcd_update_all(p); // because we force an all update here
        while lcd_busy(p) {}
    }

    pub fn lcd_pattern(p: &betrusted_pac::Peripherals, pattern: u32) {
        for words in 0..FB_SIZE / 4 {
            if words % FB_WIDTH_WORDS != 10 {
                unsafe { _lcdfb[words] = pattern; }
            } else {
                unsafe { _lcdfb[words] = (pattern & 0xFFFF) | 0x1_0000; }
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