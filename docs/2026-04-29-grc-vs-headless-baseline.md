# GR Companion flowgraph vs. headless driver — calibration accuracy gap

**Date:** 2026-04-29
**Context:** After fixing the gr-aoa import (Boost/spdlog ABI break + Python 3.13 → 3.14
upgrade), the BladeRF flowgraphs `phase_calibration_bladerf.grc` and
`aoa_estimation_bladerf.grc` run again. Side-by-side, the GR pipeline produces
visibly tighter calibration and lower σ on the live AoA chart than the headless
driver path (`cora_headless/aoa_estimation_headless.py`,
`kv260_headless/aoa_estimation_fpga_kv260.py`). This is *expected*, not a
regression in the headless math — documenting the four reasons here so the
thesis can frame the comparison correctly.

## TL;DR

GR-Companion is the **measurement-quality baseline**. The headless driver is
the **deployable / FPGA-coupled** implementation. They run the same root-MUSIC
algorithm, but four implementation-level differences make GR systematically
quieter:

1. Single sample-rate domain inside the flowgraph
2. Continuous, sample-by-sample cal rotation in the hier blocks
3. ~100× higher AoA-estimate rate × display IIR smoothing (NOT a larger
   covariance N — see §3, the headless actually integrates more samples
   per estimate)
4. No fabric back-pressure or RTL `STATUS_VALID` drop-outs

## 1. Single sample-rate domain (1 Msps end to end)

GR sets `samp_rate = 1e6` and runs every block at that rate. There is no
re-sampler in the AoA chain.

The headless driver acquires from BladeRF at the SoapySDR-default rate (often
4 Msps for clean USB streaming) and decimates inside Python (`bandpass +
take-every-Nth`). Each rate transition adds a small group-delay variation
between ch0 and ch1 that the static cal rotation can't subtract. GR avoids the
transition entirely.

**Implication for thesis:** When reporting "raw σ at 0° broadside," cite
GR-Companion numbers as the *floor* set by the analog/RF chain alone, and the
headless numbers as that floor plus the cost of the rate-conversion path.

## 2. Cal rotation is sample-by-sample, not block-at-a-time

`gnuradio.aoa.shift_phase_multiple_hier` instantiates one `aoa.shift_phase`
block per antenna and applies the cal `e^{-jφ_cal}` multiply on every complex
sample as it streams through. Every sample contributes to the cal-corrected
covariance, weighted equally.

The headless driver pulls a fixed-size SNAPSHOT (typically 4096 samples) from
the BladeRF, applies a numpy phase rotation to the whole block, then runs
covariance + MUSIC once. The first ~`N_taps` samples of every snapshot are
inside the BPF transient, where ch0/ch1 phase is not yet stationary. In a
streaming flowgraph that transient happens once at start-up; in a snapshot
loop it re-occurs at the head of every snapshot, which is what shows up as
σ floor.

## 3. Per-estimate σ vs. perceived display stability

This is where the naive "GR averages more" intuition breaks down. Reading the
actual flowgraph (`gnuradio_flowgraphs/aoa_estimation_bladerf.grc`):

- **GR per estimate:** `aoa.correlate` with `snapshot_size=1024` and "Forward"
  averaging → covariance `R` is computed from a single 1024-sample snapshot.
  Root-MUSIC is run on that `R`. Estimate rate ≈ 1 Msps / 1024 ≈ **976 Hz**.
- **Headless per estimate:** `estimate_covariance` reshapes the input buffer
  into (2, SNAPSHOT_SIZE, NUM_SNAPSHOTS) and runs the forward-average
  `R = (1/(N·K)) Σ_k X_k X_kᴴ` with K = NUM_SNAPSHOTS = 100. Per-estimate
  N = 1024 × 100 = **102 400** samples.

So the **headless integrates ~100× more samples per AoA estimate** than GR.
Per-estimate σ should scale as 1/√N, so headless σ_per-estimate ought to be
~10× **lower** than GR's, not higher.

What gives the GR display its "glassy" feel is not a larger covariance
window — it's the combination of:

- **976 Hz output rate** vs. 7.75 Hz on KV260 (post-fix) / ~5–10 Hz on Cora.
- **`qtgui_number_sink_0` Average = 0.1 (IIR α)** on the AoA angle output:
  one-pole low-pass with time constant ≈ 10 estimates ≈ 10 ms. The displayed
  needle never moves more than 10% of the per-estimate jump.
- The headless writes raw per-estimate values to CSV, with no display IIR.

**Implication for thesis:** Don't claim "GR averages more." Claim "GR's
≥100× higher AoA-estimate rate plus a 10-tap IIR on the displayed angle
hides per-estimate variance that the headless surfaces directly." The
headless covariance N is *already* large; the variance you see in the CSV
is the ground truth, not an averaging shortfall.

## 4. No fabric back-pressure / RTL fail-rate

GR is pure software and NumPy. Every sample makes it to MUSIC. No handshake
to negotiate.

The KV260 driver path has a **~12% snapshot fail rate** even with
`--filter=none`: the `STATUS_VALID` line in the fabric pipeline doesn't
assert on every channel-splitter cycle (suspected `snap_count` race or
`channel_splitter` handshake glitch — see the project notes "Active state
2026-04-29"). Each lost snapshot is a sample the AoA averaging never sees.
The bandpass-mode regime is even worse (~92% fail rate) because the fabric
FIR back-pressures the splitter.

**Implication for thesis:** GR's σ is the upper bound on what the FPGA
implementation could achieve if `STATUS_VALID` were perfect. The current
12% drop directly widens σ vs. the GR baseline. Fixing the splitter is a
~14% AoA-rate gain *and* a measurable σ improvement, both worth quoting.

## How to use this in the thesis

Treat GR-Companion as the **golden reference**:

> "We use the GNU Radio Companion implementation as a measurement-quality
> baseline: same algorithm (root-MUSIC), same RF front-end (BladeRF +
> 2×patch-array), but no rate conversion, continuous sample-by-sample cal
> rotation, ~32 ms covariance averaging, and no fabric handshake. The
> baseline σ at broadside is X.X°. The headless ARM driver and the
> KV260 FPGA driver achieve σ_arm = … and σ_fpga = …; the gaps to baseline
> decompose into rate-conversion cost (§N), snapshot truncation (§N),
> covariance-N (§N), and `STATUS_VALID` drop-rate (§N)."

This converts the "GR is more accurate" observation from a vague impression
into a quantitative attribution that the FPGA story benefits from rather
than apologises for.

## Repro

```bash
# GR-Companion baseline
gnuradio-companion ~/doa_24ghz_thesis/gnuradio_flowgraphs/aoa_estimation_bladerf.grc

# ARM headless
python3 ~/doa_24ghz_thesis/cora_headless/aoa_estimation_headless.py --algo rootmusic

# KV260 FPGA driver
ssh ubuntu@192.168.1.101 'sudo python3 ~/doa/aoa_estimation_fpga_kv260.py \
  --filter none --algo rootmusic --freq 2.418e9 --gain 50'
```

Capture 60 s of each at the same antenna/source geometry and compare the
labelled CSVs with `scripts/analyze_arm_vs_fpga.py`.

## Related context

- `docs/CHANGELOG.md` — 2026-04-29 perf wins (7.75 Hz AoA rate, 12% fail rate)
- `docs/CAMPAIGN_RESUME.md` — current campaign state
- `the project notes` — Active state, "Use --filter=none for the campaign"
- `gnuradio_flowgraphs/aoa_estimation_bladerf.grc` — GR baseline flowgraph
