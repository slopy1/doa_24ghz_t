# ARM vs FPGA DoA estimation — summary

All values are folded to resolve 2-element ULA front-back ambiguity
(θ → min(θ, 180°−θ)), i.e. angular offset from broadside in [0°, 90°].

| Algo | Group | μ ARM | μ FPGA | \|Δμ\| | σ ARM | σ FPGA | σ ratio |
|---|---|---|---|---|---|---|---|
| ROOTMUSIC | rootmusic_pair_90deg | 70.35° | 77.31° | 6.96° | 3.98° | 10.06° | 2.53 |
| MUSIC | music_pair_90deg | 45.34° | 56.40° | 11.06° | 18.18° | 17.72° | 0.97 |
