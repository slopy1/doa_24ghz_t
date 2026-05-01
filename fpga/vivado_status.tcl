# vivado_status.tcl — Read-only status snapshot for the Cora DoA Vivado
# project. Reports sources, block-design cells, synth/impl run status +
# timing + utilization, and whether a bitstream exists yet.
#
# Does NOT modify the project. Does NOT launch, reset, or delete runs.
#
# USAGE
# -----
# Batch (on the build VM, no GUI, no project currently open — best for a
# quick one-shot snapshot or polling over SSH):
#
#     cd ~   # or anywhere writable for .jou / .log
#     vivado -mode batch -notrace -source /path/to/fpga/vivado_status.tcl
#
# Interactive (inside the Vivado Tcl console with the project already
# open — best while a run is in progress, since this re-uses the live
# project and sees up-to-the-moment state):
#
#     source /path/to/fpga/vivado_status.tcl
#
# NOTE: Vivado holds a write lock on an open project. If the GUI has the
# project open, batch mode will fail to open it and print an error. In
# that case use the interactive path instead.

set project_xpr "/home/vmau/tools/projects/cora-linux/cora_doa_hw/cora_doa_hw.xpr"

# --- open project only if nothing is open ---
set opened_here 0
if {[catch {current_project} err]} {
    if {![file exists $project_xpr]} {
        puts stderr "ERROR: no project is open and $project_xpr does not exist"
        return
    }
    if {[catch {open_project $project_xpr} oe]} {
        puts stderr "ERROR: could not open $project_xpr"
        puts stderr "       $oe"
        puts stderr "       (is the project already open in the Vivado GUI?)"
        return
    }
    set opened_here 1
}

set proj      [current_project]
set proj_name [get_property NAME      $proj]
set proj_dir  [get_property DIRECTORY $proj]
set proj_part [get_property PART      $proj]

puts ""
puts "================================================================"
puts "  Cora DoA project status"
puts "================================================================"
puts "  project      : $proj_name"
puts "  directory    : $proj_dir"
puts "  target part  : $proj_part"
puts "  top module   : [get_property top [current_fileset]]"

# --- HDL sources -------------------------------------------------------
puts ""
puts "-- HDL sources --"
set hdl [list]
foreach f [get_files -of_objects [get_filesets sources_1]] {
    set ft [get_property FILE_TYPE [get_files $f]]
    if {$ft eq "Verilog" || $ft eq "SystemVerilog" || $ft eq "VHDL"} {
        lappend hdl $f
    }
}
puts "  count        : [llength $hdl]"
foreach f $hdl {
    set name [file tail $f]
    set ft   [get_property FILE_TYPE [get_files $f]]
    puts [format "    %-32s (%s)" $name $ft]
}

# --- block designs -----------------------------------------------------
foreach bd [get_files -filter {FILE_TYPE == "Block Designs"}] {
    set bd_name [file rootname [file tail $bd]]
    puts ""
    puts "-- block design: $bd_name --"
    if {[catch {current_bd_design [get_bd_designs $bd_name]} e]} {
        puts "  (could not make current: $e)"
        continue
    }
    set cells [get_bd_cells]
    puts "  cells ([llength $cells]):"
    foreach c $cells {
        set name [get_property NAME $c]
        if {[catch {set vlnv [get_property VLNV $c]}]} { set vlnv "?" }
        puts [format "    %-24s %s" $name $vlnv]
    }
}

# --- runs (synth_1, impl_1, …) -----------------------------------------
puts ""
puts "-- runs --"
foreach run [get_runs] {
    puts ""
    puts "  [get_property NAME $run]"
    puts "    status         : [get_property STATUS        $run]"
    puts "    progress       : [get_property PROGRESS      $run]"
    puts "    needs refresh  : [get_property NEEDS_REFRESH $run]"
    # STATS.* only populate after the run produces a checkpoint. Wrap
    # each in its own catch so a missing property doesn't abort the loop.
    foreach p {
        STATS.WNS  STATS.TNS  STATS.WHS  STATS.THS
        STATS.SLICE_LUTS STATS.SLICE_FFS STATS.BRAMS STATS.DSPS
    } {
        if {[catch {set v [get_property $p $run]}]} { continue }
        if {$v eq ""} { continue }
        puts [format "    %-15s: %s" $p $v]
    }
}

# --- bitstream ---------------------------------------------------------
puts ""
puts "-- bitstream --"
set impl_dir [file join $proj_dir "${proj_name}.runs" impl_1]
set bitfiles [glob -nocomplain -directory $impl_dir *.bit]
if {[llength $bitfiles] == 0} {
    puts "  none yet"
    puts "  expected at: $impl_dir/<top>.bit once write_bitstream completes"
} else {
    foreach b $bitfiles {
        puts "  [file tail $b]"
        puts "    path  : $b"
        puts "    size  : [file size $b] bytes"
        puts "    mtime : [clock format [file mtime $b] -format {%Y-%m-%d %H:%M:%S}]"
    }
}

puts ""
puts "================================================================"

# --- leave project state untouched ------------------------------------
# If we opened the project ourselves (batch mode), close it so we don't
# leave a write lock behind. If it was already open (interactive), don't
# touch it.
if {$opened_here} {
    close_project
}
