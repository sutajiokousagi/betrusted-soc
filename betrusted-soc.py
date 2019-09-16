#!/usr/bin/env python3
# This variable defines all the external programs that this module
# relies on.  lxbuildenv reads this variable in order to ensure
# the build will finish without exiting due to missing third-party
# programs.
LX_DEPENDENCIES = ["riscv", "vivado"]

# Import lxbuildenv to integrate the deps/ directory
import lxbuildenv

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
from litex.soc.cores import gpio

_io = [
    ("clk12", 0, Pins("R3"), IOStandard("LVCMOS18")),  # provisional

    ("serial", 0,
     Subsignal("tx", Pins("V6")), # provisional
     Subsignal("rx", Pins("V7")), # provisional
     IOStandard("LVCMOS18"),
     ),

    ("audio_on", 0, Pins("G13"), IOStandard("LVCMOS33")),
    ("noisebias_on", 0, Pins("A13"), IOStandard("LVCMOS33")),
    ("noise_on", 0, Pins("P14", "R13"), IOStandard("LVCMOS18")),

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

slow_clock = True

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

                         # VCO @ 800 MHz or 600 MHz
                         p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=(1 / refclk_freq) * 1e9,
                         p_CLKFBOUT_MULT_F=60, p_DIVCLK_DIVIDE=1,
                         i_CLKIN1=clk12_distbuf, i_CLKFBIN=pll_fb_bufg, o_CLKFBOUT=pll_fb,

                         # 150 MHz - sysclk
                         p_CLKOUT0_DIVIDE_F=5, p_CLKOUT0_PHASE=0.0,
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
    }
    mem_map.update(SoCCore.mem_map)

    def __init__(self, platform, spiflash="spiflash_1x", **kwargs):
        if slow_clock:
            clk_freq = int(12e6)
        else:
            clk_freq = int(125e6)

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

        self.submodules.info = info.Info(platform, self.__class__.__name__)
        self.add_csr("info")

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

        # "FLASH" as stand-in for RAM
        self.submodules.sram_ext = Sram32(platform.request("sram_ext"), 1, 1)
        self.register_mem("sram_ext", self.mem_map["sram_ext"],
                          self.sram_ext.bus, size=0x1000000)

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
    platform = Platform()
    soc = BaseSoC(platform)
    builder = Builder(soc, output_dir="build", csr_csv="test/csr.csv")
    vns = builder.build()
    soc.do_exit(vns)

if __name__ == "__main__":
    main()
