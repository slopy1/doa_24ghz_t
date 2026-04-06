# Cross-Correlation MAC Datapath: Math and Implementation Notes

## 1. What the Module Computes

The `xcorr_acc` module computes the sample cross-correlation between two complex baseband signals over a snapshot of N samples:

```
r_01 = (1/N) * sum_{n=0}^{N-1} x_0[n] * conj(x_1[n])
```

where `x_0[n]` and `x_1[n]` are the complex I/Q samples from antenna channels 0 and 1. The division by N happens on the ARM side (or is skipped entirely, since `atan2(im, re)` is scale-invariant).

This quantity `r_01` is the (0,1) element of the 2x2 spatial covariance matrix **R** used by all array signal processing algorithms (MUSIC, Root-MUSIC, MVDR, phase differencing).

## 2. Complex Multiply with Conjugate

Each channel sample is complex:
```
x_0 = a + jb     (ch0_i = a, ch0_q = b)
x_1 = c + jd     (ch1_i = c, ch1_q = d)
```

The conjugate of x_1 is:
```
conj(x_1) = c - jd
```

Expanding the product:
```
x_0 * conj(x_1) = (a + jb)(c - jd)
                 = ac - jad + jbc - j^2 bd
                 = (ac + bd) + j(bc - ad)
```

Therefore:
```
re(r_01) += ch0_i * ch1_i + ch0_q * ch1_q
im(r_01) += ch0_q * ch1_i - ch0_i * ch1_q
```

This requires 4 multiplies and 2 add/subtracts per sample — mapping to 4 DSP48E1 slices on the Zynq.

## 3. Why Cross-Correlation Gives Phase (and Therefore Angle)

For a narrowband far-field source at angle theta, the signal at antenna 1 is a delayed copy of antenna 0:

```
x_1[n] = x_0[n] * exp(-j * 2*pi*d*sin(theta) / lambda)
```

where `d` is the antenna spacing and `lambda` is the wavelength.

Substituting into the cross-correlation:
```
r_01 = (1/N) * sum x_0[n] * conj(x_0[n] * exp(-j*phi))
     = (1/N) * sum |x_0[n]|^2 * exp(j*phi)
     = P_0 * exp(j*phi)
```

where `phi = 2*pi*d*sin(theta)/lambda` is the inter-element phase shift and `P_0` is the signal power.

So:
```
angle(r_01) = phi = 2*pi*d*sin(theta)/lambda
theta = arcsin(phi * lambda / (2*pi*d))
```

This is the fundamental relationship that all DoA algorithms exploit.

## 4. Fixed-Point Sizing

| Signal | Bit Width | Justification |
|--------|-----------|---------------|
| Input samples (SC16) | 16-bit signed | BladeRF native format |
| Each multiply product | 32-bit | 16 x 16 = 32 bits |
| Accumulator | 48-bit signed | 32 + ceil(log2(N)) = 32 + 10 = 42 bits for N=1024. Using 48 gives 6 bits of headroom, and matches the DSP48E1 native accumulator width |

Overflow check: worst case is all samples at full scale (+/-32767) with coherent accumulation over 1024 samples:
```
max value = 32767^2 * 2 * 1024 = 2.2 * 10^12
```
This fits in 42 bits (4.4 * 10^12 capacity). The 48-bit accumulator has 64x headroom.

## 5. Test Results Explained

The testbench uses a tone with amplitude 1000 and 8 samples per cycle (45-degree phase steps).

For **Test 1 (0-degree offset)**, both channels are identical:
```
Each sample contributes: ch0_i*ch1_i + ch0_q*ch1_q = |x|^2
Summed over 64 samples of a discrete tone:
  sum of cos^2 + sin^2 values at 8 discrete phases, repeated 8 times
  = 8 * (1000^2 + 0^2 + 707^2 + 707^2 + 0^2 + 1000^2 + 707^2 + 707^2)
  = 8 * 7,998,792 (accounting for integer truncation of 707.1 -> 707)
  ~ 63,990,336
```
The imaginary part is exactly 0 because there is no phase offset.

For **Test 2 (90-degree offset)**, ch1 leads ch0 by 90 degrees:
```
re(r_01) = 0      (real part cancels)
im(r_01) = -63M   (negative = ch1 leads ch0)
atan2(-63M, 0) = -pi/2 = -90 degrees
```

For **Test 3 (45-degree offset)**:
```
re(r_01) = +45M
im(r_01) = -45M
atan2(-45M, +45M) = -pi/4 = -45 degrees
```

The magnitudes differ from Test 1/2 because the 45-degree shifted tone doesn't hit the same lookup table entries, slightly changing the sum.

## 6. How This Connects to the Full DoA Pipeline

```
BladeRF 2ch MIMO --> DMA --> xcorr_acc (PL) --> AXI-Lite regs
                                                     |
                                                     v
                                              ARM reads r_01
                                                     |
                                                     v
                                           phase = atan2(im, re)
                                                     |
                                                     v
                                           theta = arcsin(phase * lambda / (2*pi*d))
                                                     |
                                                     v
                                           Display / dashboard
```

The FPGA handles the streaming multiply-accumulate at line rate. The ARM does the trigonometry and display — operations that happen once per snapshot (every 204.8 us at 5 MS/s with N=1024), which is trivially fast even in Python.

## 7. References

### Textbooks

1. **Van Trees, H. L. (2002).** *Optimum Array Processing: Part IV of Detection, Estimation, and Modulation Theory.* Wiley-Interscience.
   - Chapter 2: spatial covariance matrix definition and properties
   - Chapter 8: MUSIC and Root-MUSIC algorithms
   - The standard graduate reference for array signal processing

2. **Haykin, S. (2014).** *Adaptive Filter Theory.* 5th ed., Pearson.
   - Chapter 9: cross-correlation in the context of adaptive beamforming
   - Clear treatment of sample covariance estimation

3. **Johnson, D. H. and Dudgeon, D. E. (1993).** *Array Signal Processing: Concepts and Techniques.* Prentice Hall.
   - Chapter 4: narrowband array model and inter-element phase
   - Chapter 7: spectral estimation methods (MUSIC, MVDR)

### Journal Papers

4. **Schmidt, R. O. (1986).** "Multiple emitter location and signal parameter estimation." *IEEE Transactions on Antennas and Propagation*, 34(3), pp. 276-280.
   - The original MUSIC paper. Derives DoA from eigendecomposition of the spatial covariance matrix R, whose off-diagonal element is exactly what `xcorr_acc` computes.

5. **Barabell, A. J. (1983).** "Improving the resolution performance of eigenstructure-based direction-finding algorithms." *Proc. IEEE ICASSP*, pp. 336-339.
   - Introduces Root-MUSIC, which finds DoA by polynomial rooting rather than spectral search. Still requires the same covariance matrix estimate.

6. **Capon, J. (1969).** "High-resolution frequency-wavenumber spectrum analysis." *Proceedings of the IEEE*, 57(8), pp. 1408-1418.
   - The MVDR / Capon beamformer. Uses the inverse of the covariance matrix for adaptive beamforming.

### FPGA Implementation References

7. **Xilinx (2018).** *UG479: 7 Series DSP48E1 Slice User Guide.* Xilinx Inc.
   - Details the DSP48E1 primitive used for the 16x16 multiplies and 48-bit accumulation. The accumulator width (48-bit) was chosen to match the native DSP48 datapath.

8. **Dick, C. and Harris, F. (2003).** "FPGA Signal Processing Using Sigma-Delta Modulation." *IEEE Signal Processing Magazine*, 20(1), pp. 74-83.
   - General reference for fixed-point signal processing on FPGAs, including accumulator sizing and overflow analysis.

9. **Jeong, D. et al. (2020).** "FPGA-based real-time DOA estimation using MUSIC algorithm." *IEEE Access*, 8, pp. 205528-205538.
   - A recent example of MUSIC DoA on FPGA, including cross-correlation computation in programmable logic.
