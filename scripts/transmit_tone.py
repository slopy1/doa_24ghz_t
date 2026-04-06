#!/usr/bin/env python3
"""
Transmit a continuous tone from TX0 for DOA experiments.

Run this in one terminal, then collect data in another.

Usage:
    python scripts/transmit_tone.py
    Press Ctrl+C to stop transmitting
"""

import numpy as np
import signal
import sys

running = True


def signal_handler(sig, frame):
    global running
    print("\n\n🛑 Stopping transmission...")
    running = False


def main():
    global running
    
    print("=" * 60)
    print("TX TONE GENERATOR FOR DOA EXPERIMENTS")
    print("=" * 60)
    
    try:
        from bladerf import _bladerf
    except ImportError:
        print("❌ Cannot import bladerf module")
        print("   Make sure BladeRF Python bindings are installed.")
        sys.exit(1)
    
    # Parameters
    fc = 2.45e9
    fs = 5e6
    tone_offset = 100e3
    tx_gain = 40
    
    print("\n📡 TX Configuration:")
    print(f"   Frequency: {fc/1e9:.3f} GHz + {tone_offset/1e3:.0f} kHz")
    print(f"   Sample rate: {fs/1e6:.1f} MS/s")
    print(f"   TX Gain: {tx_gain} dB")
    
    # Open device
    print("\n[1/4] Opening BladeRF...")
    try:
        device = _bladerf.BladeRF()
        print(f"      ✓ Connected to {device.get_board_name()}")
    except Exception as e:
        print(f"      ❌ Failed: {e}")
        sys.exit(1)
    
    # Configure TX
    print("\n[2/4] Configuring TX0...")
    try:
        tx = device.Channel(_bladerf.CHANNEL_TX(0))
        tx.frequency = int(fc)
        tx.sample_rate = int(fs)
        tx.bandwidth = int(fs * 0.75)
        tx.gain = tx_gain
        print("      ✓ TX0 configured")
    except Exception as e:
        print(f"      ❌ Failed: {e}")
        device.close()
        sys.exit(1)
    
    # Generate tone
    print("\n[3/4] Generating tone signal...")
    duration = 0.1
    n_samples = int(fs * duration)
    t = np.arange(n_samples) / fs
    
    tone = np.exp(1j * 2 * np.pi * tone_offset * t)
    scale = 2000
    tone_i = (np.real(tone) * scale).astype(np.int16)
    tone_q = (np.imag(tone) * scale).astype(np.int16)
    
    tx_buffer = np.empty(n_samples * 2, dtype=np.int16)
    tx_buffer[0::2] = tone_i
    tx_buffer[1::2] = tone_q
    print(f"      ✓ Generated {n_samples:,} samples")
    
    # Setup sync
    print("\n[4/4] Setting up TX sync...")
    try:
        device.sync_config(
            layout=_bladerf.ChannelLayout.TX_X1,
            fmt=_bladerf.Format.SC16_Q11,
            num_buffers=16,
            buffer_size=16384,
            num_transfers=8,
            stream_timeout=5000
        )
        tx.enable = True
        print("      ✓ TX enabled")
    except Exception as e:
        print(f"      ❌ Failed: {e}")
        device.close()
        sys.exit(1)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    print("\n" + "=" * 60)
    print("📻 TRANSMITTING...")
    print("=" * 60)
    print("\n   Position TX antenna at desired angle from RX array")
    print("\n   In another terminal, run:")
    print("   python scripts/collect_dataset.py --angle <ANGLE> --distance <DIST> --snr high")
    print("\n   Press Ctrl+C to stop")
    print("=" * 60)
    
    tx_count = 0
    try:
        while running:
            device.sync_tx(tx_buffer, n_samples)
            tx_count += 1
            if tx_count % 10 == 0:
                elapsed = tx_count * duration
                print(f"\r   ⏱️  Transmitting... {elapsed:.1f}s", end="", flush=True)
    except Exception as e:
        print(f"\n❌ TX error: {e}")
    
    # Cleanup
    print("\n\n[Cleanup] Disabling TX...")
    try:
        tx.enable = False
        device.close()
        print("✓ TX disabled, device closed")
    except Exception:
        pass
    
    print("\n" + "=" * 60)
    print("✓ Transmission complete")
    print("=" * 60)


if __name__ == "__main__":
    main()

