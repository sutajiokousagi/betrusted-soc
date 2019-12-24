#![no_std]

pub mod efuse_ecc {
    /// given an unprotected 24-bit data record, return
    /// a number which is the data + its 6-bit ECC code
    pub fn add_ecc(data: u32) -> u32 {
        assert!(data & 0xFF00_0000 == 0); // if the top 8 bits are filled in, that's an error
        const GENERATOR: [u32; 6] = [16_515_312, 14_911_249, 10_180_898, 5_696_068, 3_011_720, 16_777_215];

        let mut code: u32 = 0;

        for row in 0..GENERATOR.len() {
            let mut parity: u32 = 0;
            for bit in 0..24 {
                parity = parity ^ (((GENERATOR[row] & data) >> bit) & 0x1);
            }
            code ^= parity << row;
        }
        if (code & 0x20) != 0 {
            code = (!code & 0x1F) | 0x20;
        }

        let secded = ((((code >> 5) ^ (code >> 4) ^ (code >> 3) ^ (code >> 2) ^ (code >> 1) ^ code) & 0x1) << 5) | code;

        data | secded << 24
    }
}

// run with `cargo test --target x86_64-unknown-linux-gnu`
#[cfg(test)]
mod tests {
    use crate::efuse_ecc::*;

    #[test]
    fn it_works() {
       assert_eq!(2 + 2, 4);
   }

   #[test]
   fn vectors() {
       const INPUTS: [u32; 7] = [0xFF_FFFD, 0xA003, 0xA00A, 0xF00A, 0xF00F, 0xB00F, 0x00C5_B000];
       const OUTPUTS: [u32; 7] = [0x25FFFFFD, 0x2400A003, 0x3600A00A, 0x1E00F00A, 0x1400F00F, 0x3700B00F, 0x2AC5B000];

       for i in 0..INPUTS.len() {
          assert_eq!(OUTPUTS[i], add_ecc(INPUTS[i]));
        }
    }

    #[test]
    fn gen_test() {
        assert_eq!(0x2708_63C1, add_ecc(0x8_63C1));
        assert_eq!(0x2C02_A541, add_ecc(0x2_A541));
    }
}
