# KV260 Separate FPGA Build

This is a parallel FPGA-side path. It does not replace the existing
`create_project.tcl`, `doa_pipeline.dts`, or `fpga/rtl/doa_pipeline.v`.

Files:

- `../rtl/doa_pipeline_kv260_separate.v` — self-contained RTL top with the same AXI-Lite register map as the current driver expects.
- `../tb/tb_doa_pipeline_kv260_separate.v` — minimal RTL smoke test for the no-filter covariance path.
- `create_project_kv260_separate.tcl` — separate Vivado project generator using `doa_pipeline_kv260_separate`.
- `doa_pipeline_kv260_separate.dts` — separate generic-uio overlay.

Local syntax/smoke test:

```bash
iverilog -g2012 -Wall -o /tmp/tb_doa_pipeline_kv260_separate.vvp \
  ../rtl/doa_pipeline_kv260_separate.v \
  ../tb/tb_doa_pipeline_kv260_separate.v
vvp /tmp/tb_doa_pipeline_kv260_separate.vvp
```

Build from `fpga/vivado_kv260` in Vivado:

```tcl
source create_project_kv260_separate.tcl
launch_runs synth_1 -jobs 4
launch_runs impl_1 -to_step write_bitstream -jobs 4
```

Create a stripped bitstream:

```bash
cat > system.bif <<'EOF'
all:
{
  [destination_device = pl] project_fpga_side/kv260_doa_fpga_side.runs/impl_1/kv260_doa_fpga_side_wrapper.bit
}
EOF
bootgen -arch zynqmp -process_bitstream bin -image system.bif -w -o doa_pipeline_kv260_separate.bit.bin
dtc -@ -I dts -O dtb -o doa_pipeline_kv260_separate.dtbo doa_pipeline_kv260_separate.dts
```

Runtime contract:

- `doa_pipeline` register window: `0xA001_0000`
- `axi_dma` register window: `0xA000_0000`
- `/dev/uio0`: `doa_pipeline`
- `/dev/uio1`: `axi_dma`

The existing `kv260_headless/aoa_estimation_fpga_kv260.py` should still work
because it uses UIO device paths and the same register offsets.
