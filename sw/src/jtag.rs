/// Simple JTAG machine implementation
/// 
/// Applications calling this implementation first loads queries into the JtagMach pending queue.
/// Queries are structured as JtagLeg, which is a bit-vector that corresponds to either an IR
/// or DR sequencee. Reads of the DR should include a dummy "input vector" of corresponding to
/// the length of the DR readback they are expecting. 
/// 
/// At any time, the machine can be asked to step() or next(), which will try to take the
/// oldest query added to the pending queue and execute it. step() will move one or two JTAG
/// PHY cycles, whereas next() will attempt to complete the execution of the latest pending
/// leg, if any are available or in-flight.
/// 
/// Legs that have been executed are added to the "done" queue. The calling code can add a
/// "tag" to the JtagLegs to help decode what data or command they corresponded to. 
/// 


use betrusted_hal::hal_uart::*;
use alloc::vec::Vec;
use alloc::string::String;

pub enum JtagState {
    TestReset,
    RunIdle,
    Select,
    Capture,
    Shift,
    Exit1,
    Pause,
    Exit2,
    Update,
}

#[derive(Copy, Clone)]
pub enum JtagChain {
    DR,
    IR,
}

pub enum JtagEndian {
    Big,    // MSB-first shiftout
    Little   // LSB-first shiftout
}

/// option 1: make a "leg" machine that contains the shift-in/shift-out records specific to each leg
/// option 2: make a comprehensive machine that receives meta-commands to transition between states
/// 
/// I think we want a machine that has a Vector which holds a set of instructions that encapsulate either
/// data to send into the IR or DR. There should be a state bit that indicates if the data has been
/// executed; after execution, there is a result vector that is now valid.
/// 
#[derive(Clone)]
pub struct JtagLeg {
    /// which chain (DR or IR)
    c: JtagChain,
    /// output bit vector to device; chain length is defined by vector length
    o: Vec<bool>,
    /// input bit vector from device; length is dynamically allocated as leg traverses
    i: Vec<bool>,
    /// a tag for the leg, to be used by higher level logic to track pending/done entries
    tag: String,
}

/*
impl Clone for JtagLeg {
    pub fn copy(&self) -> JtagLeg {
        let mut cloned: JtagLeg;
        match self.c {
            JtagChain::DR => {
                cloned = JtagLeg::new(JtagChain::DR);
            },
            JtagChain::IR => {
                cloned = JtagLeg::new(JtagChain::IR);
            }
        }

        cloned.tag = self.tag.clone();
        cloned.o = self.o.clone();
        cloned.i = self.i.clone();

        cloned
    }
}*/

impl JtagLeg {
    pub fn new(chain_type: JtagChain, mytag: &str) -> Self {
        JtagLeg {
            c: chain_type,
            o: Vec::new(),
            i: Vec::new(),
            tag: String::from(mytag),
        }
    }

    /// `push` will take data in the form of an unsigned int (either u128 or u32)
    /// and append it to the JTAG input vector in preparation for sending. 
    /// "count" specifies the number of bits of the vector that are valid, and 
    /// "endian" specifies if the MSB or LSB first should be pushed into the JTAG 
    /// chain. 
    /// 
    /// In the case that "count" is less than the full data length and MSB first
    /// order is requested, `push` first discards the left-most unused bits and
    /// then starts push from the remaining MSB. e.g., to push the number
    /// `101100` into the JTAG chain MSB first, store 0x2C into "data" and specify
    /// a "count" of 6, and an "endian" of JtagEndian::Big. Do not shift
    /// data all the way to the MSB of the containing "data" parameter in this case!
    pub fn push_u128(&mut self, data: u128, count: usize, endian: JtagEndian) {
        assert!(count < 128);
        for i in 0..count {
            match endian {
                JtagEndian::Little => {
                    if (data & (1 << i)) == 0 { self.i.push(false) } else { self.i.push(true) }
                },
                JtagEndian::Big => {
                    if (data & (1 << (count-i))) == 0 { self.i.push(false) } else { self.i.push(true) }
                },
            }
        }
    }

    pub fn push_u32(&mut self, data: u32, count: usize, endian: JtagEndian) {
        assert!(count < 32);
        for i in 0..count {
            match endian {
                JtagEndian::Little => {
                    if (data & (1 << i)) == 0 { self.i.push(false) } else { self.i.push(true) }
                },
                JtagEndian::Big => {
                    if (data & (1 << (count-i))) == 0 { self.i.push(false) } else { self.i.push(true) }
                },
            }
        }
    }

    pub fn pop_u32(&mut self, count: usize, endian: JtagEndian) -> Option<u32> {
        if self.o.len() < count {
            // error out before trying to touch the vector, so that in case
            // of a parameter error we can try again without having lost our data
            // in general, "count" should be very well specified in this protocol.
            return None;
        }

        let mut data: u32 = 0;
        for _ in 0..count {
            match endian {
                JtagEndian::Big => {
                    data <<= 1;
                    if self.o.pop().unwrap() { data |= 0x1; }
                }
                JtagEndian::Little => {
                    data >>= 1;
                    if self.o.pop().unwrap() { data |= 0x8000_0000; }
                }
            }
        }

        Some(data)
    }

    pub fn pop_u128(&mut self, count: usize, endian: JtagEndian) -> Option<u128> {
        if self.o.len() < count {
            return None;
        }

        let mut data: u128 = 0;
        for _ in 0..count {
            match endian {
                JtagEndian::Big => {
                    data <<= 1;
                    if self.o.pop().unwrap() { data |= 0x1; }
                },
                JtagEndian::Little => {
                    data >>= 1;
                    if self.o.pop().unwrap() { data |= 0x8000_0000_0000_0000_0000_0000_0000_0000; }
                }
            }
        }

        Some(data)
    }
    
    pub fn tag(&self) -> String {
        self.tag.clone()
    }
}

trait JtagPhy {
    fn new() -> Self;
    fn sync(&mut self, tdi: bool, tms: bool) -> bool; 
    fn nosync(&mut self, tdi: bool, tms: bool, tck: bool) -> bool;
}

pub struct JtagUartPhy {
    uart: BtUart,
}

impl JtagUartPhy {
    const SYNC_UART_CODE: u8 = 0x60;
    const ASYNC_UART_CODE: u8 = 0x40;
    const MASK_TCK: u8 = 0x4;
    const MASK_TMS: u8 = 0x2;
    const MASK_TDI: u8 = 0x1;
}

impl JtagPhy for JtagUartPhy {

    fn new() -> Self {
        let mut ret: JtagUartPhy = 
        JtagUartPhy {
            uart: BtUart::new(),
        };

        ret.uart.init();
        ret
    }

    /// given a tdi and tms value, pulse the clock, and then return the tdo that comes out 
    fn sync(&mut self, tdi: bool, tms: bool) -> bool {
        let mut c: u8 = JtagUartPhy::SYNC_UART_CODE;
        if tdi { c |= JtagUartPhy::MASK_TDI; }
        if tms { c |= JtagUartPhy::MASK_TMS; }
        self.uart.write(c);

        if self.uart.read() == 0x31 {  // 0x31 is '1', incidentally
            true
        } else {
            false
        }
    }

    fn nosync(&mut self, tdi: bool, tms: bool, tck: bool) -> bool {
        let mut c: u8 = JtagUartPhy::ASYNC_UART_CODE;
        if tdi { c |= JtagUartPhy::MASK_TDI; }
        if tms { c |= JtagUartPhy::MASK_TMS; }
        if tck { c |= JtagUartPhy::MASK_TCK; }
        self.uart.write(c);

        if self.uart.read() == 0x31 {
            true
        } else {
            false
        }
    }
}

pub struct JtagMach {
    /// current state (could be in one of two generics, or in DR/IR chain; check top of Vector for current chain)
    s: JtagState,
    /// a vector of legs to traverse. An entry stays in pending until the traversal is complete. Aborted
    /// traversals leave the leg in place
    pending: Vec<JtagLeg>,
    /// a vector of legs traversed. An entry is only put into the done vector once its traversal is completed.
    done: Vec<JtagLeg>,
    /// the current leg being processed
    current: Option<JtagLeg>,
    /// a PHY that implements the JtagPhy traits
    phy: JtagUartPhy,
}

impl JtagMach {
    pub fn new() -> Self {
        JtagMach {
            s: JtagState::TestReset,
            pending: Vec::new(),
            done: Vec::new(),
            current: None,
            phy: JtagUartPhy::new(),
        }
    }

    /// add() -- add a leg to the pending queue
    pub fn add(&mut self, leg: JtagLeg) {
        self.pending.push(leg);
    }

    /// get() -- get the oldest result in the done queue. Returns an option.
    pub fn get(&mut self) -> Option<JtagLeg> {
        self.done.pop()
    }

    /// has_pending() -- tells if the jtag machine has a pending leg to traverse. Returns the tag of the pending item, or None.
    pub fn has_pending(&self) -> bool {
        if self.pending.len() > 0 {
            true
        } else {
            false
        }
    }

    /// has_done() -- tells if the jtag machine has any legs that are done to read out. Returns the tag of the done item, or None.
    pub fn has_done(&self) -> bool {
        if self.done.len() > 0 {
            true
        } else {
            false
        }
    }

    /// step() -- move state machine by one cycle
    /// if there is nothing in the pending queue, stay in idle
    /// if something in the pending queue, traverse to execute it
    pub fn step(&mut self) {
        match self.s {
            JtagState::TestReset => {
                self.phy.sync(false, false);
                self.s = JtagState::RunIdle;
            },
            JtagState::RunIdle => {
                if self.current.is_none() {
                    if !self.has_pending() {
                        // nothing pending, nothing current
                        // stay in the current state
                        self.phy.sync(false, false);
                        self.s = JtagState::RunIdle;
                        return;
                    } else {
                        // nothing current, but has pending --> assign a current
                        self.current = Some(self.pending.pop().unwrap().clone());
                    }
                } else {
                    // we have a current item, traverse to the correct tree based on the type
                    let cur: JtagLeg = self.current.as_mut().unwrap().clone();

                    match cur.c {
                        JtagChain::DR => {
                            self.phy.sync(false, true);
                            self.s = JtagState::Select;
                        },
                        JtagChain::IR => {
                            // must be IR -- do two TMS high pulses to get to the IR leg
                            self.phy.sync(false, true);
                            self.phy.sync(false, true);
                            self.s = JtagState::Select;
                        }
                    }
                    self.current = Some(cur);
                }
            },
            JtagState::Select => {
                self.phy.sync(false, false);
                self.s = JtagState::Capture;
            }, 
            JtagState::Capture => {
                // always move to shift, because leg structures always have data
                self.phy.sync(false, false);
                self.s = JtagState::Shift;
            },
            JtagState::Shift => {
                // shift data until the input vector is exhausted
                let mut cur: JtagLeg = self.current.as_mut().unwrap().clone();
                if cur.o.len() > 0 {
                    let tdi: bool = cur.o.pop().unwrap();
                    let tdo: bool = self.phy.sync(tdi, false);
                    cur.i.push(tdo);
                } else {
                    self.phy.sync(false, true);
                    self.s = JtagState::Exit1;
                }
                self.current = Some(cur);
            },
            JtagState::Exit1 => {
                self.phy.sync(false, true);
                self.s = JtagState::Update;
            },
            JtagState::Pause => {
                self.phy.sync(false, true);
                self.s = JtagState::Exit2;
            },
            JtagState::Exit2 => {
                self.phy.sync(false, true);
                self.s = JtagState::Update;
            },
            JtagState::Update => {
                self.phy.sync(false, true);
                self.s = JtagState::RunIdle;

                self.pending.pop(); // remove and discard the pending entry
                let cur: JtagLeg = self.current.as_mut().unwrap().clone();
                self.done.push(cur);
                self.current = None;
            }
        }
    }

    /// reset() -- bring the state machine back to the TEST_RESET state
    pub fn reset(&mut self) {
        // regardless of what state we are in, 5 cycles of TMS=1 will bring us to RESET
        for _ in 0..5 {
            self.phy.sync(false, true);
        }
        self.s = JtagState::TestReset;
    }

    /// next() -- advance until a RUN_IDLE state. If currently RUN_IDLE, traverse the next available leg, if one exists
    pub fn next(&mut self) {
        match self.s {
            JtagState::RunIdle | JtagState::TestReset => {
                if self.has_pending() {
                    // if pending, step until we're into a leg
                    loop {
                        match self.s {
                            JtagState::RunIdle | JtagState::TestReset => self.step(),
                            _ => break,
                        }
                    }
                    // then step until we're out of the leg
                    loop {
                        match self.s {
                            JtagState::RunIdle | JtagState::TestReset => break,
                            _ => self.step(),
                        }
                    }
                } else {
                    self.step(); // this should be a single step with no state change
                }
            },
            _ => {
                // in the case that we're not already in idle or reset, run the machine until we get to idle or reset
                loop {
                    match self.s {
                        JtagState::RunIdle | JtagState::TestReset => break,
                        _ => self.step(),
                    }
                }
            },
        }
    }
}