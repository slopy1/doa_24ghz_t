# AMD IP Shortlist for KV260 and Cora Z7

Date: 2026-04-23

Purpose: quick reference for AMD/Xilinx IP cores that are worth considering for this DoA project, split by board.

This note was prepared against AMD's public IP catalog pages and filtered against the actual repo datapath:
- `fpga/rtl/doa_pipeline.v`
- `fpga/rtl/fir_filter_sc16.v`
- `fpga/rtl/phase_rotate_sc16.v`
- `fpga/rtl/xcorr_acc.v`
- `fpga/rtl/autocorr_acc.v`

The current design is a small streaming DSP chain with FIR, phase rotation, xcorr/autocorr, AXI-Lite control, and AXI DMA or equivalent data movement. The goal here is not "all IP that exists," but "IP that would materially help this project."

## Board Context

### KV260

Board class: Kria KV260 / Zynq UltraScale+ MPSoC K26

Practical implication: KV260 has much more headroom than Cora, so it is the better place to use heavier debug infrastructure and more standardized IP blocks without fighting the resource budget as hard.

### Cora Z7

Board class: Digilent Cora Z7-07S / Zynq-7000 XC7Z007S

Practical implication: Cora is much smaller. IP choices need to stay lean and focused. Anything introduced here should either replace fragile custom logic or materially simplify bring-up.

## KV260: Strong Fits

### 1. FIR Compiler

Best use: replace `fir_filter_sc16.v` if the FIR itself is not the thesis contribution.

Why it helps:
- Standard, proven FIR implementation
- Better coefficient handling and architecture options than hand-rolled RTL
- Cleaner path to timing closure
- Good fit for AXI-Stream based DSP chains

Official page:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/fir_compiler.html>

AMD page notes:
- Device support includes `Zynq UltraScale+ MPSoC`

### 2. System ILA

Best use: AXI-Lite and AXI-Stream debug on KV260.

Why it helps:
- This is the single most useful debug IP for your current KV260 bring-up situation
- Can monitor AXI4-MM and AXI4-Stream
- Includes protocol checking in IP Integrator flows

Official page:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/system-ila.html>

AMD page notes:
- Device support includes `Zynq UltraScale+ MPSoC`

### 3. AXI BRAM Controller + Block Memory Generator

Best use:
- Minimal smoke-test endpoints
- Scratch RAM
- Coefficient storage
- Snapshot buffer experiments

Why it helps:
- Very good "known-good fabric endpoint" for isolating platform vs custom-slave bugs
- Much safer for sanity checks than custom AXI-Lite during unstable bring-up

Official pages:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/axi_bram_if_ctlr.html>
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/block_memory_generator.html>

AMD page notes:
- Both list `Zynq UltraScale+ MPSoC`

### 4. AXI DMA Controller

Best use: high-throughput transfer between AXI4 memory-mapped PS/DDR space and AXI4-Stream DSP blocks.

Why it helps:
- It already matches the architecture direction of your design
- Still the right standard core once the control path is stable

Official page:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/axi_dma.html>

AMD page notes:
- Device support includes `Zynq UltraScale+ MPSoC`

### 5. AXI Streaming FIFO

Best use: low-complexity memory-mapped access to an AXI-Stream path when DMA is unnecessary.

Why it helps:
- Good for debug and low-rate test paths
- Simpler than full DMA when you only need small transfers or visibility

Official page:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/axi_fifo.html>

AMD page notes:
- Device support includes `Zynq UltraScale+ MPSoC`

### 6. CORDIC

Best use:
- `atan2`
- rectangular/polar conversion
- phase extraction in PL

Why it helps:
- Fits your DoA math better than generic "math IP"
- Good candidate if you move phase extraction out of PS

Official page:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/cordic.html>

AMD page notes:
- Device support includes `Zynq UltraScale+ MPSoC`

## KV260: Conditional / Optional

### CIC Compiler

Use only if you add explicit decimation or interpolation stages.

Why it helps:
- Good for sample-rate change blocks
- Not a direct replacement for your current FIR unless the architecture changes

Official page:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/cic_compiler.html>

### AXI GPIO

Use for:
- debug flags
- reset strobes
- heartbeat/status bits
- simple trigger lines

Official page:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/axi_gpio.html>

### FFT

Use only if the algorithm path changes toward frequency-domain processing, channelization, or FFT-assisted estimation.

Official page:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/fft.html>

Note:
- Worth verifying directly in the Vivado 2025.2 IP catalog before planning around it for KV260. The AMD public page is less explicit than some others about current UltraScale+ MPSoC wording.

## Cora Z7: Strong Fits

### 1. FIR Compiler

Best use: same as KV260, but with tighter resource discipline.

Why it helps:
- Replaces fragile custom FIR work with a standard core
- Likely the best "engineering value per hour" swap if the FIR is not research novelty

Official page:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/fir_compiler.html>

AMD page notes:
- Device support includes `Zynq 7000`

### 2. Complex Multiplier

Best use: candidate replacement for the complex multiply inside `phase_rotate_sc16.v`, or other complex arithmetic blocks.

Why it helps:
- Strong fit for the project's math
- Better targeted than dropping in broader DSP infrastructure

Official page:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/complex_multiplier.html>

AMD page notes:
- Device support includes `Zynq 7000`
- The AMD page does not list `Zynq UltraScale+ MPSoC`, so this one is a better Cora candidate than KV260 candidate

### 3. CORDIC

Best use:
- phase extraction
- rectangular/polar conversion

Why it helps:
- Gives you a standard PL-side phase block if you want to push more math off PS without writing custom iterative logic

Official page:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/cordic.html>

AMD page notes:
- Device support includes `Zynq 7000`

### 4. AXI Streaming FIFO

Best use: simple memory-mapped access to a stream without paying the complexity of DMA.

Why it helps:
- Especially attractive on a small board where "simple and debuggable" matters more than peak throughput

Official page:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/axi_fifo.html>

AMD page notes:
- Device support includes `Zynq 7000`

### 5. AXI BRAM Controller + Block Memory Generator

Best use:
- coefficient storage
- small buffers
- minimal test designs

Why it helps:
- Excellent for controlled experiments on a small fabric budget

Official pages:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/axi_bram_if_ctlr.html>
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/block_memory_generator.html>

## Cora Z7: Conditional / Optional

### AXI DMA Controller

Use if you truly need the throughput and already have the path stable.

Why it helps:
- Standard streaming-to-memory bridge

Why it is only optional on Cora:
- More moving parts than FIFO/BRAM-based debug and test flows
- On a small Zynq-7000 part, simplicity often wins

Official page:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/axi_dma.html>

### System ILA / ILA

Use any time AXI behavior is in doubt.

Official pages:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/system-ila.html>
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/ila.html>

### CIC Compiler

Use only if sample-rate conversion becomes part of the design.

Official page:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/cic_compiler.html>

## Not For This Project

### Zynq UltraScale+ RFSoC DFE IP Cores

Not applicable to either KV260 or Cora.

Why:
- KV260 is `Zynq UltraScale+ MPSoC`, not RFSoC
- Cora is `Zynq-7000`
- AMD's page lists RFSoC-only support

Official page:
- <https://www.amd.com/en/products/adaptive-socs-and-fpgas/intellectual-property/zynq-usplus-rfsoc-dfe.html>

## Recommended Adoption Order

### KV260

1. `System ILA`
2. `AXI BRAM Controller + Block Memory Generator`
3. `FIR Compiler`
4. `AXI DMA`
5. `CORDIC` if phase extraction moves into PL

### Cora Z7

1. `FIR Compiler`
2. `AXI Streaming FIFO`
3. `System ILA`
4. `Complex Multiplier` or `CORDIC`
5. `AXI DMA` only if simpler interfaces are no longer enough

## Bottom Line

If the goal is to reduce implementation risk quickly:
- KV260: use AMD IP aggressively for debug and standard DSP plumbing
- Cora: use AMD IP selectively, mainly where it replaces fragile custom blocks with a simpler and more proven alternative

If only one custom datapath block gets replaced first, `FIR Compiler` is the highest-value candidate on both boards.
