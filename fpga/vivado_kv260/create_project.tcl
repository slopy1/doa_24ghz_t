# create_project.tcl — KV260 DoA Pipeline Vivado Project
#
# Creates a Vivado project for the Kria KV260 (xck26-sfvc784-2LV-c) that
# reuses the doa_pipeline RTL unchanged from the Cora Z7 Phase A bitstream.
#
# Key differences from the Cora Z7 block design (cora_doa_hw):
#   PS IP:          zynq_ultra_ps_e_0  (not processing_system7_0)
#   AXI-Lite master: M_AXI_HPM0_FPD   (not M_AXI_GP0)
#   HP slave:        S_AXI_HP0_FPD    (not S_AXI_HP0)
#   HPM0_FPD aperture: 0xA000_0000 (NOT 0x8000_0000 — that is HPM0_LPD)
#     axi_dma_0      → 0xA000_0000, 64 KB
#     doa_pipeline_0 → 0xA001_0000, 64 KB
#   Control fabric: two smartconnects (legacy axi_interconnect deprecated)
#     axi_smc_ctrl_0 → AXI-Lite control path
#     axi_smc_0      → DMA data-return path to S_AXI_HP0_FPD
#   PL clock:       from PS FCLK only  (no on-board PL oscillator on KV260)
#
# Usage (from Vivado Tcl console or vivado -mode batch):
#   source create_project.tcl
#
# After running:
#   1. Run Block Automation to apply KV260 board preset (configures DDR4, etc.)
#   2. Add remaining IP and wire connections per the block design guide
#   3. Validate, synthesise, implement, generate bitstream
#   4. Convert: bootgen -image doa.bif -arch zynqmp -process_bitstream bin
#   5. Deploy: sudo fpgautil -b doa.bit.bin -o doa.dtbo -f Full -n Full

set project_name "kv260_doa_hw"
set project_dir  "[file dirname [info script]]/project"
set part         "xck26-sfvc784-2LV-c"
set board        "xilinx.com:kv260_som:part0:1.4"

# RTL sources (shared with Cora — vendor-neutral Verilog)
set rtl_dir "[file dirname [info script]]/../rtl"

create_project $project_name $project_dir -part $part -force
set_property board_part $board [current_project]

# Add all RTL sources
add_files -norecurse [glob $rtl_dir/*.v]
update_compile_order -fileset sources_1

# ─── Block Design ──────────────────────────────────────────────────────────
create_bd_design "kv260_doa"
current_bd_design kv260_doa

# PS — Zynq UltraScale+ MPSoC
create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e:* zynq_ultra_ps_e_0
# apply_bd_automation applies the KV260 board preset (DDR4, QSPI, etc.)
# apply_board_preset is NOT a valid standalone command — must use apply_bd_automation.
apply_bd_automation \
    -rule xilinx.com:bd_rule:zynq_ultra_ps_e \
    -config {apply_board_preset "1"} \
    [get_bd_cells zynq_ultra_ps_e_0]
# Enable HPM0_FPD (AXI master → PL control) and HP0_FPD (DMA → DDR).
# PSU__USE__M_AXI_GP0 = M_AXI_HPM0_FPD
# PSU__USE__S_AXI_GP2 = S_AXI_HP0_FPD  (GP2 maps to HP0 in ZU+ IP naming)
set_property -dict [list \
    CONFIG.PSU__USE__M_AXI_GP0  {1} \
    CONFIG.PSU__USE__M_AXI_GP1  {0} \
    CONFIG.PSU__MAXIGP0__DATA_WIDTH {32} \
    CONFIG.PSU__USE__S_AXI_GP2  {1} \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ {100} \
    CONFIG.PSU__FPGA_PL0_ENABLE {1} \
] [get_bd_cells zynq_ultra_ps_e_0]

# Processor System Reset (put back — direct pl_resetn0 wiring wedges AXI on KV260)
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:* proc_sys_reset_0
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_clk0] \
               [get_bd_pins proc_sys_reset_0/slowest_sync_clk]
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_resetn0] \
               [get_bd_pins proc_sys_reset_0/ext_reset_in]

# AXI DMA (Scatter-Gather, MM2S only — same as Cora design)
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:* axi_dma_0
set_property -dict [list \
    CONFIG.c_include_sg        {1} \
    CONFIG.c_sg_include_stscntrl_strm {0} \
    CONFIG.c_include_mm2s      {1} \
    CONFIG.c_include_s2mm      {0} \
    CONFIG.c_m_axi_mm2s_data_width {32} \
    CONFIG.c_sg_length_width   {23} \
] [get_bd_cells axi_dma_0]

# doa_pipeline (module_ref — same RTL as Phase A)
# RTL no longer hardcodes FREQ_HZ in X_INTERFACE_PARAMETER, so IP Integrator
# auto-propagates pl_clk0's actual frequency (~49,999,500 Hz) to the interfaces.
create_bd_cell -type module -reference doa_pipeline doa_pipeline_0

# SmartConnect for AXI-Lite control path (PS master → doa_pipeline + axi_dma).
# Replaces legacy axi_interconnect. smartconnect auto-handles clock domain
# crossing, data-width conversion, and uses a single aclk/aresetn per instance.
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:* axi_smc_ctrl_0
set_property -dict [list \
    CONFIG.NUM_SI {1} \
    CONFIG.NUM_MI {2} \
] [get_bd_cells axi_smc_ctrl_0]

# Clock connections — single pl_clk0 domain drives everything.
set pl_clk [get_bd_pins zynq_ultra_ps_e_0/pl_clk0]
foreach pin [list \
    zynq_ultra_ps_e_0/maxihpm0_fpd_aclk \
    zynq_ultra_ps_e_0/saxihp0_fpd_aclk \
    axi_dma_0/s_axi_lite_aclk \
    axi_dma_0/m_axi_sg_aclk \
    axi_dma_0/m_axi_mm2s_aclk \
    doa_pipeline_0/s_axi_aclk \
    axi_smc_ctrl_0/aclk \
] { connect_bd_net $pl_clk [get_bd_pins $pin] }

# Reset connections
set aresetn [get_bd_pins proc_sys_reset_0/peripheral_aresetn]
foreach pin [list \
    axi_dma_0/axi_resetn \
    doa_pipeline_0/s_axi_aresetn \
    axi_smc_ctrl_0/aresetn \
] { connect_bd_net $aresetn [get_bd_pins $pin] }

# AXI-Lite control path:
#   PS M_AXI_HPM0_FPD → smartconnect → doa_pipeline_0 (M00)
#                                      → axi_dma_0     (M01)
connect_bd_intf_net [get_bd_intf_pins zynq_ultra_ps_e_0/M_AXI_HPM0_FPD] \
                    [get_bd_intf_pins axi_smc_ctrl_0/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_smc_ctrl_0/M00_AXI] \
                    [get_bd_intf_pins doa_pipeline_0/s_axi]
connect_bd_intf_net [get_bd_intf_pins axi_smc_ctrl_0/M01_AXI] \
                    [get_bd_intf_pins axi_dma_0/S_AXI_LITE]

# DMA data path: axi_dma_0 MM2S → doa_pipeline_0 AXI-Stream
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXIS_MM2S] \
                    [get_bd_intf_pins doa_pipeline_0/s_axis]

# DMA scatter-gather + buffer path: axi_dma_0 → PS S_AXI_HP0_FPD (DDR)
# Two AXI masters (M_AXI_SG and M_AXI_MM2S) cannot connect to one AXI slave
# interface directly — BD validation will reject it. SmartConnect merges them.
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:* axi_smc_0
set_property CONFIG.NUM_SI {2} [get_bd_cells axi_smc_0]
connect_bd_net $pl_clk    [get_bd_pins axi_smc_0/aclk]
connect_bd_net $aresetn   [get_bd_pins axi_smc_0/aresetn]

connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXI_SG]   [get_bd_intf_pins axi_smc_0/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXI_MM2S] [get_bd_intf_pins axi_smc_0/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_smc_0/M00_AXI]    [get_bd_intf_pins zynq_ultra_ps_e_0/S_AXI_HP0_FPD]

# ─── Address Editor ────────────────────────────────────────────────────────
# ZU+ HPM0_FPD aperture on KV260 starts at 0xA000_0000 (NOT 0x8000_0000 — that
# is HPM0_LPD). Vivado reports valid apertures as:
#     <0xA000_0000 [ 256M ]>, <0x4_0000_0000 [ 4G ]>, <0x10_0000_0000 [ 224G ]>
#
# Auto-assignment places IPs in alphabetical cell name order:
#     axi_dma_0/S_AXI_LITE/Reg   → 0xA000_0000
#     doa_pipeline_0/s_axi/reg0  → 0xA001_0000
#
# We accept that layout — the driver uses UIO paths (/dev/uio0 = doa_pipeline,
# /dev/uio1 = axi_dma), not hardcoded physical addresses. UIO numbering follows
# device-tree node order, NOT physical address order: doa_pipeline.dts lists
# doa_pipeline FIRST so it becomes uio0 regardless of its address.
#
# Force both ranges to 64 KB so there is headroom for register-map growth and
# the DTS reg-size matches exactly.
assign_bd_address
# Explicitly pin offsets + ranges so the map is stable against cell renames or
# future AXI slave additions. These values match what auto-assignment chose
# alphabetically, so set_property here is idempotent — no conflict.
set_property offset 0xA0000000 [get_bd_addr_segs {zynq_ultra_ps_e_0/Data/SEG_axi_dma_0_Reg}]
set_property range  64K        [get_bd_addr_segs {zynq_ultra_ps_e_0/Data/SEG_axi_dma_0_Reg}]
set_property offset 0xA0010000 [get_bd_addr_segs {zynq_ultra_ps_e_0/Data/SEG_doa_pipeline_0_reg0}]
set_property range  64K        [get_bd_addr_segs {zynq_ultra_ps_e_0/Data/SEG_doa_pipeline_0_reg0}]

# ─── Generate and wrap ─────────────────────────────────────────────────────
validate_bd_design
save_bd_design
make_wrapper -files [get_files kv260_doa.bd] -top
add_files -norecurse $project_dir/${project_name}.gen/sources_1/bd/kv260_doa/hdl/kv260_doa_wrapper.v
set_property top kv260_doa_wrapper [current_fileset]
update_compile_order -fileset sources_1

puts "Block design created. Next steps:"
puts "  1. Review address assignments in Address Editor (GUI or uncomment above)"
puts "  2. Run synthesis, implementation, generate bitstream"
puts "  3. Convert .bit to .bit.bin with bootgen"
puts "  4. Compile doa.dts to doa.dtbo"
puts "  5. Deploy with fpgautil or xmutil"
