# KV260 carrier fan-gate constraint.
#
# UG1089 §Fan and Heat Sink: "the fan gating signal is connected to a FPGA HD
# I/O bank pin for control." None of our bitstreams drive this pin, so every
# load has been shutting the fan off and riding into thermal shutdown in
# 15-60 s. Drive it constant HIGH (fan always on) so the board survives long
# enough to capture ILA data.
#
# Pin: package ball A12, LVCMOS33. Confirmed by:
#   - Hackster "KV260 Temperature Controlled Cooling Fan" (Tai-Min, Vivado
#     2021.1, tested): PACKAGE_PIN A12, IOSTANDARD LVCMOS33.
#   - Polarity from the same project's pwm.v: reset default state = 1'b1 and
#     duty-cycle-on maps to state=1 -> active high -> drive 1 to turn fan on.
#
# Expects a top-level output port named `fan_en`. TCL must create the port
# and tie it to an xlconstant(CONST_VAL 1, CONST_WIDTH 1).
set_property PACKAGE_PIN A12      [get_ports {fan_en}]
set_property IOSTANDARD  LVCMOS33 [get_ports {fan_en}]
