from litex.soc.integration.doc import AutoDoc, ModuleDoc
from litex.soc.interconnect.csr_eventmanager import *
from migen.genlib.cdc import MultiReg

class SpiMaster(Module, AutoCSR, AutoDoc):
    def __init__(self, pads):
        self.intro = ModuleDoc("""Simple soft SPI master module optimized for Betrusted applications

        Requires a clock domain 'spi', which runs at the speed of the SPI bus. 
        """)

        self.miso = pads.miso
        self.mosi = pads.mosi
        self.sclk = pads.sclk
        self.csn = pads.csn

        self.comb += self.sclk.eq(~ClockSignal("spi"))  # TODO: add clock gating to save power

        self.tx = CSRStorage(16, name="tx", description="""Tx data, for MOSI""")
        self.rx = CSRStatus(16, name="rx", description="""Rx data, from MISO""")
        self.control = CSRStorage(fields=[
            CSRField("go", description="Initiate a SPI cycle by writing a `1`", pulse=True),
            CSRField("intena", description="Enable interrupt on transaction finished"),
        ])
        self.status = CSRStatus(fields=[
            CSRField("tip", description="Set when transaction is in progress"),
            CSRField("txfull", description="Set when Tx register is full"),
        ])

        self.submodules.ev = EventManager()
        self.ev.spi_int = EventSourceProcess()  # falling edge triggered
        self.ev.finalize()
        self.comb += self.ev.spi_int.trigger.eq(self.control.fields.intena & self.status.fields.tip)

        # Replica CSR into "spi" clock domain
        self.tx_r = Signal(16)
        self.rx_r = Signal(16)
        self.tip_r = Signal()
        self.txfull_r = Signal()
        self.go_r = Signal()
        self.tx_written = Signal()

        self.specials += MultiReg(self.tip_r, self.status.fields.tip)
        self.specials += MultiReg(self.txfull_r, self.status.fields.txfull)
        self.specials += MultiReg(self.control.fields.go, self.go_r, "spi")
        self.specials += MultiReg(self.tx.re, self.tx_written, "spi")
        # extract rising edge of go -- necessary in case of huge disparity in sysclk-to-spi clock domain
        self.go_d = Signal()
        self.go_edge = Signal()
        self.sync.spi += self.go_d.eq(self.go_r)
        self.comb += self.go_edge.eq(self.go_r & ~self.go_d)

        fsm = FSM(reset_state="IDLE")
        fsm = ClockDomainsRenamer("spi")(fsm)
        self.submodules += fsm
        spicount = Signal(4)
        fsm.act("IDLE",
                If(self.go_edge,
                   NextState("RUN"),
                   NextValue(self.tx_r, Cat(0, self.tx.storage[:15])),
                   # stability guaranteed so no synchronizer necessary
                   NextValue(spicount, 15),
                   NextValue(self.txfull_r, 0),
                   NextValue(self.tip_r, 1),
                   NextValue(self.csn, 0),
                   NextValue(self.mosi, self.tx.storage[15]),
                ).Else(
                    NextValue(self.tip_r, 0),
                    NextValue(self.csn, 1),
                    If(self.tx_written,
                       NextValue(self.txfull_r, 1),
                    ),
                )
        )
        fsm.act("RUN",
                If(spicount > 0,
                   NextValue(self.mosi, self.tx_r[15]),
                   NextValue(self.tx_r, Cat(0, self.tx_r[:15])),
                   NextValue(spicount, spicount - 1),
                ).Else(
                    NextValue(self.csn, 1),
                    NextValue(self.tip_r, 0),
                    NextState("IDLE"),
                ),
                NextValue(self.rx_r, Cat(self.miso, self.rx_r[:15])),
        )


class SpiSlave(Module, AutoCSR, AutoDoc):
    def __init__(self, pads):
        self.intro = ModuleDoc("""Simple soft SPI slave module optimized for Betrusted-EC (UP5K arch) use

        Requires a clock domain 'spi', which runs at the speed of the SPI bus.
        This one relies on FIFOs to do large block transfers, as the CPU runs slowly enough
        that it may not be able to keep up with the SPI bus. 
        """)

        self.miso = pads.miso
        self.mosi = pads.mosi
        self.sclk = pads.sclk
        self.csn = pads.csn

        self.comb += self.sclk.eq(~ClockSignal("spi"))

        self.tx = CSRStorage(16, name="tx", description="""Tx data, for MOSI""")
        self.rx = CSRStatus(16, name="rx", description="""Rx data, from MISO""")
        self.control = CSRStorage(fields=[
            CSRField("go", description="Initiate a SPI cycle by writing a `1`", pulse=True),
            CSRField("intena", description="Enable interrupt on transaction finished"),
        ])
        self.status = CSRStatus(fields=[
            CSRField("tip", description="Set when transaction is in progress"),
            CSRField("txfull", description="Set when Tx register is full"),
        ])

        self.submodules.ev = EventManager()
        self.ev.spi_int = EventSourceProcess()  # falling edge triggered
        self.ev.finalize()
        self.comb += self.ev.spi_int.trigger.eq(self.control.fields.intena & self.status.fields.tip)

        # Replica CSR into "spi" clock domain
        self.tx_r = Signal(16)
        self.rx_r = Signal(16)
        self.tip_r = Signal()
        self.txfull_r = Signal()
        self.go_r = Signal()
        self.tx_written = Signal()

        self.specials += MultiReg(self.tip_r, self.status.fields.tip)
        self.specials += MultiReg(self.txfull_r, self.status.fields.txfull)
        self.specials += MultiReg(self.control.fields.go, self.go_r, "spi")
        self.specials += MultiReg(self.tx.re, self.tx_written, "spi")
        # extract rising edge of go -- necessary in case of huge disparity in sysclk-to-spi clock domain
        self.go_d = Signal()
        self.go_edge = Signal()
        self.sync.spi += self.go_d.eq(self.go_r)
        self.comb += self.go_edge.eq(self.go_r & ~self.go_d)

        fsm = FSM(reset_state="IDLE")
        fsm = ClockDomainsRenamer("spi")(fsm)
        self.submodules += fsm
        spicount = Signal(4)
        fsm.act("IDLE",
                If(self.go_edge,
                   NextState("RUN"),
                   NextValue(self.tx_r, Cat(0, self.tx.storage[:15])),
                   # stability guaranteed so no synchronizer necessary
                   NextValue(spicount, 15),
                   NextValue(self.txfull_r, 0),
                   NextValue(self.tip_r, 1),
                   NextValue(self.csn, 0),
                   NextValue(self.mosi, self.tx.storage[15]),
                ).Else(
                    NextValue(self.tip_r, 0),
                    NextValue(self.csn, 1),
                    If(self.tx_written,
                       NextValue(self.txfull_r, 1),
                    ),
                )
        )
        fsm.act("RUN",
                If(spicount > 0,
                   NextValue(self.mosi, self.tx_r[15]),
                   NextValue(self.tx_r, Cat(0, self.tx_r[:15])),
                   NextValue(spicount, spicount - 1),
                ).Else(
                    NextValue(self.csn, 1),
                    NextValue(self.tip_r, 0),
                    NextState("IDLE"),
                ),
                NextValue(self.rx_r, Cat(self.miso, self.rx_r[:15])),
        )
