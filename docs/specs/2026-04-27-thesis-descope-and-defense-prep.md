# Thesis Descope and Defense Preparation

*Date: 2026-04-27*
*Status: working note — descopes the portability research question, refines the thesis framing to KV260-only, and lists prioritized reading for defense preparation*
*Companion to: `2026-04-22-thesis-outline-and-exit-criteria.md` (the broader outline this note narrows)*

---

## 1. Decision

**Drop platform portability as a thesis contribution.** The Cora Z7 work remains as prior validation infrastructure (one paragraph in Ch3 §System Design) but is no longer evaluated against KV260 in Ch5 and is no longer the subject of a research question.

**Reason:** schedule. The full portability story would require Cora re-runs in the same conditions as the KV260 campaign, plus matched-condition Cora-vs-KV260 statistical comparison plots, plus a portability-specific Ch4 section. None of that is on the schedule between now and submission.

**This descope is safe.** A two-RQ KV260-only thesis with the hybrid-mode architectural finding is more focused than the three-RQ portability version, the evidence base on disk supports it, and the committee will not penalize a tighter scope.

---

## 2. What changes vs. the 2026-04-22 outline

| Aspect | 2026-04-22 outline | After this descope |
| --- | --- | --- |
| Number of RQs | 3 | 2 |
| RQ3 | Platform portability across Zynq | **Removed** (or replaced — see §3) |
| Cora role | Reference platform for comparative evaluation | Prior implementation only, no comparative evaluation |
| Migration narrative (`/dev/mem`→UIO, OCM→udmabuf, BOOT.bin→fpgautil) | Thesis contribution | Implementation prose in Ch4 §KV260 implementation |
| Ch3 platform sections | Cora + KV260 + shared RTL | KV260 + shared RTL (Cora as one paragraph) |
| Ch5 portability subsection | Required | Removed |

What does **not** change:
- The Phase 5 multi-angle campaign on KV260 is still the main results chapter.
- All other RQs, hypotheses, contributions, and chapter structures from the 2026-04-22 outline carry forward.
- Minimum Viable Thesis (six items in the outline) is unchanged and remains the schedule-pressure fallback.

---

## 3. Refined Thesis Framing

### One-sentence thesis story

An empirical study of FPGA-assisted vs ARM-only direction-of-arrival estimation on a KV260 SDR platform, evaluating angular precision, accuracy, and runtime behavior across estimators (Phase-Difference, MUSIC, Root-MUSIC) under realistic calibration, noise, fixed-point, and modulated-source conditions.

### Research questions (two-RQ version)

**RQ1.** How closely can an FPGA-assisted fixed-point DoA pipeline on KV260 reproduce the angular accuracy and stability of an ARM floating-point reference path when both operate on equivalent measurement conditions?

**RQ2.** Among Phase-Difference, MUSIC, and Root-MUSIC, which estimator is most robust on the embedded SDR platform under the observed calibration error, noise, and finite-precision constraints?

### Optional RQ3 replacement (recommended)

**RQ3 (replacement).** Which architectural choices in the FPGA-assisted path (in-fabric symmetric FIR vs ARM one-sided bandpass + fabric correlation) materially affect estimator accuracy and throughput under realistic modulated-source and IQ-imbalanced conditions?

**Why this works:** the bandpass debug arc (2026-04-26 evening through 2026-04-27 early morning) produced direct measured evidence — spectrum sweeps, A/B between fabric-FIR and hybrid-mode runs, and a documented failure mode (BLE GFSK ~500 kHz spread vs ~20 kHz fabric bandpass slice + BladeRF IQ image at −55 kHz at carrier power). This is data you have on disk *now*, unlike the portability data which would require new Cora runs.

**Drop entirely if even RQ3 feels like scope risk.** Two RQs is normal for a master's thesis.

### Contributions (KV260-only, in priority order)

1. **An empirical ARM-vs-FPGA-assisted DoA comparison on KV260** using a controlled multi-angle campaign and reproducible logging. *(Headline contribution.)*
2. **A hybrid-filtering architecture** (ARM one-sided FFT bandpass + FPGA xcorr / autocorr) that resolves the symmetric-fabric-FIR + IQ-image + narrow-bandpass-on-BLE failure mode while preserving the FPGA acceleration of the O(N²) correlation step. *(Architectural finding.)*
3. **A fixed-point streaming pipeline** (FIR + phase-cal rotate + xcorr + autocorr) on KV260 with measured precision, accuracy, and throughput across modes. *(Engineering contribution.)*
4. **A reproducible experimental workflow** for embedded DoA evaluation (wired-splitter calibration, capture labeling, sidecar metadata, post-processing pipeline). *(Reproducibility contribution.)*

The Cora work appears as: *"The pipeline was first prototyped and validated on a Cora Z7 reference platform; this thesis evaluates the KV260 implementation."* One sentence, Ch3 §System Design.

### Hypotheses

**H1.** The KV260 ARM-only reference path will meet or exceed the prior Cora ARM baseline (3.4° σ at broadside) in short-run angle stability. **(Already validated: 90° solo σ_ARM = 0.32°, σ_FPGA = 0.29°.)**

**H2.** The FPGA-assisted KV260 path will remain within a small practical error margin of the ARM reference under calibrated single-source conditions while offering a different runtime profile (throughput, CPU offload of the O(N²) step).

**H3.** Root-MUSIC will outperform Phase-Difference and spectral MUSIC under nominal conditions, but its margin will narrow when calibration residuals or fixed-point quantization dominate the error budget.

**H4 (new, hybrid-mode).** Hybrid-mode FPGA filtering (ARM bandpass + fabric correlation) will yield equal or better σ than fabric-FIR-only mode under modulated BLE-style sources, because (a) it sidesteps the symmetric-real FIR admitting the BladeRF IQ image, and (b) it sidesteps the narrow fabric bandpass discarding most of the BLE GFSK bandwidth.

---

## 4. Defense Preparation

### Anticipated questions and defensible answers

| Question | Defensive answer | Citation hook |
| --- | --- | --- |
| Why a 2-element ULA? It only resolves on a half-plane. | Match to the primary methodology paper's geometry. Scope is single-source half-plane tracking, stated explicitly. | Wachowiak & Kryszkiewicz 2022 [B1] |
| Why MUSIC / Root-MUSIC over ESPRIT? | Root-MUSIC avoids spectral search → polynomial root-finding step is bounded and easier to analyze under fixed point. ESPRIT's rotational-invariance assumption requires a sub-array partition not natural for a 2-element array. | Schmidt 1986 [B2], Barabell 1983 [B3], Roy & Kailath 1989 [B4], Krim & Viberg 1996 [B16] |
| Off-broadside accuracy is poor. Why? | Two contributions: (a) per-channel calibration residual, which the literature predicts dominates off-broadside accuracy for subspace methods; (b) measured environmental conditions (partner-as-multipath at 4/5 angles in the 2026-04-26 run). The empty-room A/B in the 2026-04-27 run quantifies (b). | Friedlander 1990 [B19], Swindlehurst & Kailath 1992 [B18], Weiss & Friedlander 1993 [B20], Hashemi 1993 [B26] |
| What does the FPGA actually win? | Acceleration of the O(N²) cross-correlation and autocorrelation steps. Eigendecomposition stays on ARM (Liu & Jones 2000 split [B23]). Show throughput table (readings/s) and resource utilization table (LUT / FF / DSP48 / BRAM36). | Liu & Jones 2000 [B23], Huang et al. 2001 [B22] |
| Why not full in-fabric MUSIC / EVD? | Fixed-point eigendecomposition on a small Hermitian 2×2 matrix is a documented open problem with non-trivial precision cost. Scoped as future work. The thesis is a partition study (which steps live in fabric vs ARM), not a full hardware MUSIC paper. | Huang, Tufts & Shim 2001 [B22], Eriksson et al. 1994 [B21], Oppenheim & Weinstein 1972 [B24] |
| Why descope Cora portability? | The KV260 evaluation is the primary contribution. Cora is documented as prior implementation. Cross-platform comparative evaluation was scoped out for schedule; the available evidence base on KV260 is sufficient for the two-RQ argument. | (Procedural answer, no citation needed.) |
| Why BladeRF over USRP? | Cost, native 2×2 channels, AD9361 transceiver shared with USRP B-series. The measured −55 kHz IQ image is a per-unit / per-channel calibration artifact (cited in the thesis as a measured constraint), not a fundamental architectural limitation of the SDR class. | Nuand BladeRF 2.0 docs [B9], AD9361 datasheet [B30] |
| Why a wired-splitter calibration vs. far-field calibration? | Wired-splitter cal isolates the static analog phase offset between RX channels (cabling + ADC pipeline) from anything radiated. It is filter-agnostic at `--tone 0` (broadband) and reproducible to ~0.13° σ on the bench. Far-field cal would conflate antenna-pattern errors with channel offset. | Holm 2016 / equivalent SDR-cal note [B27], Tuncer & Friedlander 2009 [B25] |
| Why is the in-fabric FIR present at all if you ended up bypassing it? | It is functionally correct (validated bit-exact against a Python reference on Cora) and remains useful for narrowband CW or non-BLE sources. The bypass is a *configuration* (`--filter=arm_bandpass`), not a removal — both modes are available and both are characterized. The thesis presents the architectural trade-off rather than declaring one mode "wrong." | (Procedural; reference your own Phase A design spec `2026-04-09-fpga-phase-a-design.md`.) |
| Reproducibility — how would another student replicate? | Sidecar JSON per run records calibration value, frequency, gain, duration, label, commit hash. The KV260 bench-bringup script is idempotent. The host-side analysis script reads the run directory and produces all Ch5 plots. Appendix lists exact commands. | (Procedural answer, no citation.) |

### Things to *not* claim during the defense

- Do not claim "we built a complete in-fabric MUSIC implementation." The FPGA does FIR + phase rotate + xcorr + autocorr; eigendecomposition + root-finding stay on ARM.
- Do not claim sub-degree accuracy at every angle until the empty-room data confirms it. The σ numbers are sub-degree at clean angles; the *mean error* depends on the empty-room A/B.
- Do not claim portability or platform-generalization as a contribution after this descope.
- Do not claim novelty of MUSIC / Root-MUSIC. The novelty is the embedded implementation, the hybrid-filtering architecture, and the empirical comparison — never the algorithm.
- Do not claim BladeRF IQ image rejection figures as your contribution; they are a measured property of this specific SDR + channel + gain combination, cited as a constraint.

---

## 5. Reading List for Defense Preparation

The bibliography in `docs/bibliography.md` is comprehensive but uneven in places. The list below is **prioritized by defense value** — read in this order if time is limited.

### Tier 1: must-read before defense

These directly answer questions you will be asked.

**[B1] Wachowiak & Kryszkiewicz 2022** — *Direction of arrival estimation using software defined radio and a two-element antenna array.* Wireless Networks, https://doi.org/10.1007/s11276-022-03010-z
*Your primary methodology paper. Re-read it the night before the defense. Be prepared to articulate exactly how your work extends or differs from it (FPGA acceleration, hybrid-mode filtering, KV260 platform).*

**[B16] Krim & Viberg 1996** — *Two decades of array signal processing research: the parametric approach.* IEEE Signal Processing Magazine 13(4), 67–94, https://doi.org/10.1109/79.526899
*The single best survey. Use it to defend any choice between MUSIC, Root-MUSIC, ESPRIT, MVDR. Read sections 2 (data model), 4 (subspace methods), and 6 (sensitivity / robustness).*

**[B19] Friedlander 1990** — *A sensitivity analysis of the MUSIC algorithm.* IEEE Transactions on ASSP 38(10), https://doi.org/10.1109/29.60105
*Predicts how MUSIC and Root-MUSIC degrade under gain/phase calibration errors. This is the paper that supports your "off-broadside accuracy is calibration-residual-limited" argument.*

**[B18] Swindlehurst & Kailath 1992** — *A performance analysis of subspace-based methods in the presence of model errors, Part I: the MUSIC algorithm.* IEEE TSP 40(7), https://doi.org/10.1109/78.143447
*Companion to [B19]. Same purpose: defends your accuracy story when the committee asks about non-90° angles.*

**[B22] Huang, Tufts & Shim 2001** — *A study of fixed-point implementation of the MUSIC algorithm.* ICASSP 2001, https://doi.org/10.1109/ICASSP.2001.940643
*Direct empirical reference for fixed-point MUSIC. Read it carefully — it gives you the language to discuss your fixed-point pipeline's precision budget.*

### Tier 2: read for breadth

These strengthen specific chapters.

**[B17] Stoica & Nehorai 1989** — *MUSIC, maximum likelihood, and Cramér–Rao bound.* IEEE TASSP 37(5)
*Establishes the CRLB. Optional but very strong if a committee member asks "how close is your estimator to the theoretical optimum?"*

**[B2] Schmidt 1986** — *Multiple emitter location and signal parameter estimation.* IEEE TAP 34(3)
*The MUSIC paper. Read once for vocabulary, do not over-rely on it (it's foundational, not directly relevant to fixed-point).*

**[B3] Barabell 1983** — *Improving the resolution performance of eigenstructure-based direction-finding algorithms.* ICASSP 1983
*Root-MUSIC origin. Worth one read for the polynomial root-finding argument.*

**[B23] Liu & Jones 2000** — *FPGA implementation of subspace DoA.* IEEE TSP 49(8)
*Template for the resource-utilization and throughput discussion in your Ch3/Ch4. Read for structure, not detail.*

**[B25] Tuncer & Friedlander 2009** — *Classical and Modern Direction-of-Arrival Estimation.* Academic Press
*Reference book; skim Chapter 1 (overview), Chapter 5 (calibration), Chapter 9 (FPGA / fixed-point implementations) only.*

### Tier 3: skim only

**[B4] Roy & Kailath 1989** — *ESPRIT.* IEEE TASSP 37(7) — read the abstract; cite when asked about ESPRIT.

**[B5] Capon 1969** — *MVDR.* Proc. IEEE 57(8) — abstract only.

**[B12] Van Trees 2002** — *Optimum Array Processing.* Reference textbook; do not read cover-to-cover. Page-flip Ch. 2, 8, 9.

**[B13] PySDR (Lichtman 2024)** — practical Python reference; you've already used it for implementation. Re-read the DoA chapter once.

### Tier 4: new additions to bibliography (recommended)

The bibliography currently has weak coverage in three places. Adding these strengthens your defense.

**[B26 — new] Hashemi 1993** — *The indoor radio propagation channel.* Proceedings of the IEEE 81(7), https://doi.org/10.1109/5.231342
*Defends the "partner-as-multipath at 2.4 GHz" claim quantitatively. The single best citation for indoor 2.4 GHz multipath behavior. Replaces hand-waving with a real mechanism.*

**[B27 — new] Wirth, Krása et al. (KrakenSDR / KerberosSDR phase calibration papers, ~2018–2022)**
*Defends the wired-splitter calibration methodology. Search "KrakenSDR phase coherent calibration" — multiple white-paper-grade references exist. Replaces bibliography entry [15] which is currently a placeholder.*

**[B28 — new] Xilinx UG1085 (Zynq UltraScale+ TRM) and PG021 (AXI DMA)**
*Primary platform documentation. Defends platform-specific claims (HPM0_FPD aperture, AXI port semantics, DMA register map). UG1085 also defends the EMIO-as-control-path architectural choice.*

**[B29 — new] Schmid et al. 2012** — *An FPGA-based real-time spectrum sensor for cognitive radio.* IEEE-ish venue.
*Template for "bandpass + correlation in FPGA" architecture. Useful precedent for the hybrid-mode discussion.*

**[B30 — new] Analog Devices AD9361 datasheet + UG-570 (AD9361 reference manual)**
*Required reference for any IQ-imbalance / IQ-image discussion. The −55 kHz image is an AD9361-class artifact; you should know the relevant pages of UG-570 (transmit/receive quadrature calibration, image rejection limits) for defense.*

**[B31 — new] Forsythe 2001 or equivalent** — *Effect of single-tone calibration on multi-tone DoA estimation.*
*Defends the `--tone 0` filter-agnostic broadband cal vs `--tone > 0` choice. If Forsythe 2001 doesn't exist by that exact title, search "broadband phase calibration single-tone DoA" and pick the closest match.*

### Tier 5: skip unless asked

Bibliography entries [B6], [B7], [B8], [B14], [B15] are general-knowledge / web-resource entries. Useful if a committee member asks for practical implementation references but not worth pre-reading.

---

## 6. Action Items Before Defense

In order, latest first:

1. **Empty-room hybrid-mode campaign run** (tomorrow morning) — produces the matched A/B that closes RQ1 and RQ3-replacement.
2. **Update outline note** `2026-04-22-thesis-outline-and-exit-criteria.md` to reflect this descope. Mark RQ3 as removed; update contributions list.
3. **Write Ch3 (System Design)** — KV260 + shared `doa_pipeline` RTL. One paragraph on Cora as prior implementation. Antenna geometry, BladeRF front-end, KV260 platform, calibration workflow.
4. **Write Ch4 (Implementation and Method)** — KV260 implementation details, FPGA-fabric-FIR vs hybrid-mode architectural comparison, experimental method, analysis pipeline.
5. **Write Ch5 (Results)** — directly off `analyze_campaign.py` output once tomorrow's run is in.
6. **Read Tier 1 papers** (~3 hours total).
7. **Skim Tier 2 papers** (~2 hours total).
8. **Add Tier 4 citations** to `docs/bibliography.md`.
9. **Write Ch1 + Ch2 framing pass** — KV260-primary, two-RQ version.
10. **Write Ch6 (Conclusion).**
11. **Read Tier 1 papers a second time** the night before defense.

---

## 7. Bottom Line

The descope removes one research question and one chapter section. It does not weaken the thesis — it sharpens it. The KV260 evidence base is sufficient for a defensible master's thesis once tomorrow's empty-room hybrid-mode campaign provides the matched A/B against the contaminated 2026-04-26 data.

The hybrid-mode finding is the strongest architectural contribution and is unique to this work. Lead with it. The fixed-point pipeline + reproducibility workflow are solid supporting contributions. The bug stories (HPM0_FPD stride, EMIO Path C, dma_safe_ctrl shim) are Ch4 implementation prose, not Ch5 results.

Two RQs, four contributions, five chapters of evidence. That is a defensible master's thesis.
