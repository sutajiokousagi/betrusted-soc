from migen import *
from migen.genlib.fsm import FSM, NextState

from litex.soc.interconnect import wishbone
from litex.soc.interconnect.csr import *

class Sram32(Module, AutoCSR):
    def __init__(self, pads, rd_timing, wr_timing, page_rd_timing):
        self.bus = wishbone.Interface()

        config_status = self.config_status = CSRStatus(32)
        read_config = self.read_config = CSRStorage(1)

        ###
        # min 150us, at 100MHz this is 15,000 cycles
        sram_zz = Signal(reset=1)
        load_config = Signal()
        self.sram_ready = Signal()
        reset_counter = Signal(14, reset=50) # cut short because 150us > FPGA config time
        self.sync += [
            If(reset_counter != 0,
                reset_counter.eq(reset_counter - 1),
                self.sram_ready.eq(0)
            ).Else(
                self.sram_ready.eq(1)
            ),

            If(reset_counter == 1,
               load_config.eq(1)
            ).Else(
                load_config.eq(0)
            )
        ]

        data = TSTriple(32)

        self.specials += data.get_tristate(pads.d)
        self.comb += [
            data.oe.eq(pads.oe_n),
        ]

        store = Signal()
        load = Signal()
        config = Signal()
        config_override = Signal()
        config_ce_n = Signal(reset=1)
        config_we_n = Signal(reset=1)
        config_oe_n = Signal(reset=1)

        pads.oe_n.reset, pads.we_n.reset = 1, 1
        pads.zz_n.reset, pads.ce_n.reset = 1, 1
        self.sync += [
            pads.oe_n.eq(1),
            pads.we_n.eq(1),
            pads.zz_n.eq(sram_zz),
            pads.ce_n.eq(1),

            If(config_override,
               pads.oe_n.eq(config_oe_n),
               pads.we_n.eq(config_we_n),
               pads.ce_n.eq(config_ce_n),
               pads.zz_n.eq(1),
               If(config_ce_n,  # DM should track CE_n
                  pads.dm_n.eq(0xf),
                ).Else(
                   pads.dm_n.eq(0x0)
               ),
               pads.adr.eq(0x3fffff),
               data.o.eq(0),
            ).Else(
                # Register data/address to avoid off-chip glitches
                If(sram_zz == 0,
                   pads.adr.eq(0xf0),  # 1111_0000   page mode enabled, TCR = 85C, PAR enabled, full array PAR
                   pads.dm_n.eq(0xf),
                ).Elif(self.bus.cyc & self.bus.stb,
                    pads.adr.eq(self.bus.adr),
                    pads.dm_n.eq(~self.bus.sel),
                    If(self.bus.we,
                       data.o.eq(self.bus.dat_w)
                    ).Else(
                        pads.oe_n.eq(0)
                    )
                ),

                If(load,
                    self.bus.dat_r.eq(data.i),
                ),

                If(store | config, pads.we_n.eq(0)),

                If(store | config | (self.bus.cyc & self.bus.stb & ~self.bus.we), pads.ce_n.eq(0))
            )
        ]

        counter = Signal(max=max(rd_timing, wr_timing, 15)+1)
        counter_limit = Signal(max=max(rd_timing, wr_timing, 15)+1)
        counter_en = Signal()
        counter_done = Signal()
        self.comb += counter_done.eq(counter == counter_limit)
        self.sync += If(counter_en & ~counter_done,
                counter.eq(counter + 1)
            ).Else(
                counter.eq(0)
            )

        fsm = FSM()
        self.submodules += fsm

        last_page_adr = Signal(22)
        last_cycle_was_rd = Signal()

        fsm.act("IDLE",
            NextValue(config, 0),
            If(read_config.re,
              NextValue(config_override, 1),
              NextState("CONFIG_READ"),
            ),
            If(load_config,
               NextState("CONFIG_PRE"),
               NextValue(last_cycle_was_rd, 0),
               NextValue(counter_limit, 10),  # 100 ns, assuming sysclk = 10ns. A little margin over min 70ns
               NextValue(sram_zz, 0), ## zz has to fall before WE
            ).Elif(self.bus.cyc & self.bus.stb,
                   NextValue(sram_zz, 1),
                   If(self.bus.we,
                     NextValue(counter_limit, wr_timing),
                     counter_en.eq(1),
                     store.eq(1),
                     NextValue(last_cycle_was_rd, 0),
                     NextState("WR")
                   ).Else(
                      counter_en.eq(1),
                      NextValue(last_page_adr,self.bus.adr),
                      NextValue(last_cycle_was_rd, 1),
                      If( (self.bus.adr[4:last_page_adr.nbits] == last_page_adr[4:last_page_adr.nbits]) & last_cycle_was_rd,
                        NextState("RD"),
                        NextValue(counter_limit, page_rd_timing),
                      ).Else(
                        NextValue(counter_limit, rd_timing),
                        NextState("RD")
                      )
                   )
            ).Else(
                NextValue(sram_zz, 1),
            )
        )
        fsm.act("CONFIG_READ",
                NextValue(counter_limit, rd_timing),
                NextValue(config_ce_n, 1),
                NextValue(config_we_n, 1),
                NextValue(config_oe_n, 1),
                NextState("CFGRD1"),
        )
        fsm.act("CFGRD1",
                counter_en.eq(1),
                NextValue(config_ce_n, 0),
                NextValue(config_oe_n, 0),
                If(counter_done,
                   NextState("CFGRD2"),
                   NextValue(counter_limit, rd_timing),
                   NextValue(config_ce_n, 1), # should be 5ns min high time
                   NextValue(config_oe_n, 1),
                )
        )
        fsm.act("CFGRD2",
                counter_en.eq(1),
                NextValue(config_ce_n, 0),
                NextValue(config_oe_n, 0),
                If(counter_done,
                   NextState("CFGWR1"),
                   NextValue(counter_limit, rd_timing),
                   NextValue(config_ce_n, 1), # should be 5ns min high time
                   NextValue(config_oe_n, 1),
                )
        )
        fsm.act("CFGWR1",
                counter_en.eq(1),
                NextValue(config_ce_n, 0),
                NextValue(config_we_n, 0),
                If(counter_done,
                   NextState("CFGRD3"),
                   NextValue(counter_limit, rd_timing),
                   NextValue(config_ce_n, 1), # should be 5ns min high time
                   NextValue(config_we_n, 1),
                )
        )
        fsm.act("CFGRD3",
                counter_en.eq(1),
                NextValue(config_ce_n, 0),
                NextValue(config_oe_n, 0),
                If(counter_done,
                   NextValue(config_status.status,data.i),
                   NextState("IDLE"),
                   NextValue(config_ce_n, 1), # should be 5ns min high time
                   NextValue(config_oe_n, 1),
                   NextValue(config_override, 0)
                )
        )

        fsm.act("CONFIG_PRE",
            NextState("CONFIG")
        )
        fsm.act("CONFIG",
            counter_en.eq(1),
            If(counter_done,
               NextState("ZZ_UP"),
               NextValue(config, 0),
            ).Else(
                NextValue(config, 1),
            ),
        )
        fsm.act("ZZ_UP",
            NextValue(config, 0),
            NextValue(sram_zz, 1),
            NextState("IDLE"),
        )
        fsm.act("RD",
            counter_en.eq(1),
            If(counter_done,
                load.eq(1),
                NextState("ACK")
            )
        )
        fsm.act("WR",
            counter_en.eq(1),
            store.eq(1),
            If(counter_done, NextState("ACK"))
        )
        fsm.act("ACK",
            self.bus.ack.eq(1),
            NextState("IDLE")
        )
