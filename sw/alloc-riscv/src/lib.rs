//! A heap allocator for RiscV processors
//!
//! # Example
//!
//! ```
//! #![feature(alloc)]
//! #![feature(global_allocator)]
//! #![feature(lang_items)]
//!
//! // Plug in the allocator crate
//! extern crate alloc;
//! extern crate alloc_cortex_m;
//! #[macro_use]
//! extern crate cortex_m_rt as rt; // v0.5.x
//!
//! use alloc::Vec;
//! use alloc_cortex_m::RiscvHeap;
//!
//! #[global_allocator]
//! static ALLOCATOR: RiscvHeap = RiscvHeap::empty();
//!
//! entry!(main);
//!
//! fn main() -> ! {
//!     // Initialize the allocator BEFORE you use it
//!     let start = rt::heap_start() as usize;
//!     let size = 1024; // in bytes
//!     unsafe { ALLOCATOR.init(start, size) }
//!
//!     let mut xs = Vec::new();
//!     xs.push(1);
//!
//!     loop { /* .. */ }
//! }
//!
//! // required: define how Out Of Memory (OOM) conditions should be handled
//! // *if* no other crate has already defined `oom`
//! #[lang = "oom"]
//! #[no_mangle]
//! pub fn rust_oom() -> ! {
//!     // ..
//! }
//!
//!
//! // omitted: exception handlers
//! ```

#![feature(alloc)]
#![feature(allocator_api)]
#![feature(const_fn)]
#![no_std]

extern crate alloc;
extern crate riscv;
extern crate linked_list_allocator;
extern crate spin;

use core::alloc::{GlobalAlloc, Layout};
use core::ptr::NonNull;

// use riscv::interrupt::Mutex;
// mod mutex;
// use mutex::Mutex;
use spin::Mutex;

use linked_list_allocator::Heap;

pub struct RiscvHeap {
    heap: Mutex<Heap>,
}

impl RiscvHeap {
    /// Crate a new UNINITIALIZED heap allocator
    ///
    /// You must initialize this heap using the
    /// [`init`](struct.RiscvHeap.html#method.init) method before using the allocator.
    pub const fn empty() -> RiscvHeap {
        RiscvHeap {
            heap: Mutex::new(Heap::empty()),
        }
    }

    /// Initializes the heap
    ///
    /// This function must be called BEFORE you run any code that makes use of the
    /// allocator.
    ///
    /// `start_addr` is the address where the heap will be located.
    ///
    /// `size` is the size of the heap in bytes.
    ///
    /// Note that:
    ///
    /// - The heap grows "upwards", towards larger addresses. Thus `end_addr` must
    ///   be larger than `start_addr`
    ///
    /// - The size of the heap is `(end_addr as usize) - (start_addr as usize)`. The
    ///   allocator won't use the byte at `end_addr`.
    ///
    /// # Unsafety
    ///
    /// Obey these or Bad Stuff will happen.
    ///
    /// - This function must be called exactly ONCE.
    /// - `size > 0`
    pub unsafe fn init(&self, start_addr: usize, size: usize) {
        //self.heap.init(start_addr, size);
        //self.heap.lock(|heap| heap.init(start_addr, size));
        self.heap.lock()
        .init(start_addr, size);
    }
}

unsafe impl GlobalAlloc for RiscvHeap {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
//        self.heap.allocate_first_fit(layout).ok()
//       .map_or(0 as *mut u8, |allocation| allocation.as_ptr()) }

        //self.heap
        //    .lock(|heap| heap.allocate_first_fit(layout))
        //    .ok()
        //    .map_or(0 as *mut u8, |allocation| allocation.as_ptr())

        self.heap
        .lock()
        .allocate_first_fit(layout)
        .ok()
        .map_or(0 as *mut u8, |allocation| allocation.as_ptr())
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
//        (&mut *self).heap.deallocate(NonNull::new_unchecked(ptr), layout);
//            .lock(|heap| heap.deallocate(NonNull::new_unchecked(ptr), layout));
        self.heap
        .lock()
        .deallocate(NonNull::new_unchecked(ptr), layout)
    }
}
