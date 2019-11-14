#[allow(dead_code)]

/// com_txrx is a polled-implementation of an atomit TX/RX swap operation
/// The code is a little awkward for several reasons:
///   * CSR space splits values longer than 8 bits into separate registers;
///     this means that we can't, for example, infer in the hardware that the
///     transaction should simply start upon the write of data to the TX register
///     so we have to burn a cycle hitting "go" as well
///   * The SPI block runs about 5x slower than the CPU if the code is in cache;
///     but if there is a cache miss, the SPI block can complete its transaction
///     in the time it takes for the cache to fill. Thus, we have a situation where
///     we can both "beat" a transaction-in-progress signal reported back from
///     the hardware (as that might take a couple cycles to set, and the CPU
///     could read fast enough to see the TIP signal before its set), and "lag"
///     a transaction in progress signal, e.g. the transaction could finish
///     before the cache is refilled. 
/// The solution to this was to implement a "done" signal that is explicitly
/// cleared and checked by the CPU prior to "go", which guarantees that the done
/// is low. After "go", we can safely just check for done being high. Auto-clearing
/// "done" on "go" doesn't work because the time it takes to auto-clear the signal
/// is long enough that the CPU may actually see the stale done value after hitting
/// go if the CPU is running on the fast side...
pub fn com_txrx(p: &betrusted_pac::Peripherals, tx: u16) -> u16 {
    // clear the done bit
    p.COM.control.write(|w| w.clrdone().bit(true));
    // wait until the done register clears
    while p.COM.status.read().done().bit_is_set() { }

    // load the TX register
    unsafe{ p.COM.tx0.write(|w| w.bits((tx & 0xFF) as u32)); }
    unsafe{ p.COM.tx1.write(|w| w.bits(((tx >> 8) & 0xFF) as u32)); }

    // set the go bit
    p.COM.control.write(|w| w.go().bit(true));

    // wait until the done register is set
    while !p.COM.status.read().done().bit_is_set() { }

    // grab the RX value and return it
    let rx: u16 = (p.COM.rx0.read().bits() as u16) | ((p.COM.rx1.read().bits() as u16) << 8);
    rx
}