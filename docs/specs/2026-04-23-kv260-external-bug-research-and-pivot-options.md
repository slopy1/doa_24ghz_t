# KV260 external bug research and pivot options

Date: 2026-04-23

## Why this note exists

Short memo capturing the external findings gathered after the KV260 Phase 2 bug narrowed down to the PS `M_AXI_HPM0_FPD` control path.

Current local symptom: only 16-byte-aligned 32-bit accesses round-trip; non-16-byte AXI-Lite offsets read as 0 or hang, across `doa_pipeline`, `axi_bram_ctrl`, and `axi_gpio`.

## What the external search actually showed

### 1. The KV260 workshop repo is not the fix source

- `Xilinx_Kria_KV260_Workshop` is about `xmutil`, prebuilt accelerated apps, package install, media devices, and display setup.
- It does not cover custom AXI-Lite/UIO/HPM0_FPD register bring-up.
- Conclusion: the workshop repo is useful for understanding the intended Kria user flow, but not for debugging this specific custom-hardware failure.

### 2. There is a real public KV260 symptom close to ours

- AMD support thread from 2021: `KV260 & Petalinux 2021.1 UIO unable to write AXI GPIO IP address 0xA0000000`.
- The reporter said that writing to `0xA0000000` hung the board, and even `devmem 0xA0000000` hung.
- That is close to our `axi_gpio` / `doa_pipeline` class of failure and makes a pure local RTL bug less likely.

### 3. Public KV260 custom-hardware guidance keeps coming back to boot/firmware alignment

- AMD support thread from 2026 about custom AXI GPIO on KV260 focused on two paths:
  - control the boot chain with a matching `BOOT.BIN`, or
  - use Linux FPGA manager / `fpgautil` correctly.
- The reported unblock was to convert the bitstream to `.bit.bin` and load it from U-Boot before Linux.
- This is consistent with the idea that the live PS/platform contract matters as much as the PL design.

### 4. Official Kria docs assume stable platforms plus overlays

- Official AMD docs route custom work through:
  - `kria-vitis-platforms`
  - platform generation
  - accelerator overlay generation
  - `.bit.bin`, `.dtbo`, `.xclbin`
  - `xmutil` / `dfx-mgr`
- The official `filter2d` example replaces SmartCam's stock accelerator while reusing the existing platform and metadata.
- This strongly suggests AMD expected users to keep the PS/platform side stable and swap accelerators on top of it.

### 5. Some working KV260 examples deliberately avoid PL AXI-GPIO/custom control IP

- GitHub repo `ikwzm/Kv260-Pmod-gpio-emio` explicitly chooses PS GPIO via EMIO instead of PL-side AXI-GPIO or custom IP.
- Its stated benefits are:
  - fewer PL resources
  - no new device tree work
  - no kernel-driver work
- This is not a direct DoA solution, but it is useful evidence that other developers avoid the Kria custom control path when possible.

### 6. No GitHub-wide exact match for the 16-byte stride signature was found

- Searches for phrases like `every 4th word`, `16-byte aligned only`, and `AXI GPIO 0x04 reads 0` did not produce a strong direct match.
- The strongest public matches were still:
  - KV260 AXI GPIO / UIO hangs
  - Kria overlay/runtime-flow issues
  - working examples that route around custom PL control
- Conclusion: the exact signature looks niche, but the surrounding symptom family is real.

### 7. User-supplied external anecdote fits the local evidence very well

- The reported issue: KV260 can continue booting from factory QSPI firmware even when PetaLinux generated an FSBL/PMUFW that matches a custom Vivado design.
- If true, the live PS can disagree with the XSA used to build the bitstream.
- The example mismatches called out were low-level PS settings such as AXI widths, clocks, and enabled devices.
- That lines up with our current bug much better than an RTL-only explanation does.

### 8. Reddit reports the same KV260 failure family in multiple forms

- Reddit thread from August 5, 2025: `Kria SoM KV260 Petalinux boot hangs at xilinx_dma_probe`.
- The key claim was that the generated FSBL/PMUFW matched the custom PS configuration, but the board still booted from factory firmware in QSPI, causing low-level PS mismatches.
- The original poster explicitly said that explanation unblocked their issue.

- Reddit thread from July 22, 2022: `Kria SoM KV260 Petalinux`.
- One user reported that they could only get reliable custom-hardware boot progress after changing the boot-mode resistors from QSPI to SD1 mode.
- This is directionally consistent with "the default KV260 boot path is fighting the custom hardware flow."

- Reddit thread from 2025 about AXI DMA on KV260:
  `Getting an AXI DMA working on the Zynq MPSoC/Petalinux platform`.
- The reported issue was that FSBL said the PL was configured successfully, but Linux later reprogrammed the PL from a default firmware image under `/lib/firmware/xilinx/`.
- That is another way the live hardware can stop matching the expected device tree and software contract.

- Reddit thread from 2025: `Kria / Petalinux`.
- The most relevant claim was that on KV260/KR260 the PS configuration is effectively fixed unless you take control of the boot path, and the practical advice was to start from a known-good PS preset instead of inventing a fresh one.

### 9. AMD support independently reports the same QSPI / FSBL mismatch story

- AMD support thread from July 12, 2022: `Petalinux Custom XSA Device Tree`.
- A responder stated plainly that on KV260, default PetaLinux flow programs the PL in FSBL, but the board still starts FSBL and U-Boot from QSPI on the module.
- Their explanation was that the QSPI FSBL does not see the custom bitstream, so the board later fails because the hardware no longer matches the device tree.
- They reported an SD-boot-forcing workaround via the Kria boot-mode TCL flow.

### 10. There is also evidence that BSP/rootfs defaults can silently reload the wrong PL

- Reddit and AMD threads both show variants of the same pattern:
  - FSBL says the PL was configured
  - boot gets farther than expected
  - then later Linux or the BSP rootfs loads something else, or the running platform contract still does not match the custom XSA
- That means "the bitstream loaded once" is not enough evidence that the system is still running with the expected hardware later in boot.

## What this means for the current bug

### Less likely

- `doa_pipeline.v` itself is broken
- Python / `mmap` / `ctypes` is the root cause
- the bug is specific to one slave IP

### More likely

- PS/PL platform mismatch
- boot firmware mismatch
- late PL reprogramming from BSP/default firmware
- unsupported or poorly-supported Vivado-first custom hardware flow on KV260
- a Kria-specific control-path issue that disappears when the official platform contract is preserved

## Recommended paths forward

### Path A: one last dispositive A/B

- Keep the minimal `axi_gpio` or `axi_bram_ctrl` design.
- Run it once under the stock factory boot path.
- Run it again under a `BOOT.BIN` generated from the same XSA/FSBL/PMUFW as the design.
- If the stride or partial-register bug disappears, the RTL is effectively cleared.

### Path B: pivot to the supported Kria model

- Stop owning the full PS/platform design.
- Rebuild on top of `kria-vitis-platforms`.
- Integrate the custom logic as an overlay/accelerator while preserving AMD's known-good platform setup.
- This is the strongest "different path entirely" that still keeps KV260 in play.

### Path B.1: keep the AMD PS preset even if using Vivado

- If a full Vitis platform pivot is too heavy, the next-cleanest option is still to start from an AMD example platform or saved PS preset.
- Avoid fresh PS configuration work unless there is a clear reason to change it.
- This reduces the chance that the XSA expects a PS setup different from what the board actually boots with.

### Path C: simplify the control path

- If possible, avoid early dependence on custom AXI-Lite control from `M_AXI_HPM0_FPD`.
- Move simple control/status to PS-side GPIO/EMIO or other lower-risk PS-managed paths.
- Keep the custom PL limited to the datapath/streaming portion first.

### Path C.1: decouple PL loading from the BSP defaults

- Audit `/lib/firmware/xilinx/`, FPGA-manager behavior, and any BSP-provided firmware packages before assuming the currently loaded PL matches the bitstream you built.
- Prefer one explicit PL loading mechanism and disable the others during bring-up.

### Path D: thesis-first fallback

- If schedule risk dominates, complete the AoA/DoA evaluation on the working ARM-only KV260 path.
- Treat the FPGA issue as a documented platform bring-up constraint rather than the central thesis risk.

## Bottom line

The external evidence does not clear every possibility, but it shifts the center of gravity away from "your RTL is probably wrong" and toward "the KV260 platform/boot contract may be wrong for the design you are loading."

The two strongest next steps are:

1. A matching-boot-image A/B with the minimal GPIO/BRAM design.
2. A platform pivot to `kria-vitis-platforms` if the custom Vivado-first route continues to fight us.

The cleanest practical route to the AoA/DoA goal now looks like:

1. Keep the ARM-only KV260 path as the always-working baseline.
2. For FPGA, either:
   - use a matching controlled boot image, or
   - reuse AMD's platform and add only the accelerator/datapath.
3. Avoid any flow where factory QSPI firmware, starter-kit BSP defaults, and custom Vivado XSA are all competing at once.

## Why KV260 is uniquely fragile here

KV260 has no board-level PL fabric clock. All PL clocks are produced by the PS via `FCLK_CLK*`. KR260 and KD240 have independent 25 MHz PL clock sources; KV260 does not. This is a KV260-specific constraint (see AMD info post on Kria PL clocking).

Consequence for our bug class: a running PS whose clock, AXI width, or AFI programming disagrees with the XSA used to build the bitstream will produce subtly-wrong PL behavior that no fabric-side probe can detect. The PL loads successfully, AXI handshakes complete, but transactions at offsets the PS config didn't plan for can silently return zero. KR260/KD240 would fail more loudly because their PL clock is external and independent — mismatched PS config wouldn't wholesale break fabric clocking.

This does not by itself explain the exact 16-byte stride signature. A dead or grossly-wrong `FCLK_CLK0` would produce catastrophic failure, not a clean "aligned works, unaligned returns 0" pattern. But it is supporting evidence that KV260 cannot tolerate PS/XSA mismatch the way richer-carrier Kria variants can, which makes the `kria-vitis-platforms` pivot the correct structural answer even if the proximate cause is something narrower.

## Live-board sanity check results (2026-04-23 late session)

Goal: eliminate loader path as a variable in the stride bug.

**Method:** Same `bram32` bitstream loaded two different ways against the same KV260 in the same session.
- Run 1: `sudo fpgautil -b min_bram32_wrapper.bit.bin -o min_bram32.dtbo -f Full -n Full` (raw FPGA manager path)
- Run 2: `sudo xmutil loadapp bram32` (Kria app bundle path)

**Platform observations before the test:**
- `xmutil listapps` shows `k24-starter-kits`, `bram32`, `k26-starter-kits` installed.
- `k26-starter-kits` active exposes only PS-internal `axi-pmon` Performance Monitor Counters at `0xffa00000 / 0xfd0b0000 / 0xfd490000 / 0xffa10000`. Zero PL-side IP — it is a bare base-platform overlay with no accelerator fabric. Not usable as a "known-good fabric sanity target." Implication: there is no pre-installed AMD-authored KV260 overlay on this board that exposes a custom AXI-Lite window we can independently probe.
- kernel cmdline: `clk_ignore_unused cma=800M`, normal Kria boot, FPGA manager framework and `of-fpga-region` both probed cleanly.
- Loading `bram32` via `xmutil` logged two benign `OF: overlay: WARNING: memory leak will occur if overlay removed` messages — identical to the warnings `k26-starter-kits` produces at load, i.e. not a regression.

**Result (stride probe, `stride_probe.py /dev/uio4` → `bram_ctrl @ 0xA0010000`):**

```
  0x0000  0xCAFE0000  0xCAFE0000  OK
  0x0004  0xCAFE0004  0x00000000  ZERO (stride bug)
  0x0008  0xCAFE0008  0x00000000  ZERO (stride bug)
  0x000C  0xCAFE000C  0x00000000  ZERO (stride bug)
  0x0010  0xCAFE0010  0xCAFE0010  OK
  0x0014  0xCAFE0014  0x00000000  ZERO (stride bug)
  0x0018  0xCAFE0018  0x00000000  ZERO (stride bug)
  0x001C  0xCAFE001C  0x00000000  ZERO (stride bug)
  0x0020  0xCAFE0020  0xCAFE0020  OK
  0x0024  0xCAFE0024  0x00000000  ZERO (stride bug)
  0x0030  0xCAFE0030  0xCAFE0030  OK
```

**Verdict:** Stride pattern is bit-identical under `xmutil loadapp` and under `fpgautil -b`. Loader path is conclusively eliminated as a variable.

**What this rules out in addition to the prior A/Bs:**
- fpgautil vs xmutil device-tree application semantics
- Kria app metadata / `dfx-mgr` slot bookkeeping
- generic-uio vs xmutil-specific UIO binding

**What remains as the center of gravity:**
- PS `M_AXI_HPM0_FPD` transaction geometry (AWSIZE / AWLEN / WSTRB at misaligned offsets) driven by XSA/PS-config vs live factory QSPI firmware
- Coherency / AFI programming difference between our PS config and the running platform
- Any interaction unique to `axi_smartconnect` AXI4→AXI4-Lite downsizing in this PS-config context (since `axi_bram_ctrl`, `axi_gpio`, and `doa_pipeline` all fail identically)

**Side observations:**
- Loading `bram32` via `xmutil loadapp` dropped the SSH session mid-load, while serial console stayed up. The board did not hang — ssh resumed cleanly after reconnection and the overlay was still in slot 0. This suggests a transient network perturbation during overlay application (possibly a PHY reset ripple or a systemd-networkd re-enumeration), not a crash. Worth one line in the session log but not a standalone debug target.
- Heredocs pasted through picocom at 115200 are unreliable on this link — the shell interleaves clipboard bytes with echoed command output. For any non-trivial test, prefer `scp + ssh` over pasting into serial. `stride_probe.py` is checked in under `fpga/vivado_kv260/bram_test/bram32/` for repeatability.

## 2026-04-24 addendum — AMD PS override A/B result

Goal: test whether AMD's `kv260_bist` PS override block alone fixes the stride bug without paying the cost of a full platform rebuild.

**Method:** Build `create_min_bram_amd.tcl`, which keeps the failing `min_bram32` BRAM harness but swaps in AMD's verbatim 37-line PS override block from `kria-vitis-platforms/kv260/platforms/kv260_bist/scripts/config_bd.tcl`. Deploy the resulting bundle with `host_deploy_bram_amd.sh`, which stages `amd_build/min_bram_amd_wrapper.bit.bin` (md5 `ec703deb22da76d115a0f9f4a5f7cd56`), `min_bram_amd.dtbo`, and `shell.json`, then loads `bram32_amd` via `xmutil` and runs `stride_probe.py /dev/uio4`.

**Result:** Exact same fingerprint as the baseline `min_bram32` design (`95887baf38075c73edfe2e42441070c4`): only `0x00`, `0x10`, `0x20`, and `0x30` round-trip; `0x04`, `0x08`, `0x0C`, `0x14`, `0x18`, `0x1C`, and `0x24` still read back as zero.

**Verdict:** AMD's verbatim `kv260_bist` PS override block is **not** sufficient to fix the bug. "Copy AMD's PS config" is now formally eliminated. A future `kria-vitis-platforms` rebuild would still be useful, but only as a test of the broader Kria platform contract, not of the PS override list alone.

## Revised next-session plan (updated 2026-04-24 after AMD PS override A/B)

Given that loader path, overlay memtype, and AMD's verbatim PS override block are all eliminated, the next step moves back to direct AXI capture:

**Primary:** System ILA on `smc/S00_AXI` + `smc/M00_AXI`.
- Extend the current `create_min_gpio.tcl` harness with a two-slot `system_ila`.
- Capture `AWADDR`, `AWSIZE`, `AWLEN`, `AWBURST`, `WSTRB`, `WDATA`, and `BRESP` for writes at `0x00`, `0x04`, `0x08`, `0x10`, `0x14`, `0x20`, `0x24`.
- If S00 is already wrong, fix is at PS port generation / transaction geometry.
- If S00 is clean and M00 is wrong, fix is at smartconnect translation.
- If both look clean while stride still reproduces, the remaining suspect is a deeper platform-contract issue.

**Backup (only if primary is inconclusive):** broader `kria-vitis-platforms` rebuild.
- Clone repo, select the leanest KV260 platform variant (not `smartcam` / `nlp` — pick the base with the fewest extra IP blocks to strip).
- Add only `axi_bram_ctrl` at `0xA001_0000` as the accelerator.
- Build, deploy, re-run `stride_probe.py /dev/uio4`.
- If clean → the broader Kria platform contract was the issue.
- If stride persists → revisit Path C (EMIO control + HPM0 streaming only) or thesis-first fallback options.

**Hard stop:** 2 working days across the post-ILA path. If stride still reproduces after an ILA pass plus a broader AMD-platform rebuild, revisit Path C (EMIO control + HPM0 streaming only) or Path D (ARM-only KV260 + Cora FPGA reference data) for thesis delivery.

**Path A (matching BOOT.BIN A/B) is formally dropped:** not viable on KV260 because factory FSBL/PMUFW live in QSPI, and reflashing QSPI is a brick-risk operation that also un-Kria-izes the board for all future AMD overlays.

## Sources

- Workshop Part 2:
  `https://github.com/Xilinx/Xilinx_Kria_KV260_Workshop/blob/main/Part%202:%20Exploring%20the%20Different%20AAs.md`
- Workshop FAQ:
  `https://github.com/Xilinx/Xilinx_Kria_KV260_Workshop/blob/main/FAQ.md`
- AMD support, KV260 UIO / AXI GPIO hang:
  `https://adaptivesupport.amd.com/s/question/0D52E00006jrRe4SAE/kv260-petalinux-20211-uio-unabled-to-write-axi-gpio-ip-address-0xa0000000?language=en_US`
- AMD support, custom AXI GPIO / boot flow:
  `https://adaptivesupport.amd.com/s/question/0D5Pd00001OGCWjKAP/petalinux-20232-on-kv260-with-bsp-with-custom-axi-gpio?language=en_US`
- Official KV260 platform flow:
  `https://xilinx.github.io/kria-apps-docs/kv260/2022.1/build/html/docs/build_vitis_platform.html`
- Official overlay flow:
  `https://xilinx.github.io/kria-apps-docs/kv260/2022.1/build/html/docs/build_accel.html`
- Official on-target utilities:
  `https://xilinx.github.io/kria-apps-docs/creating_applications/2022.1/build/html/docs/target.html`
- Official example replacing a stock accelerator:
  `https://xilinx.github.io/kria-apps-docs/creating_applications/2022.1/build/html/docs/vitis_accel_flow_smartcam_filter2d_example.html`
- Working KV260 example using PS GPIO over EMIO:
  `https://github.com/ikwzm/Kv260-Pmod-gpio-emio`
- User-supplied anecdotal report about factory firmware / FSBL mismatch:
  kept in chat context for this session; not independently re-verified in this note.
- Reddit, `Kria SoM KV260 Petalinux boot hangs at xilinx_dma_probe`:
  `https://www.reddit.com/r/FPGA/comments/1mib8ai/kria_som_kv260_petalinux_boot_hangs_at_xilinx_dma/`
- Reddit, `Kria SoM KV260 Petalinux`:
  `https://www.reddit.com/r/FPGA/comments/w5c2s7/kria_som_kv260_petalinux/`
- Reddit, `Getting an AXI DMA working on the Zynq MPSoC/Petalinux platform`:
  `https://www.reddit.com/r/FPGA/comments/1mk8egy/getting_an_axi_dma_working_on_the_zynq/`
- Reddit, `Kria / Petalinux`:
  `https://www.reddit.com/r/FPGA/comments/1kbm9xb/kria_petalinux/`
