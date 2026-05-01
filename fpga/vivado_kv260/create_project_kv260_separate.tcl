# create_project_kv260_separate.tcl
#
# Separate KV260 FPGA-side Vivado project. This script intentionally does not
# modify or depend on fpga/vivado_kv260/create_project.tcl. It builds the
# standalone RTL top in:
#
#   fpga/rtl/doa_pipeline_kv260_separate.v
#
# Software-visible address contract:
#   axi_dma_0      S_AXI_LITE -> 0xA000_0000, 64 KB
#   doa_pipeline_0 s_axi      -> 0xA001_0000, 64 KB
#
# Run from Vivado:
#   vivado -mode batch -source create_project_kv260_separate.tcl

set project_name "kv260_doa_fpga_side"
set project_dir  "[file dirname [info script]]/project_fpga_side"
set part         "xck26-sfvc784-2LV-c"
set board        "xilinx.com:kv260_som:part0:1.4"
set rtl_file     "[file normalize [file join [file dirname [info script]] .. rtl doa_pipeline_kv260_separate.v]]"

create_project $project_name $project_dir -part $part -force
set_property board_part $board [current_project]

add_files -norecurse $rtl_file
update_compile_order -fileset sources_1

create_bd_design "kv260_doa_fpga_side"
current_bd_design kv260_doa_fpga_side

# Zynq UltraScale+ MPSoC with KV260 board preset.
create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e:* zynq_ultra_ps_e_0
apply_bd_automation \
    -rule xilinx.com:bd_rule:zynq_ultra_ps_e \
    -config {apply_board_preset "1"} \
    [get_bd_cells zynq_ultra_ps_e_0]

# Enable one FPD AXI master for control and one FPD HP slave for DMA reads.
set_property -dict [list \
    CONFIG.PSU__USE__M_AXI_GP0 {1} \
    CONFIG.PSU__USE__M_AXI_GP1 {0} \
    CONFIG.PSU__MAXIGP0__DATA_WIDTH {32} \
    CONFIG.PSU__USE__S_AXI_GP2 {1} \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ {100} \
    CONFIG.PSU__FPGA_PL0_ENABLE {1} \
] [get_bd_cells zynq_ultra_ps_e_0]

create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:* proc_sys_reset_0
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_clk0] \
               [get_bd_pins proc_sys_reset_0/slowest_sync_clk]
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_resetn0] \
               [get_bd_pins proc_sys_reset_0/ext_reset_in]

# MM2S-only scatter-gather DMA. The ARM writes SC16 snapshots into udmabuf,
# then the DMA streams those snapshots into the RTL top.
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:* axi_dma_0
set_property -dict [list \
    CONFIG.c_include_sg {1} \
    CONFIG.c_sg_include_stscntrl_strm {0} \
    CONFIG.c_include_mm2s {1} \
    CONFIG.c_include_s2mm {0} \
    CONFIG.c_m_axi_mm2s_data_width {32} \
    CONFIG.c_sg_length_width {23} \
] [get_bd_cells axi_dma_0]

create_bd_cell -type module -reference doa_pipeline_kv260_separate doa_pipeline_0

# Control path: PS HPM0_FPD -> SmartConnect -> pipeline and DMA AXI-Lite.
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:* axi_smc_ctrl_0
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {2}] [get_bd_cells axi_smc_ctrl_0]

set pl_clk [get_bd_pins zynq_ultra_ps_e_0/pl_clk0]
foreach pin [list \
    zynq_ultra_ps_e_0/maxihpm0_fpd_aclk \
    zynq_ultra_ps_e_0/saxihp0_fpd_aclk \
    axi_dma_0/s_axi_lite_aclk \
    axi_dma_0/m_axi_sg_aclk \
    axi_dma_0/m_axi_mm2s_aclk \
    doa_pipeline_0/s_axi_aclk \
    axi_smc_ctrl_0/aclk \
] {
    connect_bd_net $pl_clk [get_bd_pins $pin]
}

set aresetn [get_bd_pins proc_sys_reset_0/peripheral_aresetn]
foreach pin [list \
    axi_dma_0/axi_resetn \
    doa_pipeline_0/s_axi_aresetn \
    axi_smc_ctrl_0/aresetn \
] {
    connect_bd_net $aresetn [get_bd_pins $pin]
}

connect_bd_intf_net [get_bd_intf_pins zynq_ultra_ps_e_0/M_AXI_HPM0_FPD] \
                    [get_bd_intf_pins axi_smc_ctrl_0/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_smc_ctrl_0/M00_AXI] \
                    [get_bd_intf_pins doa_pipeline_0/s_axi]
connect_bd_intf_net [get_bd_intf_pins axi_smc_ctrl_0/M01_AXI] \
                    [get_bd_intf_pins axi_dma_0/S_AXI_LITE]

connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXIS_MM2S] \
                    [get_bd_intf_pins doa_pipeline_0/s_axis]

# DMA read masters -> PS DDR through HP0_FPD.
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:* axi_smc_0
set_property CONFIG.NUM_SI {2} [get_bd_cells axi_smc_0]
connect_bd_net $pl_clk  [get_bd_pins axi_smc_0/aclk]
connect_bd_net $aresetn [get_bd_pins axi_smc_0/aresetn]
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXI_SG] \
                    [get_bd_intf_pins axi_smc_0/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXI_MM2S] \
                    [get_bd_intf_pins axi_smc_0/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_smc_0/M00_AXI] \
                    [get_bd_intf_pins zynq_ultra_ps_e_0/S_AXI_HP0_FPD]

# Stable address map. These addresses match the separate DTS overlay.
assign_bd_address
set dma_seg  [get_bd_addr_segs -quiet {zynq_ultra_ps_e_0/Data/SEG_axi_dma_0_Reg}]
set pipe_seg [get_bd_addr_segs -quiet {zynq_ultra_ps_e_0/Data/SEG_doa_pipeline_0_reg0}]
if {[llength $dma_seg] == 0} {
    error "Could not find DMA AXI-Lite address segment"
}
if {[llength $pipe_seg] == 0} {
    error "Could not find doa_pipeline AXI-Lite address segment"
}
set_property offset 0xA0000000 $dma_seg
set_property range  64K        $dma_seg
set_property offset 0xA0010000 $pipe_seg
set_property range  64K        $pipe_seg

# Fan-gate (UG1089): tie PL HD bank pin A12 HIGH so the carrier fan stays
# on whenever this bitstream is loaded. Without this, loading any custom
# bitstream turns the fan off and the board thermally shuts down within
# 15-60 s (see docs/CHANGELOG.md 2026-04-24). XDC is repo-relative so
# this works on any Vivado host.
set fan_on [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 fan_on]
set_property -dict [list CONFIG.CONST_WIDTH {1} CONFIG.CONST_VAL {1}] $fan_on
create_bd_port -dir O fan_en
connect_bd_net [get_bd_pins fan_on/dout] [get_bd_ports fan_en]

set fan_xdc [file normalize [file join [file dirname [info script]] constraints kv260_fan_gate.xdc]]
add_files -fileset constrs_1 $fan_xdc

validate_bd_design
save_bd_design
make_wrapper -files [get_files kv260_doa_fpga_side.bd] -top
add_files -norecurse $project_dir/${project_name}.gen/sources_1/bd/kv260_doa_fpga_side/hdl/kv260_doa_fpga_side_wrapper.v
set_property top kv260_doa_fpga_side_wrapper [current_fileset]
update_compile_order -fileset sources_1

puts "Created separate KV260 FPGA-side project: $project_dir"
puts "Next:"
puts "  launch_runs synth_1 -jobs 4"
puts "  launch_runs impl_1 -to_step write_bitstream -jobs 4"
puts "  bootgen -arch zynqmp -process_bitstream bin -image system.bif -w -o doa_pipeline_kv260_separate.bit.bin"
puts "  dtc -@ -I dts -O dtb -o doa_pipeline_kv260_separate.dtbo doa_pipeline_kv260_separate.dts"
