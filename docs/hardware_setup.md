# Hardware Setup Guide

## Equipment List

| Item | Model | Quantity |
|------|-------|----------|
| SDR Receiver | Nuand BladeRF 2.0 micro | 1 |
| FPGA Board | Digilent Cora Z7-07S | 1 |
| Antenna | 2.4 GHz whip | 2 |
| Antenna Mount | Aluminum bracket | 1 |
| USB Cable | USB 3.0 Type-A to Micro-B | 1 |
| Power Supply | 5V 3A USB-C (for Cora) | 1 |

## BladeRF 2.0 Configuration

### Channel Mapping

```
         ┌─────────────────────────────┐
         │       BladeRF 2.0           │
         │                             │
   RX0 ◄─┤ SMA (LEFT)     SMA (RIGHT) ├─► RX1
         │                             │
         │     ○ LED    ○ LED          │
         │                             │
         └──────────┬──────────────────┘
                    │
                 USB 3.0
```

- **RX0** = `channel_0` = Left antenna (viewed from behind)
- **RX1** = `channel_1` = Right antenna

### MIMO Synchronization

The BladeRF 2.0 micro uses a single clock for both RX channels, ensuring coherent sampling. No external sync cables needed.

```python
# MIMO configuration
device.sync_config(
    layout=_bladerf.ChannelLayout.RX_X2,  # 2-channel RX
    fmt=_bladerf.Format.SC16_Q11,          # 16-bit I/Q
    num_buffers=32,
    buffer_size=16384,
    num_transfers=16,
    stream_timeout=5000
)
```

## Antenna Array Setup

### Spacing Measurement

```
     ◄───── d = 6.1 cm ─────►
     
    [ANT0]              [ANT1]
       │                   │
       └─────────┬─────────┘
                 │
            Array Center
                 │
                 ▼
            Broadside (θ = 0°)
```

**Target spacing:** d = λ/2 = 6.1 cm at 2.45 GHz

**Measurement method:**
1. Use digital calipers
2. Measure center-to-center
3. Tolerance: ±0.5 mm

### Mounting

- Use rigid aluminum bracket
- Maintain identical antenna heights
- Ensure antennas are parallel
- Avoid metal objects within 20 cm

## TX Setup (Controlled Experiments)

### Option 1: BladeRF TX

Use a second BladeRF (or TX channel of same unit in loopback):

```python
tx = device.Channel(_bladerf.CHANNEL_TX(0))
tx.frequency = int(2.45e9)
tx.sample_rate = int(5e6)
tx.gain = 40  # Adjust for distance
```

### Option 2: ESP32 Beacon

Simple WiFi beacon at 2.4 GHz:
- Constant carrier mode
- Known position
- Battery powered for mobility

## Cora Z7 Setup

### Connections

```
Cora Z7          BladeRF
┌──────┐         ┌──────┐
│      │         │      │
│ PMOD ├─────────┤ GPIO │  (optional, for triggers)
│      │         │      │
│ USB  │         │ USB  │
└──┬───┘         └──┬───┘
   │                │
   └────────────────┴──► Host PC
```

### FPGA Image

The streaming covariance computation runs on PL. See `fpga/` for:
- Vivado project files
- HLS source for cross-correlation IP
- Bitstream

## Software Requirements

```bash
# BladeRF libraries
sudo apt install libbladerf-dev bladerf-fpga-hostedx40

# Python bindings
pip install pybladerf  # or build from source

# Verify connection
bladeRF-cli -p
```

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Device not found | USB permission | Add udev rule, reconnect |
| Low coherence | Bad cable | Replace SMA cables |
| Clipping | Gain too high | Reduce RX gain |
| No signal | TX off | Check TX script running |
| Phase jumps | Temperature drift | Let warm up 10 min |
| `ImportError: libspdlog.so.1.11` / `libfmt.so.9` when importing `gnuradio.aoa` | `gr-aoa` was built against older `spdlog`/`fmt` SONAMEs (common after a system upgrade) | Run the provided wrappers that set up a tiny compat `LD_LIBRARY_PATH`: `scripts/run_aoa_estimation_bladerf.sh` or `scripts/run_gnuradio_companion_aoa.sh` |

### gr-aoa shared-library mismatch (Arch / rolling distros)

If you see an error like:

```
ImportError: libspdlog.so.1.11: cannot open shared object file: No such file or directory
```

it means your installed `gr-aoa` binaries are linked against older SONAMEs (`libspdlog.so.1.11`, `libfmt.so.9`), while your system ships newer ones (e.g. `libspdlog.so.1.16`, `libfmt.so.12`).

This repo includes wrappers that create a minimal compat directory with the missing SONAMEs (symlinked from an existing conda install) and then execute the command with `LD_LIBRARY_PATH` pointing there:

```bash
# Run the AoA flowgraph directly
./scripts/run_aoa_estimation_bladerf.sh

# Or launch GRC with the same environment
./scripts/run_gnuradio_companion_aoa.sh
```

### bladeRF Soapy: DC removal unsupported

Some bladeRF Soapy backends do not support `set_dc_offset_mode(...)` and will throw:

```
ValueError: source: Channel 0 does not support automatic DC removal setting
```

This repo uses a custom GRC block `soapy_source_safe` (auto-installed when you launch GRC via `scripts/run_gnuradio_companion_aoa.sh`) that wraps the DC-removal call in `try/except`, so the flowgraphs still start.

