# KV260 DoA — Plan of Attack to Finish the Thesis

*Date: 2026-04-22*
*Status: active plan, replaces all Cora-forward plans as of this date*

## Context

KV260 is now the primary hardware target for the thesis. Cora Z7 on `feature/fir-backpressure` is the frozen reference build. This document is the end-to-end plan from "Phase 1 ARM first-light is committed" (where we are) to "thesis chapter draft is done" (where we need to be).

All work lives on worktree `/home/mau/doa_24ghz_thesis-kv260` on branch `feature/kv260`. `fpga/rtl/` is shared with Cora — do not fork it.

The pitfall register is `docs/specs/2026-04-22-kv260-research-and-viability.md §6`. Every phase below cross-references the pitfalls that apply.

---

## Decision log addendum (2026-04-24 afternoon)

**Phase 2 as written here (HPM0_FPD bitstream + UIO mmap) is REPLACED by EMIO Path C.** Today's session closed every TCL-controllable variable — PS config (lean and AMD verbatim), smartconnect presence, slave protocol, slave IP, explicit data-width converter — all reproduce the 16-byte stride bug bit-for-bit. The remaining open hypothesis is firmware-mismatch between our Vivado-2025.2 XSA's PS init and the 2022.1 PMUFW/FSBL on QSPI, but apt does not ship a newer firmware (`xlnx-firmware = 2022.1-5`, both A/B slots already at `K26-BootFW-01.02-06140626`), so `xmutil bootfw_update` with the supplied file is a no-op. Materially testing the firmware hypothesis requires a custom BOOT.BIN built via Vitis 2024.1+ (8-12 hr envelope, ~50% probability of fix, ~20% probability of breaking udmabuf which Phase 3 needs).

**Path C (EMIO + libgpiod) is the new committed forward path** — see the project notes §"DECISION 2026-04-24" for full rationale and architecture. Effort estimate ~8 hr to working bitstream + driver. Phase 3 (FPGA-accelerated DoA), Phase 4 (boot autonomy), Phase 5 (campaign + chapter) below are unchanged in scope; Phase 3 just consumes the EMIO register IO instead of UIO mmap. Plan-file step-by-step at `<plan-file>` + today's CHANGELOG entry.

**Two sub-resolutions also landed today** (carried forward, not re-derived next session):

- **Fan-gate fix.** Pin `A12 LVCMOS33 active-high`. XDC at `fpga/vivado_kv260/constraints/kv260_fan_gate.xdc`, applied to all three TCL bitstream scripts. Without this, every custom bitstream killed the board in 15-60 s; with it, board ran 28+ min with active fan response. Memory: `project_kv260_fan_gate_pin.md`.
- **JTAG ILA via Vivado HW Manager is unsafe on this image.** Brings the board down ~1-2 min after arming. Documented community issue. EMIO needs no JTAG.

---

## Phase 1 — ARM-only DoA on KV260 (done)

**Exit criteria** ✅
- Ubuntu 22.04 boots from microSD, SSH reachable on wired Ethernet
- BladeRF 2.0 xA4 enumerates on USB 3.0 (barrel jack powered)
- `aoa_estimation_headless.py` (unchanged from Cora) produces ROOTMUSIC angles at the expected rate
- nRF5340 ch19 at ~89° broadside gives <5° std-dev inline

**State** — hit 2026-04-21, committed `aa4380e`, measured std-dev ~2.5° over first 70 samples.

**Follow-ups still owed:**
- Formal 60-second capture with CSV + sidecar JSON (Cora parity).
- Document exact Ubuntu image build/date in `kv260_headless/README.md` or equivalent so future builds are reproducible.

---

## Phase 2 — KV260 bitstream built and loaded at runtime

**Goal:** A `.bit.bin` + `.dtbo` pair that instantiates `doa_pipeline_0` on the ZU+ fabric, loads cleanly at runtime, exposes UIO devices, and answers register reads/writes via `/dev/uio0`.

**Tasks (in order):**

1. **Vivado build on Windows host.**
   - Run `fpga/vivado_kv260/create_project.tcl` in Vivado 2025.2 on the Windows machine.
   - Verify the generated BD has `zynq_ultra_ps_e_0`, two `smartconnect` blocks (one for AXI-Lite control, one merging DMA SG + MM2S masters onto HP0_FPD), `axi_dma_0` at `0xA000_0000`, and `doa_pipeline_0` at `0xA001_0000`. The HPM0_FPD aperture on KV260 starts at `0xA000_0000`, not `0x8000_0000` (which is HPM0_LPD).
   - Synth + impl + bitstream. Target: WNS ≥ +2 ns at 50 MHz.
   - Export: `system_wrapper.bit` from `.runs/impl_1/`.

2. **Generate `.bit.bin` (stripped) via `bootgen`.**
   - Run on Windows or Linux host with Vivado installed: `bootgen -arch zynqmp -process_bitstream bin -image system.bif -w -o system.bit.bin`.
   - `system.bif` needs a single `[destination_device = pl] system_wrapper.bit` line.
   - Verify size is roughly half of the raw `.bit` (stripped header).

3. **Compile the device tree overlay.**
   - `dtc -@ -I dts -O dtb -o doa_pipeline.dtbo fpga/vivado_kv260/doa_pipeline.dts`
   - Check `@` symbol refs against a decompile of the live KV260 base DT — `&amba_pl` must resolve.

4. **Copy artifacts to KV260.**
   - `scp system.bit.bin doa_pipeline.dtbo ubuntu@<kv260-ip>:~/doa/bitstream/`

5. **Load at runtime and verify.**
   - `sudo fpgautil -b ~/doa/bitstream/system.bit.bin -o ~/doa/bitstream/doa_pipeline.dtbo`
   - or: `sudo xmutil loadapp doa_pipeline` if the overlay is installed under `/lib/firmware/xilinx/`
   - Check `/sys/class/fpga_manager/fpga0/state` → `operating`.
   - Check `ls /dev/uio*` → at least two entries.
   - Write a minimal `kv260_headless/test_uio.py`:
     - Open `/dev/uio0`, mmap 4 KB.
     - Write `0x1234` to offset 0x28 (COS_CAL), read back, expect `0x1234`.
     - Write `0x8000` to 0x28, expect `0xFFFF8000` on readback (sign extension, same as Cora verification).

6. **Commit with clear handoff notes** — bitstream artifacts go under `fpga/vivado_kv260/release/` or equivalent. Do not check the raw `.bit` into git (too large) but do check `.bit.bin` (stripped) and `.dtbo`.

**Pitfalls to watch:**
- **HIGH — `.bit` vs `.bit.bin`.** `fpgautil` rejects raw `.bit` on most KV260 images; must be `bootgen`-stripped. If `fpgautil` fails with `Invalid bitstream format`, re-run bootgen.
- **HIGH — DTS base address mismatch.** If the Vivado BD and `doa_pipeline.dts` disagree on `reg = <0x0 0x80000000 0x0 0x1000>`, reads return 0 with no error. Treat any all-zero register read as a DTS/BD mismatch first, wiring second.
- **MEDIUM — UIO permissions.** `/dev/uio0` defaults to `root:root 0600`. Either run as root or add a udev rule: `SUBSYSTEM=="uio", GROUP="dialout", MODE="0660"` in `/etc/udev/rules.d/90-uio.rules`.
- **MEDIUM — udmabuf kernel module.** The KV260 Ubuntu image may not ship `udmabuf` precompiled. `setup_kv260.sh` already handles this — verify it runs clean under Ubuntu 22.04's current kernel (check `uname -r` matches what udmabuf was built against).

**Exit criteria:**
- `fpgautil` returns success and `/sys/class/fpga_manager/fpga0/state == operating`
- `test_uio.py` round-trips `0x1234` and sign-extends `0x8000` correctly on COS_CAL
- `/dev/udmabuf0` exists with non-zero `phys_addr` sysfs entry

---

## Phase 3 — FPGA-accelerated DoA on KV260 (replicates Cora Phase A)

**Goal:** `aoa_estimation_fpga_kv260.py` produces real-time DoA estimates at rate ≥ 3 Hz (filter on) / ≥ 10 Hz (filter off), std-dev comparable to or better than Cora Phase A baseline.

**Tasks:**

1. **Install SoapySDR stack from source on Ubuntu 22.04 aarch64.**
   - `libbladeRF` → `SoapySDR` → `SoapyBladeRF` in that order.
   - Extend `kv260_headless/setup_kv260.sh` with the build commands. No prior art — expect iteration.
   - Sanity: `SoapySDRUtil --find` lists the BladeRF xA4 by serial.

2. **Audit the driver for remaining Cora-isms.**
   - grep `kv260_headless/aoa_estimation_fpga_kv260.py` for: `/dev/mem`, `0x4000_0000`, `0x1F00_0000`, `ctypes.c_uint32` at locations holding 64-bit physical addresses. Every hit is a bug.
   - Verify `udmabuf` physical address read from `/sys/class/udmabuf/udmabuf0/phys_addr` happens before DMA descriptor programming.
   - Verify DMA descriptor width (ZU+ DMA can be programmed in 32- or 64-bit addressing mode; choose 32-bit addressing with high-address fixed at 0 if `udmabuf` allocates under 4 GB, otherwise use 64-bit).

3. **Smoke test against known-angle source.**
   - Power BladeRF barrel jack, boot KV260, load bitstream, run `python3 aoa_estimation_fpga_kv260.py --algo ROOTMUSIC --filter none --duration 30`.
   - Compare mean angle to ARM baseline (same session, same angle). Should agree within 5°.
   - Enable filter: `--filter bandpass`. Rate should drop (expected — same FIR throughput issue until backpressure fix ported).

4. **Port the FIR backpressure fix forward.**
   - The RTL fix is on `feature/fir-backpressure` commits `31c1962` (FIR m_tready), `b49da7d` (interleaver m_tready), `1763850` (delay-line shift gating), `d76f6ec` (phase_rotate handshake), `6f0f649` (splitter s_axis_tready), `2bfe63f` (xcorr s_axis_tready declaration).
   - Merge or cherry-pick these onto `feature/kv260` so the RTL matches. Keep the decision explicit — do NOT silently carry the rest of `feature/fir-backpressure` (which has Cora-specific OCM + petalinux DT commits).
   - Rebuild bitstream (Phase 2 again). Verify filter rate jumps from ~3 Hz to ~10 Hz.

5. **Calibration run.**
   - Static target at a known broadside angle (~90°). Write `calibration.json` with cal offset 0.
   - Run ROOTMUSIC with filter on, observe mean angle, use `ADJUST_CAL` semantics to converge.
   - Record the converged cal value and the single-angle std-dev. Commit as KV260's calibration baseline.

**Pitfalls to watch:**
- **HIGH — SoapyBladeRF build from source.** No KV260 prior art. Expect `cmake` find-package issues for `libbladeRF`. Pin all three (`libbladeRF`, `SoapySDR`, `SoapyBladeRF`) to tagged releases matching Cora's (libbladeRF 2.6.0, SoapySDR 0.8.1, SoapyBladeRF 0.4.1) to avoid API drift.
- **HIGH — 64-bit ctypes.** If the driver reads a `udmabuf` `phys_addr` > `0xFFFF_FFFF` into a `c_uint32`, descriptor corruption is silent and DMA will either hang or read garbage. Any DMA wedge with register reads working is almost always a 64-bit address truncation bug on aarch64.
- **MEDIUM — BladeRF USB reset spike.** Same as Cora — the barrel jack + BladeRF init sequence can pulse the USB hub and glitch other devices. Keep the USB reconnect logic from Cora's `main.py` if a `main.py` equivalent is built on KV260.
- **MEDIUM — Filter phase response on rebuilt bitstream.** The FIR coefficients are loaded from software (v3 pattern), not baked into the bitstream, so filter response should be identical to Cora. But if the calibration diverges badly, suspect a toolchain-induced multiplier rounding change (switch from DSP48E1 to DSP48E2).

**Exit criteria:**
- `--filter none` ROOTMUSIC: rate ≥ 10 Hz, std-dev ≤ 5° at broadside
- `--filter bandpass` ROOTMUSIC (post-backpressure fix): rate ≥ 8 Hz, std-dev ≤ 3° at broadside
- ARM vs FPGA mean-angle divergence ≤ 2° at the same calibration offset

---

## Phase 4 — Production packaging

**Goal:** KV260 boots, waits for BladeRF USB, loads bitstream, allocates udmabuf, starts the DoA controller, logs CSV + sidecar JSON — all without manual intervention.

**Tasks:**

1. **systemd unit for bitstream + udmabuf + doa-controller.**
   - `doa-bitstream-load.service` (oneshot, runs `fpgautil`) → ordering `Before=doa-udmabuf.service`
   - `doa-udmabuf.service` (oneshot, runs `insmod udmabuf.ko size=8388608`)
   - `doa-controller.service` (main.py equivalent, `After=doa-udmabuf.service doa-bitstream-load.service`, `Wants=network-online.target`)
   - All under `/etc/systemd/system/`, enabled with `systemctl enable`.

2. **BladeRF udev rule.**
   - `/etc/udev/rules.d/88-nuand.rules` with the standard Nuand rule for accessible `bladeRF` via plugdev group.

3. **Static IP or mDNS for host discovery.**
   - KV260 default is DHCP. Options: assign a static IP via Netplan, or rely on Avahi/mDNS (Ubuntu ships it). Pick one and document.

4. **Clock sync on boot.**
   - If KV260 has no RTC, add a `ConditionPathExists=/dev/rtc0` check and fall back to an NTP pull (Ubuntu has `systemd-timesyncd`).
   - Otherwise, same `date -s` workaround as Cora, hooked into `doa-controller.service` `ExecStartPre=`.

5. **SSH deploy script.**
   - `scripts/deploy_kv260.sh` parallel to the Cora version, scp's `kv260_headless/*.py` and restarts the systemd service.

6. **Data logging parity.**
   - `DataLogger` class from Cora's `main.py` should drop in unchanged (Python stdlib). Verify CSV + sidecar JSON land under `~/doa/data/` with correct timestamps.

**Pitfalls to watch:**
- **MEDIUM — systemd ordering races.** If `doa-controller` starts before `udmabuf` is ready, first DMA fails silently. Use `ExecStartPre=/usr/bin/test -e /dev/udmabuf0` to gate.
- **MEDIUM — BladeRF enumeration delay.** USB 3.0 enumeration can take several seconds after boot. `doa-controller` should retry on `SoapyUSBError` with exponential backoff — port the Cora reconnect logic.
- **LOW — Ubuntu unattended-upgrades.** Can reboot the board mid-campaign. Disable or mask `apt-daily.timer` and `apt-daily-upgrade.timer` before long capture runs.

**Exit criteria:**
- Power cycle → 60 s later → `systemctl status doa-controller` shows active and log files are growing
- No manual SSH commands required between cold boot and data capture

---

## Phase 5 — Thesis campaign and chapter draft

**Goal:** Publishable data + a complete thesis chapter covering both platforms.

**Tasks:**

1. **Multi-angle campaign on KV260.**
   - Angles: 50°, 70°, 90°, 110°, 130° at 40 cm (also 1 m if time permits).
   - Per angle: ARM ROOTMUSIC × 60 s, FPGA ROOTMUSIC × 60 s, with filter on.
   - Set `current_label.txt` before each run (label `<N>deg` for auto-discovery in `scripts/analyze_arm_vs_fpga.py`).
   - Calibrate once at session start, do not retune mid-campaign.

2. **Analysis.**
   - Run `scripts/analyze_arm_vs_fpga.py` on the KV260 dataset.
   - Generate per-angle std-dev tables, mean-error vs true-angle plots, ARM-vs-FPGA difference histograms.
   - Verify clean-room baseline std-dev ≤ 3° (parity with Cora).

3. **Cora comparison capture (optional, if time).**
   - Re-run the same angle set on Cora's `feature/fir-backpressure` build for a side-by-side platform comparison in the thesis.
   - If we skip this, cite the existing Cora baseline data.

4. **Thesis chapter draft.**
   - Framing: "hardware-impact" primary (A), "methodology-first" fallback (B), per `memory/project_thesis_framing.md`.
   - Sections: platform comparison (Cora vs KV260), pitfall register, calibration methodology, results, discussion of FIR throughput limitation + the backpressure fix as an engineering lesson, discussion of the `/dev/mem` → UIO migration as a portability lesson.
   - FPGA resource utilization tables for both platforms (Cora Phase A numbers already in CHANGELOG 2026-04-11; collect KV260 numbers from Phase 2).

5. **Reproducibility appendix.**
   - Exact commands to rebuild bitstream from `create_project.tcl`.
   - Exact commands to deploy to a fresh KV260 (SoapySDR build, udmabuf install, systemd unit install).
   - Ubuntu 22.04 image hash + kernel version.

**Exit criteria:**
- 5 angles × 2 paths × 60 s = 10 CSVs logged, analyzed, plotted
- Chapter draft reviewed at least once by advisor
- Reproducibility appendix tested by deploying to a freshly-flashed SD card

---

## Cross-Phase Discipline

1. **Never edit `fpga/rtl/*.v` on `feature/kv260` in a way that breaks Cora.** If an RTL change is KV260-specific (unlikely — the RTL is vendor-neutral), stop and redesign. Otherwise, the change is a shared-infrastructure change and should go on main or a shared branch.

2. **Cora `feature/fir-backpressure` stays unmerged** until the thesis chapter decides platform order. The branch is the frozen reference build; merging it would lose that anchor.

3. **Do not copy-paste Cora TCL or Cora driver code without a diff review.** Every file that mentions `processing_system7_0`, `/dev/mem`, `0x4000_0000`, `0x1F000000`, `M_AXI_GP0`, `S_AXI_HP0` (without `_FPD`), or `petalinux` is suspect.

4. **Log every KV260 gotcha in real time.** The Cora pitfall register was reconstructed from memory after the fact and is incomplete. KV260 pitfalls go straight into the viability doc (`docs/specs/2026-04-22-kv260-research-and-viability.md §6`) and then into the thesis appendix.

5. **Budget: aim to hit Phase 2 exit criteria within a week, Phase 3 within two weeks.** If either slips more than 3 days past plan, stop and audit the plan — don't push harder on a wrong path. (Cora PetaLinux DMA saga was the warning.)

---

## Files That Will Be Created/Modified

| File | Phase | Action |
|---|---|---|
| `kv260_headless/test_uio.py` | 2 | new — 20-line smoke test |
| `kv260_headless/setup_kv260.sh` | 2, 3 | extend — add SoapySDR stack |
| `kv260_headless/aoa_estimation_fpga_kv260.py` | 3 | audit + fix 64-bit issues |
| `fpga/vivado_kv260/release/system.bit.bin` | 2 | new — checked in |
| `fpga/vivado_kv260/release/doa_pipeline.dtbo` | 2 | new — checked in |
| `fpga/rtl/*.v` | 3 | cherry-pick FIR backpressure commits |
| `kv260_headless/systemd/*.service` | 4 | new |
| `kv260_headless/udev/88-nuand.rules` | 4 | new |
| `scripts/deploy_kv260.sh` | 4 | new |
| `docs/CHANGELOG.md` | each phase | 1 entry per phase exit |
| `docs/specs/2026-04-22-kv260-research-and-viability.md` | ongoing | §6 pitfall updates |
| Thesis chapter (location TBD) | 5 | draft |
