#[allow(dead_code)]

use alloc::vec::Vec;

/// note: the code is structured to use at most 16 rows or 16 cols
const KBD_ROWS: usize = 9;
const KBD_COLS: usize = 10;

/// Keyboard driver HAL. Very basic at the moment.
/// 
/// FIXME: add software debouncing once interrupts are working. At the moment, the system will
/// probably pick up too much switch chatter.

/// returns the rows that have changed
/// the result is a vector where each bit corresponds to one row
fn kbd_rowchange(p: &betrusted_pac::Peripherals) -> u16 {
    (p.KEYBOARD.rowchange0.read().bits() as u16) | ((p.KEYBOARD.rowchange1.read().bits() as u16) << 8)
}

/// get the column activation contents of the given row
/// row is coded as a binary number, so the result of kbd_rowchange has to be decoded from a binary
/// vector of rows to a set of numbers prior to using this function
fn kbd_getrow(p: &betrusted_pac::Peripherals, row: u8) -> u16 {
    match row {
        0 => (p.KEYBOARD.row0dat0.read().bits() as u16) | ((p.KEYBOARD.row0dat1.read().bits() as u16) << 8),
        1 => (p.KEYBOARD.row1dat0.read().bits() as u16) | ((p.KEYBOARD.row1dat1.read().bits() as u16) << 8),
        2 => (p.KEYBOARD.row2dat0.read().bits() as u16) | ((p.KEYBOARD.row2dat1.read().bits() as u16) << 8),
        3 => (p.KEYBOARD.row3dat0.read().bits() as u16) | ((p.KEYBOARD.row3dat1.read().bits() as u16) << 8),
        4 => (p.KEYBOARD.row4dat0.read().bits() as u16) | ((p.KEYBOARD.row4dat1.read().bits() as u16) << 8),
        5 => (p.KEYBOARD.row5dat0.read().bits() as u16) | ((p.KEYBOARD.row5dat1.read().bits() as u16) << 8),
        6 => (p.KEYBOARD.row6dat0.read().bits() as u16) | ((p.KEYBOARD.row6dat1.read().bits() as u16) << 8),
        7 => (p.KEYBOARD.row7dat0.read().bits() as u16) | ((p.KEYBOARD.row7dat1.read().bits() as u16) << 8),
        8 => (p.KEYBOARD.row8dat0.read().bits() as u16) | ((p.KEYBOARD.row8dat1.read().bits() as u16) << 8),
        _ => 0
    }
}

/// scan the entire key matrix and return the list of keys that are currently
/// pressed as key codes. Return format is an option-wrapped vector of u8, 
/// which is structured as (row : col), where each of row and col are a u8.
/// Option "none" means no keys were pressed during this scan.
fn kbd_getcodes(p: &betrusted_pac::Peripherals) -> Option<Vec<(usize,usize)>> {
    let mut keys = Vec::new();

    for r in 0..KBD_ROWS {
        let cols: u16 = kbd_getrow(&p, r as u8);
        for c in 0..KBD_COLS {
            if (cols & (1 << c)) != 0 {
                keys.push( (r, c) )
            }
        }
    }

    if keys.len() > 0 {
        Some(keys)
    } else {
        None
    }
}

/// holds the four basic possible values of a key location
pub struct ScanCode {
    /// base key value
    key: Option<char>,    
    /// tap blue shift key, then key
    shift: Option<char>,  
    /// hold blue shift key, then key
    hold: Option<char>,    
    /// hold orange shift key, then key
    alt: Option<char>,    
}

/// This is the main keyboard manager construct.
pub struct KeyManager {
    /// the peripheral access crate pointer
    p: betrusted_pac::Peripherals,
    /// debounce counter array
    debounce: [[u8; KBD_ROWS]; KBD_COLS],
    /// threshold for considering an up or down event to be debounced, in loop interations
    threshold: u8,
}

impl KeyManager {
    pub fn new() -> Self {
        unsafe{ 
            KeyManager{
                p: betrusted_pac::Peripherals::steal(),
                debounce: [[0; KBD_ROWS]; KBD_COLS],
                threshold: 5,
            }
        }
    }

    //// returns the current set of codes from the keyboard matrix
    pub fn getcodes(&self) -> Option<Vec<(usize, usize)>> {
        kbd_getcodes(&self.p)
    }
    
    //// periodically call this with the results of getcodes() to update the debounce matrix
    /// returns a tuple of (keydown, keyup) scan codes, each of which are an Option-wrapped vector
    pub fn update(&mut self, codes: Option<Vec<(usize,usize)>>) -> (Option<Vec<(usize, usize)>>, Option<Vec<(usize,usize)>>) {
        let mut downs: [[u8; KBD_ROWS]; KBD_COLS] = [[0; KBD_ROWS]; KBD_COLS];
        let mut keydowns = Vec::new();
        let mut keyups = Vec::new();

        match codes {
            Some(code) => {
                for key in code {
                    let (row, col) = key;
                    if self.debounce[row][col] < self.threshold {
                        self.debounce[row][col] += 1;
                        downs[row][col] = 1;  // record that we did a keydown event
                        // now check if we've passed the debounce threshold, and report a keydown                        
                        if self.debounce[row][col] == self.threshold {
                            keydowns.push((row,col));
                        }
                    }
                }
            }
            None => {
                // do nothing
            }
        }

        for row in 0..KBD_ROWS {
            for col in 0..KBD_COLS {
                // skip elements that recorded a key being pressed above
                if (downs[row][col] == 0) && (self.debounce[row][col] > 0) {
                    self.debounce[row][col] -= 1;
                    // if we get to 0, then we conclude the key has been released
                    if self.debounce[row][col] == 0 {
                        keyups.push((row, col));
                    }
                }
            }
        }

        let retdowns: Option<Vec<(usize, usize)>>;
        if keydowns.len() > 0 {
            retdowns = Some(keydowns);
        } else {
            retdowns = None;
        }
        let retups: Option<Vec<(usize, usize)>>;
        if keyups.len() > 0 {
            retups = Some(keyups);
        } else {
            retups = None;
        }

        (retdowns, retups)
    }

    /// Compute the dvorak key mapping of row/col to key tuples
    pub fn map_dvorak(code: (usize,usize)) -> ScanCode {
        match code {
            (0, 0) => ScanCode{key: Some('1'), shift: Some('1'), hold: None, alt: None},
            (0, 1) => ScanCode{key: Some('2'), shift: Some('2'), hold: None, alt: None},
            (0, 2) => ScanCode{key: Some('3'), shift: Some('3'), hold: None, alt: None},
            (0, 3) => ScanCode{key: Some('4'), shift: Some('4'), hold: None, alt: None},
            (0, 4) => ScanCode{key: Some('5'), shift: Some('5'), hold: None, alt: None},
            (4, 5) => ScanCode{key: Some('6'), shift: Some('6'), hold: None, alt: None},
            (4, 6) => ScanCode{key: Some('7'), shift: Some('7'), hold: None, alt: None},
            (4, 7) => ScanCode{key: Some('8'), shift: Some('8'), hold: None, alt: None},
            (4, 8) => ScanCode{key: Some('9'), shift: Some('9'), hold: None, alt: None},
            (4, 9) => ScanCode{key: Some('0'), shift: Some('0'), hold: None, alt: None},

            (1, 0) => ScanCode{key: Some(0x8_u8.into()), shift: Some(0x8_u8.into()), hold: Some(0x8_u8.into()), alt: Some(0x8_u8.into())}, // backspace
            (1, 1) => ScanCode{key: Some('\''), shift: Some('\''), hold: Some('@'), alt: None},
            (1, 2) => ScanCode{key: Some('p'), shift: Some('P'), hold: Some('#'), alt: None},
            (1, 3) => ScanCode{key: Some('y'), shift: Some('Y'), hold: Some('&'), alt: None},
            (1, 4) => ScanCode{key: Some('f'), shift: Some('F'), hold: Some('*'), alt: None},
            (1, 5) => ScanCode{key: Some('g'), shift: Some('G'), hold: Some('-'), alt: None},
            (1, 6) => ScanCode{key: Some('c'), shift: Some('C'), hold: Some('+'), alt: None},
            (1, 7) => ScanCode{key: Some('r'), shift: Some('R'), hold: Some('('), alt: None},
            (1, 8) => ScanCode{key: Some('l'), shift: Some('L'), hold: Some(')'), alt: None},
            (1, 9) => ScanCode{key: Some('?'), shift: Some('?'), hold: Some('!'), alt: None},

            _ => ScanCode {key: None, shift: None, hold: None, alt: None}
        }
    }
}