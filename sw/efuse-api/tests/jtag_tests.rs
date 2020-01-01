// to see print outputs run with `cargo test -- --nocapture`
extern crate std;
#[macro_use]

#[cfg(test)]
mod tests {
    use jtag::*;
    use std::fs::File;
    use std::io::prelude::*;
    use std::path::Path;
    use efuse_api::*;
        
    #[cfg(test)]
    const TIMESTEP: f64 = 1e-6;
    #[cfg(test)]
    pub struct JtagTestPhy {
        time: f64,
        ofile: File,
    }
    #[cfg(test)]
    impl JtagTestPhy {
        pub fn new(filename: &str) -> Self {
            let path = Path::new(&filename);
            let mut file = File::create(&path).unwrap();

            write!(file, "time, clk, tdo, tms, tdi\n").unwrap();
            JtagTestPhy {
                time: 0.05,
                ofile: file,
            }
        }
    }

    #[cfg(test)]
    impl JtagPhy for JtagTestPhy {
        fn sync(&mut self, tdi: bool, tms: bool) -> bool {

            let mut local_tdi: u8 = 0;
            let mut local_tms: u8 = 0;
            if tdi {
                local_tdi = 1;
            }
            if tms {
                local_tms = 1;
            }
            self.time += TIMESTEP;
            write!(self.ofile, "{:.08}, {}, {}, {}, {}\n", self.time, 0, 0, local_tms, local_tdi).unwrap();
            self.time += TIMESTEP;
            write!(self.ofile, "{:.08}, {}, {}, {}, {}\n", self.time, 1, 0, local_tms, local_tdi).unwrap();
            self.time += TIMESTEP;
            write!(self.ofile, "{:.08}, {}, {}, {}, {}\n", self.time, 0, 0, local_tms, local_tdi).unwrap();

            false
        }

        fn nosync(&mut self, _tdi: bool, _tms: bool, _tck: bool) -> bool {
            // not actually used, not implemented -- fail if called
            assert!(false);

            false
        }

        fn pause(&mut self, us: u32) {
            self.time += (us as f64) * 1e-6;
        }
    }

    #[test]
    fn jtag_fetch() {
        let mut jm: JtagMach = JtagMach::new();
        let mut jp: JtagTestPhy = JtagTestPhy::new("jtag_fetch.csv");

        let mut efuse: EfuseApi = EfuseApi::new();

        efuse.fetch(&mut jm, &mut jp);
    }

    #[test]
    fn jtag_burn() {
        let mut jm: JtagMach = JtagMach::new();
        let mut jp: JtagTestPhy = JtagTestPhy::new("jtag_burn.csv");

        let mut efuse: EfuseApi = EfuseApi::new();

        efuse.fetch(&mut jm, &mut jp);
        let mut key: [u8; 32] = [0; 32];
        key[0] = 0xB;
        key[31] = 0xF0;
        key[29] = 0x1;
        efuse.set_key(key);
        efuse.set_user(0xA000_0002);
        efuse.set_cntl(0x3);

        assert!(efuse.is_valid());
        assert!(efuse.burn(&mut jm, &mut jp));
    }

}
