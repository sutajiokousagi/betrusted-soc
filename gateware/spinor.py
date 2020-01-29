from litex.build.xilinx.vivado import XilinxVivadoToolchain
from litex.soc.interconnect.csr_eventmanager import *
from litex.soc.interconnect import wishbone
from litex.soc.integration.doc import AutoDoc, ModuleDoc
from migen.genlib.cdc import MultiReg

class SpiOpi(Module, AutoCSR, AutoDoc):
    def __init__(self, pads, dq_delay_taps=0, sclk_name="SCLK_ODDR",
                 iddr_name="SPI_IDDR", miso_name="MISO_FDRE", sim=False):
        self.intro = ModuleDoc("""
        SpiOpi implements a dual-mode SPI or OPI interface. OPI is an octal (8-bit) wide
        variant of SPI, which is unique to Macronix parts. It is concurrently interoperable
        with SPI. The chip supports "DTR mode" (double transfer rate, e.g. DDR) where data
        is transferred on each edge of the clock, and there is a source-synchronous DQS
        associated with the input data.
        
        The chip by default boots into SPI-only mode (unless NV bits are burned otherwise)
        so to enable OPI, a config register needs to be written with SPI mode. 
        
        The SpiOpi architecture is split into two levels: a command manager, and a
        cycle manager. The command manager is responsible for taking the current wishbone
        request and CSR state and unpacking these into cycle-by-cycle requests. The cycle
        manager is responsible for coordinating the cycle-by-cycle requests. 
        
        In SPI mode, this means marshalling byte-wide requests into a series of 8 serial cyles.
        
        In OPI mode, this means marshalling 16-bit wide requests into a pair of back-to-back DDR
        cycles. Note that because the cycles are DDR, this means one 16-bit wide request must be
        issued every cycle to keep up with the interface. 
        
        For the output of data to ROM, expects a clock called "spinor_delayed" which is a delayed 
        version of "sys". The delay is necessary to get the correct phase relationship between 
        the SIO and SCLK in DTR/DDR mode, and it also has to compensate for the special-case
        difference in the CCLK pad vs other I/O.
        
        For the input, DQS signal is independently delayed relative to the DQ signals using
        an IDELAYE2 block. At a REFCLK frequency of 200 MHz, each delay tap adds 78ps, so up
        to a 2.418ns delay is possible between DQS and DQ. The goal is to delay DQS relative
        to DQ, because the SPI chip launches both with concurrent rising edges (to within 0.6ns),
        but the IDDR register needs the rising edge of DQS to be centered inside the DQ eye.
        """)
        cs_n = Signal(reset=1)

        self.config = CSRStorage(fields=[
            CSRField("dummy", size=5, description="Number of dummy cycles", reset=10),
        ])

        delay_type="VAR_LOAD" # FIXED for timing closure analysis; change to "VAR_LOAD" for production if runtime adjustments are needed

        # DQS input conditioning -----------------------------------------------------------------
        dqs_delayed = Signal()
        dqs_iobuf = Signal()
        self.dqs_delay_config = CSRStorage(fields=[
            CSRField("d", size=5, description="Delay amount; each increment is 78ps"),
            CSRField("load", size=1, description="Set delay taps to delay_d"),
            CSRField("inc", size=1, description="`1` increments delay, `0` decrements delay when CE is pulsed"),
            CSRField("ce", size=1, pulse=True, description="Writing to this register changes increment according to inc"),
        ])
        self.dqs_delay_status = CSRStatus(fields=[
            CSRField("q", size=5, description="Readback of current delay amount, useful if inc/ce is used to set"),
        ])
        self.specials += [
            Instance("BUFR", i_I=pads.dqs, o_O=dqs_iobuf),
        ]


        # DQ connections -------------------------------------------------------------------------
        # PHY API
        self.do = Signal(16) # OPI data to SPI
        self.di = Signal(16) # OPI data from SPI
        self.tx = Signal() # when asserted OPI is transmitting data to SPI, otherwise, receiving

        self.mosi = Signal() # SPI data to SPI
        self.miso = Signal() # SPI data from SPI

        # Delay programming API
        self.delay_config = CSRStorage(fields=[
            CSRField("d", size=5, description="Delay amount; each increment is 78ps", reset=31),
            CSRField("load", size=1, description="Force delay taps to delay_d"),
        ])
        self.delay_status = CSRStatus(fields=[
            CSRField("q", size=5, description="Readback of current delay amount, useful if inc/ce is used to set"),
        ])
        self.delay_update = Signal()
        self.hw_delay_load = Signal()
        self.sync += self.delay_update.eq(self.hw_delay_load | self.delay_config.fields.load)

        # Break system API into rising/falling edge samples
        do_rise = Signal(8) # data output presented on the rising edge
        do_fall = Signal(8) # data output presented on the falling edge
        self.comb += [do_rise.eq(self.do[8:]), do_fall.eq(self.do[:8])]

        di_rise = Signal(8)
        di_fall = Signal(8)
        self.comb += self.di.eq(Cat(di_fall, di_rise))  # data is ordered D1(r)/D0(f) and Cat is LSB to MSB

        # OPI DDR registers
        dq = TSTriple(7) # dq[0] is special because it is also MOSI
        dq_delayed = Signal(8)
        self.specials += dq.get_tristate(pads.dq[1:])
        for i in range(1, 8):
            self.specials += Instance("ODDR",
                p_DDR_CLK_EDGE="SAME_EDGE",
                i_C=ClockSignal(), i_R=ResetSignal(), i_S=0, i_CE=1,
                i_D1=do_rise[i], i_D2=do_fall[i], o_Q=dq.o[i-1],
            )
            if sim == False:
                if i == 1: # only wire up o_CNTVALUEOUT for one instance
                    self.specials += Instance("IDELAYE2",
                             p_DELAY_SRC="IDATAIN", p_SIGNAL_PATTERN="DATA",
                             p_CINVCTRL_SEL="FALSE", p_HIGH_PERFORMANCE_MODE="FALSE", p_REFCLK_FREQUENCY=200.0,
                             p_PIPE_SEL="FALSE", p_IDELAY_VALUE=dq_delay_taps, p_IDELAY_TYPE=delay_type,

                             i_C=ClockSignal(), i_CINVCTRL=0, i_REGRST=0, i_LDPIPEEN=0, i_INC=0, i_CE=0,
                             i_LD=self.delay_update,
                             i_CNTVALUEIN=self.delay_config.fields.d, o_CNTVALUEOUT=self.delay_status.fields.q,
                             i_IDATAIN=dq.i[i-1], o_DATAOUT=dq_delayed[i],
                    ),
                else: # don't wire up o_CNTVALUEOUT for others
                    self.specials += Instance("IDELAYE2",
                              p_DELAY_SRC="IDATAIN", p_SIGNAL_PATTERN="DATA",
                              p_CINVCTRL_SEL="FALSE", p_HIGH_PERFORMANCE_MODE="FALSE", p_REFCLK_FREQUENCY=200.0,
                              p_PIPE_SEL="FALSE", p_IDELAY_VALUE=dq_delay_taps, p_IDELAY_TYPE=delay_type,

                              i_C=ClockSignal(), i_CINVCTRL=0, i_REGRST=0, i_LDPIPEEN=0, i_INC=0, i_CE=0,
                              i_LD=self.delay_update,
                              i_CNTVALUEIN=self.delay_config.fields.d,
                              i_IDATAIN=dq.i[i-1], o_DATAOUT=dq_delayed[i],
                  ),
            else:
                self.comb += dq_delayed[i].eq(dq.i[i-1])
            self.specials += Instance("IDDR", name="{}{}".format(iddr_name, str(i)),
                p_DDR_CLK_EDGE="SAME_EDGE_PIPELINED",
                i_C=dqs_iobuf, i_R=ResetSignal(), i_S=0, i_CE=1,
                i_D=dq_delayed[i], o_Q1=di_rise[i], o_Q2=di_fall[i],
            )
        # SPI SDR register
        self.specials += [
            Instance("FDRE", name="{}".format(miso_name), i_C=~ClockSignal("spinor"), i_CE=1, i_R=0, o_Q=self.miso,
                     i_D=dq_delayed[1],
            )
        ]

        # bit 0 (MOSI) is special-cased to handle SPI mode
        dq_mosi = TSTriple(1) # this has similar structure but an independent "oe" signal
        self.specials += dq_mosi.get_tristate(pads.dq[0])
        do_mux_rise = Signal() # mux signal for mosi/dq select of bit 0
        do_mux_fall = Signal()
        self.specials += [
            Instance("ODDR",
              p_DDR_CLK_EDGE="SAME_EDGE",
              i_C=ClockSignal(), i_R=ResetSignal(), i_S=0, i_CE=1,
              i_D1=do_mux_rise, i_D2=do_mux_fall, o_Q=dq_mosi.o,
            ),
            Instance("IDDR",
              p_DDR_CLK_EDGE="SAME_EDGE_PIPELINED",
              i_C=dqs_iobuf, i_R=ResetSignal(), i_S=0, i_CE=1,
              o_Q1=di_rise[0], o_Q2=di_fall[0], i_D=dq_delayed[0],
            ),
        ]
        if sim == False:
            self.specials += [
            Instance("IDELAYE2",
                     p_DELAY_SRC="IDATAIN", p_SIGNAL_PATTERN="DATA",
                     p_CINVCTRL_SEL="FALSE", p_HIGH_PERFORMANCE_MODE="FALSE", p_REFCLK_FREQUENCY=200.0,
                     p_PIPE_SEL="FALSE", p_IDELAY_VALUE=dq_delay_taps, p_IDELAY_TYPE=delay_type,

                     i_C=ClockSignal(), i_CINVCTRL=0, i_REGRST=0, i_LDPIPEEN=0, i_INC=0, i_CE=0,
                     i_LD=self.delay_update,
                     i_CNTVALUEIN=self.delay_config.fields.d,
                     i_IDATAIN=dq_mosi.i, o_DATAOUT=dq_delayed[0],
                     ),
            ]
        else:
            self.comb += dq_delayed[0].eq(dq_mosi.i)

        # wire up SCLK interface
        clk_en = Signal()
        self.specials += [
            # de-activate the CCLK interface, parallel it with a GPIO
            Instance("STARTUPE2",
                     i_CLK=0, i_GSR=0, i_GTS=0, i_KEYCLEARB=0, i_PACK=0, i_USRDONEO=1, i_USRDONETS=1,
                     i_USRCCLKO=0, i_USRCCLKTS=1,  # force to tristate
                     ),
            Instance("ODDR", name=sclk_name, # need to name this so we can constrain it properly
                     p_DDR_CLK_EDGE="SAME_EDGE",
                     i_C=ClockSignal("spinor"), i_R=ResetSignal("spinor"), i_S=0, i_CE=1,
                     i_D1=clk_en, i_D2=0, o_Q=pads.sclk,
                     )
        ]

        # wire up CS_N
        self.specials += [
            Instance("ODDR",
              p_DDR_CLK_EDGE="SAME_EDGE",
              i_C=ClockSignal(), i_R=0, i_S=ResetSignal(), i_CE=1,
              i_D1=cs_n, i_D2=cs_n, o_Q=pads.cs_n,
            ),
        ]

        self.phydoc = ModuleDoc("""
        The architecture is split into two levels: MAC and PHY. 
        
        The MAC layer is responsible for:
        * receiving requests via CSR register to perform config/status/special command sequences,
        and dispatching these to either OPI or SPI PHY
        * translating wishbone bus requests into command sequences, and routing them to either OPI
        or SPI PHY.
        * managing the chip select to the chip, and ensuring that one dummy cycle is inserted after
        chip select is asserted, or before it is de-asserted; and that the chip select "high" times
        are adequate (1 cycle between reads, 4 cycles for all other operations)
        
        On boot, the interface runs in SPI; once the wakeup sequence is executed, the chip permanently
        switches to OPI mode unless the CR2 registers are written to fall back, or the 
        reset to the chip is asserted.
          
        The PHY layers are responsible for the following tasks:
        * Serializing and deserializing data, standardized on 8 bits for SPI and 16 bits for OPI
        * counting dummy cycles
        * managing the clock enable
        
        As such, the PHY is configured with a "dummy cycle" count register. Data is presented at the
        respective bit-widths. PHY cycles are initiated with a "req" signal, which is only sampled for 
        one cycle and then ignored until the PHY issues an "ack" that the current cycle is complete. 
        Thus holding "req" high can allow the PHY to back-to-back issue cycles without pause.
        
        In OPI mode, read data is `mesochronous`, that is, they return at precisely the same frequency
        as SCLK, but with an unknown phase relationship. The DQS strobe is provided as a "hint" to
        the receiving side to help retime the data. 
        
        DQS is basically an extra data output that is guaranteed to change polarity with each
        data byte; the skew mismatch of DQS to data is within +/-0.6ns or so. It turns out the mere
        act of routing the DQS into a BUFR buffer before clocking the data into an IDDR primitive
        is sufficient to delay the DQS signal and meet setup and hold time on the IDDR. 
        
        Once captured by the IDDR, the data is fed into a dual-clock FIFO to make the transition
        from the DQS to sysclk domains cleanly. 
        
        Because of the latency involved in going from pin->IDDR->FIFO, excess read cycles are
        required beyond the end of the requested cache line. However, there is virtually no 
        penalty in pre-filling the FIFO with data; if a new cache line has to be fetched, 
        the FIFO can simply be reset and all pointers zeroed. 
        
        Thus, the architecture of an OPI read is as follows:
        
        * When BUS/STB are asserted:
           - capture bus_adr, and compare against the *next read* address pointer
              - if they match, allow the read machine to do the work
           
           - if bus_adr and next read address don't match, save to next read address pointer, and 
             cycle wr/rd clk for 5 cycle while asserting reset to reset the FIFO
           - initiate an 8DTRD with the read address pointer
           - wait the specified dummy cycles
           
           - greedily pre-fill the FIFO by continuing to clock DQS until either:
             - the FIFO is full
             - pre-fetch is aborted because bus_adr and next read address don't match and FIFO is reset
        
           - while CTI==2, assemble data into 32-bit words as soon as EMPTY is deasserted,
             present a bus_ack, and increment the next read address pointer
           - when CTI==7, ack the data, and wait until the next bus cycle with CTI==2 to resume
             reading
        
        A FIFO_SYNC_MACRO is used to instatiate the FIFO. This is chosen because:
           - we can specify RAMB18's, which seem to be under-utilized by the auto-inferred memories by migen
           - the XPM_FIFO_ASYNC macro claims no instantiation support, and also looks like it has weird
             requirements for resetting the pointers: you must check the reset outputs, and the time to
             reset is reported to be as high as around 200ns (anecdotally -- could be just that the sim I
             read on the web is using a really slow clock, but I'm guessing it's around 10 cycles). 
           - the FIFO_SYNC_MACRO has a well-specified fixed reset latency of 5 cycles.
           - The main downside of FIFO_SYNC_MACRO over XPM_FIFO_ASYNC is that XPM_FIFO_ASYNC could allow
             for output data to be read at 32-bit widths, with writes at 16-bit widths -- this means in
             the case that the FIFO is already full and a cache line hits, we could fill the cache line
             at full bus speed, whereas with a 16-bit read width we can only fill the cache line at half
             bus speed. One possible solution to this is to double the width of the FIFO_SYNC_MACRO and 
             require more clocks on the DQS strobe to fill the FIFO. This will increase the latency
             from a new address by 1-2 cycles, at the benefit of improving the readout speed on a hit
             by 2x.
        """)

        # PHY machine mux --------------------------------------------------------------------------
        # clk_en mux
        self.spi_mode = Signal() # when asserted, force into SPI mode only
        spi_clk_en = Signal()
        opi_clk_en = Signal()
        self.sync += clk_en.eq(~self.spi_mode & opi_clk_en | self.spi_mode & spi_clk_en)
        # tristate mux
        self.sync += [
            dq.oe.eq(~self.spi_mode & self.tx),
            dq_mosi.oe.eq(self.spi_mode | self.tx),
        ]
        # data out mux (no data in mux, as we can just sample data in all the time without harm)
        self.comb += do_mux_rise.eq(~self.spi_mode & do_rise[0] | self.spi_mode & self.mosi)
        self.comb += do_mux_fall.eq(~self.spi_mode & do_fall[0] | self.spi_mode & self.mosi)

        has_dummy = Signal() # indicates if the current "req" requires dummy cycles to be appended (used for both OPI/SPI)
        rom_addr = Signal(32, reset=0xFFFFFFFC)  # location of the internal ROM address pointer; reset to invalid address to force an address request on first read

        spi_req = Signal()
        spi_ack = Signal()
        spi_do = Signal(8) # this is the API to the machine
        spi_di = Signal(8)

        opi_req_tx = Signal()
        opi_req_rx = Signal()
        opi_ack = Signal()
        opi_do = Signal(16)
        opi_di = Signal(16)
        # PHY machine: SPI -------------------------------------------------------------------------

        # internal signals are:
        # selection - self.spi_mode
        # OPI - self.do(16), self.di(16), self.tx
        # SPI - self.mosi, self.miso
        # cs_n - both
        # ecs_n - OPI
        # clk_en - both

        spicount = Signal(5)
        spi_so = Signal(8) # this internal to the machine
        spi_si = Signal(8)
        spi_dummy = Signal()
        spi_di_load = Signal() # spi_do load is pipelined back one cycle using this mechanism
        spi_di_load2 = Signal()
        spi_ack_pipe = Signal()
        self.sync += [ # pipelining is required the MISO path is very slow (IOB->fabric FD), and a falling-edge retiming reg is used to meet timing
            spi_di_load2.eq(spi_di_load),
            If(spi_di_load2, spi_di.eq(Cat(self.miso, spi_si[:-1]))).Else(spi_di.eq(spi_di)),
            spi_ack.eq(spi_ack_pipe),
        ]
        self.comb += self.mosi.eq(spi_so[7])
        self.sync += spi_si.eq(Cat(self.miso, spi_si[:-1]))
        self.submodules.spiphy = spiphy = FSM(reset_state="RESET")
        spiphy.act("RESET",
                   If(spi_req,
                      NextState("REQ"),
                      NextValue(spicount, 7),
                      NextValue(spi_clk_en, 1),
                      NextValue(spi_so, spi_do),
                      NextValue(spi_dummy, has_dummy),
                   ).Else(
                       NextValue(spi_clk_en, 0),
                       NextValue(spi_ack_pipe, 0),
                       NextValue(spicount, 0),
                       NextValue(spi_dummy, 0),
                   )
        )
        spiphy.act("REQ",
                   If(spicount > 0,
                      NextValue(spicount, spicount-1),
                      NextValue(spi_clk_en, 1),
                      NextValue(spi_so, Cat(0, spi_so[:-1])),
                      NextValue(spi_ack_pipe, 0),
                   ).Elif( (spicount == 0) & spi_req & ~spi_dummy, # back-to-back transaction
                          NextValue(spi_clk_en, 1),
                          NextValue(spicount, 7),
                          NextValue(spi_clk_en, 1),
                          NextValue(spi_so, spi_do), # reload the so register
                          spi_di_load.eq(1), # "naked" .eq() create single-cycle pulses that default back to 0
                          NextValue(spi_ack_pipe, 1),
                          NextValue(spi_dummy, has_dummy),
                   ).Elif( (spicount == 0) & ~spi_req & ~spi_dummy, # go back to idle
                          spi_di_load.eq(1),
                          NextValue(spi_ack_pipe, 1),
                          NextValue(spi_clk_en, 0),
                          NextState("RESET"),
                   ).Elif( (spicount == 0) & spi_dummy,
                          spi_di_load.eq(1),
                          NextValue(spicount, self.config.fields.dummy),
                          NextValue(spi_clk_en, 1),
                          NextValue(spi_ack_pipe, 0),
                          NextValue(spi_so, 0),  # do a dummy with '0' as the output
                          NextState("DUMMY"),
                   ) # this actually should be a fully defined situation, no "Else" applicable
        )
        spiphy.act("DUMMY",
                   If(spicount > 1, # instead of doing dummy-1, we stop at count == 1
                      NextValue(spicount, spicount - 1),
                      NextValue(spi_clk_en, 1),
                   ).Elif(spicount <= 1 & spi_req,
                          NextValue(spi_clk_en, 1),
                          NextValue(spicount, 7),
                          NextValue(spi_so, spi_do),  # reload the so register
                          NextValue(spi_ack_pipe, 1), # finally ack the cycle
                          NextValue(spi_dummy, has_dummy),
                   ).Else(
                       NextValue(spi_clk_en, 0),
                       NextValue(spi_ack_pipe, 1),  # finally ack the cycle
                       NextState("RESET")
                   )
        )

        # PHY machine: OPI -------------------------------------------------------------------------
        opicount = Signal(5)
        self.submodules.opiphy = opiphy = FSM(reset_state="IDLE")
        opiphy.act("IDLE",
                   If(opi_req_tx & ~has_dummy,
                      NextState("IDLE"),
                      NextValue(self.tx, 1),
                      NextValue(opi_clk_en, 1),
                      NextValue(self.do, opi_do),
                      NextValue(opi_ack, 1),
                   ).Elif(opi_req_tx & has_dummy,
                          NextValue(self.tx, 1),
                          NextState("DUMMY"),
                          NextValue(opi_clk_en, 1),
                          NextValue(self.do, opi_do),
                          NextValue(opicount, self.config.fields.dummy - 1),
                          NextValue(opi_ack, 0),
                   ).Elif(opi_req_rx, # note: there are no valid RX cycles followed by a dummy, so we ignore that input
                          NextValue(self.tx, 0),
                          NextState("RX_PIPE"),
                          NextValue(opi_clk_en, 1),
                   ).Else(
                       NextValue(self.tx, 0),
                       NextValue(opi_clk_en, 0),
                       NextValue(opi_ack, 0),
                       NextValue(opicount, 0),
                   )
        )
        opiphy.act("RX_PIPE",
                   NextValue(opi_di, self.di),
                   NextValue(opi_ack, 1),
                   If(~opi_req_rx,
                      NextState("IDLE"),
                      NextValue(opi_clk_en, 0),
                    ).Else(
                       NextValue(opi_clk_en, 1),
                   )
        )
        opiphy.act("DUMMY", # note, once in dummy, the next cycle must either be an opi_req_rx, or idle
                   NextValue(self.tx, 0),
                   If(opicount > 0,
                      NextValue(opicount, opicount-1),
                      NextValue(self.do, 0),
                      NextValue(opi_clk_en, 1),
                   ).Elif(opicount == 0 & opi_req_rx,
                          NextState("RX_PIPE"),
                          NextValue(opi_clk_en, 1),
                          NextValue(opi_ack, 1),
                   ).Else(
                       NextValue(opi_clk_en, 0),
                       NextValue(opi_ack, 1),
                   ) # if there is an opi_req_tx at this point...we ignore it here, and handle it in idle
        )

        # MAC machine -------------------------------------------------------------------------------
        self.bus = wishbone.Interface()

        self.command = CSRStorage(description="Write individual bits to issue special commands to SPI; setting multiple bits at once leads to undefined behavior.",
        write_from_dev=True,
        fields=[
            CSRField("rdid", size=1, description="Issue a RDID command & update id register"),
            CSRField("wakeup", size=1, description="Sequence through init & wakeup routine"),
        ])
        self.id = CSRStatus(description="ID code of FLASH, need to issue rdid command first", fields=[
            CSRField("id", size=24, description="ID code of the device")
        ])
        # TODO: implement ECC detailed register readback, CRC checking

        addr_updated = Signal()
        d_to_wb = Signal(32) # data going back to wishbone
        mac_count = Signal(5)
        new_cycle = Signal(1)
        self.submodules.mac = mac = FSM(reset_state="RESET")
        mac.act("RESET",
                NextValue(self.spi_mode, 1),
                NextValue(addr_updated, 0),
                NextValue(d_to_wb, 0),
                NextValue(cs_n, 1),
                NextValue(has_dummy, 0),
                NextValue(spi_do, 0),
                NextValue(spi_req, 0),
                NextValue(opi_do, 0),
                NextValue(opi_req_tx, 0),
                NextValue(opi_req_rx, 0),
                NextValue(mac_count, 0),
                NextValue(self.bus.ack, 0),
                NextState("WAKEUP_PRE"),
                NextValue(new_cycle, 1),
        )
        mac.act("IDLE",
                NextValue(self.bus.ack, 0),
                If( self.bus.stb == 0,
                    NextValue(new_cycle, 1)
                ),
                If((self.bus.cyc == 1) & (self.bus.stb == 1) & (self.bus.we == 0) & (self.bus.cti != 7), # read cycle requested, not end-of-burst
                   If( (rom_addr[2:] != self.bus.adr) & new_cycle,
                      NextValue(rom_addr, Cat(Signal(2, reset=0), self.bus.adr)),
                      NextValue(addr_updated, 1),
                      NextValue(cs_n, 1), # raise CS in anticipation of a new address cycle

                      NextValue(new_cycle, 0),
                      If(self.spi_mode,
                         NextValue(mac_count, 3),
                         NextState("SPI_READ_32_CS")
                      ).Else(
                         NextValue(mac_count, 0),
                         NextState("OPI_READ_32_CS")
                      )
                   ).Elif( (rom_addr[2:] == self.bus.adr) | (~new_cycle & self.bus.cti == 2),
                           If(self.spi_mode,
                              NextValue(mac_count, 3),  # get another beat of 4 bytes at the next address
                              NextState("SPI_READ_32")
                           ).Else(
                               NextValue(opi_req_rx, 1),
                               NextState("OPI_READ_32_D")
                           )
                   ).Else(
                       NextValue(addr_updated, 0),
                       NextValue(cs_n, 0),
                       If(~self.spi_mode,
                          NextValue(opi_req_rx, 1),
                          NextState("OPI_READ_32_D"),
                       ).Else(
                           # assume: cs_n is low, and address is in the right place
                           NextState("SPI_READ_32"),
                           NextValue(mac_count, 3), # prep the MAC state counter to count out 4 bytes
                       )
                   ),
                ).Elif(self.command.fields.wakeup,
                       NextValue(cs_n, 1),
                       NextValue(self.command.storage, 0),  # clear all pending commands
                       NextState("WAKEUP_PRE"),
                )
        )

        #---------  OPI read machine ------------------------------
        mac.act("OPI_READ_32_D",
               NextValue(d_to_wb, Cat(d_to_wb[16:],opi_di)),
               NextValue(rom_addr, rom_addr + 2),
               NextState("OPI_READ_32_DLO"),
        )
        mac.act("OPI_READ_32_DLO",
                NextValue(d_to_wb, Cat(d_to_wb[16:], opi_di)),
                NextValue(self.bus.ack, 1),
                NextValue(rom_addr, rom_addr + 2),
                NextValue(opi_req_rx, 0),
                NextState("IDLE")
        )
        mac.act("OPI_READ_32_CS",
                NextValue(mac_count, mac_count-1),
                If(mac_count == 0,
                   NextValue(cs_n, 0),
                   NextState("OPI_READ_32_A0")
                )
        )
        mac.act("OPI_READ_32_A0",
                NextValue(opi_do,0xEE11),
                NextValue(opi_req_tx, 1),
                NextState("OPI_READ_32_A1"),
        )
        mac.act("OPI_READ_32_A1",
                  NextValue(opi_do,rom_addr[16:] & 0x07FF), # mask off unused bits
                  NextState("OPI_READ_32_A2"),
        )
        mac.act("OPI_READ_32_A2",
                  NextValue(opi_do,rom_addr[:16]),
                   NextValue(has_dummy, 1),
                   NextState("OPI_READ_32_ACKWAIT"),
        )
        mac.act("OPI_READ_32_ACKWAIT",
                NextValue(has_dummy, 0),
                NextValue(opi_req_tx, 0),
                NextState("OPI_READ_32_DUMMY")
        )
        mac.act("OPI_READ_32_DUMMY",
                If(opi_ack,
                   NextValue(opi_req_rx, 1),
                   NextState("OPI_READ_32_D"),
                )
        )


        #---------  wakup chip ------------------------------
        mac.act("WAKEUP_PRE",
                NextValue(cs_n, 1), # why isn't this sticking? i shouldn't have to put this here
                NextValue(mac_count, 4),
                NextState("WAKEUP_PRE_CS_WAIT")
        )
        mac.act("WAKEUP_PRE_CS_WAIT",
                NextValue(mac_count, mac_count-1),
                If(mac_count == 0,
                   NextState("WAKEUP_WUP"),
                   NextValue(cs_n, 0),
                )
        )
        mac.act("WAKEUP_WUP",
                NextValue(mac_count, mac_count-1),
                If(mac_count == 0,
                   NextValue(cs_n, 0),
                   NextValue(spi_do, 0xab),  # wakeup from deep sleep
                   NextValue(spi_req, 1),
                   NextState("WAKEUP_WUP_WAIT"),
                )
        )
        mac.act("WAKEUP_WUP_WAIT",
                NextValue(spi_req, 0),
                If(spi_ack,
                   NextValue(cs_n, 1),  # raise CS
                   NextValue(mac_count, 4),  # for >4 cycles per specsheet
                   NextState("WAKEUP_CR2_WREN_1")
                )
        )

        #---------  WREN+CR2 - dummy cycles ------------------------------
        mac.act("WAKEUP_CR2_WREN_1",
                NextValue(mac_count, mac_count-1),
                If(mac_count == 0,
                   NextValue(cs_n, 0),
                   NextValue(spi_do, 0x06),  # WREN to unlock CR2 writing
                   NextValue(spi_req, 1),
                   NextState("WAKEUP_CR2_WREN_1_WAIT"),
                )
        )
        mac.act("WAKEUP_CR2_WREN_1_WAIT",
                NextValue(spi_req, 0),
                If(spi_ack,
                   NextValue(cs_n, 1),
                   NextValue(mac_count, 4),
                   NextState("WAKEUP_CR2_DUMMY_CMD"),
                )
        )
        mac.act("WAKEUP_CR2_DUMMY_CMD",
                NextValue(mac_count, mac_count-1),
                If(mac_count == 0,
                   NextValue(cs_n, 0),
                   NextValue(spi_do, 0x72), # CR2 command
                   NextValue(spi_req, 1),
                   NextValue(mac_count, 2),
                   NextState("WAKEUP_CR2_DUMMY_ADRHI"),
                )
        )
        mac.act("WAKEUP_CR2_DUMMY_ADRHI",
                NextValue(spi_do, 0x00),   # we want to send 00_00_03_00
                If(spi_ack,
                   NextValue(mac_count, mac_count -1),
                ),
                If(mac_count == 0,
                   NextState("WAKEUP_CR2_DUMMY_ADRMID")
                )
        )
        mac.act("WAKEUP_CR2_DUMMY_ADRMID",
                NextValue(spi_do, 0x03),
                If(spi_ack, NextState("WAKEUP_CR2_DUMMY_ADRLO")),
        )
        mac.act("WAKEUP_CR2_DUMMY_ADRLO",
                NextValue(spi_do, 0x00),
                If(spi_ack, NextState("WAKEUP_CR2_DUMMY_DATA")),
        )
        mac.act("WAKEUP_CR2_DUMMY_DATA",
                NextValue(spi_do, 0x05),   # 10 dummy cycles as required for 84MHz-104MHz operation
                If(spi_ack, NextState("WAKEUP_CR2_DUMMY_WAIT")),
        )
        mac.act("WAKEUP_CR2_DUMMY_WAIT",
                NextValue(spi_req, 0),
                If(spi_ack,
                   NextValue(cs_n, 1),
                   NextValue(mac_count, 4),
                   NextState("WAKEUP_CR2_WREN_2")
                )
        )

        #---------  WREN+CR2 to DOPI mode ------------------------------
        mac.act("WAKEUP_CR2_WREN_2",
                NextValue(mac_count, mac_count-1),
                If(mac_count == 0,
                   NextValue(cs_n, 0),
                   NextValue(spi_do, 0x06),  # WREN to unlock CR2 writing
                   NextValue(spi_req, 1),
                   NextState("WAKEUP_CR2_WREN_2_WAIT"),
                )
        )
        mac.act("WAKEUP_CR2_WREN_2_WAIT",
                NextValue(spi_req, 0),
                If(spi_ack,
                   NextValue(cs_n, 1),
                   NextValue(mac_count, 4),
                   NextState("WAKEUP_CR2_DOPI_CMD"),
                )
        )
        mac.act("WAKEUP_CR2_DOPI_CMD",
                NextValue(mac_count, mac_count-1),
                If(mac_count == 0,
                   NextValue(cs_n, 0),
                   NextValue(spi_do, 0x72),  # CR2 command
                   NextValue(spi_req, 1),
                   NextValue(mac_count, 4),
                   NextState("WAKEUP_CR2_DOPI_ADR"),
                )
        )
        mac.act("WAKEUP_CR2_DOPI_ADR",  # send 0x00_00_00_00 as address
                NextValue(spi_do, 0x00),  # no need to raise CS or lower spi_req, this is back-to-back
                If(spi_ack,
                   NextValue(mac_count, mac_count - 1),
                ),
                If(mac_count == 0,
                   NextState("WAKEUP_CR2_DOPI_DATA"),
                )
        ),
        mac.act("WAKEUP_CR2_DOPI_DATA",
                NextValue(spi_do, 2),    # enable DOPI mode
                If(spi_ack, NextState("WAKEUP_CR2_DOPI_WAIT")),
        )
        mac.act("WAKEUP_CR2_DOPI_WAIT", # trailing CS wait
                NextValue(spi_req, 0),
                If(spi_ack,
                   NextValue(cs_n, 1),
                   NextValue(mac_count, 4),
                   NextState("WAKEUP_CS_EXIT")
                )
        )
        mac.act("WAKEUP_CS_EXIT",
                NextValue(self.spi_mode, 0),  # now enter DOPI mode
                NextValue(mac_count, mac_count-1),
                If(mac_count == 0,
                   NextState("IDLE"),
                )
        )


        #---------  SPI read machine ------------------------------
        mac.act("SPI_READ_32",
                If(addr_updated,
                   NextState("SPI_READ_32_CS"),
                   NextValue(has_dummy, 0),
                   NextValue(mac_count, 3),
                   NextValue(cs_n, 1),
                   NextValue(spi_req, 0),
                ).Else(
                    If(mac_count > 0,
                       NextValue(has_dummy, 0),
                       NextValue(spi_req, 1),
                       NextState("SPI_READ_32_D")
                    ).Else(
                        NextValue(spi_req, 0),
                        If(spi_ack,
                           NextValue(self.bus.dat_r, Cat(d_to_wb[8:],spi_di)),
                           NextValue(self.bus.ack, 1),
                           NextValue(rom_addr, rom_addr + 1),
                           NextState("IDLE")
                        )
                    )
                )
        )
        mac.act("SPI_READ_32_D",
                If(spi_ack,
                   # shift in one byte at a time to d_to_wb(32)
                   NextValue(d_to_wb, Cat(d_to_wb[8:],spi_di,)),
                   NextValue(mac_count, mac_count - 1),
                   NextState("SPI_READ_32"),
                   NextValue(rom_addr, rom_addr + 1),
                )
        )
        mac.act("SPI_READ_32_CS",
                NextValue(mac_count, mac_count-1),
                If(mac_count == 0,
                   NextValue(cs_n, 0),
                   NextState("SPI_READ_32_A0"),
                )
        )
        mac.act("SPI_READ_32_A0",
                NextValue(spi_do, 0x0c), # 32-bit address write for "fast read" command
                NextValue(spi_req, 1),
                NextState("SPI_READ_32_A1"),
        )
        mac.act("SPI_READ_32_A1",
                NextValue(spi_do, rom_addr[24:] & 0x7), # queue up MSB to send, leave req high; mask off unused high bits
                If(spi_ack,
                   NextState("SPI_READ_32_A2"),
                )
        )
        mac.act("SPI_READ_32_A2",
                NextValue(spi_do, rom_addr[16:24]),
                If(spi_ack,
                   NextState("SPI_READ_32_A3"),
                )
        )
        mac.act("SPI_READ_32_A3",
                NextValue(spi_do, rom_addr[8:16]),
                If(spi_ack,
                   NextState("SPI_READ_32_A4"),
                )
        )
        mac.act("SPI_READ_32_A4",
                NextValue(spi_do, rom_addr[:8]),
                If(spi_ack,
                   NextState("SPI_READ_32_A5"),
                )
        )
        mac.act("SPI_READ_32_A5",
                NextValue(spi_do, 0),
                If(spi_ack,
                   NextState("SPI_READ_32_DUMMY")
                )
        )
        mac.act("SPI_READ_32_DUMMY",
                NextValue(spi_req, 0),
                NextValue(addr_updated, 0),
                If(spi_ack,
                   NextState("SPI_READ_32"),
                   NextValue(mac_count, 3),  # prep the MAC state counter to count out 4 bytes
                ).Else(
                    NextState("SPI_READ_32_DUMMY")
                )
        )

        # Handle ECS_n -----------------------------------------------------------------------------
        # treat ECS_N as an async signal -- just a "rough guide" of problems
        ecs_n = Signal()
        self.specials += MultiReg(pads.ecs_n, ecs_n)

        self.submodules.ev = EventManager()
        self.ev.ecc_error = EventSourceProcess()  # Falling edge triggered
        self.ev.finalize()
        self.comb += self.ev.ecc_error.trigger.eq(ecs_n)
        ecc_reported = Signal()
        ecs_n_delay = Signal()
        ecs_pulse = Signal()

        self.ecc_address = CSRStatus(fields=[
            CSRField("ecc_address", size=32, description="Address of the most recent ECC event")
        ])
        self.ecc_status = CSRStatus(fields=[
            CSRField("ecc_error", size=1, description="Live status of the ECS_N bit (ECC error on current packet when low)"),
            CSRField("ecc_overflow", size=1, description="More than one ECS_N event has happened since th last time ecc_address was checked")
        ])

        self.comb += self.ecc_status.fields.ecc_error.eq(ecs_n)
        self.comb += [
            ecs_pulse.eq(ecs_n_delay & ~ecs_n), # falling edge -> positive pulse
            If(ecs_pulse,
               self.ecc_address.fields.ecc_address.eq(rom_addr),
               If(ecc_reported,
                  self.ecc_status.fields.ecc_overflow.eq(1)
               ).Else(
                   self.ecc_status.fields.ecc_overflow.eq(self.ecc_status.fields.ecc_overflow),
               )
            ).Else(
                self.ecc_address.fields.ecc_address.eq(self.ecc_address.fields.ecc_address),
                If(self.ecc_status.we,
                   self.ecc_status.fields.ecc_overflow.eq(0),
                ).Else(
                    self.ecc_status.fields.ecc_overflow.eq(self.ecc_status.fields.ecc_overflow),
                )
            )
        ]
        self.sync += [
            ecs_n_delay.eq(ecs_n),
            If(ecs_pulse,
               ecc_reported.eq(1)
            ).Elif(self.ecc_address.we,
                ecc_reported.eq(0)
            )
        ]

"""
        ### THIS IS A BAD IDEA -- CR1 takes 40ms to write! too long on the boot. these states archived
        #---------  WREN+CR1 ------------------------------
        mac.act("WAKEUP_CR1_WREN",
                NextValue(mac_count, mac_count-1),
                If(mac_count == 0,
                   NextValue(cs_n, 0),
                   NextValue(spi_do, 0x06),  # WREN to unlock CR1 writing
                   NextValue(spi_req, 1),
                   NextState("WAKEUP_CR1_WREN_WAIT")
                )
        )
        mac.act("WAKEUP_CR1_WREN_WAIT",
                NextValue(spi_req, 0),
                If(spi_ack,
                   NextValue(cs_n, 1),
                   NextValue(mac_count, 4),
                   NextState("WAKEUP_CR1_1")
                )
        )
        mac.act("WAKEUP_CR1_1",
                NextValue(mac_count, mac_count-1),
                If(mac_count == 0,
                   NextValue(cs_n, 0),
                   NextValue(spi_do, 0x01),  # write config sequence
                   NextValue(spi_req, 1),
                   NextState("WAKEUP_CR1_3")
                )
        )
        mac.act("WAKEUP_CR1_3",
                NextValue(spi_do, 0x00),
                If(spi_ack, NextState("WAKEUP_CR1_4")),
        )
        mac.act("WAKEUP_CR1_4",
                NextValue(spi_do, 0x13),  # set to 41 ohms drive strength, PRE enabled
                If(spi_ack, NextState("WAKEUP_CR1_8")),
        )
        mac.act("WAKEUP_CR1_8",
                NextValue(spi_req, 0),
                If(spi_ack,
                   NextValue(cs_n, 1),
                   NextValue(mac_count, 4),
                   NextState("WAKEUP_CR2_WREN_2"),
                )
        )
"""


class SPINOR(Module, AutoCSR):
    def __init__(self, platform, pads, size=2*1024*1024):
        self.size = size
        self.bus  = bus = wishbone.Interface()

        self.reset = Signal()

        self.cfg0 = CSRStorage(size=8)
        self.cfg1 = CSRStorage(size=8)
        self.cfg2 = CSRStorage(size=8)
        self.cfg3 = CSRStorage(size=8)

        self.stat0 = CSRStatus(size=8)
        self.stat1 = CSRStatus(size=8)
        self.stat2 = CSRStatus(size=8)
        self.stat3 = CSRStatus(size=8)

        # # #

        cfg     = Signal(32)
        cfg_we  = Signal(4)
        cfg_out = Signal(32)
        self.comb += [
            cfg.eq(Cat(self.cfg0.storage, self.cfg1.storage, self.cfg2.storage, self.cfg3.storage)),
            cfg_we.eq(Cat(self.cfg0.re, self.cfg1.re, self.cfg2.re, self.cfg3.re)),
            self.stat0.status.eq(cfg_out[0:8]),
            self.stat1.status.eq(cfg_out[8:16]),
            self.stat2.status.eq(cfg_out[16:24]),
            self.stat3.status.eq(cfg_out[24:32]),
        ]

        mosi_pad = TSTriple()
        miso_pad = TSTriple()
        cs_n_pad = TSTriple()
        if isinstance(platform.toolchain, XilinxVivadoToolchain) == False:
            clk_pad  = TSTriple()
        wp_pad   = TSTriple()
        hold_pad = TSTriple()
        self.specials += mosi_pad.get_tristate(pads.mosi)
        self.specials += miso_pad.get_tristate(pads.miso)
        self.specials += cs_n_pad.get_tristate(pads.cs_n)
        if isinstance(platform.toolchain, XilinxVivadoToolchain) == False:
            self.specials += clk_pad.get_tristate(pads.clk)
        self.specials += wp_pad.get_tristate(pads.wp)
        self.specials += hold_pad.get_tristate(pads.hold)

        reset = Signal()
        self.comb += [
            reset.eq(ResetSignal() | self.reset),
            cs_n_pad.oe.eq(~reset),
        ]
        if isinstance(platform.toolchain, XilinxVivadoToolchain) == False:
            self.comb +=  clk_pad.oe.eq(~reset)

        flash_addr = Signal(24)
        # Size/4 because data bus is 32 bits wide, -1 for base 0
        mem_bits = bits_for(int(size/4)-1)
        pad = Signal(2)
        self.comb += flash_addr.eq(Cat(pad, bus.adr[0:mem_bits-1]))

        read_active = Signal()
        spi_ready   = Signal()
        self.sync += [
            bus.ack.eq(0),
            read_active.eq(0),
            If(bus.stb & bus.cyc & ~read_active,
                read_active.eq(1)
            )
            .Elif(read_active & spi_ready,
                bus.ack.eq(1)
            )
        ]

        o_rdata = Signal(32)
        self.comb += bus.dat_r.eq(o_rdata)

        instance_clk = Signal()
        if isinstance(platform.toolchain, XilinxVivadoToolchain):
            self.specials += Instance("STARTUPE2",
                i_CLK       = 0,
                i_GSR       = 0,
                i_GTS       = 0,
                i_KEYCLEARB = 0,
                i_PACK      = 0,
                i_USRCCLKO  = instance_clk,
                i_USRCCLKTS = 0,
                i_USRDONEO  = 1,
                i_USRDONETS = 1
            )
        else:
            self.comb += clk_pad.o.eq(instance_clk)
        self.specials += Instance("spimemio",
            o_flash_io0_oe = mosi_pad.oe,
            o_flash_io1_oe = miso_pad.oe,
            o_flash_io2_oe = wp_pad.oe,
            o_flash_io3_oe = hold_pad.oe,

            o_flash_io0_do = mosi_pad.o,
            o_flash_io1_do = miso_pad.o,
            o_flash_io2_do = wp_pad.o,
            o_flash_io3_do = hold_pad.o,
            o_flash_csb    = cs_n_pad.o,
            o_flash_clk    = instance_clk,

            i_flash_io0_di = mosi_pad.i,
            i_flash_io1_di = miso_pad.i,
            i_flash_io2_di = wp_pad.i,
            i_flash_io3_di = hold_pad.i,

            i_resetn       = ~reset,
            i_clk          = ClockSignal(),

            i_valid        = bus.stb & bus.cyc,
            o_ready        = spi_ready,
            i_addr         = flash_addr,
            o_rdata        = o_rdata,

            i_cfgreg_we    = cfg_we,
            i_cfgreg_di    = cfg,
            o_cfgreg_do    = cfg_out,
        )
        platform.add_source("gateware/spimemio.v")
