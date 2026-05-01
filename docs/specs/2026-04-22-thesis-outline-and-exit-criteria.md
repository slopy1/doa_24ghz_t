# Thesis Outline and Exit Criteria After KV260 Pivot

*Date: 2026-04-22*
*Status: working thesis-planning note aligned with `docs/thesis/ch1.md`, `docs/thesis/ch2.md`, and the KV260 plan*

## Purpose

This note tightens the thesis from "project plan" into "defensible academic argument."
It does three things:

1. fixes the primary thesis framing after the KV260 pivot,
2. turns the existing draft research questions into a cleaner set of thesis claims,
3. adds phase exit criteria tied to thesis evidence rather than only engineering progress.

The current Chapter 1 and Chapter 2 drafts are usable. They do not need a full rewrite. They do need a framing pass so that KV260 is the primary platform and Cora Z7 is the validated reference platform.

---

## Recommended Thesis Framing

**Primary framing:** this is a practical embedded DoA thesis about porting and validating a two-channel SDR + FPGA DoA pipeline on KV260, then comparing ARM-only and FPGA-assisted estimation under real hardware constraints.

**What the thesis is not:** it is not mainly a "new algorithm" thesis, and it is not mainly a "full MUSIC in hardware" thesis. The novelty is in the embedded implementation, portability across platforms, and empirical comparison under fixed-point and calibration constraints.

**One-sentence thesis story:**
Port a validated DoA pipeline from a Cora Z7 reference system to KV260, preserve the DoA math and shared RTL, replace platform-specific plumbing, and measure what is gained or lost in accuracy, stability, and runtime behavior when moving from ARM-only processing to an FPGA-assisted path.

---

## Research Questions

The Chapter 1 draft already has the right shape. Keep three research questions, but frame them around the final KV260 campaign.

### RQ1

How closely can an FPGA-assisted fixed-point DoA pipeline on KV260 reproduce the angular accuracy and stability of an ARM floating-point reference path when both operate on equivalent measurement conditions?

Why this works:
- It is measurable.
- It does not promise bit-exact equality.
- It fits the current hardware reality better than a more ambitious "full in-fabric MUSIC" claim.

### RQ2

Among Phase-Difference, MUSIC, and Root-MUSIC, which estimator is most robust on the embedded SDR platform under the observed calibration error, noise, and finite-precision constraints?

Why this works:
- It matches the current Chapter 2 theory.
- It gives Chapter 5 a clear comparison table.
- It remains valid whether the strongest final dataset is KV260-only or KV260 plus Cora reference data.

### RQ3

How portable is the DoA pipeline across Zynq platforms when the signal-processing core is held constant and only the platform interface changes?

Concrete subtopics:
- `/dev/mem` + OCM on Cora vs UIO + `udmabuf` on KV260
- `BOOT.bin` deployment vs runtime `fpgautil` + overlay deployment
- SysVinit vs `systemd`
- 32-bit ARM assumptions vs aarch64 assumptions

Why this works:
- It converts the port itself into a thesis contribution instead of treating it as mere setup work.
- It matches the real engineering effort you have already done.

**Note:** the current `ch1.md` RQ3 is about cross-precision calibration transfer. That can remain as a Chapter 5 discussion question, but it is weaker as a top-level thesis RQ than platform portability. If you want only three top-level RQs, portability is the better third question.

---

## Hypotheses

These should be stated explicitly in Chapter 1 and tested in Chapter 5.

### H1

The KV260 ARM-only reference path will meet or exceed the Cora ARM baseline in short-run angle stability because the A53 platform has more CPU headroom and a less constrained software environment.

### H2

The FPGA-assisted KV260 path will remain within a small practical error margin of the ARM reference under calibrated single-source conditions, while offering a better runtime profile in at least one operational metric such as update rate or CPU load.

Recommended wording if you want a number:
- "within 3 degrees mean difference" is reasonable only if you are willing to live or die by it.
- Safer wording: "within a small practical margin suitable for single-source tracking at the tested geometry."

### H3

Root-MUSIC will remain the strongest estimator in nominal conditions, but its advantage will be reduced if calibration residuals or fixed-point effects dominate the error budget.

### H4

The signal-processing RTL can be reused across Cora and KV260 without algorithmic changes, but the platform-specific control, memory-mapping, and deployment layers materially affect reproducibility and integration effort.

---

## Contributions

The contribution list in `docs/thesis/ch1.md` is close, but it should be tightened around the KV260-primary story.

Recommended contribution set:

1. **A portable embedded DoA architecture** spanning Cora Z7 and KV260, with shared RTL and estimator math but platform-specific control and deployment layers.
2. **An empirical ARM-vs-FPGA comparison on KV260** using a controlled multi-angle campaign and reproducible logging.
3. **A documented migration from legacy embedded access patterns to Linux-safe interfaces**: `/dev/mem` to UIO, fixed OCM buffers to `udmabuf`, baked boot artifacts to runtime overlays.
4. **A reproducible experimental workflow for embedded DoA evaluation**, including calibration, capture labeling, CSV + sidecar metadata, and post-processing scripts.
5. **An engineering case study in FPGA streaming correctness**, covering FIR backpressure and the lessons learned from shared RTL validation across platforms.

This ordering puts the thesis-weight items first and keeps the backpressure work as a real contribution without letting it dominate the narrative.

---

## Recommended Chapter Structure

## Chapter 1 - Introduction

Keep most of the current draft. Update:
- KV260 should be the primary target.
- Cora should be described as the validated reference implementation.
- Move any stale Cora-only blocker language out of the main problem statement unless it still affects the final thesis evidence.
- Add the final RQs and hypotheses explicitly.

## Chapter 2 - Theoretical Background

Current draft is strong and mostly reusable.

Keep:
- ULA model
- covariance model
- Phase-Difference, MUSIC, Root-MUSIC, MVDR
- synchronization requirements
- fixed-point effects

Add only if needed:
- a short bridge paragraph at the end saying Chapter 2 motivates the metrics used later: mean error, standard deviation, outlier behavior, and runtime tradeoffs.

## Chapter 3 - System Design and Platform Architecture

Recommended sections:
- antenna geometry and 2.4 GHz signal source
- BladeRF 2.0 front end
- Cora Z7 reference platform
- KV260 target platform
- shared `doa_pipeline` RTL architecture
- calibration workflow
- control and deployment architecture

Purpose:
- explain what is shared between platforms
- explain what changes across platforms

## Chapter 4 - Implementation and Experimental Method

Recommended sections:
- ARM-only processing path
- FPGA-assisted processing path
- Cora implementation summary
- KV260 port details: UIO, `udmabuf`, `fpgautil`, overlay flow
- logging and metadata
- experiment geometry and capture protocol
- analysis metrics

Purpose:
- make the experimental method reproducible
- separate design from evaluation

## Chapter 5 - Results and Discussion

Recommended sections:
- KV260 ARM baseline validation
- KV260 FPGA bring-up validation
- ARM vs FPGA comparison on KV260
- estimator comparison
- calibration transfer observations
- optional Cora vs KV260 reference comparison
- engineering lessons from portability and FPGA integration

This chapter should answer the RQs directly.

## Chapter 6 - Conclusion and Future Work

Keep focused:
- answer each RQ in one short subsection
- summarize main findings
- state limitations
- list scoped future work

Future work should include:
- full in-fabric eigendecomposition
- multi-source scenarios
- wider-angle or range-dependent campaigns
- more formal calibration compensation

---

## Phase Exit Criteria Tied to Thesis Evidence

The existing KV260 plan has good engineering milestones. The thesis needs a second layer: what artifact each phase must produce for the final document.

## Phase 2 - Runtime bitstream load and UIO validation

Engineering exit:
- `.bit.bin` and `.dtbo` load successfully on KV260
- register smoke test passes

Thesis artifact:
- one figure showing the KV260 deployment stack
- one table listing platform differences between Cora and KV260
- one short subsection describing why UIO and `udmabuf` replaced `/dev/mem` and OCM

## Phase 3 - FPGA-accelerated DoA on KV260

Engineering exit:
- FPGA path produces plausible angles
- calibration path works
- no blocking register or DMA faults remain

Thesis artifact:
- one validation table comparing ARM and FPGA outputs on a short smoke-test run
- one paragraph stating whether the FPGA path is accurate enough to proceed to the full campaign

## Phase 4 - Boot-time integration and service packaging

Engineering exit:
- reproducible startup with minimal manual intervention

Thesis artifact:
- only a short reproducibility subsection

Important:
- do not let this phase expand. It supports the thesis, but it is not the thesis.

## Phase 5 - Multi-angle campaign and writing

Engineering exit:
- 5 angles x 2 paths x 60 s complete on KV260
- plots and summary tables generated

Thesis artifact:
- this is the main results chapter
- every result should map back to one RQ or hypothesis

---

## Minimum Viable Thesis

If schedule pressure hits, this is the minimum complete thesis that still works academically:

1. KV260 ARM-only path validated.
2. KV260 FPGA-assisted path validated.
3. Multi-angle campaign completed on KV260 for ARM and FPGA.
4. One estimator comparison table across the tested algorithms.
5. Cora retained as reference architecture and prior validated baseline, even if not fully re-run in the final campaign.
6. Reproducibility appendix with commands, commit hashes, calibration notes, and hardware setup.

If you hit these six items, the thesis is coherent.

---

## Descope First If Time Gets Tight

These are useful but not essential to the thesis argument:

- boot-time polish beyond what is needed for reproducibility
- `systemd` quality-of-life work that does not affect experiments
- display LABEL button
- enclosure finishing work
- 1 m follow-on campaign
- full Phase C in-fabric MUSIC / EVD
- extensive GNU Radio packaging on KV260 if the headless path is already sufficient

This is where time should be cut first, not from the core measurement campaign.

---

## Quantitative Success Definition

Before the campaign, define a single success table and use it everywhere.

Recommended metrics:
- mean angle estimate per run
- absolute error vs labeled angle
- standard deviation per run
- outlier rate beyond a chosen threshold
- update rate or effective sample rate
- CPU utilization for ARM vs FPGA path, if easy to capture

Recommended campaign minimum:
- 5 angles: 50, 70, 90, 110, 130 degrees
- 60 seconds per run
- one calibration at session start
- labels embedded in filenames and sidecar JSON
- exact commit hash and hardware state recorded per session

If possible, define one acceptance line now:
- "A valid campaign run is one with correct metadata, stable RF setup, no mid-run recalibration, and complete CSV + sidecar output."

---

## What To Change In The Current Chapter Drafts

## `docs/thesis/ch1.md`

Change:
- primary platform description from Cora-centered to KV260-centered
- RQ3 from calibration-transfer discussion to platform-portability question, unless you strongly prefer the calibration angle
- contributions to emphasize portability and KV260 validation

Revisit:
- the limitation paragraph about the unresolved Cora block-design issue

Rule:
- if that bug is no longer central to the final evidence set, move it to Chapter 5 as a historical engineering issue rather than leaving it in Chapter 1 as a thesis-defining limitation

## `docs/thesis/ch2.md`

Likely keep as-is.

Minor change:
- at the end of the chapter, add one short paragraph mapping the theory to the evaluation metrics used later

---

## Recommended Writing Order

Do not write the thesis in chapter order.

Recommended order:

1. lock Chapter 1 RQs, hypotheses, and contributions
2. freeze Chapter 3 platform diagrams and architecture text
3. freeze Chapter 4 experimental method before the full campaign
4. run the campaign
5. write Chapter 5 directly from plots and tables
6. finish Chapter 6 last

This keeps the writing aligned with real evidence instead of speculative wording.

---

## Bottom Line

The current phased plan is good enough for a thesis if it is interpreted as a **validation and comparison study**, not as an open-ended platform engineering project.

The clean version of the thesis claim is:
- Cora proves the pipeline concept.
- KV260 becomes the main evaluation platform.
- The thesis contribution is the validated migration, the ARM-vs-FPGA comparison, and the evidence from the multi-angle campaign.

That is a defensible master's thesis scope.
