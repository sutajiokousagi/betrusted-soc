from litex.build.xilinx.vivado import XilinxVivadoToolchain
from litex.soc.interconnect.csr_eventmanager import *
from litex.soc.interconnect import wishbone
from litex.soc.integration.doc import AutoDoc, ModuleDoc
from migen.genlib.cdc import MultiReg

class SpiOpi(Module, AutoCSR, AutoDoc):
    def __init__(self, pads, dqs_delay_taps=0, dq_delay_taps=31, sclk_instance="SCLK_ODDR", iddr_instance="SPI_IDDR"):
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
        self.bus = wishbone.Interface()

        cs_n = Signal()
        self.sync += [cs_n.eq(self.bus.stb)] # dummy statement for timing closure

        # treat ECS_N as an async signal -- just a "rough guide" of problems
        ecs_n = Signal()
        self.specials += MultiReg(pads.ecs_n, ecs_n)

        self.mode = CSRStorage(fields=[
            CSRField("opi_mode", size=1, description="Set to `1` to enable OPI mode"),
            CSRField("clkgate_test", size=1, description="Gate clock - for testing only. Set to `0` to turn off clock.", reset=1),
        ])

        self.status = CSRStatus(fields=[
            CSRField("ecc_error", size=1, description="Live status of the ECS_N bit (ECC error on current packet when low)")
        ])
        self.comb += self.status.fields.ecc_error.eq(ecs_n)
        # TODO: record current address when ECS_N triggers, wire up an interrupt to ECS_N, record if ECS_N overflow happens

        delay_type="FIXED" # FIXED for timing closure; change to "VAR_LOAD" for production

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
            # Instance("IDELAYE2",
            #          p_DELAY_SRC="IDATAIN", p_SIGNAL_PATTERN="CLOCK",
            #          p_CINVCTRL_SEL="FALSE", p_HIGH_PERFORMANCE_MODE="FALSE", p_REFCLK_FREQUENCY=200,
            #          p_PIPE_SEL="FALSE", p_IDELAY_VALUE=dqs_delay_taps, p_IDELAY_TYPE=delay_type,
            #
            #          i_C=ClockSignal(),
            #          i_LD=self.dqs_delay_config.fields.load, i_CE=self.dqs_delay_config.fields.ce,
            #          i_LDPIPEEN=0, i_INC=self.dqs_delay_config.fields.inc,
            #          i_CNTVALUEIN=self.dqs_delay_config.fields.d, o_CNTVALUEOUT=self.dqs_delay_status.fields.q,
            #          i_IDATAIN=pads.dqs, o_DATAOUT=dqs_delayed,
            # ),
            # Instance("BUFIO", i_I=dqs_delayed, o_O=dqs_iobuf),
            Instance("BUFR", i_I=pads.dqs, o_O=dqs_iobuf),
        ]

        # DQ connections -------------------------------------------------------------------------
        # System API
        self.do = Signal(16) # OPI data to SPI
        self.di = Signal(16) # OPI data from SPI
        self.tx = Signal() # when asserted OPI is transmitting data to SPI, otherwise, receiving
        self.comb += self.tx.eq(self.bus.dat_w)  ### THIS IS TEMPORARY

        self.mosi = Signal() # SPI data to SPI
        self.miso = Signal() # SPI data from SPI
        self.spi_mode = Signal() # when asserted, force into SPI mode only
        self.comb += self.spi_mode.eq(~self.mode.fields.opi_mode)

        # Programming API
        self.delay_config = CSRStorage(fields=[
            CSRField("d", size=5, description="Delay amount; each increment is 78ps"),
            CSRField("load", size=1, description="Set delay taps to delay_d"),
            CSRField("inc", size=1, description="`1` increments delay, `0` decrements delay when CE is pulsed"),
            CSRField("ce", size=1, pulse=True, description="Writing to this register changes increment according to inc"),
        ])
        self.delay_status = CSRStatus(fields=[
            CSRField("q", size=5, description="Readback of current delay amount, useful if inc/ce is used to set"),
        ])

        # Break system API into rising/falling edge samples
        do_rise = Signal(8) # data output presented on the rising edge
        do_fall = Signal(8) # data output presented on the falling edge
        self.comb += [do_rise.eq(self.do[8:]), do_fall.eq(self.do[:8])]

        di_rise = Signal(8)
        di_fall = Signal(8)
        self.comb += self.di.eq(Cat(di_fall, di_rise))  # data is ordered D1(r)/D0(f) and Cat is LSB to MSB

        dq = TSTriple(7) # dq[0] is special because it is also MOSI
        dq_delayed = Signal(8)
        self.specials += dq.get_tristate(pads.dq[1:])
        for i in range(1, 8):
            self.specials += Instance("ODDR",
                p_DDR_CLK_EDGE="SAME_EDGE",
                i_C=ClockSignal(), i_R=ResetSignal(), i_S=0, i_CE=1,
                i_D1=do_rise[i], i_D2=do_fall[i], o_Q=dq.o[i-1],
            )
            if i == 1: # only wire up o_CNTVALUEOUT for one instance
                self.specials += Instance("IDELAYE2",
                         p_DELAY_SRC="IDATAIN", p_SIGNAL_PATTERN="DATA",
                         p_CINVCTRL_SEL="FALSE", p_HIGH_PERFORMANCE_MODE="FALSE", p_REFCLK_FREQUENCY=200,
                         p_PIPE_SEL="FALSE", p_IDELAY_VALUE=dq_delay_taps, p_IDELAY_TYPE=delay_type,

                         i_C=ClockSignal(),
                         i_LD=self.delay_config.fields.load, i_CE=self.delay_config.fields.ce,
                         i_LDPIPEEN=0, i_INC=self.delay_config.fields.inc,
                         i_CNTVALUEIN=self.delay_config.fields.d, o_CNTVALUEOUT=self.delay_status.fields.q,
                         i_IDATAIN=dq.i[i-1], o_DATAOUT=dq_delayed[i],
                ),
            else: # don't wire up o_CNTVALUEOUT for others
                self.specials += Instance("IDELAYE2",
                          p_DELAY_SRC="IDATAIN", p_SIGNAL_PATTERN="DATA",
                          p_CINVCTRL_SEL="FALSE", p_HIGH_PERFORMANCE_MODE="FALSE",
                          p_REFCLK_FREQUENCY=200,
                          p_PIPE_SEL="FALSE", p_IDELAY_VALUE=dq_delay_taps, p_IDELAY_TYPE=delay_type,

                          i_C=ClockSignal(),
                          i_LD=self.delay_config.fields.load, i_CE=self.delay_config.fields.ce,
                          i_LDPIPEEN=0, i_INC=self.delay_config.fields.inc,
                          i_CNTVALUEIN=self.delay_config.fields.d,
                          i_IDATAIN=dq.i[i-1], o_DATAOUT=dq_delayed[i],
              ),
            self.specials += Instance("IDDR", name="SPI_IDDR{}".format(str(i)),
                p_DDR_CLK_EDGE="SAME_EDGE_PIPELINED", # higher latency, but easier timing closure
                i_C=dqs_iobuf, i_R=ResetSignal(), i_S=0, i_CE=1,
                i_D=dq_delayed[i], o_Q1=di_rise[i], o_Q2=di_fall[i],
            )

        # bit 0 (MOSI) is special-cased to handle SPI mode
        dq_mosi = TSTriple(1) # this has similar structure but an independent "oe" signal
        self.specials += dq_mosi.get_tristate(pads.dq[0])
        do_mux = Signal() # mux signal for mosi/dq select of bit 0
        self.specials += [
            Instance("ODDR",
              p_DDR_CLK_EDGE="SAME_EDGE",
              i_C=ClockSignal(), i_R=ResetSignal(), i_S=0, i_CE=1,
              i_D1=do_mux, i_D2=do_fall[0], o_Q=dq_mosi.o,
            ),
            Instance("IDELAYE2",
                     p_DELAY_SRC="IDATAIN", p_SIGNAL_PATTERN="DATA",
                     p_CINVCTRL_SEL="FALSE", p_HIGH_PERFORMANCE_MODE="FALSE", p_REFCLK_FREQUENCY=200,
                     p_PIPE_SEL="FALSE", p_IDELAY_VALUE=dq_delay_taps, p_IDELAY_TYPE=delay_type,

                     i_C=ClockSignal(),
                     i_LD=self.delay_config.fields.load, i_CE=self.delay_config.fields.ce,
                     i_LDPIPEEN=0, i_INC=self.delay_config.fields.inc,
                     i_CNTVALUEIN=self.delay_config.fields.d,
                     i_IDATAIN=dq_mosi.i, o_DATAOUT=dq_delayed[0],
            ),
            Instance("IDDR",
              p_DDR_CLK_EDGE="SAME_EDGE_PIPELINED",  # higher latency, but easier timing closure
              i_C=dqs_iobuf, i_R=ResetSignal(), i_S=0, i_CE=1,
              i_D=dq_delayed[0], o_Q1=di_rise[0], o_Q2=di_fall[0],
            ),
        ]

        # wire up SCLK interface
        clkgate = Signal()
        self.sync += clkgate.eq(self.mode.fields.clkgate_test)
        self.specials += [
            # de-activate the CCLK interface, parallel it with a GPIO
            Instance("STARTUPE2",
                     i_CLK=0, i_GSR=0, i_GTS=0, i_KEYCLEARB=0, i_PACK=0, i_USRDONEO=1, i_USRDONETS=1,
                     i_USRCCLKO=0, i_USRCCLKTS=1,  # force to tristate
                     ),
            Instance("ODDR", name=sclk_instance, # need to name this so we can constrain it properly
                     p_DDR_CLK_EDGE="SAME_EDGE",
                     i_C=ClockSignal("spinor"), i_R=ResetSignal("spinor"), i_S=0, i_CE=clkgate,
                     i_D1=1, i_D2=0, o_Q=pads.sclk,
                     )
        ]

        # wire up CS_N
        self.specials += [
            Instance("ODDR",
              p_DDR_CLK_EDGE="SAME_EDGE",
              i_C=ClockSignal(), i_R=ResetSignal(), i_S=0, i_CE=1,
              i_D1=cs_n, i_D2=cs_n, o_Q=pads.cs_n,
            ),
        ]

        # wire up SPI and decode tristate signals
        self.specials += [
            Instance("FDRE", i_C=~ClockSignal("spinor"), i_D=dq.i[0], i_CE=1, i_R=0, o_Q=self.miso)
        ]
        self.sync += [
            dq.oe.eq(~self.spi_mode & self.tx),
            dq_mosi.oe.eq(self.spi_mode | self.tx),
        ]
        self.comb += [
            do_mux.eq(~self.spi_mode & do_rise[0] | self.spi_mode & self.mosi),
        ]


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
