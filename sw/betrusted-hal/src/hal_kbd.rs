#[allow(dead_code)]

/// returns the rows that have changed
/// the result is a vector where each bit corresponds to one row
pub fn kbd_rowchange(p: &betrusted_pac::Peripherals) -> u16 {
    (p.KEYBOARD.rowchange0.read().bits() as u16) | ((p.KEYBOARD.rowchange1.read().bits() as u16) << 8)
}

/// get the column activation contents of the given row
/// row is coded as a binary number, so the result of kbd_rowchange has to be decoded from a binary
/// vector of rows to a set of numbers prior to using this function
pub fn kbd_getrow(p: &betrusted_pac::Peripherals, row: u8) -> u16 {
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