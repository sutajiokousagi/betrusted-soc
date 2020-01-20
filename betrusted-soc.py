#!/usr/bin/env python3

# This variable defines all the external programs that this module
# relies on.  lxbuildenv reads this variable in order to ensure
# the build will finish without exiting due to missing third-party
# programs.

LX_DEPENDENCIES = ["riscv", "vivado"]

# Import lxbuildenv to integrate the deps/ directory
import lxbuildenv
import lxsocdoc
from pathlib import Path
import subprocess

from random import SystemRandom
import argparse

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer
from migen.genlib.cdc import MultiReg

from litex.build.generic_platform import *
from litex.build.xilinx import XilinxPlatform, VivadoProgrammer

from litex.soc.interconnect.csr import *
from litex.soc.interconnect.csr_eventmanager import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.integration.doc import AutoDoc, ModuleDoc
from litex.soc.cores.clock import S7MMCM
from litex.soc.cores import spi_flash

from gateware import info
from gateware import sram_32
from gateware import memlcd
from gateware import spi
from gateware import messible
from gateware import i2c
from gateware import ticktimer

from gateware import spinor
from gateware import keyboard

from gateware.trng import TrngRingOsc

# IOs ----------------------------------------------------------------------------------------------

_io = [
    ("clk12", 0, Pins("R3"), IOStandard("LVCMOS18")),

    ("analog", 0,
        Subsignal("usbc_cc1",    Pins("C17"), IOStandard("LVCMOS33")),
        Subsignal("usbc_cc2",    Pins("E16"), IOStandard("LVCMOS33")),
        Subsignal("vbus_div",    Pins("E12"), IOStandard("LVCMOS33")),
        Subsignal("noise0",      Pins("B13"), IOStandard("LVCMOS33")),
        Subsignal("noise1",      Pins("B14"), IOStandard("LVCMOS33")),
        Subsignal("ana_vn",      Pins("K9")),  # no I/O standard as this is a dedicated pin
        Subsignal("ana_vp",      Pins("J10")), # no I/O standard as this is a dedicated pin
        Subsignal("noise0_n",    Pins("A13"), IOStandard("LVCMOS33")),  # PATCH
     ),

    ("lpclk", 0, Pins("N15"), IOStandard("LVCMOS18")),  # wifi_lpclk

    # Power control signals
    ("power", 0,
        Subsignal("audio_on",     Pins("G13"), IOStandard("LVCMOS33")),
        Subsignal("fpga_sys_on",  Pins("N13"), IOStandard("LVCMOS18")),
        # Subsignal("noisebias_on", Pins("A13"), IOStandard("LVCMOS33")),  # PATCH
        Subsignal("allow_up5k_n", Pins("U7"), IOStandard("LVCMOS18")),
        Subsignal("pwr_s0",       Pins("U6"), IOStandard("LVCMOS18")),
        Subsignal("pwr_s1",       Pins("L13"), IOStandard("LVCMOS18")),
        # Noise generator
        Subsignal("noise_on", Pins("P14 R13"), IOStandard("LVCMOS18")),
     ),

    # Audio interface
    ("au_clk1",  0, Pins("D14"), IOStandard("LVCMOS33")),
    ("au_clk2",  0, Pins("F14"), IOStandard("LVCMOS33")),
    ("au_mclk",  0, Pins("D18"), IOStandard("LVCMOS33")),
    ("au_sdi1",  0, Pins("D12"), IOStandard("LVCMOS33")),
    ("au_sdi2",  0, Pins("A15"), IOStandard("LVCMOS33")),
    ("au_sdo1",  0, Pins("C13"), IOStandard("LVCMOS33")),
    ("au_sync1", 0, Pins("B15"), IOStandard("LVCMOS33")),
    ("au_sync2", 0, Pins("B17"), IOStandard("LVCMOS33")),

    # I2C1 bus -- to RTC and audio CODEC
    ("i2c", 0,
        Subsignal("scl", Pins("C14"), IOStandard("LVCMOS33")),
        Subsignal("sda", Pins("A14"), IOStandard("LVCMOS33")),
    ),

    # RTC interrupt
    ("rtc_irq", 0, Pins("N5"), IOStandard("LVCMOS18")),

    # COM interface to UP5K
    ("com", 0,
        Subsignal("csn",  Pins("T15"), IOStandard("LVCMOS18")),
        Subsignal("miso", Pins("P16"), IOStandard("LVCMOS18")),
        Subsignal("mosi", Pins("N18"), IOStandard("LVCMOS18")),
        Subsignal("sclk", Pins("R16"), IOStandard("LVCMOS18")),
     ),
    ("com_irq", 0, Pins("M16"), IOStandard("LVCMOS18")),

    # Top-side internal FPC header (B18 and D15 are used by the serial bridge)
    ("gpio", 0, Pins("A16 B16 D16"), IOStandard("LVCMOS33"), Misc("SLEW=SLOW")),

    # Keyboard scan matrix
    ("kbd", 0,
        # "key" 0-8 are rows, 9-18 are columns
        # column scan with 1's, so PD to default 0
        Subsignal("row", Pins("F15 E17 G17 E14 E15 H15 G15 H14 H16"), Misc("PULLDOWN True")),
        Subsignal("col", Pins("H17 E18 F18 G18 E13 H18 F13 H13 J13 K13")),
        IOStandard("LVCMOS33")
    ),

    # LCD interface
    ("lcd", 0,
        Subsignal("sclk", Pins("A17")),
        Subsignal("scs",  Pins("C18")),
        Subsignal("si",   Pins("D17")),
        IOStandard("LVCMOS33"),
        Misc("SLEW=SLOW")

     ),

    # SD card (TF) interface
    ("sdcard", 0,
        Subsignal("data", Pins("J15 J14 K16 K14"), Misc("PULLUP True")),
        Subsignal("cmd",  Pins("J16"), Misc("PULLUP True")),
        Subsignal("clk",  Pins("G16")),
        IOStandard("LVCMOS33"),
        Misc("SLEW=SLOW")
     ),

    # SPI Flash
    ("spiflash_4x", 0, # clock needs to be accessed through STARTUPE2
        Subsignal("cs_n", Pins("M13")),
        Subsignal("dq", Pins("K17 K18 L14 M15")),
        IOStandard("LVCMOS18")
    ),
    ("spiflash_1x", 0, # clock needs to be accessed through STARTUPE2
        Subsignal("cs_n", Pins("M13")),
        Subsignal("mosi", Pins("K17")),
        Subsignal("miso", Pins("K18")),
        Subsignal("wp",   Pins("L14")), # provisional
        Subsignal("hold", Pins("M15")), # provisional
        IOStandard("LVCMOS18")
    ),
    ("spiflash_8x", 0, # clock needs to be accessed through STARTUPE2
        Subsignal("cs_n", Pins("M13")),
        Subsignal("dq",   Pins("K17 K18 L14 M15 L17 L18 M14 N14")),
        Subsignal("dqs",  Pins("R14")),
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
        Subsignal("ce_n", Pins("V5"),  IOStandard("LVCMOS18"), Misc("PULLUP True")),
        Subsignal("oe_n", Pins("U12"), IOStandard("LVCMOS18"), Misc("PULLUP True")),
        Subsignal("we_n", Pins("K4"),  IOStandard("LVCMOS18"), Misc("PULLUP True")),
        Subsignal("zz_n", Pins("V17"), IOStandard("LVCMOS18"), Misc("PULLUP True")),
        Subsignal("d", Pins(
            "M2  R4  P2  L4  L1  M1  R1  P1",
            "U3  V2  V4  U2  N2  T1  K6  J6",
            "V16 V15 U17 U18 P17 T18 P18 M17",
            "N3  T4  V13 P15 T14 R15 T3  R7"),
            IOStandard("LVCMOS18")),
        Subsignal("dm_n", Pins("V3 R2 T5 T13"), IOStandard("LVCMOS18")),
    ),
]

_io_uart_debug = [
    ("debug", 0,  # wired to the Rpi
        Subsignal("tx", Pins("V6")),
        Subsignal("rx", Pins("V7")),
        IOStandard("LVCMOS18"),
    ),

    ("serial", 0, # wired to the internal flex
        Subsignal("tx", Pins("B18")), # debug0 breakout
        Subsignal("rx", Pins("D15")), # debug1
        IOStandard("LVCMOS33"),
    ),
]

_io_uart_debug_swapped = [
    ("serial", 0, # wired to the RPi
     Subsignal("tx", Pins("V6")),
     Subsignal("rx", Pins("V7")),
     IOStandard("LVCMOS18"),
     ),

    ("debug", 0, # wired to the internal flex
     Subsignal("tx", Pins("B18")), # debug0 breakout
     Subsignal("rx", Pins("D15")), # debug1
     IOStandard("LVCMOS33"),
     ),
]

# Platform -----------------------------------------------------------------------------------------

class Platform(XilinxPlatform):
    def __init__(self, toolchain="vivado", programmer="vivado", part="50", encrypt=False, make_mod=False):
        part = "xc7s" + part + "-csga324-1il"
        XilinxPlatform.__init__(self, part, _io, toolchain=toolchain)

        # NOTE: to do quad-SPI mode, the QE bit has to be set in the SPINOR status register. OpenOCD
        # won't do this natively, have to find a work-around (like using iMPACT to set it once)
        self.add_platform_command(
            "set_property CONFIG_VOLTAGE 1.8 [current_design]")
        self.add_platform_command(
            "set_property CFGBVS VCCO [current_design]")
        self.add_platform_command(
            "set_property BITSTREAM.CONFIG.CONFIGRATE 66 [current_design]")
        self.add_platform_command(
            "set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 1 [current_design]")
        self.toolchain.bitstream_commands = [
            "set_property CONFIG_VOLTAGE 1.8 [current_design]",
            "set_property CFGBVS GND [current_design]",
            "set_property BITSTREAM.CONFIG.CONFIGRATE 66 [current_design]",
            "set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 1 [current_design]",
        ]
        if encrypt:
            self.toolchain.bitstream_commands += [
                "set_property BITSTREAM.ENCRYPTION.ENCRYPT YES [current_design]",
                "set_property BITSTREAM.ENCRYPTION.ENCRYPTKEYSELECT eFUSE [current_design]",
                "set_property BITSTREAM.ENCRYPTION.KEYFILE ../../dummy.nky [current_design]"
            ]

        self.toolchain.additional_commands += \
            ["write_cfgmem -verbose -force -format bin -interface spix1 -size 64 "
             "-loadbit \"up 0x0 {build_name}.bit\" -file {build_name}.bin"]
        self.programmer = programmer

        # this routine retained in case we have to re-explore the bitstream to find the location of the ROM LUTs
        if make_mod:
            # build a version of the bitstream with a different INIT value for the ROM lut, so the offset frame can
            # be discovered by diffing
            for bit in range(0, 32):
                for lut in range(4):
                    if lut == 0:
                        lutname = 'A'
                    elif lut == 1:
                        lutname = 'B'
                    elif lut == 2:
                        lutname = 'C'
                    else:
                        lutname = 'D'

                    self.toolchain.additional_commands += ["set_property INIT 64'hA6C355555555A6C3 [get_cells KEYROM" + str(bit) + lutname + "]"]

            self.toolchain.additional_commands += ["write_bitstream -bin_file -force top-mod.bit"]

    def create_programmer(self):
        if self.programmer == "vivado":
            return VivadoProgrammer(flash_part="n25q128-1.8v-spi-x1_x2_x4")
        else:
            raise ValueError("{} programmer is not supported".format(self.programmer))

    def do_finalize(self, fragment):
        XilinxPlatform.do_finalize(self, fragment)

# CRG ----------------------------------------------------------------------------------------------

class CRG(Module, AutoCSR):
    def __init__(self, platform, sys_clk_freq):
        self.warm_reset = Signal()

        self.clock_domains.cd_sys   = ClockDomain()
        self.clock_domains.cd_spi   = ClockDomain()
        self.clock_domains.cd_lpclk = ClockDomain()

        # # #

        clk32khz = platform.request("lpclk")
        self.specials += Instance("BUFG", i_I=clk32khz, o_O=self.cd_lpclk.clk)
        platform.add_period_constraint(clk32khz, 1e9/32.768e3)

        clk12 = platform.request("clk12")
        platform.add_period_constraint(clk12, 1e9/12e6)

        # This allows PLLs/MMCMEs to be placed anywhere and reference the input clock
        clk12_bufg = Signal()
        self.specials += Instance("BUFG", i_I=clk12, o_O=clk12_bufg)

        self.submodules.mmcm = mmcm = S7MMCM(speedgrade=-1)
        self.comb += mmcm.reset.eq(self.warm_reset)
        mmcm.register_clkin(clk12_bufg, 12e6)
        mmcm.create_clkout(self.cd_sys, sys_clk_freq, margin=0) # there should be a precise solution by design
        mmcm.create_clkout(self.cd_spi, 20e6)
        mmcm.expose_drp()

# WarmBoot -----------------------------------------------------------------------------------------

class WarmBoot(Module, AutoCSR):
    def __init__(self, parent, reset_vector=0):
        self.ctrl = CSRStorage(size=8)
        self.addr = CSRStorage(size=32, reset=reset_vector)
        self.do_reset = Signal()
        # "Reset Key" is 0xac (0b101011xx)
        self.comb += self.do_reset.eq((self.ctrl.storage & 0xfc) == 0xac)

# BtEvents -----------------------------------------------------------------------------------------

class BtEvents(Module, AutoCSR, AutoDoc):
    def __init__(self, com, rtc):
        self.submodules.ev = EventManager()
        self.ev.com_int    = EventSourcePulse()   # rising edge triggered
        self.ev.rtc_int    = EventSourceProcess() # falling edge triggered
        self.ev.finalize()

        com_int = Signal()
        rtc_int = Signal()
        self.specials += MultiReg(com, com_int)
        self.specials += MultiReg(rtc, rtc_int)
        self.comb += self.ev.com_int.trigger.eq(com_int)
        self.comb += self.ev.rtc_int.trigger.eq(rtc_int)

# BtPower ------------------------------------------------------------------------------------------

class BtPower(Module, AutoCSR, AutoDoc):
    def __init__(self, pads):
        self.intro = ModuleDoc("""BtPower - power control pins
        """)

        self.power = CSRStorage(8, fields=[
            CSRField("audio",     size=1, description="Write `1` to power on the audio subsystem"),
            CSRField("self",      size=1, description="Writing `1` forces self power-on (overrides the EC's ability to power me down)", reset=1),
            CSRField("ec_snoop",  size=1, description="Writing `1` allows the insecure EC to snoop a couple keyboard pads for wakeup key sequence recognition"),
            CSRField("state",     size=2, description="Current SoC power state. 0x=off or not ready, 10=on and safe to shutdown, 11=on and not safe to shut down, resets to 01 to allow extSRAM access immediately during init", reset=1),
            CSRField("noisebias", size=1, description="Writing `1` enables the primary bias supply for the noise generator"),
            CSRField("noise",     size=2, description="Controls which of two noise channels are active; all combos valid. noisebias must be on first.")
        ])

        self.comb += [
            pads.audio_on.eq(self.power.fields.audio),
            pads.fpga_sys_on.eq(self.power.fields.self),
            # This signal automatically enables snoop when SoC is powered down
            pads.allow_up5k_n.eq(~self.power.fields.ec_snoop),
            # Ensure SRAM isolation during reset (CE & ZZ = 1 by pull-ups)
            pads.pwr_s0.eq(self.power.fields.state[0] & ~ResetSignal()),
            pads.pwr_s1.eq(self.power.fields.state[1]),
            # pads.noisebias_on.eq(self.power.fields.noisebias),  # PATCH
            pads.noise_on.eq(self.power.fields.noise),
        ]

# BtGpio -------------------------------------------------------------------------------------------

class BtGpio(Module, AutoDoc, AutoCSR):
    def __init__(self, pads):
        self.intro = ModuleDoc("""BtGpio - GPIO interface for betrusted""")

        gpio_in  = Signal(pads.nbits)
        gpio_out = Signal(pads.nbits)
        gpio_oe  = Signal(pads.nbits)

        for g in range(0, pads.nbits):
            gpio_ts = TSTriple(1)
            self.specials += gpio_ts.get_tristate(pads[g])
            self.comb += [
                gpio_ts.oe.eq(gpio_oe[g]),
                gpio_ts.o.eq(gpio_out[g]),
                gpio_in[g].eq(gpio_ts.i),
            ]

        self.output = CSRStorage(pads.nbits, name="output", description="Values to appear on GPIO when respective `drive` bit is asserted")
        self.input  = CSRStatus(pads.nbits,  name="input",  description="Value measured on the respective GPIO pin")
        self.drive  = CSRStorage(pads.nbits, name="drive",  description="When a bit is set to `1`, the respective pad drives its value out")
        self.intena = CSRStatus(pads.nbits,  name="intena", description="Enable interrupts when a respective bit is set")
        self.intpol = CSRStatus(pads.nbits,  name="intpol", description="When a bit is `1`, falling-edges cause interrupts. Otherwise, rising edges cause interrupts.")

        self.specials += MultiReg(gpio_in, self.input.status)
        self.comb += [
            gpio_out.eq(self.output.storage),
            gpio_oe.eq(self.drive.storage),
        ]

        self.submodules.ev = EventManager()

        for i in range(0, pads.nbits):
            setattr(self.ev, "gpioint" + str(i), EventSourcePulse() ) # pulse => rising edge

        self.ev.finalize()

        for i in range(0, pads.nbits):
            # pull from input.status because it's after the MultiReg synchronizer
            self.comb += getattr(self.ev, "gpioint" + str(i)).trigger.eq(self.input.status[i] ^ self.intpol.status[i])
            # note that if you change the polarity on the interrupt it could trigger an interrupt

# BtSeed -------------------------------------------------------------------------------------------

class BtSeed(Module, AutoDoc, AutoCSR):
    def __init__(self, reproduceable=False):
        self.intro = ModuleDoc("""Place and route seed. Set to a fixed number for reproduceable builds.
        Use a random number or your own number if you are paranoid about hardware implants that target
        fixed locations within the FPGA.""")

        if reproduceable:
          seed_reset = "4" # chosen by fair dice roll. guaranteed to be random.
        else:
          rng        = SystemRandom()
          seed_reset = rng.getrandbits(64)
        self.seed = CSRStatus(64, name="seed", description="Seed used for the build", reset=seed_reset)

# RomTest -----------------------------------------------------------------------------------------

class RomTest(Module, AutoDoc, AutoCSR):
    def __init__(self, platform):
        self.intro = ModuleDoc("""Test for bitstream insertion of BRAM initialization contents""")
        platform.toolchain.attr_translate["KEEP"] = ("KEEP", "TRUE")
        platform.toolchain.attr_translate["DONT_TOUCH"] = ("DONT_TOUCH", "TRUE")

        import binascii
        self.address = CSRStorage(8, name="address", description="address for ROM")
        self.data = CSRStatus(32, name="data", description="data from ROM")

        rng = SystemRandom()
        with open("rom.db", "w") as f:
            for bit in range(0,32):
                lutsel = Signal(4)
                for lut in range(4):
                    if lut == 0:
                        lutname = 'A'
                    elif lut == 1:
                        lutname = 'B'
                    elif lut == 2:
                        lutname = 'C'
                    else:
                        lutname = 'D'
                    romval = rng.getrandbits(64)
                    # print("rom bit ", str(bit), lutname, ": ", binascii.hexlify(romval.to_bytes(8, byteorder='big')))
                    rom_name = "KEYROM" + str(bit) + lutname
                    # X36Y99 and counting down
                    if bit % 2 == 0:
                        platform.toolchain.attr_translate[rom_name] = ("LOC", "SLICE_X36Y" + str(50 + bit // 2))
                    else:
                        platform.toolchain.attr_translate[rom_name] = ("LOC", "SLICE_X37Y" + str(50 + bit // 2))
                    platform.toolchain.attr_translate[rom_name + 'BEL'] = ("BEL", lutname + '6LUT')
                    platform.toolchain.attr_translate[rom_name + 'LOCK'] = ( "LOCK_PINS", "I5:A6, I4:A5, I3:A4, I2:A3, I1:A2, I0:A1" )
                    self.specials += [
                        Instance( "LUT6",
                                  name=rom_name,
                                  # p_INIT=0x0000000000000000000000000000000000000000000000000000000000000000,
                                  p_INIT=romval,
                                  i_I0= self.address.storage[0],
                                  i_I1= self.address.storage[1],
                                  i_I2= self.address.storage[2],
                                  i_I3= self.address.storage[3],
                                  i_I4= self.address.storage[4],
                                  i_I5= self.address.storage[5],
                                  o_O= lutsel[lut],
                                  attr=("KEEP", "DONT_TOUCH", rom_name, rom_name + 'BEL', rom_name + 'LOCK')
                                  )
                    ]
                    # record the ROM LUT locations in a DB and annotate the initial random value given
                    f.write("KEYROM " + str(bit) + ' ' + lutname + ' ' + platform.toolchain.attr_translate[rom_name][1] +
                            ' ' + str(binascii.hexlify(romval.to_bytes(8, byteorder='big'))) + '\n')
                self.comb += [
                    If( self.address.storage[6:] == 0,
                        self.data.status[bit].eq(lutsel[2]))
                    .Elif(self.address.storage[6:] == 1,
                          self.data.status[bit].eq(lutsel[3]))
                    .Elif(self.address.storage[6:] == 2,
                          self.data.status[bit].eq(lutsel[0]))
                    .Else(self.data.status[bit].eq(lutsel[1]))
                ]

class Aes(Module, AutoDoc, AutoCSR):
    def __init__(self, platform):
        self.key_0_q = CSRStorage(fields=[
            CSRField("key_0", size=32, description="least significant key word")
        ])
        self.key_1_q = CSRStorage(fields=[
            CSRField("key_1", size=32, description="key word 1")
        ])
        self.key_2_q = CSRStorage(fields=[
            CSRField("key_2", size=32, description="key word 2")
        ])
        self.key_3_q = CSRStorage(fields=[
            CSRField("key_3", size=32, description="key word 3")
        ])
        self.key_4_q = CSRStorage(fields=[
            CSRField("key_4", size=32, description="key word 4")
        ])
        self.key_5_q = CSRStorage(fields=[
            CSRField("key_5", size=32, description="key word 5")
        ])
        self.key_6_q = CSRStorage(fields=[
            CSRField("key_6", size=32, description="key word 6")
        ])
        self.key_7_q = CSRStorage(fields=[
            CSRField("key_7", size=32, description="most significant key word")
        ])

        self.dataout_0 = CSRStatus(fields=[
            CSRField("data", size=32, description="data output from cipher")
        ])
        self.dataout_1 = CSRStatus(fields=[
            CSRField("data", size=32, description="data output from cipher")
        ])
        self.dataout_2 = CSRStatus(fields=[
            CSRField("data", size=32, description="data output from cipher")
        ])
        self.dataout_3 = CSRStatus(fields=[
            CSRField("data", size=32, description="data output from cipher")
        ])
        self.specials += Instance("aes_reg_top",
                                  i_clk_i = ClockSignal(),
                                  i_rst_ni = ~ResetSignal(),

                                  i_key_0_q=self.key_0_q.fields.key_0,
                                  i_key_0_qe=self.key_0_q.re,
                                  i_key_1_q=self.key_1_q.fields.key_1,
                                  i_key_1_qe=self.key_1_q.re,
                                  i_key_2_q=self.key_2_q.fields.key_2,
                                  i_key_2_qe=self.key_2_q.re,
                                  i_key_3_q=self.key_3_q.fields.key_3,
                                  i_key_3_qe=self.key_3_q.re,
                                  i_key_4_q=self.key_4_q.fields.key_4,
                                  i_key_4_qe=self.key_4_q.re,
                                  i_key_5_q=self.key_5_q.fields.key_5,
                                  i_key_5_qe=self.key_5_q.re,
                                  i_key_6_q=self.key_6_q.fields.key_6,
                                  i_key_6_qe=self.key_6_q.re,
                                  i_key_7_q=self.key_7_q.fields.key_7,
                                  i_key_7_qe=self.key_7_q.re,

                                  o_data_out_0=self.dataout_0.fields.data,
                                  i_data_out_0_re=self.dataout_0.we,
                                  o_data_out_1=self.dataout_1.fields.data,
                                  i_data_out_1_re=self.dataout_1.we,
                                  o_data_out_2=self.dataout_2.fields.data,
                                  i_data_out_2_re=self.dataout_2.we,
                                  o_data_out_3=self.dataout_3.fields.data,
                                  i_data_out_3_re=self.dataout_3.we,
                                  )
        platform.add_source(os.path.join("deps", "opentitan", "hw", "ip", "aes", "rtl", "aes_reg_pkg.sv"))
        platform.add_source(os.path.join("deps", "opentitan", "hw", "ip", "aes", "rtl", "aes_pkg.sv"))
        platform.add_source(os.path.join("deps", "opentitan", "hw", "ip", "aes", "rtl", "aes_control.sv"))
        platform.add_source(os.path.join("deps", "opentitan", "hw", "ip", "aes", "rtl", "aes_key_expand.sv"))
        platform.add_source(os.path.join("deps", "opentitan", "hw", "ip", "aes", "rtl", "aes_mix_columns.sv"))
        platform.add_source(os.path.join("deps", "opentitan", "hw", "ip", "aes", "rtl", "aes_mix_single_column.sv"))
        platform.add_source(os.path.join("deps", "opentitan", "hw", "ip", "aes", "rtl", "aes_sbox_canright.sv"))
        platform.add_source(os.path.join("deps", "opentitan", "hw", "ip", "aes", "rtl", "aes_sbox_lut.sv"))
        platform.add_source(os.path.join("deps", "opentitan", "hw", "ip", "aes", "rtl", "aes_sbox.sv"))
        platform.add_source(os.path.join("deps", "opentitan", "hw", "ip", "aes", "rtl", "aes_shift_rows.sv"))
        platform.add_source(os.path.join("deps", "opentitan", "hw", "ip", "aes", "rtl", "aes_sub_bytes.sv"))
        platform.add_source(os.path.join("deps", "opentitan", "hw", "ip", "aes", "rtl", "aes_core.sv"))
        platform.add_source(os.path.join("gateware", "aes_reg_litex.sv"))


# System constants ---------------------------------------------------------------------------------

boot_offset    = 0x500000 # enough space to hold 2x FPGA bitstreams before the firmware start
bios_size      = 0x8000
# 128 MB (1024 Mb), but reduce to 64Mbit for bring-up because we don't have extended page addressing implemented yet
SPI_FLASH_SIZE = 16 * 1024 * 1024

# BetrustedSoC -------------------------------------------------------------------------------------

class BetrustedSoC(SoCCore):
    # I/O range: 0x80000000-0xfffffffff (not cacheable)
    SoCCore.mem_map = {
        "rom":      0x00000000, # required to keep litex happy
        "sram":     0x10000000,
        "spiflash": 0x20000000,
        "sram_ext": 0x40000000,
        "memlcd":   0xb0000000,
        "csr":      0xf0000000,
    }

    def __init__(self, platform, sys_clk_freq=int(100e6), spiflash="spiflash_1x", **kwargs):
        assert sys_clk_freq in [int(12e6), int(100e6)]

        # CPU cluster
        ## For dev work, we're booting from SPI directly. However, for enhanced security
        ## we will eventually want to move to a bitstream-ROM based bootloader that does
        ## a signature verification of the external SPI code before running it. The theory is that
        ## a user will burn a random AES key into their FPGA and encrypt their bitstream to their
        ## unique AES key, creating a root of trust that offers a defense against trivial patch attacks.

        # SoCCore ----------------------------------------------------------------------------------
        SoCCore.__init__(self, platform, sys_clk_freq,
            integrated_rom_size  = 0,
            integrated_sram_size = 0x20000,
            ident                = "betrusted.io LiteX Base SoC",
            cpu_type             = "vexriscv",
            #cpu_variant="linux+debug",  # this core doesn't work, but left for jogging my memory later on if I need to try it
            **kwargs)

        # CPU --------------------------------------------------------------------------------------
        self.cpu.use_external_variant("gateware/cpu/VexRiscv_BetrustedSoC_Debug.v")
        self.cpu.add_debug()
        self.add_memory_region("rom", 0, 0) # Required to keep litex happy
        kwargs["cpu_reset_address"] = self.mem_map["spiflash"]+boot_offset
        self.submodules.reboot = WarmBoot(self, reset_vector=kwargs["cpu_reset_address"])
        self.add_csr("reboot")
        warm_reset = Signal()
        self.comb += warm_reset.eq(self.reboot.do_reset)
        self.cpu.cpu_params.update(i_externalResetVector=self.reboot.addr.storage)

        # Debug cluster ----------------------------------------------------------------------------
        from litex.soc.cores.uart import UARTWishboneBridge
        self.submodules.uart_bridge = UARTWishboneBridge(platform.request("debug"), sys_clk_freq, baudrate=115200)
        self.add_wb_master(self.uart_bridge.wishbone)
        self.register_mem("vexriscv_debug", 0xe00f0000, self.cpu.debug_bus, 0x100)

        # Clockgen cluster -------------------------------------------------------------------------
        self.submodules.crg = CRG(platform, sys_clk_freq)
        self.add_csr("crg")
        self.platform.add_period_constraint(self.crg.cd_sys.clk, 1e9/sys_clk_freq)
        self.comb += self.crg.warm_reset.eq(warm_reset)
        self.platform.add_platform_command(
            "create_clock -name sys_clk -period 10.0 [get_nets sys_clk]")
        self.platform.add_platform_command(
            "create_clock -name spi_clk -period 50.0 [get_nets spi_clk]")
        self.platform.add_platform_command(
            "create_generated_clock -name sys_clk -source [get_pins MMCME2_ADV/CLKIN1] -multiply_by 50 -divide_by 6 -add -master_clock clk12 [get_pins MMCME2_ADV/CLKOUT0]"
        )

        # Info -------------------------------------------------------------------------------------
        # XADC analog interface---------------------------------------------------------------------

        from litex.soc.cores.xadc import analog_layout
        analog_pads = Record(analog_layout)
        analog = platform.request("analog")
        self.comb += [
            # NOTE - if part is changed to XC7S25, the pin-to-channel mappings change
            analog_pads.vauxp.eq(Cat(analog.noise0,       # 0
                                     Signal(7, reset=0),  # 1,2,3,4,5,6,7
                                     analog.noise1, analog.vbus_div, analog.usbc_cc1, analog.usbc_cc2, # 8,9,10,11
                                     Signal(4, reset=0),  # 12,13,14,15
                                )),
            analog_pads.vauxn.eq(Cat(analog.noise0_n, Signal(15, reset=0))), # PATCH
            analog_pads.vp.eq(analog.ana_vp),
            analog_pads.vn.eq(analog.ana_vn),
        ]
        self.submodules.info = info.Info(platform, self.__class__.__name__, analog_pads)
        self.add_csr("info")
        self.platform.add_platform_command('create_generated_clock -name dna_cnt -source [get_pins {{info_dna_cnt_reg[0]/Q}}] -divide_by 2 [get_pins {{DNA_PORT/CLK}}]')

        # External SRAM ----------------------------------------------------------------------------
        # Note that page_rd_timing=2 works, but is a slight overclock on RAM. Cache fill time goes from 436ns to 368ns for 8 words.
        self.submodules.sram_ext = sram_32.SRAM32(platform.request("sram"), rd_timing=7, wr_timing=6, page_rd_timing=3)  # this works with 2:nbits page length with Rust firmware...
        #self.submodules.sram_ext = sram_32.SRAM32(platform.request("sram"), rd_timing=7, wr_timing=6, page_rd_timing=5)  # this worked with 3:nbits page length in C firmware
        self.add_csr("sram_ext")
        self.register_mem("sram_ext", self.mem_map["sram_ext"], self.sram_ext.bus, size=0x1000000)
        # Constraint so a total of one extra clock period is consumed in routing delays (split 5/5 evenly on in and out)
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
        self.platform.add_platform_command("set_multicycle_path 2 -setup -through [get_pins betrustedsoc_sram_ext_sync_oe_n_reg/Q]")
        self.platform.add_platform_command("set_multicycle_path 1 -hold -through [get_pins betrustedsoc_sram_ext_sync_oe_n_reg/Q]")

        # LCD interface ----------------------------------------------------------------------------
        self.submodules.memlcd = memlcd.MemLCD(platform.request("lcd"))
        self.add_csr("memlcd")
        self.register_mem("memlcd", self.mem_map["memlcd"], self.memlcd.bus, size=self.memlcd.fb_depth*4)

        # COM SPI interface ------------------------------------------------------------------------
        self.submodules.com = spi.SPIMaster(platform.request("com"))
        self.add_csr("com")
        # 20.83ns = 1/2 of 24MHz clock, we are doing falling-to-rising timing
        # up5k tsu = -0.5ns, th = 5.55ns, tpdmax = 10ns
        # in reality, we are measuring a Tpd from the UP5K of 17ns. Routed input delay is ~3.9ns, which means
        # the fastest clock period supported would be 23.9MHz - just shy of 24MHz, with no margin to spare.
        # slow down clock period of SPI to 20MHz, this gives us about a 4ns margin for setup for PVT variation
        self.platform.add_platform_command("set_input_delay -clock [get_clocks spi_clk] -min -add_delay 0.5 [get_ports {{com_miso}}]") # could be as low as -0.5ns but why not
        self.platform.add_platform_command("set_input_delay -clock [get_clocks spi_clk] -max -add_delay 17.5 [get_ports {{com_miso}}]")
        self.platform.add_platform_command("set_output_delay -clock [get_clocks spi_clk] -min -add_delay 6.0 [get_ports {{com_mosi com_csn}}]")
        self.platform.add_platform_command("set_output_delay -clock [get_clocks spi_clk] -max -add_delay 16.0 [get_ports {{com_mosi com_csn}}]")  # could be as large as 21ns but why not
        # cross domain clocking is handled with explicit software barrires, or with multiregs
        self.platform.add_false_path_constraints(self.crg.cd_sys.clk, self.crg.cd_spi.clk)
        self.platform.add_false_path_constraints(self.crg.cd_spi.clk, self.crg.cd_sys.clk)

        # I2C interface ----------------------------------------------------------------------------
        self.submodules.i2c = i2c.RTLI2C(platform, platform.request("i2c", 0))
        self.add_csr("i2c")
        self.add_interrupt("i2c")

        # Event generation for I2C and COM ---------------------------------------------------------
        self.submodules.btevents = BtEvents(platform.request("com_irq", 0), platform.request("rtc_irq", 0))
        self.add_csr("btevents")
        self.add_interrupt("btevents")

        # Messible for debug -----------------------------------------------------------------------
        self.submodules.messible = messible.Messible()
        self.add_csr("messible")

        # Tick timer -------------------------------------------------------------------------------
        self.submodules.ticktimer = ticktimer.TickTimer(sys_clk_freq/1000)
        self.add_csr("ticktimer")

        # Power control pins -----------------------------------------------------------------------
        self.submodules.power = BtPower(platform.request("power"))
        self.add_csr("power")

        # SPI flash controller ---------------------------------------------------------------------
        spi_pads = platform.request("spiflash_1x")
        self.submodules.spinor = spinor.SPINOR(platform, spi_pads, size=SPI_FLASH_SIZE)
        self.register_mem("spiflash", self.mem_map["spiflash"], self.spinor.bus, size=SPI_FLASH_SIZE)
        self.add_csr("spinor")

        # Keyboard module --------------------------------------------------------------------------
        self.submodules.keyboard = ClockDomainsRenamer(cd_remapping={"kbd":"lpclk"})(keyboard.KeyScan(platform.request("kbd")))
        self.add_csr("keyboard")
        self.add_interrupt("keyboard")

        # GPIO module ------90f63ac2678aed36813c9ecb1de9a245b7ef137a------------------------------------------------------------------------
        self.submodules.gpio = BtGpio(platform.request("gpio"))
        self.add_csr("gpio")
        self.add_interrupt("gpio")

        # Build seed -------------------------------------------------------------------------------
        self.submodules.seed = BtSeed()
        self.add_csr("seed")

        # ROM test ---------------------------------------------------------------------------------
        self.submodules.romtest = RomTest(platform)
        self.add_csr("romtest")

        # Ring Oscillator TRNG ---------------------------------------------------------------------
        self.submodules.trng_osc = TrngRingOsc(platform, target_freq=1e6)
        self.add_csr("trng_osc")
        # ignore ring osc paths
        self.platform.add_platform_command("set_false_path -through [get_nets betrustedsoc_trng_osc_ena]")
        self.platform.add_platform_command("set_false_path -through [get_nets betrustedsoc_trng_osc_ring_ccw_0]")
        self.platform.add_platform_command("set_false_path -through [get_nets betrustedsoc_trng_osc_ring_cw_1]")
        # MEMO: diagnostic option, need to turn off GPIO
        # gpio_pads = platform.request("gpio")
        # self.comb += gpio_pads[0].eq(self.trng_osc.trng_fast)
        # self.comb += gpio_pads[1].eq(self.trng_osc.trng_slow)
        # self.comb += gpio_pads[2].eq(self.trng_osc.trng_raw)

        # AES block --------------------------------------------------------------------------------
        # self.submodules.aes = Aes(platform)
        # self.add_csr("aes")

        ## TODO: audio, wide-width/fast SPINOR

        # Lock down both ICAPE2 blocks -------------------------------------------------------------
        # this attempts to make it harder to partially reconfigure a bitstream that attempts to use
        # the ICAP block. An ICAP block can read out everything inside the FPGA, including key ROM,
        # even when the encryption fuses are set for the configuration stream.
        platform.toolchain.attr_translate["icap0"] = ("LOC", "ICAP_X0Y0")
        platform.toolchain.attr_translate["icap1"] = ("LOC", "ICAP_X0Y1")
        self.specials += [
            Instance("ICAPE2", i_I=0, i_CLK=0, i_CSIB=1, i_RDWRB=1,
                     attr={"KEEP", "DONT_TOUCH", "icap0"}
                     ),
            Instance("ICAPE2", i_I=0, i_CLK=0, i_CSIB=1, i_RDWRB=1,
                     attr={"KEEP", "DONT_TOUCH", "icap1"}
                     ),
        ]

# Build --------------------------------------------------------------------------------------------

def main():
    global _io

    if os.environ['PYTHONHASHSEED'] != "1":
        print( "PYTHONHASHEED must be set to 1 for consistent validation results. Failing to set this results in non-deterministic compilation results")
        exit()

    parser = argparse.ArgumentParser(description="Build the Betrusted SoC")
    parser.add_argument(
        "-D", "--document-only", default=False, action="store_true", help="Build docs only"
    )
    parser.add_argument(
        "-u", "--uart-swap", default=False, action="store_true", help="swap UART pins (GDB debug bridge <-> console)"
    )
    parser.add_argument(
        "-e", "--encrypt", default=False, action="store_true", help="Format output for encryption using the dummy key. Image is re-encrypted at sealing time with a secure key."
    )

    args = parser.parse_args()
    compile_gateware = True
    compile_software = False

    if args.document_only:
        compile_gateware = False
        compile_software = False

    platform = Platform(encrypt=args.encrypt)
    if args.uart_swap:
        platform.add_extension(_io_uart_debug_swapped)
    else:
        platform.add_extension(_io_uart_debug)
    soc = BetrustedSoC(platform)
    builder = Builder(soc, output_dir="build", csr_csv="test/csr.csv", compile_software=compile_software, compile_gateware=compile_gateware)
    vns = builder.build()
    soc.do_exit(vns)
    lxsocdoc.generate_docs(soc, "build/documentation", note_pulses=True)
    lxsocdoc.generate_svd(soc, "build/software", name="Betrusted SoC", description="Primary UI Core for Betrusted", filename="soc.svd", vendor="Betrusted-IO")

    # generate the rom-inject library code
    if ~args.document_only:
        with open('sw/rom-inject/src/lib.rs', 'w') as libfile:
            subprocess.call(['./key2bits.py', '-c', '-k../../keystore.bin', '-r../../rom.db'], cwd='deps/rom-locate', stdout=libfile)

    # now re-encrypt the binary if needed
    if args.encrypt:
        # check if we need to re-encrypt to a set key
        # my.nky -- indicates the fuses have been burned on the target device, and needs re-encryption
        # keystore.bin -- indicates we want to initialize the on-chip key ROM with a set of known values
        if Path('my.nky').is_file():
            print('Found my.nky, re-encrypting binary to the specified fuse settings.')
            keystore_args = ''
            if Path('keystore.bin').is_file():
                print('Found keystore.bin, patching bitstream to contain specified keystore values.')
                with open('keystore.patch', 'w') as patchfile:
                    subprocess.call(['./key2bits.py', '-k../../keystore.bin', '-r../../rom.db'], cwd='deps/rom-locate', stdout=patchfile)
                    keystore_args = '-pkeystore.patch'
            enc = ['deps/encrypt-bitstream-python/encrypt-bitstream.py', '-fbuild/gateware/top.bin', '-idummy.nky', '-kmy.nky', '-oencrypted'] + [keystore_args]
            subprocess.call(enc)

if __name__ == "__main__":
    main()
