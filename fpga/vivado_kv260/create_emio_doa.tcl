# create_emio_doa.tcl -- KV260 DoA build using EMIO for pipeline CSRs
#
# This keeps the data path from the existing KV260 design:
#   udmabuf DDR -> axi_dma_0 MM2S -> doa_pipeline_0/s_axis
#
# The doa_pipeline register path changes:
#   PS GPIO_EMIO -> emio_regfile_0 -> doa_pipeline_0/s_axi
#
# The broken PS M_AXI_HPM0_FPD path is not used for doa_pipeline control.
# HPM0_FPD remains only for dma_safe_ctrl_0, whose software-visible registers
# are spaced 16 bytes apart. The shim then programs axi_dma_0/S_AXI_LITE from
# inside PL, so DMA CURDESC at real offset 0x08 is no longer written directly
# by the PS.
#
# Run:
#   vivado -mode batch -source create_emio_doa.tcl

set project_name "kv260_emio_doa"
set project_dir  "[file dirname [info script]]/project_emio_doa"
set part         "xck26-sfvc784-2LV-c"
set board        "xilinx.com:kv260_som:part0:1.4"
set rtl_dir      "[file normalize [file join [file dirname [info script]] .. rtl]]"

create_project $project_name $project_dir -part $part -force
set_property board_part $board [current_project]

add_files -norecurse [glob $rtl_dir/*.v]
update_compile_order -fileset sources_1

create_bd_design "kv260_emio_doa"
current_bd_design kv260_emio_doa

# PS -- board preset, then the AMD kv260_bist-style override block that keeps
# GPIO_EMIO enabled. EMIO width stays 92 so Linux line numbering remains the
# standard ZynqMP GPIO map; this design uses only EMIO bits 0..73.
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e:* ps]
apply_bd_automation \
    -rule xilinx.com:bd_rule:zynq_ultra_ps_e \
    -config {apply_board_preset "1"} \
    $ps

set_property -dict [ list \
   CONFIG.PSU__CRF_APB__DPLL_FRAC_CFG__ENABLED  {1} \
   CONFIG.PSU__CRF_APB__VPLL_FRAC_CFG__ENABLED  {1} \
   CONFIG.PSU__CRL_APB__PL1_REF_CTRL__DIVISOR1 {1} \
   CONFIG.PSU__CRL_APB__PL1_REF_CTRL__SRCSEL {IOPLL} \
   CONFIG.PSU__CRL_APB__USB3__ENABLE {1} \
   CONFIG.PSU__FPGA_PL0_ENABLE {1} \
   CONFIG.PSU__GPIO_EMIO__PERIPHERAL__ENABLE {1} \
   CONFIG.PSU__GPIO_EMIO__PERIPHERAL__IO {92} \
   CONFIG.PSU__TTC0__WAVEOUT__ENABLE {1} \
   CONFIG.PSU__TTC0__WAVEOUT__IO {EMIO} \
   CONFIG.PSU__MAXIGP0__DATA_WIDTH {32} \
   CONFIG.PSU__MAXIGP1__DATA_WIDTH {32} \
   CONFIG.PSU__MAXIGP2__DATA_WIDTH {32} \
   CONFIG.PSU__NUM_FABRIC_RESETS {4} \
   CONFIG.PSU__SAXIGP0__DATA_WIDTH {128} \
   CONFIG.PSU__SAXIGP1__DATA_WIDTH {128} \
   CONFIG.PSU__SAXIGP2__DATA_WIDTH {128} \
   CONFIG.PSU__SAXIGP3__DATA_WIDTH {128} \
   CONFIG.PSU__SAXIGP4__DATA_WIDTH {128} \
   CONFIG.PSU__SAXIGP5__DATA_WIDTH {128} \
   CONFIG.PSU__SAXIGP6__DATA_WIDTH {128} \
   CONFIG.PSU__USE__IRQ0 {1} \
   CONFIG.PSU__USE__IRQ1 {1} \
   CONFIG.PSU__USE__M_AXI_GP0 {1} \
   CONFIG.PSU__USE__M_AXI_GP1 {1} \
   CONFIG.PSU__USE__M_AXI_GP2 {1} \
   CONFIG.PSU__USE__S_AXI_ACE {0} \
   CONFIG.PSU__USE__S_AXI_ACP {0} \
   CONFIG.PSU__USE__S_AXI_GP0 {1} \
   CONFIG.PSU__USE__S_AXI_GP1 {1} \
   CONFIG.PSU__USE__S_AXI_GP2 {1} \
   CONFIG.PSU__USE__S_AXI_GP3 {1} \
   CONFIG.PSU__USE__S_AXI_GP4 {1} \
   CONFIG.PSU__USE__S_AXI_GP5 {1} \
   CONFIG.PSU__USE__S_AXI_GP6 {1} \
 ] $ps

set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:* rst]

# MM2S-only scatter-gather DMA. Register control is reached through
# dma_safe_ctrl_0; data movement uses S_AXI_HP0_FPD, same as the existing
# KV260 design.
set dma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:* axi_dma_0]
set_property -dict [list \
    CONFIG.c_include_sg {1} \
    CONFIG.c_sg_include_stscntrl_strm {0} \
    CONFIG.c_include_mm2s {1} \
    CONFIG.c_include_s2mm {0} \
    CONFIG.c_m_axi_mm2s_data_width {32} \
    CONFIG.c_sg_length_width {23} \
] $dma

create_bd_cell -type module -reference doa_pipeline doa_pipeline_0
create_bd_cell -type module -reference emio_regfile emio_regfile_0
set_property -dict [list CONFIG.EMIO_WIDTH {92}] [get_bd_cells emio_regfile_0]
create_bd_cell -type module -reference dma_safe_ctrl dma_safe_ctrl_0

# HPM0_FPD is retained only for the 16-byte-safe DMA control shim.
set dma_safe_smc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:* axi_smc_dma_safe]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1}] $dma_safe_smc

set dma_data [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:* axi_smc_dma_data]
set_property CONFIG.NUM_SI {2} $dma_data

set pl_clk [get_bd_pins ps/pl_clk0]
connect_bd_net -net pl_clk0 $pl_clk \
    [get_bd_pins ps/maxihpm0_fpd_aclk] \
    [get_bd_pins ps/maxihpm1_fpd_aclk] \
    [get_bd_pins ps/maxihpm0_lpd_aclk] \
    [get_bd_pins ps/saxihpc0_fpd_aclk] \
    [get_bd_pins ps/saxihpc1_fpd_aclk] \
    [get_bd_pins ps/saxihp0_fpd_aclk] \
    [get_bd_pins ps/saxihp1_fpd_aclk] \
    [get_bd_pins ps/saxihp2_fpd_aclk] \
    [get_bd_pins ps/saxihp3_fpd_aclk] \
    [get_bd_pins ps/saxi_lpd_aclk] \
    [get_bd_pins rst/slowest_sync_clk] \
    [get_bd_pins axi_dma_0/s_axi_lite_aclk] \
    [get_bd_pins axi_dma_0/m_axi_sg_aclk] \
    [get_bd_pins axi_dma_0/m_axi_mm2s_aclk] \
    [get_bd_pins doa_pipeline_0/s_axi_aclk] \
    [get_bd_pins emio_regfile_0/clk] \
    [get_bd_pins dma_safe_ctrl_0/clk] \
    [get_bd_pins axi_smc_dma_safe/aclk] \
    [get_bd_pins axi_smc_dma_data/aclk]

connect_bd_net [get_bd_pins ps/pl_resetn0] [get_bd_pins rst/ext_reset_in]
set aresetn [get_bd_pins rst/peripheral_aresetn]
connect_bd_net $aresetn \
    [get_bd_pins axi_dma_0/axi_resetn] \
    [get_bd_pins doa_pipeline_0/s_axi_aresetn] \
    [get_bd_pins emio_regfile_0/resetn] \
    [get_bd_pins dma_safe_ctrl_0/resetn] \
    [get_bd_pins axi_smc_dma_safe/aresetn] \
    [get_bd_pins axi_smc_dma_data/aresetn]

# EMIO line bus. PS GPIO line directions are set from Linux via libgpiod:
# lines 0..39 output from PS; lines 40..73 input to PS.
connect_bd_net [get_bd_pins ps/emio_gpio_o] [get_bd_pins emio_regfile_0/emio_gpio_o]
connect_bd_net [get_bd_pins emio_regfile_0/emio_gpio_i] [get_bd_pins ps/emio_gpio_i]

# Pipeline control path: entirely PL-local AXI-Lite transaction generated by
# emio_regfile_0. There is no PS HPM0 or SmartConnect hop on this path.
connect_bd_intf_net [get_bd_intf_pins emio_regfile_0/m_axi] \
                    [get_bd_intf_pins doa_pipeline_0/s_axi]

# DMA stream and DMA DDR read path.
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXIS_MM2S] \
                    [get_bd_intf_pins doa_pipeline_0/s_axis]
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXI_SG] \
                    [get_bd_intf_pins axi_smc_dma_data/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXI_MM2S] \
                    [get_bd_intf_pins axi_smc_dma_data/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_smc_dma_data/M00_AXI] \
                    [get_bd_intf_pins ps/S_AXI_HP0_FPD]

# DMA AXI-Lite control is reached through a 16-byte-safe shim. Linux maps the
# shim, not the raw axi_dma_0 register file:
#   safe offset 0x00 -> DMA 0x00
#   safe offset 0x10 -> DMA 0x04
#   safe offset 0x20 -> DMA 0x08
#   safe offset 0x40 -> DMA 0x10
connect_bd_intf_net [get_bd_intf_pins ps/M_AXI_HPM0_FPD] \
                    [get_bd_intf_pins axi_smc_dma_safe/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_smc_dma_safe/M00_AXI] \
                    [get_bd_intf_pins dma_safe_ctrl_0/s_axi]
connect_bd_intf_net [get_bd_intf_pins dma_safe_ctrl_0/m_axi] \
                    [get_bd_intf_pins axi_dma_0/S_AXI_LITE]

assign_bd_address
set dma_safe_seg [get_bd_addr_segs -quiet {ps/Data/SEG_dma_safe_ctrl_0_reg0}]
if {[llength $dma_safe_seg] == 0} {
    set dma_safe_seg [get_bd_addr_segs -quiet {ps/Data/SEG_dma_safe_ctrl_0_Reg}]
}
if {[llength $dma_safe_seg] == 0} {
    error "Could not find PS address segment for dma_safe_ctrl_0/s_axi"
}
set_property offset 0xA0000000 $dma_safe_seg
set_property range  64K        $dma_safe_seg

# The shim master drives DMA-local offsets after dividing the safe window by 4.
# Keep the shim's view of the DMA register file based at 0.
set dma_local_seg [get_bd_addr_segs -quiet {dma_safe_ctrl_0/m_axi/SEG_axi_dma_0_Reg}]
if {[llength $dma_local_seg] == 0} {
    set dma_local_seg [get_bd_addr_segs -of_objects [get_bd_intf_pins dma_safe_ctrl_0/m_axi]]
}
if {[llength $dma_local_seg] == 0} {
    error "Could not find dma_safe_ctrl_0/m_axi address segment"
}
set_property offset 0x00000000 $dma_local_seg
set_property range  4K         $dma_local_seg

# Pin the emio_regfile_0 master's view of doa_pipeline at offset 0x0 with a
# 4K range. The master only drives 7 effective address bits
# ({5'b0, emio_addr_s, 2'b00}), so any non-zero base would cause every
# transaction to miss decode and silently return DEADBEEF.
set emio_seg [get_bd_addr_segs -of_objects [get_bd_intf_pins emio_regfile_0/m_axi]]
if {[llength $emio_seg] == 0} {
    error "Could not find emio_regfile_0/m_axi address segment after assign_bd_address"
}
set_property offset 0x00000000 $emio_seg
set_property range  4K          $emio_seg

# Fan-gate: drive carrier fan enable high whenever this bitstream is loaded.
set fan_on [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 fan_on]
set_property -dict [list CONFIG.CONST_WIDTH {1} CONFIG.CONST_VAL {1}] $fan_on
create_bd_port -dir O fan_en
connect_bd_net [get_bd_pins fan_on/dout] [get_bd_ports fan_en]

set fan_xdc [file normalize [file join [file dirname [info script]] constraints kv260_fan_gate.xdc]]
add_files -fileset constrs_1 $fan_xdc

validate_bd_design
save_bd_design
make_wrapper -files [get_files kv260_emio_doa.bd] -top
add_files -norecurse $project_dir/${project_name}.gen/sources_1/bd/kv260_emio_doa/hdl/kv260_emio_doa_wrapper.v
set_property top kv260_emio_doa_wrapper [current_fileset]
update_compile_order -fileset sources_1

puts "Created KV260 EMIO DoA project: $project_dir"
puts "Next:"
puts "  launch_runs synth_1 -jobs 4"
puts "  launch_runs impl_1 -to_step write_bitstream -jobs 4"
puts "  bootgen -arch zynqmp -process_bitstream bin -image emio_doa.bif -w -o emio_doa.bit.bin"
puts "  dtc -@ -I dts -O dtb -o emio_doa.dtbo emio_doa.dts"
