from litex.soc.integration.doc import AutoDoc, ModuleDoc
from litex.soc.interconnect.csr_eventmanager import *

from migen.genlib.cdc import MultiReg
from migen.genlib.coding import Decoder

# Relies on a clock called "kbd" for delay counting
# Input and output through "i" and "o" signals respectively
class Debounce(Module):
    def __init__(self, debounce_count):
        self.i = Signal()
        self.o = Signal()

        sync_i = Signal()
        self.specials += MultiReg(self.i, sync_i, odomain="kbd");
        o_kbd = Signal()
        self.specials += MultiReg(o_kbd, self.o)

        count = Signal(max=(2*debounce_count))

        self.sync.kbd += [
            If( count >= debounce_count,
                o_kbd.eq(1)
            ).Else(
                o_kbd.eq(0)
            ),

            # Basic idea: debounce_count is how long you want to debounce for
            # If key is pressed, count up to debounce_count; if it bounces, reset to 0 count
            # Only until key is held for debounce_count successive counts, do we declare a key press.
            # At this point, we set the count to 2*debounce_count, so we can repeat the same process for
            # the key release, except counting down to 0.
            If(sync_i & count < debounce_count,
               count.eq(count + 1),
            ).Elif( sync_i & count >= debounce_count,
                count.eq(2*debounce_count),  # once we've reached debounce_count, "snap" up to 2x debounce_count to prep for key release
            ).Elif( ~sync_i & count < debounce_count,
                count.eq(0),  # once we've fell below debounce_count, "snap" down to 0 to prepare for next key press
            ).Elif( ~sync_i & count >= debounce_count,
                count.eq(count - 1),
            ).Else(
                count.eq(count) # should be unreachable? I think I covered all the states...
            )
        ]

# A hardware key scanner that can run even when the CPU is powered down or stopped
class KeyScan(Module, AutoCSR, AutoDoc):
    def __init__(self, pads):
        rows_unsync = pads.row
        cols = pads.col
        # row and col are n-bit signals that correspond to the row and columns of the keyboard matrix
        # each row will generate a column register with the column result in it
        rows = Signal(rows_unsync.nbits)
        self.specials += MultiReg(rows_unsync, rows, "kbd")

        # setattr(self, name, object) is the same as self.name = object, except in this case "name" can be dynamically generated
        # this is necessary here because we CSRStatus is not iterable, so we have to manage the attributes manually
        for r in range(0, rows.nbits):
            setattr(self, "row" + str(r) + "dat", CSRStatus(cols.nbits, name="row" + str(r) + "dat", description="""Column data for the given row"""))

        settling=4  # 4 cycles to settle: 2 cycles for MultiReg stabilization + slop. Must be > 2, and a power of 2
        colcount = Signal(max=(settling*cols.nbits+2))

        update_shadow = Signal()
        reset_scan = Signal()
        scan_done = Signal()
        col_r = Signal(cols.nbits)
        scan_done_sys = Signal()
        self.specials += MultiReg(scan_done, scan_done_sys)
        for r in range(0, rows.nbits):
            row_scan = Signal(cols.nbits)
            # below is in sysclock domain; row_scan is guaranteed stable by state machine sequencing when scan_done gating is enabled
            self.sync += If(scan_done_sys, getattr(self, "row" + str(r) + "dat").status.eq(row_scan))\
                         .Else(getattr(self, "row" + str(r) + "dat").status.eq(getattr(self, "row" + str(r) + "dat").status))

            self.sync.kbd += [
                If(reset_scan,
                   row_scan.eq(0)
                ).Else(
                    If(rows[r] & (colcount[0:2] == 3),  # sample row only on the 4th cycle of colcount
                       row_scan.eq(row_scan | col_r)
                    ).Else(
                        row_scan.eq(row_scan)
                    )
                )
            ]

            rowshadow = Signal(cols.nbits)
            self.sync.kbd += If(update_shadow, rowshadow.eq(row_scan)).Else(rowshadow.eq(rowshadow))

            setattr(self, "row_scan" + str(r), row_scan)
            setattr(self, "rowshadow" + str(r), rowshadow)


        self.sync.kbd += [
            If(colcount == (settling*cols.nbits+2),
               colcount.eq(0),
            ).Else(
                colcount.eq(colcount + 1),
            ),

            If(colcount == (settling*cols.nbits),
               scan_done.eq(1),
            ).Else(
                scan_done.eq(0),
            ),
            If(colcount == (settling*cols.nbits+1),
               update_shadow.eq(1),
            ).Else(
               update_shadow.eq(0),
            ),
            If(colcount == (settling*cols.nbits+2),
               reset_scan.eq(1),
            ).Else(
                reset_scan.eq(0)
            )
        ]

        # drive the columns based on the colcount counter
        self.submodules.coldecoder = Decoder(cols.nbits)
        self.comb += [
            self.coldecoder.i.eq(colcount[log2_int(settling):]),
            self.coldecoder.n.eq(~(colcount < settling*cols.nbits)),
            cols.eq(self.coldecoder.o)
        ]
        self.sync.kbd += col_r.eq(self.coldecoder.o)

        self.submodules.ev = EventManager()
        self.ev.keypressed = EventSourcePulse() # rising edge triggered
        self.ev.finalize()
        # extract any changes just before the shadow takes its new values
        rowdiff = Signal(rows.nbits)
        for r in range(0, rows.nbits):
            self.sync.kbd += [
                If(scan_done,
                   rowdiff[r].eq( ~((getattr(self, "row_scan" + str(r)) ^ getattr(self, "rowshadow" + str(r))) == 0) )
                ).Else(
                    rowdiff[r].eq(rowdiff[r])
                )
            ]
        # fire an interrupt during the reset_scan phase. Delay by 2 cycles so that rowchange can pick up a new value
        # before the "pending" bit is set.
        kp_d = Signal()
        kp_d2 = Signal()
        kp_r = Signal()
        kp_r2 = Signal()
        self.sync.kbd += kp_d.eq( rowdiff != 0 )
        self.sync.kbd += kp_d2.eq( kp_d )
        self.sync += kp_r.eq( kp_d2 )
        self.sync += kp_r2.eq( kp_r )
        self.comb += self.ev.keypressed.trigger.eq( kp_r & ~kp_r2 )

        self.rowchange = CSRStatus(rows.nbits, name="rowchange",
                                   description="""The rows that changed at the point of interrupt generation. 
                                   Does not update again until the interrupt is serviced.""")
        reset_scan_sys = Signal()
        self.specials += MultiReg(reset_scan, reset_scan_sys)
        self.sync += [
            If(reset_scan_sys & ~self.ev.keypressed.pending,
               self.rowchange.status.eq(rowdiff)
            ).Else(
                self.rowchange.status.eq(self.rowchange.status)
            )
        ]
