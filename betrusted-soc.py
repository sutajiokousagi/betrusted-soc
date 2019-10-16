#!/usr/bin/env python3
# This variable defines all the external programs that this module
# relies on.  lxbuildenv reads this variable in order to ensure
# the build will finish without exiting due to missing third-party
# programs.
LX_DEPENDENCIES = ["riscv", "vivado"]

# Import lxbuildenv to integrate the deps/ directory
import lxbuildenv
import argparse

from migen import *
from litex.build.generic_platform import *
from litex.soc.integration.soc_core import *
from litex.build.xilinx import XilinxPlatform, VivadoProgrammer
from litex.soc.integration.builder import *

from litex.soc.cores import spi_flash

from migen.genlib.resetsync import AsyncResetSynchronizer

from litex.soc.interconnect.csr import *
from litex.soc.interconnect.csr_eventmanager import *

from gateware import info
from gateware import sram_32
from gateware import memlcd
from litex.soc.cores import gpio

import lxsocdoc

_io = [
    ("clk12", 0, Pins("R3"), IOStandard("LVCMOS18")),

    ("serial", 0,
     Subsignal("tx", Pins("V6")),
     Subsignal("rx", Pins("V7")),
     IOStandard("LVCMOS18"),
     ),

    #("usbc_cc1", 0, Pins("C17"), IOStandard("LVCMOS33")), # analog
    #("usbc_cc2", 0, Pins("E16"), IOStandard("LVCMOS33")), # analog
    # ("vbus_div", 0, Pins("E12"), IOStandard("LVCMOS33")), # analog
    ("wifi_lpclk", 0, Pins("N15"), IOStandard("LVCMOS18")),

    # Power control signals
    ("audio_on", 0, Pins("G13"), IOStandard("LVCMOS33")),
    ("fpga_sys_on", 0, Pins("N13"), IOStandard("LVCMOS18")),
    ("noisebias_on", 0, Pins("A13"), IOStandard("LVCMOS33")),
    ("allow_up5k_n", 0, Pins("U7"), IOStandard("LVCMOS18")),
    ("pwr_s0", 0, Pins("U6"), IOStandard("LVCMOS18")),
    ("pwr_s1", 0, Pins("L13"), IOStandard("LVCMOS18")),

    # Noise generator
    ("noise_on", 0, Pins("P14", "R13"), IOStandard("LVCMOS18")),
#    ("noise0", 0, Pins("B13"), IOStandard("LVCMOS33")), # these are analog
#    ("noise1", 0, Pins("B14"), IOStandard("LVCMOS33")),

    # Audio interface
    ("au_clk1", 0, Pins("D14"), IOStandard("LVCMOS33")),
    ("au_clk2", 0, Pins("F14"), IOStandard("LVCMOS33")),
    ("au_mclk", 0, Pins("D18"), IOStandard("LVCMOS33")),
    ("au_sdi1", 0, Pins("D12"), IOStandard("LVCMOS33")),
    ("au_sdi2", 0, Pins("A15"), IOStandard("LVCMOS33")),
    ("au_sdo1", 0, Pins("C13"), IOStandard("LVCMOS33")),
    ("au_sync1", 0, Pins("B15"), IOStandard("LVCMOS33")),
    ("au_sync2", 0, Pins("B17"), IOStandard("LVCMOS33")),
#    ("ana_vn", 0, Pins("K9"), IOStandard("LVCMOS33")), # analog
#    ("ana_vp", 0, Pins("J10"), IOStandard("LVCMOS33")),

    # I2C1 bus -- to RTC and audio CODEC
    ("i2c1_scl", 0, Pins("C14"), IOStandard("LVCMOS33")),
    ("i2c1_sda", 0, Pins("A14"), IOStandard("LVCMOS33")),
    # RTC interrupt
    ("rtc_int1", 0, Pins("N5"), IOStandard("LVCMOS18")),

    # COM interface to UP5K
    ("com_cs", 0, Pins("T15"), IOStandard("LVCMOS18")),
    ("com_irq", 0, Pins("M16"), IOStandard("LVCMOS18")),
    ("com_miso", 0, Pins("P16"), IOStandard("LVCMOS18")),
    ("com_mosi", 0, Pins("N18"), IOStandard("LVCMOS18")),
    ("com_sclk", 0, Pins("R16"), IOStandard("LVCMOS18")),

    # Top-side internal FPC header
    ("gpio0", 0, Pins("B18"), IOStandard("LVCMOS33")),
    ("gpio1", 0, Pins("D15"), IOStandard("LVCMOS33")),
    ("gpio2", 0, Pins("A16"), IOStandard("LVCMOS33")),
    ("gpio3", 0, Pins("B16"), IOStandard("LVCMOS33")),
    ("gpio4", 0, Pins("D16"), IOStandard("LVCMOS33")),

    # Keyboard scan matrix
    ("kbd", 0,
        Subsignal("key", Pins("F15" "E17" "G17" "E14" "E15" "H15" "G15" "H14"
                              "H16" "H17" "E18" "F18" "G18" "E13" "H18" "F13"
                              "H13" "J13" "K13"), IOStandard("LVCMOS33")),
    ),

    # LCD interface
    ("lcd", 0,
        Subsignal("sclk", Pins("A17"), IOStandard("LVCMOS33")),
        Subsignal("scs", Pins("C18"), IOStandard("LVCMOS33")),
        Subsignal("si", Pins("D17"), IOStandard("LVCMOS33")),
     ),

    # SD card (TF) interface
    ("sdcard", 0,
     Subsignal("data", Pins("J15 J14 K16 K14"), Misc("PULLUP True")),
     Subsignal("cmd", Pins("J16"), Misc("PULLUP True")),
     Subsignal("clk", Pins("G16")),
     IOStandard("LVCMOS33"), Misc("SLEW=SLOW")
     ),

    # SPI Flash
    ("spiflash_4x", 0,  # clock needs to be accessed through STARTUPE2
     Subsignal("cs_n", Pins("M13")),
     Subsignal("dq", Pins("K17", "K18", "L14", "M15")),
     IOStandard("LVCMOS18")
     ),
    ("spiflash_1x", 0,  # clock needs to be accessed through STARTUPE2
     Subsignal("cs_n", Pins("M13")),
     Subsignal("mosi", Pins("K17")),
     Subsignal("miso", Pins("K18")),
     Subsignal("wp", Pins("L14")), # provisional
     Subsignal("hold", Pins("M15")), # provisional
     IOStandard("LVCMOS18")
     ),
    ("spiflash_8x", 0,  # clock needs to be accessed through STARTUPE2
     Subsignal("cs_n", Pins("M13")),
     Subsignal("dq", Pins("K17", "K18", "L14", "M15", "L17", "L18", "M14", "N14")),
     Subsignal("dqs", Pins("R14")),
     Subsignal("ecsn", Pins("L16")),
     IOStandard("LVCMOS18")
     ),

    # SRAM
    ("sram", 0,
        Subsignal("adr", Pins(
            "V12 M5 P5 N4  V14 M3 R17 U15",
            "M4  L6 K3 R18 U16 K1 R5  T2",
            "U1  N1 L5 K2  M18 T6"),
            IOStandard("LVCMOS18")),
        Subsignal("ce_n", Pins("V5"), IOStandard("LVCMOS18"), Misc("PULLUP True")),
        Subsignal("oe_n", Pins("U12"), IOStandard("LVCMOS18"), Misc("PULLUP True")),
        Subsignal("we_n", Pins("K4"), IOStandard("LVCMOS18"), Misc("PULLUP True")),
        Subsignal("zz_n", Pins("V17"), IOStandard("LVCMOS18"), Misc("PULLUP True")),
        Subsignal("d", Pins(
            "M2  R4  P2  L4  L1  M1  R1  P1 "
            "U3  V2  V4  U2  N2  T1  K6  J6 "
            "V16 V15 U17 U18 P17 T18 P18 M17 " 
            "N3  T4  V13 P15 T14 R15 T3  R7 "), IOStandard("LVCMOS18")),
        Subsignal("dm_n", Pins("V3 R2 T5 T13"), IOStandard("LVCMOS18")),
    ),
]

class Platform(XilinxPlatform):
    def __init__(self, toolchain="vivado", programmer="vivado", part="50"):
        part = "xc7s" + part + "-csga324-1il"
        XilinxPlatform.__init__(self, part, _io,
                                toolchain=toolchain)

        # NOTE: to do quad-SPI mode, the QE bit has to be set in the SPINOR status register
        # OpenOCD won't do this natively, have to find a work-around (like using iMPACT to set it once)
        self.add_platform_command(
            "set_property CONFIG_VOLTAGE 1.8 [current_design]")
        self.add_platform_command(
            "set_property CFGBVS VCCO [current_design]")
        self.add_platform_command(
            "set_property BITSTREAM.CONFIG.CONFIGRATE 66 [current_design]")
        self.add_platform_command(
            "set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 2 [current_design]")
        self.toolchain.bitstream_commands = [
            "set_property CONFIG_VOLTAGE 1.8 [current_design]",
            "set_property CFGBVS GND [current_design]",
            "set_property BITSTREAM.CONFIG.CONFIGRATE 66 [current_design]",
            "set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 2 [current_design]",
        ]
        self.toolchain.additional_commands = \
            ["write_cfgmem -verbose -force -format bin -interface spix2 -size 64 "
             "-loadbit \"up 0x0 {build_name}.bit\" -file {build_name}.bin"]
        self.programmer = programmer

    def create_programmer(self):
        if self.programmer == "vivado":
            return VivadoProgrammer(flash_part="n25q128-1.8v-spi-x1_x2_x4")
        else:
            raise ValueError("{} programmer is not supported"
                             .format(self.programmer))

    def do_finalize(self, fragment):
        XilinxPlatform.do_finalize(self, fragment)

slow_clock = False

class CRG(Module, AutoCSR):
    def __init__(self, platform):
        refclk_freq = 12e6

        clk12 = platform.request("clk12")
        rst = Signal()
        self.clock_domains.cd_sys = ClockDomain()

        if slow_clock:
            self.specials += [
                Instance("BUFG", i_I=clk12, o_O=self.cd_sys.clk),
                AsyncResetSynchronizer(self.cd_sys, rst),
            ]

        else:
            # DRP
            self._mmcm_read = CSR()
            self._mmcm_write = CSR()
            self._mmcm_drdy = CSRStatus()
            self._mmcm_adr = CSRStorage(7)
            self._mmcm_dat_w = CSRStorage(16)
            self._mmcm_dat_r = CSRStatus(16)

            pll_locked = Signal()
            pll_fb = Signal()
            pll_sys = Signal()
            clk12_distbuf = Signal()

            self.specials += [
                Instance("BUFG", i_I=clk12, o_O=clk12_distbuf),
                # this allows PLLs/MMCMEs to be placed anywhere and reference the input clock
            ]

            pll_fb_bufg = Signal()
            mmcm_drdy = Signal()
            self.specials += [
                Instance("MMCME2_ADV",
                         p_STARTUP_WAIT="FALSE", o_LOCKED=pll_locked,
                         p_BANDWIDTH="OPTIMIZED",

                         # VCO @ 600MHz  (600-1200 range for -1LI)
                         p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=(1 / refclk_freq) * 1e9,
                         p_CLKFBOUT_MULT_F=50.0, p_DIVCLK_DIVIDE=1,
                         i_CLKIN1=clk12_distbuf, i_CLKFBIN=pll_fb_bufg, o_CLKFBOUT=pll_fb,

                         # 100 MHz - sysclk
                         p_CLKOUT0_DIVIDE_F=6.0, p_CLKOUT0_PHASE=0.0,
                         o_CLKOUT0=pll_sys,

                         # DRP
                         i_DCLK=ClockSignal(),
                         i_DWE=self._mmcm_write.re,
                         i_DEN=self._mmcm_read.re | self._mmcm_write.re,
                         o_DRDY=mmcm_drdy,
                         i_DADDR=self._mmcm_adr.storage,
                         i_DI=self._mmcm_dat_w.storage,
                         o_DO=self._mmcm_dat_r.status
                         ),

                # feedback delay compensation buffers
                Instance("BUFG", i_I=pll_fb, o_O=pll_fb_bufg),

                # global distribution buffers
                Instance("BUFG", i_I=pll_sys, o_O=self.cd_sys.clk),

                AsyncResetSynchronizer(self.cd_sys, rst | ~pll_locked),
            ]
            self.sync += [
                If(self._mmcm_read.re | self._mmcm_write.re,
                   self._mmcm_drdy.status.eq(0)
                   ).Elif(mmcm_drdy,
                          self._mmcm_drdy.status.eq(1)
                          )
            ]

boot_offset = 0x1000000
bios_size = 0x8000

class BaseSoC(SoCCore):
    mem_map = {
        "spiflash": 0x20000000,  # (default shadow @0xa0000000)
        "sram_ext": 0x40000000,
        "memlcd": 0x50000000,
    }
    mem_map.update(SoCCore.mem_map)

    def __init__(self, platform, spiflash="spiflash_1x", **kwargs):
        if slow_clock:
            clk_freq = int(12e6)
        else:
            clk_freq = int(100e6)

#        kwargs['cpu_reset_address']=self.mem_map["spiflash"]+boot_offset
        SoCCore.__init__(self, platform, clk_freq,
                         integrated_rom_size=bios_size,
                         integrated_sram_size=0x20000,
                         ident="betrusted.io LiteX Base SoC",
                         cpu_type="vexriscv",
                         **kwargs)

        self.submodules.audio = gpio.GPIOOut(platform.request("audio_on"))
        self.add_csr("audio")
        self.submodules.noisebias = gpio.GPIOOut(platform.request("noisebias_on"))
        self.add_csr("noisebias")
        self.submodules.noise = gpio.GPIOOut(platform.request("noise_on"))
        self.add_csr("noise")

        self.submodules.crg = CRG(platform)
        self.add_csr("crg")
        self.platform.add_period_constraint(self.crg.cd_sys.clk, 1e9/clk_freq)

        self.platform.add_platform_command(
            "create_clock -name clk12 -period 83.3333 [get_nets clk12]")
        self.platform.add_platform_command(
            "create_generated_clock -name sys_clk -source [get_pins MMCME2_ADV/CLKIN1] -multiply_by 50 -divide_by 6 -add -master_clock clk12 [get_pins MMCME2_ADV/CLKOUT0]"
        )

        self.submodules.info = info.Info(platform, self.__class__.__name__)
        self.add_csr("info")
        self.platform.add_platform_command('create_generated_clock -name dna_cnt -source [get_pins {{dna_cnt_reg[0]/Q}}] -divide_by 2 [get_pins {{DNA_PORT/CLK}}]')

        # external SRAM
        # Note that page_rd_timing=2 works, but is a slight overclock on RAM. Cache fill time goes from 436ns to 368ns for 8 words.
        self.submodules.sram_ext = sram_32.Sram32(platform.request("sram"), rd_timing=7, wr_timing=6, page_rd_timing=3)
        self.add_csr("sram_ext")
        self.register_mem("sram_ext", self.mem_map["sram_ext"],
                  self.sram_ext.bus, size=0x1000000)
        # constraint so a total of one extra clock period is consumed in routing delays (split 5/5 evenly on in and out)
        self.platform.add_platform_command("set_input_delay -clock [get_clocks sys_clk] -min -add_delay 5.0 [get_ports {{sram_d[*]}}]")
        self.platform.add_platform_command("set_input_delay -clock [get_clocks sys_clk] -max -add_delay 5.0 [get_ports {{sram_d[*]}}]")
        self.platform.add_platform_command("set_output_delay -clock [get_clocks sys_clk] -min -add_delay 0.0 [get_ports {{sram_adr[*] sram_d[*] sram_ce_n sram_oe_n sram_we_n sram_zz_n sram_dm_n[*]}}]")
        self.platform.add_platform_command("set_output_delay -clock [get_clocks sys_clk] -max -add_delay 4.5 [get_ports {{sram_adr[*] sram_d[*] sram_ce_n sram_oe_n sram_we_n sram_zz_n sram_dm_n[*]}}]")
        # ODDR falling edge ignore
        self.platform.add_platform_command("set_false_path -fall_from [get_clocks sys_clk] -through [get_ports {{sram_d[*] sram_adr[*] sram_ce_n sram_oe_n sram_we_n sram_zz_n sram_dm_n[*]}}]")
        self.platform.add_platform_command("set_false_path -fall_to [get_clocks sys_clk] -through [get_ports {{sram_d[*]}}]")
        self.platform.add_platform_command("set_false_path -fall_from [get_clocks sys_clk] -through [get_nets sram_ext_load]")
        self.platform.add_platform_command("set_false_path -fall_to [get_clocks sys_clk] -through [get_nets sram_ext_load]")
        self.platform.add_platform_command("set_false_path -rise_from [get_clocks sys_clk] -fall_to [get_clocks sys_clk]")  # sort of a big hammer but should be OK
        # reset ignore
        self.platform.add_platform_command("set_false_path -through [get_nets sys_rst]")
        # relax OE driver constraint (it's OK if it is a bit late, and it's an async path from fabric to output so it will be late)
        self.platform.add_platform_command("set_multicycle_path 2 -setup -through [get_pins sram_ext_sync_oe_n_reg/Q]")
        self.platform.add_platform_command("set_multicycle_path 1 -hold -through [get_pins sram_ext_sync_oe_n_reg/Q]")
        # S0 power enables SRAM CE/ZZ
        self.comb += platform.request("pwr_s0", 0).eq(~ResetSignal())  # ensure SRAM isolation during reset (CE/ZZ = 1 by pull-up resistors)

        # LCD interface
        self.submodules.memlcd = memlcd.Memlcd(platform.request("lcd"))
        self.add_csr("memlcd")
        self.register_mem("memlcd", self.mem_map["memlcd"], self.memlcd.bus, size=self.memlcd.fb_depth*4)

        # fpga_sys_on keeps the FPGA on
        self.comb += platform.request("fpga_sys_on", 0).eq(1)
"""
        # spi flash
        spiflash_pads = platform.request(spiflash)
        spiflash_pads.clk = Signal()
        self.specials += Instance("STARTUPE2",
                                  i_CLK=0, i_GSR=0, i_GTS=0, i_KEYCLEARB=0, i_PACK=0,
                                  i_USRCCLKO=spiflash_pads.clk, i_USRCCLKTS=0, i_USRDONEO=1, i_USRDONETS=1)
        spiflash_dummy = {
            "spiflash_1x": 8,  # this is specific to the device populated on the board -- if it changes, must be updated
            "spiflash_4x": 12, # this is almost certainly wrong
        }
        self.submodules.spiflash = spi_flash.SpiFlash(
                spiflash_pads,
                dummy=spiflash_dummy[spiflash],
                div=2)
        self.add_constant("SPIFLASH_PAGE_SIZE", 256)
        self.add_constant("SPIFLASH_SECTOR_SIZE", 0x10000)
        self.add_wb_slave(mem_decoder(self.mem_map["spiflash"]), self.spiflash.bus)
        self.add_memory_region(
            "spiflash", self.mem_map["spiflash"] | self.shadow_base, 512*1024*1024)

        self.flash_boot_address = 0x207b0000
"""
"""
        # SPI for flash already added above
        # SPI for network
        self.submodules.spi = SPIMaster(platform.request("spi"))
        # SPI for display
        self.submodules.spi_display = SPIMaster(platform.request("spi_display"))

        # GPIO for keyboard/user I/O
        self.submodules.gi = GPIOIn(platform.request("gpio_in", 0).gi)
        self.submodules.go = GPIOOut(platform.request("gpio_out", 0).go)

        # An external interrupt source
        self.submodules.ev = EventManager()
        self.ev.my_int1 = EventSourceProcess()
        self.ev.finalize()

        self.comb += self.ev.my_int1.trigger.eq(platform.request("int", 0).int)

        self.submodules.i2c = OpsisI2C(platform)

        self.submodules.dma = Wishbone2SPIDMA()
"""

def main():
    if os.environ['PYTHONHASHSEED'] != "1":
        print( "PYTHONHASHEED must be set to 1 for consistent validation results. Failing to set this results in non-deterministic compilation results")
        exit()

    parser = argparse.ArgumentParser(description="Build the Betrusted SoC")
    parser.add_argument(
        "-D", "--document-only", default=False, action="store_true", help="Build docs only"
    )

    args = parser.parse_args()
    compile_gateware = True
    compile_software = True

    if args.document_only:
        compile_gateware = False
        compile_software = False

    platform = Platform()
    soc = BaseSoC(platform)
    builder = Builder(soc, output_dir="build", csr_csv="test/csr.csv", compile_software=compile_software, compile_gateware=compile_gateware)
    vns = builder.build()
    soc.do_exit(vns)
    lxsocdoc.generate_docs(soc, "build/documentation", note_pulses=True)
    lxsocdoc.generate_svd(soc, "build/software")

if __name__ == "__main__":
    main()
