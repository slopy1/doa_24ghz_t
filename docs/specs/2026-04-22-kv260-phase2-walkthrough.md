# KV260 Phase 2 — Bitstream Build & Runtime Load Walkthrough

*Date: 2026-04-22*
*Scope: Start-to-first-UIO-register-read. Uses the Linux build VM (`vmau@192.168.122.93`) — no Vivado on Windows required.*

> **2026-04-22 evening status: BLOCKED at Step 10 (register smoke test).** Bitstream builds, deploys, and UIO enumerates correctly — but AXI-Lite register access to `doa_pipeline` is broken. Only offset `0x30` (COEFF_ADDR) responds; every other register silently reads 0, and `axi_dma` access hangs the PS. See the CHANGELOG entry for 2026-04-22 ("BLOCKED: KV260 Phase 2 …") and memory note `project_kv260_bitstream_broken.md` for the full debug history and hypotheses. The walkthrough steps below are otherwise correct.

---

## Prerequisites

Before starting, confirm:

- [ ] Build VM `vmau@192.168.122.93` reachable (`ssh vmau@192.168.122.93` returns a prompt)
- [ ] VM has Vivado 2025.2 installed. On this VM it's at `/home/vmau/tools/2025.2/Vivado/` (Unified installer layout — Vitis sits beside it at `/home/vmau/tools/2025.2/Vitis/`). Source with `source /home/vmau/tools/2025.2/Vivado/settings64.sh`.
- [ ] VM has `dtc` and `bootgen` on PATH (both ship inside Vitis 2025.2 — `/home/vmau/tools/2025.2/Vitis/bin/{bootgen,dtc}`. Sourcing Vivado's `settings64.sh` exports them.)
- [ ] KV260 board files installed in Vivado (check `xilinx.com:kv260_som:part0:1.4` is listed in **Tools → Settings → Boards**)
- [ ] KV260 running Ubuntu 22.04, reachable on the LAN (`ssh ubuntu@<kv260-ip>` works, default hostname `kria`)
- [ ] Phase 1 state still valid — `aoa_estimation_headless.py` runs on the KV260 and produces ARM angles

If any are missing, stop and fix before continuing.

---

## Step 0 — Get KV260 source onto the VM

The `feature/kv260` branch lives on the host. The VM needs the same tree.

**Option A: rsync the worktree (recommended):**

```bash
# From the host machine (not the VM):
rsync -av --exclude='.git' --exclude='project/' \
    /home/mau/doa_24ghz_thesis-kv260/ \
    vmau@192.168.122.93:~/kv260_doa_hw/
```

**Option B: clone the branch fresh on the VM:**

```bash
ssh vmau@192.168.122.93
cd ~
git clone -b feature/kv260 <origin-url-or-local-bundle> kv260_doa_hw
```

Option A is simpler because you already have the worktree. The `project/` exclude keeps stale Vivado project dirs from being pushed.

**Verify on VM:**

```bash
ssh vmau@192.168.122.93
ls ~/kv260_doa_hw/fpga/vivado_kv260/
#   → create_project.tcl  doa_pipeline.dts
ls ~/kv260_doa_hw/fpga/rtl/
#   → channel_splitter.v  fir_filter_sc16.v  phase_rotate_sc16.v
#     autocorr_acc.v  xcorr_acc.v  doa_pipeline.v
```

---

## Step 1 — Start Vivado on the VM with GUI forwarded

Vivado 2025.2 needs GUI for the address editor + bitstream progress. Two options:

**Option A: X11 forwarding over SSH (simpler, decent latency on LAN):**

```bash
# From host machine:
ssh -X vmau@192.168.122.93
source /home/vmau/tools/2025.2/Vivado/settings64.sh
cd ~/kv260_doa_hw/fpga/vivado_kv260/
vivado &
```

If X11 refuses with "untrusted connection," try `ssh -Y` instead (trusted forwarding — OK on a LAN).

**Option B: VNC into the VM (smoother if the VM has a desktop):**

Set up `tightvncserver` or `x11vnc` on the VM once, then point a VNC client at `192.168.122.93:5901`. Better for long synth runs where you want to walk away.

Use Option A for this first run — setup takes <1 min.

---

## Step 2 — Create the block design (run the TCL)

In the Vivado Tcl Console (bottom pane), type:

```tcl
cd /home/vmau/kv260_doa_hw/fpga/vivado_kv260
source create_project.tcl
```

Watch for:
- ✅ `create_project kv260_doa_hw ...` — project created
- ✅ `apply_bd_automation` success — KV260 board preset applied (DDR4, QSPI, clocks configured automatically)
- ✅ `create_bd_cell -type module -reference doa_pipeline doa_pipeline_0` — RTL instantiated as BD cell
- ⚠️ `validate_bd_design` — this may print "Critical Warning: Missing address segments" because the TCL leaves address assignment as a manual step (see Step 3)

If validate_bd_design fails outright, don't panic — it's expected. Continue to Step 3.

---

## Step 3 — Assign addresses (manual, one-time)

The TCL has the address assignment commented out. Open the **Address Editor** tab (bottom pane) and:

1. Right-click in the empty area → **Assign All**. This gives each AXI slave a default address.
2. Verify the assignments match the DTS:

    | Slave | Base | Range |
    |---|---|---|
    | `doa_pipeline_0/s_axi/reg0` | `0x80000000` | 64K |
    | `axi_dma_0/S_AXI_LITE/Reg` | `0x80400000` | 64K |

   If Vivado picked different addresses, click each and manually set the base to match (double-click the Offset Address field and type the new value). **The DTS and driver assume these exact addresses — do not skip this.**

3. In the Tcl Console, lock the assignments:

    ```tcl
    set_property offset 0x80000000 [get_bd_addr_segs {doa_pipeline_0/s_axi/reg0}]
    set_property range  64K        [get_bd_addr_segs {doa_pipeline_0/s_axi/reg0}]
    set_property offset 0x80400000 [get_bd_addr_segs {axi_dma_0/S_AXI_LITE/Reg}]
    set_property range  64K        [get_bd_addr_segs {axi_dma_0/S_AXI_LITE/Reg}]
    ```

4. Re-validate:

    ```tcl
    validate_bd_design
    save_bd_design
    ```

    Expected: `validate_bd_design: Validation successful`. If you still see errors, read them — most common is a missing clock/reset connection, which means the TCL needs a fix and should be reported back before continuing.

---

## Step 4 — Synthesize, implement, generate bitstream

In Vivado GUI (Flow Navigator on the left):

1. **Run Synthesis** — ~5-10 min on the VM. Check the resource estimate when it finishes:
   - LUT: expect single digits % (KV260 has ~117k LUTs; `doa_pipeline` uses ~7.8k)
   - DSP48E2: ~17 (same count as Cora; KV260 has 1248 total — trivially under budget)
   - If utilization is way higher than this, something's wrong — stop and investigate.

2. **Run Implementation** — ~10-20 min. Check **Design Runs → impl_1 → Timing Report**:
   - WNS (worst negative slack) should be positive by ≥ +2 ns at the 50 MHz PL clock.
   - If timing fails, open Timing Report and inspect the failing path. 50 MHz on KV260 should have massive margin — a fail usually means a clock/reset constraint is missing.

3. **Generate Bitstream** — ~3-5 min. On success, the bitstream lands at:

    ```
    ~/kv260_doa_hw/fpga/vivado_kv260/project/kv260_doa_hw.runs/impl_1/kv260_doa_wrapper.bit
    ```

   Leave Vivado open while you do Step 5 — you may need it again.

---

## Step 5 — Convert `.bit` to `.bit.bin` with bootgen

KV260's `fpgautil` rejects raw `.bit` files. You need the stripped `.bit.bin` format.

**Create a BIF file:**

```bash
# On the VM, terminal outside Vivado:
cd ~/kv260_doa_hw/fpga/vivado_kv260/
cat > system.bif << 'EOF'
all:
{
    [destination_device = pl] project/kv260_doa_hw.runs/impl_1/kv260_doa_wrapper.bit
}
EOF
```

**Run bootgen:**

```bash
source /home/vmau/tools/2025.2/Vivado/settings64.sh   # if not already sourced
bootgen -arch zynqmp -image system.bif -w -o doa_pipeline.bit.bin -process_bitstream bin
```

Expected output: a `doa_pipeline.bit.bin` file, roughly **half** the size of the raw `.bit`. If sizes match, bootgen didn't strip — re-check the `-process_bitstream bin` flag.

---

## Step 6 — Compile the device tree overlay

```bash
cd ~/kv260_doa_hw/fpga/vivado_kv260/
dtc -@ -I dts -O dtb -o doa_pipeline.dtbo doa_pipeline.dts
```

The `-@` flag is critical — it preserves symbol references like `&amba_pl`. Without it, the overlay silently fails to apply.

Verify:

```bash
file doa_pipeline.dtbo
# → doa_pipeline.dtbo: Device Tree Blob version 17, size=..., ...
fdtdump doa_pipeline.dtbo | head -20
# Should show the fragment@0 block with doa_pipeline@80000000 and axi_dma@80400000
```

---

## Step 7 — Copy artifacts to KV260

```bash
# From the VM, to KV260:
KV260_IP=<kv260-ip>   # e.g., 192.168.1.200
scp doa_pipeline.bit.bin doa_pipeline.dtbo \
    ubuntu@$KV260_IP:~/doa/bitstream/
```

If the target dir doesn't exist yet:

```bash
ssh ubuntu@$KV260_IP 'mkdir -p ~/doa/bitstream'
```

---

## Step 8 — Load the bitstream at runtime

```bash
ssh ubuntu@$KV260_IP
cd ~/doa/bitstream
sudo fpgautil -b doa_pipeline.bit.bin -o doa_pipeline.dtbo -f Full -n Full
```

Expected output:

```
Time taken to load BIN is ... Milliseconds.
BIN FILE loaded through FPGA manager successfully
Loading dtbo: /configfs/device-tree/overlays/...
```

Verify the PL is programmed and UIO nodes appeared:

```bash
cat /sys/class/fpga_manager/fpga0/state
# → operating

ls /dev/uio*
# → /dev/uio0  /dev/uio1   (uio0 = doa_pipeline, uio1 = axi_dma)
```

If `/dev/uio*` is missing, the overlay didn't apply. Check `dmesg | tail -30` for errors — most common is address mismatch between the BD and the DTS (Step 3 was skipped or done wrong).

---

## Step 9 — Smoke-test UIO register access

The `kv260_headless/aoa_estimation_fpga_kv260.py` has a `--probe` mode (per `setup_kv260.sh` line 70). Run it:

```bash
cd ~/doa/   # wherever the script lives on KV260
sudo python3 aoa_estimation_fpga_kv260.py --probe
```

Expected output: register map dump, and successful write→read on `COS_CAL` with sign extension. If that script doesn't exist or `--probe` isn't implemented, fall back to a hand-rolled test:

```python
#!/usr/bin/env python3
# test_uio.py — KV260 UIO smoke test
import mmap, struct, os

uio = os.open('/dev/uio0', os.O_RDWR)
regs = mmap.mmap(uio, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)

# Phase A register map: COS_CAL at 0x28
regs[0x28:0x2C] = struct.pack('<I', 0x1234)
val = struct.unpack('<I', regs[0x28:0x2C])[0]
assert val == 0x1234, f"COS_CAL round-trip failed: wrote 0x1234 got {val:#010x}"

# Sign extension test
regs[0x28:0x2C] = struct.pack('<I', 0x8000)
val = struct.unpack('<I', regs[0x28:0x2C])[0]
assert val == 0xFFFF8000, f"COS_CAL sign-ext failed: got {val:#010x}"

print("PASS: UIO register access works, sign extension correct")
regs.close()
os.close(uio)
```

```bash
sudo python3 test_uio.py
# → PASS: UIO register access works, sign extension correct
```

If this passes, Phase 2 is done.

---

## Step 10 — Commit artifacts and update status

On the host (not the VM):

```bash
cd /home/mau/doa_24ghz_thesis-kv260
mkdir -p fpga/vivado_kv260/release
# pull the artifacts back from the VM:
scp vmau@192.168.122.93:~/kv260_doa_hw/fpga/vivado_kv260/doa_pipeline.bit.bin \
    vmau@192.168.122.93:~/kv260_doa_hw/fpga/vivado_kv260/doa_pipeline.dtbo \
    fpga/vivado_kv260/release/

git add fpga/vivado_kv260/release/doa_pipeline.bit.bin \
        fpga/vivado_kv260/release/doa_pipeline.dtbo
git commit -m "KV260 Phase 2: first bitstream + DT overlay (UIO smoke test passes)"
```

Also add a CHANGELOG entry marking Phase 2 complete and calling out any gotchas encountered.

---

## Common Pitfalls — Debug Quick Reference

| Symptom | Likely Cause | Fix |
|---|---|---|
| `validate_bd_design` fails with "missing address segments" | Address Editor not assigned | Step 3 |
| Bitstream generation fails with timing error at 50 MHz | Clock/reset not wired to all cells | Open BD, check clock/reset nets on every AXI-capable cell |
| `fpgautil` says "Invalid bitstream format" | Used raw `.bit`, not `.bit.bin` | Step 5 (re-run bootgen) |
| `fpgautil` succeeds but `/dev/uio*` never appears | DTS compiled without `-@` flag | Step 6 (recompile with `-@`) |
| `/dev/uio0` exists but register reads return 0 | BD address ≠ DTS reg address | Verify Step 3 base matches DTS Step 6 |
| Read returns wrong bits but some activity | Byte-endianness, wrong offset, or 64-bit truncation | Check `struct.unpack` format; check DMA addressing width |
| `sudo` says "permission denied" on `/dev/uio0` | Default is root-only | Add udev rule (deferred to Phase 4) or just `sudo` for now |
| `fpgautil` fails with "Resource busy" | Previous overlay still loaded | `sudo xmutil unloadapp` or reboot |
| `smartconnect` rejects NUM_SI=2 | IP version mismatch | Open IP catalog, update `smartconnect` to latest minor version |
| Vivado address editor shows `[Infeasible]` | AXI master does not reach the slave | Check interconnect NUM_MI and intf net connections |
| KV260 HDMI/DP output blank after `fpgautil` | Overlay accidentally disturbed PS display clocks | Don't touch PS-side DT nodes — overlay should only add to `&amba_pl` |

---

## Time Budget

- Steps 0-3 (setup + BD + address): **30-60 min first time**, 5 min every subsequent rebuild
- Step 4 (synth + impl + bitstream): **~30-45 min** on the VM unattended
- Steps 5-9 (post-build + deploy + smoke test): **~15 min**

Total: **~90 min for a successful first pass**. Budget 4 hours for the first run to absorb debugging.

---

## What This Does NOT Cover (comes in Phase 3)

- SoapyBladeRF stack build on Ubuntu aarch64
- FIR backpressure RTL cherry-pick from `feature/fir-backpressure`
- Full `aoa_estimation_fpga_kv260.py` end-to-end against the nRF5340 signal
- Calibration convergence
- DMA with real udmabuf-backed descriptors

Phase 2 exits when UIO register access is proven. The driver's DMA path is Phase 3.
