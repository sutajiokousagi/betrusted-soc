#!/bin/bash

riscv64-unknown-elf-objcopy -O binary ../sw/target/riscv32i-unknown-none-elf/release/betrusted-soc /tmp/betrusted-soc.bin
# cat ../build/gateware/top_pad.bin /tmp/betrusted-ec.bin > /tmp/bt-ec.bin
