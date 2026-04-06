# FPGA Mapping Notes

**Target Platform:** Cora Z7 (Zynq-7000 XC7Z007S)

## Overview

This document outlines the FPGA-friendly partitioning of the Bayesian DOA pipeline. The goal is streaming acceleration on Programmable Logic (PL) while keeping complex computations on the Processing System (PS).

## 1. Streaming Sufficient Statistics

DOA estimation requires only a few **streaming statistics** from raw samples. These are ideal for FPGA implementation.

### 1.1 Cross-Correlation (CRITICAL)

```
r_01 = Σ(ch0[n] × conj(ch1[n])) / N
```

| Property | Value |
|----------|-------|
| Input | Two complex streams (I/Q pairs) |
| Output | One complex value per snapshot |
| Operations | Complex multiply, accumulate |
| Rate | 5 MS/s → ~4883 snapshots/sec (1024 samples/snapshot) |

### 1.2 Power Estimates

```
P_0 = Σ|ch0[n]|² / N
P_1 = Σ|ch1[n]|² / N
```

Used for normalization and gain ratio estimation.

### 1.3 Phase Extraction

```
phase = atan2(imag(r_01), real(r_01))
```

CORDIC or lookup table. Can run on PS if latency is acceptable.

## 2. PL vs PS Partition

| Function | Where | Rationale |
|----------|-------|-----------|
| Sample buffering | PL | High rate, streaming |
| DC removal | PL | Simple running average |
| Cross-correlation | PL | Streaming, high throughput |
| Power estimation | PL | Streaming |
| Phase extraction | PS or PL | Low rate (once/snapshot) |
| DOA grid search | PS | Complex indexing |
| Kalman filter | PS | Sequential state |
| Posterior computation | PS | Array operations |
| Logging/plotting | PS/PC | Not real-time |

## 3. Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Programmable Logic (PL)                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ADC RX0 ──┬──► DC Remove ──► ┐                           │
│             │                   ├──► Cross-Corr ──► AXI    │
│   ADC RX1 ──┼──► DC Remove ──► ┘        │         Stream   │
│             │                           │                   │
│             └──► Power Acc ─────────────┘                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  Processing System (PS - ARM)               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   DMA ──► Phase Extract ──► Grid Search ──► Kalman Filter  │
│                                    │             │          │
│                                    ▼             ▼          │
│                              MAP Estimate    Drift Estimate │
│                                    │             │          │
│                                    └──────┬──────┘          │
│                                           ▼                 │
│                                    Output (UART/USB)        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 4. Resource Estimates

| Resource | Available | Estimated | Notes |
|----------|-----------|-----------|-------|
| DSP48 | 66 | 4-8 | Complex MAC |
| BRAM (36Kb) | 50 | 2-4 | Double buffer |
| LUTs | 14,400 | ~500-1000 | Control logic |
| FFs | 28,800 | ~1000-2000 | Pipeline regs |

This is a **very modest** footprint with room for expansion.

## 5. Throughput Analysis

| Parameter | Value |
|-----------|-------|
| Sample rate | 5 MS/s |
| Snapshot size | 1024 samples |
| Snapshots/sec | 4,883 |
| Latency/snapshot | 204.8 µs |
| DOA update rate | ~4.8 kHz |

This is **far faster** than needed for practical DOA (humans move at ~1-2 m/s).

## 6. Fixed-Point Format

| Signal | Format | Range |
|--------|--------|-------|
| Raw samples | SC16 | ±32767 |
| Accumulator | 48-bit complex | N≤65536 |
| Normalized r_01 | Q1.15 | ±2.0 |
| Phase output | 16-bit signed | ±π → ±32768 |

## 7. Implementation Options

### Option A: Vitis HLS (Recommended)

Create HLS IP for cross-correlation:
- Input: AXI-Stream SC16 samples
- Output: AXI-Lite registers with r_01, P_0, P_1
- Development time: 1-2 days

### Option B: Vivado Block Design

Use Xilinx IP blocks:
- CMAC (Complex Multiply-Accumulator)
- DMA for streaming
- Custom FSM

### Option C: Pure ARM (Baseline)

Process on ARM, no PL acceleration:
- Useful for algorithm validation
- Current Python code serves this purpose

## 8. Future Extensions

1. **Multi-snapshot averaging:** Further noise reduction
2. **Adaptive snapshot size:** Based on estimated SNR
3. **Full Bayesian on FPGA:** Lookup tables for likelihoods
4. **Beamformer output:** Stream MVDR signal downstream

## References

- Xilinx UG585: Zynq-7000 Technical Reference Manual
- Xilinx UG1399: Vitis HLS User Guide
- BladeRF 2.0 FPGA documentation

