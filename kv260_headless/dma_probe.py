#!/usr/bin/env python3
"""DMA state dump — walks through the same MM2S setup as run_snapshot()
and prints DMACR/DMASR/CURDESC/TAILDESC/SG_STATUS + doa_pipeline STATUS
at every step so we can localize where the pipeline hangs.

With the dma_safe_ctrl overlay, _read_dma/_write_dma use the 16-byte-spaced
shim window while reporting logical AXI DMA offsets.

Usage:  sudo python3 dma_probe.py
"""
import sys, time, struct, mmap, os
sys.path.insert(0, os.path.expanduser("~/doa"))
from aoa_estimation_fpga_kv260 import (
    KV260Config, KV260Pipeline,
    MM2S_DMACR, MM2S_DMASR, MM2S_CURDESC, MM2S_TAILDESC,
    SG_NXTDESC, SG_BUFFER, SG_CONTROL, SG_STATUS,
    SG_SOF, SG_EOF,
    REG_STATUS,
)
import numpy as np


def dmasr_decode(v: int) -> str:
    bits = []
    if v & (1 << 0):  bits.append("HALTED")
    if v & (1 << 1):  bits.append("IDLE")
    if v & (1 << 3):  bits.append("SGINCLD")
    if v & (1 << 4):  bits.append("DMAINTERR")
    if v & (1 << 5):  bits.append("DMASLVERR")
    if v & (1 << 6):  bits.append("DMADECERR")
    if v & (1 << 8):  bits.append("SGINTERR")
    if v & (1 << 9):  bits.append("SGSLVERR")
    if v & (1 << 10): bits.append("SGDECERR")
    if v & (1 << 12): bits.append("IOC_IRQ")
    if v & (1 << 13): bits.append("DLY_IRQ")
    if v & (1 << 14): bits.append("ERR_IRQ")
    return "|".join(bits) if bits else "(zero)"


def dump(p, label):
    cr  = p._read_dma(MM2S_DMACR)
    sr  = p._read_dma(MM2S_DMASR)
    cd  = p._read_dma(MM2S_CURDESC)
    td  = p._read_dma(MM2S_TAILDESC)
    sgs = p._read_desc(SG_STATUS)
    sgc = p._read_desc(SG_CONTROL)
    sgb = p._read_desc(SG_BUFFER)
    pl_status = p._read32(REG_STATUS)
    print(f"--- {label} ---")
    print(f"  DMACR        = 0x{cr:08x}  (RS={bool(cr & 1)} RESET={bool(cr & 4)})")
    print(f"  DMASR        = 0x{sr:08x}  [{dmasr_decode(sr)}]")
    print(f"  MM2S_CURDESC = 0x{cd:08x}")
    print(f"  MM2S_TAILDESC= 0x{td:08x}")
    print(f"  SG_BUFFER    = 0x{sgb:08x}")
    print(f"  SG_CONTROL   = 0x{sgc:08x}  (nbytes={sgc & 0x7FFFFF} SOF={bool(sgc & SG_SOF)} EOF={bool(sgc & SG_EOF)})")
    print(f"  SG_STATUS    = 0x{sgs:08x}  (DONE={bool(sgs & 0x80000000)})")
    print(f"  PL_STATUS    = 0x{pl_status:08x}  (VALID={bool(pl_status & 1)})")


def main():
    cfg = KV260Config()
    with KV260Pipeline(cfg) as p:
        n = cfg.SNAPSHOT_SIZE
        buf = np.zeros(n * 2, dtype=np.uint32)
        # fill with deterministic non-zero pattern so we can verify TLAST timing if needed
        buf[:] = np.arange(n * 2, dtype=np.uint32) | 0x00010001
        data_bytes = buf.tobytes()
        nbytes = len(data_bytes)
        print(f"phys: desc=0x{p._desc_phys:08x}  buf=0x{p._buf_phys:08x}  nbytes={nbytes}")

        dump(p, "STEP 0: pristine, before any writes")

        # Reset MM2S
        p._write_dma(MM2S_DMACR, 0x0004)
        for _ in range(100):
            if not (p._read_dma(MM2S_DMACR) & 0x0004):
                break
            time.sleep(0.0001)
        dump(p, "STEP 1: after MM2S reset (DMACR=0x4)")

        # Write data into udmabuf
        p.buf_m.seek(0)
        p.buf_m.write(data_bytes)
        dump(p, "STEP 2: data written to udmabuf")

        # Set up SG descriptor
        p._setup_sg_descriptor(nbytes)
        dump(p, "STEP 3: SG descriptor written")

        # Point CURDESC at descriptor
        p._write_dma(MM2S_CURDESC, p._desc_phys)
        dump(p, "STEP 4: MM2S_CURDESC = desc_phys")

        # Start DMA (RS=1)
        p._write_dma(MM2S_DMACR, 0x0001)
        time.sleep(0.0005)
        dump(p, "STEP 5: DMACR.RS=1 (DMA armed)")

        # Kick by writing TAILDESC
        p._write_dma(MM2S_TAILDESC, p._desc_phys)
        dump(p, "STEP 6: TAILDESC written (DMA kicked)")

        # Sample over time
        for delay_ms in [1, 5, 20, 100, 500]:
            time.sleep(delay_ms / 1000.0)
            dump(p, f"STEP 7: +{delay_ms}ms after kick")

    return 0


if __name__ == "__main__":
    sys.exit(main())
