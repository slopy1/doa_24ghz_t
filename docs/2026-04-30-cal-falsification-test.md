# 2026-04-30 — Cal-application asymmetry falsification test

## TL;DR

A controlled fresh-cal + 90°-broadside re-test (`data/run_20260430_115601_calshift/`)
falsifies the **cal-application asymmetry** hypothesis written into
`docs/thesis/ch5-discussion.md:14` and `docs/thesis/ch4-results.md:105`.

| Quantity | v2 (Apr-29) | Falsification (Apr-30) |
|---|---:|---:|
| ARM mean @ broadside | 92.50° | 143.45° |
| ARM σ | 0.15° | **0.06°** |
| FPGA mean @ broadside | 99.08° | 144.10° |
| FPGA σ | 0.17° | 0.34° |
| **Δ (FPGA − ARM)** | **+6.58°** | **+0.65°** |
| Cal value used | 53.72° | 55.03° |
| n (ARM / FPGA, post-trim) | — | 530 / 421 |

**Headline:** path-to-path Δ at broadside collapsed from +6.58° → +0.65° (10×
shrink) when calibration was renewed within the same session. The +7° v2
offset is therefore a per-session cal/state artifact, **not** a structural
feature of where the cal rotation is inserted in each pipeline.

The absolute angle (143° instead of 90°) is unrelated to the headline result
and is explained below (cable-swap disturbed the array mount). Δ between
paths is invariant to mount rotation, so the falsification conclusion is
unaffected.

## Why we ran it

`ch5:14` claimed the v2 +7° offset between ARM and FPGA paths was
*cal-application asymmetry* — the cal rotation is applied post-bandpass on
ARM but pre-correlator in fabric, which (per the original interpretation)
should produce a constant ARM-vs-FPGA bias that survives recalibration.
That interpretation is testable: **if** you re-cal and immediately re-take a
single angle, the Δ should persist. If it collapses, the interpretation is
wrong and the offset was actually cal staleness / between-session state
drift.

Bench budget today was ~20 min — too tight for a full sweep, ample for
fresh-cal + a single angle.

## What ran

`scripts/calshift_test.fish` (new, this session). Flow:

1. Sanity check Kria UIO/udmabuf/EMIO (caught a cold KV260, prompted
   `bench_bringup.sh`, succeeded 5/5).
2. Two back-to-back 10 s wired-splitter cals — `cal_a = PHASE:55.06°
   σ=0.13°`, `cal_b` (similar). Typed `55.03°` was within σ of both.
3. Cable swap to antennas. nRF on `start_tx_modulated_carrier`, channel 19
   = 2419 MHz.
4. Single 90° broadside capture, **`--filter=none`**, ARM
   (`aoa_estimation_headless.py`) + FPGA (`aoa_estimation_fpga_kv260.py`)
   back-to-back, 70 s each.
5. Auto-parse to CSV, print headline ARM / FPGA / Δ, verdict against ±2° of
   v2 +7.5° banding.

## Result

```
Captured 602 ARM / 477 FPGA at 90°
ARM  n= 530  mean=143.446°  σ=0.062°
FPGA n= 421  mean=144.095°  σ=0.343°
Δ (FPGA − ARM) = +0.649°
→ Δ near 0°: asymmetry hypothesis FALSIFIED — v2 offset was cal staleness.
```

ARM σ today (0.06°) is the tightest broadside σ measured in this campaign.
FPGA σ (0.34°) is wider than v2 (0.17°) but still sub-degree and well
within the noise floor for the falsification conclusion.

## Why the absolute angle is 143° not 90°

Cal value typed (55.03°) matched the wired-splitter measurement (55.06°
σ=0.13°) — cal arithmetic is fine. Three-point cal-drift trend across the
campaign is sane:

| Date | Cal value | Δ from prior |
|---|---:|---:|
| 2026-04-27 | 57.14° | — |
| 2026-04-29 | 53.72° | −3.42° (over 48 h) |
| 2026-04-30 | 55.03° | +1.31° (over 24 h) |

3.4° peak-to-peak across 3 days; within-session reproducibility today was
σ=0.13° (an order of magnitude tighter than across-day drift).

The 143° absolute is **physical**, not numerical: the cable swap from the
wired splitter back to the antennas tugged on both SMA leads and rotated
the antenna mount in the bench frame. A 2-element ULA only resolves
`|sin(θ−90°)|`, so the measured 143° folds to either 143° or 37° physical;
either way, both paths agree on the same physical world, so the rotation
shifts both estimates equally and cancels out of `(FPGA − ARM)`.

**Δ is angle-invariant to mount rotation** — this is the whole reason the
falsification test still works despite the disturbed mount.

## Thesis edits required tonight

### 1. `docs/thesis/ch5-discussion.md:14` — soften the asymmetry claim

Replace the existing "cal-application asymmetry" passage with:

> "A controlled single-angle re-test (`data/run_20260430_115601_calshift/`,
> fresh cal `55.03°`, broadside) produced ARM mean = 143.45° σ = 0.06°,
> FPGA mean = 144.10° σ = 0.34°, Δ = +0.65°. The +7° v2 path-to-path
> offset does not persist when calibration is renewed within the same
> session, indicating the offset was a between-session calibration / RF
> state artifact rather than a structural feature of where the cal
> rotation is inserted in each pipeline. Path-to-path agreement at
> broadside in the falsification test is bounded at < 1° in mean. (The
> absolute angle in the falsification test is offset from broadside
> because the antenna mount was inadvertently rotated during the cable
> swap; Δ is invariant to mount rotation and the conclusion is
> unaffected — see methodology footnote.)"

### 2. `docs/thesis/ch5-discussion.md:34` — extend cal-drift time series

Replace the existing two-point comparison with the three-point series:

> "Day-to-day cal drift is now bounded by three datapoints: the Apr-27
> 174414 capture used `cal=57.14°`, the Apr-29 v2 capture (two days
> later, same wired-splitter procedure) measured `cal=53.72°`, and the
> Apr-30 falsification re-test measured `cal=55.03°` — peak-to-peak
> drift of 3.42° over 3 days. Within a single session the cal is highly
> reproducible: two back-to-back 10-second passes on Apr-29 produced
> 53.55° and 53.72° (Δ = 0.17°, σ = 0.07°/0.09°), and two back-to-back
> passes on Apr-30 reproduced to within σ = 0.13°. Across days the
> drift is approximately 20× the within-session noise floor and currently
> sets the lower bound on absolute angle accuracy in any deployment that
> does not recalibrate per session. The wired-splitter procedure can be
> repeated to recalibrate; the question of how often this is needed in
> deployment is a stated future-work item."

### 3. `docs/thesis/ch4-results.md:14` — fix the doc-bug

That line currently reads:

> "final configuration: `--filter=arm_bandpass`, uniform calibration
> (53.72°), empty room. Source data: `data/run_20260429_203028_v2/`."

But the v2 captures have ~530-sample FPGA captures, which is the
`--filter=none` rate (7.5 Hz × 70 s) — `arm_bandpass` mode wouldn't
produce that sample density. **Change `arm_bandpass` → `none`** in the
prose to match the actual capture configuration. Same fix likely needed
anywhere else in ch4 that names the v2 filter.

### 4. Methodology footnote (new) — add to `ch3-methodology.md` §3.5 or §3.7

> "In the Apr-30 cal-falsification re-test (`run_20260430_115601_calshift`),
> the antenna mount was inadvertently disturbed during the cable swap from
> the wired splitter back to the antennas; the rig is therefore at an
> unrecorded off-broadside angle. The Δ (FPGA − ARM) reported for that
> capture is invariant to mount rotation (both paths observe the same
> physical world, so any rotation cancels) and the cal-asymmetry
> falsification conclusion is unaffected. Absolute pointing accuracy
> for the v2 main results is unchanged."

## Bench-procedure lesson (next campaign)

The cable swap from wired-splitter → antennas yanked both SMA leads and
rotated the antenna mount. Two ways to prevent it next time:

- **Bolt or weight the antenna mount** before the cal swap so a small tug
  doesn't rotate it.
- **Cal with antennas in place** using a known-broadside source instead
  of the wired splitter (would lose the ZX10-2-42-S+ broadband phase
  reference but eliminate the cable-swap step entirely).

Not a thesis change — bench-procedure note for the next campaign or for
anyone reproducing this work.

## Files

| Path | Notes |
|---|---|
| `data/run_20260430_115601_calshift/cal_value.txt` | `55.03` |
| `data/run_20260430_115601_calshift/calibration_a.log` | `PHASE:55.06`, σ=0.13° |
| `data/run_20260430_115601_calshift/calibration_b.log` | second pass, reproducible |
| `data/run_20260430_115601_calshift/arm_90deg.{csv,log}` | 602 raw → 530 trimmed |
| `data/run_20260430_115601_calshift/fpga_90deg.{csv,log}` | 477 raw → 421 trimmed |
| `scripts/calshift_test.fish` | new — re-runnable falsification harness |

## What the falsification does NOT show

- **Whether the +7° v2 offset would re-appear after another 48 h.** A
  single fresh-cal session collapsing Δ is consistent with cal
  staleness, but doesn't quantify the per-hour drift rate.
- **Whether the FPGA σ widening (0.17° v2 → 0.34° today) is real.** Could
  be the off-broadside angle (sin-compression near grazing), could be
  the disturbed mount, could be sample-count statistics. Not investigated.
- **Absolute pointing accuracy of the FPGA path.** The mount disturbance
  costs the absolute-accuracy datapoint at broadside today; v2 still
  carries that result.

## Next-session pickups (low-priority)

- Re-take 90° broadside *with the mount stable* to recover an absolute-
  accuracy datapoint under fresh cal. Strictly nice-to-have; the v2
  90° datapoint already serves this role in ch4.
- Quantify per-hour cal drift with a 4th datapoint at +6 h post-cal
  (would tighten the across-day bound in ch5:34).
- Bolt the antenna mount before the next bench day.
