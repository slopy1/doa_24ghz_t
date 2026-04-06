#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: BladeRF AoA Estimation (Root-MUSIC)
# Author: DoA Thesis Project
# Description: Real-time Direction of Arrival estimation using Root-MUSIC
# GNU Radio version: 3.10.12.0

from PyQt5 import Qt
from gnuradio import qtgui
from PyQt5 import QtCore
from gnuradio import analog
from gnuradio import filter
from gnuradio.filter import firdes
from gnuradio import gr
from gnuradio.fft import window
import sys
import signal
from PyQt5 import Qt
from argparse import ArgumentParser
from gnuradio.eng_arg import eng_float, intx
from gnuradio import eng_notation
from gnuradio import soapy
import gnuradio.aoa as aoa
import sip
import threading



class aoa_estimation_bladerf(gr.top_block, Qt.QWidget):

    def __init__(self):
        gr.top_block.__init__(self, "BladeRF AoA Estimation (Root-MUSIC)", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("BladeRF AoA Estimation (Root-MUSIC)")
        qtgui.util.check_set_qss()
        try:
            self.setWindowIcon(Qt.QIcon.fromTheme('gnuradio-grc'))
        except BaseException as exc:
            print(f"Qt GUI: Could not set Icon: {str(exc)}", file=sys.stderr)
        self.top_scroll_layout = Qt.QVBoxLayout()
        self.setLayout(self.top_scroll_layout)
        self.top_scroll = Qt.QScrollArea()
        self.top_scroll.setFrameStyle(Qt.QFrame.NoFrame)
        self.top_scroll_layout.addWidget(self.top_scroll)
        self.top_scroll.setWidgetResizable(True)
        self.top_widget = Qt.QWidget()
        self.top_scroll.setWidget(self.top_widget)
        self.top_layout = Qt.QVBoxLayout(self.top_widget)
        self.top_grid_layout = Qt.QGridLayout()
        self.top_layout.addLayout(self.top_grid_layout)

        self.settings = Qt.QSettings("gnuradio/flowgraphs", "aoa_estimation_bladerf")

        try:
            geometry = self.settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)
        except BaseException as exc:
            print(f"Qt GUI: Could not restore geometry: {str(exc)}", file=sys.stderr)
        self.flowgraph_started = threading.Event()

        ##################################################
        # Variables
        ##################################################
        self.phase_cal_deg = phase_cal_deg = 0
        self.tone_freq = tone_freq = 50e3
        self.snapshot_size = snapshot_size = 1024
        self.sample_rate = sample_rate = 1e6
        self.rx_gain = rx_gain = 40
        self.phase_cal_rad = phase_cal_rad = phase_cal_deg * 3.14159265359 / 180.0
        self.center_freq = center_freq = 2.42e9
        self.antenna_spacing = antenna_spacing = 0.5

        ##################################################
        # Blocks
        ##################################################

        self.soapy_bladerf_source_0 = None
        # Make sure that the gain mode is valid
        if('Overall' not in ['Overall', 'Specific', 'Settings Field']):
            raise ValueError("Wrong gain mode on channel 0. Allowed gain modes: "
                  "['Overall', 'Specific', 'Settings Field']")
        if('Overall' not in ['Overall', 'Specific', 'Settings Field']):
            raise ValueError("Wrong gain mode on channel 1. Allowed gain modes: "
                  "['Overall', 'Specific', 'Settings Field']")

        dev = 'driver=bladerf'

        # Stream arguments
        stream_args = ''

        # Tune arguments for every activated stream
        tune_args = ['', '']
        settings = ['', '']

        # Setup the device arguments
        dev_args = ''

        self.soapy_bladerf_source_0 = soapy.source(dev, "fc32", 2, dev_args,
                                  stream_args, tune_args, settings)

        self.soapy_bladerf_source_0.set_sample_rate(0, sample_rate)
        self.soapy_bladerf_source_0.set_sample_rate(1, sample_rate)



        def __gr_bool(v):
            if isinstance(v, bool):
                return v
            return str(v).strip().lower() in ('1', 'true', 'yes', 'on')

        # Some SoapySDR drivers (including certain bladeRF backends) do not
        # support the DC removal API and will throw if called.
        # This must not crash the whole flowgraph.
        try:
            self.soapy_bladerf_source_0.set_dc_offset_mode(0,__gr_bool(False))
        except (ValueError, TypeError):
            pass
        try:
            self.soapy_bladerf_source_0.set_dc_offset_mode(1,__gr_bool(False))
        except (ValueError, TypeError):
            pass

        # Set up DC offset. If set to (0, 0) internally the source block
        # will handle the case if no DC offset correction is supported
        self.soapy_bladerf_source_0.set_dc_offset(0,0)
        self.soapy_bladerf_source_0.set_dc_offset(1,0)

        # Setup IQ Balance. If set to (0, 0) internally the source block
        # will handle the case if no IQ balance correction is supported
        self.soapy_bladerf_source_0.set_iq_balance(0,0)
        self.soapy_bladerf_source_0.set_iq_balance(1,0)

        self.soapy_bladerf_source_0.set_gain_mode(0,False)
        self.soapy_bladerf_source_0.set_gain_mode(1,False)

        # generic frequency setting should be specified first
        self.soapy_bladerf_source_0.set_frequency(0, center_freq)
        self.soapy_bladerf_source_0.set_frequency(1, center_freq)

        self.soapy_bladerf_source_0.set_frequency(0,"BB",0)
        self.soapy_bladerf_source_0.set_frequency(1,"BB",0)

        # Setup Frequency correction. If set to 0 internally the source block
        # will handle the case if no frequency correction is supported
        self.soapy_bladerf_source_0.set_frequency_correction(0,0)
        self.soapy_bladerf_source_0.set_frequency_correction(1,0)

        self.soapy_bladerf_source_0.set_antenna(0,'RX')
        self.soapy_bladerf_source_0.set_antenna(1,'RX')

        self.soapy_bladerf_source_0.set_bandwidth(0,0)
        self.soapy_bladerf_source_0.set_bandwidth(1,0)

        if('Overall' != 'Settings Field'):
            # pass is needed, in case the template does not evaluare anything
            pass
            self.soapy_bladerf_source_0.set_gain(0,10)


        if('Overall' != 'Settings Field'):
            # pass is needed, in case the template does not evaluare anything
            pass
            self.soapy_bladerf_source_0.set_gain(1,10)
        self._rx_gain_range = qtgui.Range(0, 60, 1, 40, 200)
        self._rx_gain_win = qtgui.RangeWidget(self._rx_gain_range, self.set_rx_gain, "RX Gain (dB)", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_grid_layout.addWidget(self._rx_gain_win, 0, 0, 1, 1)
        for r in range(0, 1):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 1):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.qtgui_vector_sink_f_0 = qtgui.vector_sink_f(
            1024,
            0,
            (180.0/1024),
            "Angle (deg)",
            "Power (dB)",
            "MUSIC Pseudo-Spectrum",
            1, # Number of inputs
            None # parent
        )
        self.qtgui_vector_sink_f_0.set_update_time(0.2)
        self.qtgui_vector_sink_f_0.set_y_axis((-60), 0)
        self.qtgui_vector_sink_f_0.enable_autoscale(False)
        self.qtgui_vector_sink_f_0.enable_grid(True)
        self.qtgui_vector_sink_f_0.set_x_axis_units("deg")
        self.qtgui_vector_sink_f_0.set_y_axis_units("dB")
        self.qtgui_vector_sink_f_0.set_ref_level(0)


        labels = ['MUSIC Spectrum', '', '', '', '',
            '', '', '', '', '']
        widths = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        colors = ["blue", "red", "green", "black", "cyan",
            "magenta", "yellow", "dark red", "dark green", "dark blue"]
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0, 1.0]

        for i in range(1):
            if len(labels[i]) == 0:
                self.qtgui_vector_sink_f_0.set_line_label(i, "Data {0}".format(i))
            else:
                self.qtgui_vector_sink_f_0.set_line_label(i, labels[i])
            self.qtgui_vector_sink_f_0.set_line_width(i, widths[i])
            self.qtgui_vector_sink_f_0.set_line_color(i, colors[i])
            self.qtgui_vector_sink_f_0.set_line_alpha(i, alphas[i])

        self._qtgui_vector_sink_f_0_win = sip.wrapinstance(self.qtgui_vector_sink_f_0.qwidget(), Qt.QWidget)
        self.top_grid_layout.addWidget(self._qtgui_vector_sink_f_0_win, 4, 0, 2, 2)
        for r in range(4, 6):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 2):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.qtgui_time_sink_x_0 = qtgui.time_sink_f(
            5000, #size
            sample_rate/snapshot_size, #samp_rate
            "AoA Time Series", #name
            1, #number of inputs
            None # parent
        )
        self.qtgui_time_sink_x_0.set_update_time(0.1)
        self.qtgui_time_sink_x_0.set_y_axis(0, 180)

        self.qtgui_time_sink_x_0.set_y_label('Angle (deg)', "")

        self.qtgui_time_sink_x_0.enable_tags(True)
        self.qtgui_time_sink_x_0.set_trigger_mode(qtgui.TRIG_MODE_FREE, qtgui.TRIG_SLOPE_POS, 0.0, 0, 0, "")
        self.qtgui_time_sink_x_0.enable_autoscale(False)
        self.qtgui_time_sink_x_0.enable_grid(True)
        self.qtgui_time_sink_x_0.enable_axis_labels(True)
        self.qtgui_time_sink_x_0.enable_control_panel(False)
        self.qtgui_time_sink_x_0.enable_stem_plot(False)


        labels = ['AoA', 'Signal 2', 'Signal 3', 'Signal 4', 'Signal 5',
            'Signal 6', 'Signal 7', 'Signal 8', 'Signal 9', 'Signal 10']
        widths = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        colors = ['blue', 'red', 'green', 'black', 'cyan',
            'magenta', 'yellow', 'dark red', 'dark green', 'dark blue']
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0, 1.0]
        styles = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        markers = [-1, -1, -1, -1, -1,
            -1, -1, -1, -1, -1]


        for i in range(1):
            if len(labels[i]) == 0:
                self.qtgui_time_sink_x_0.set_line_label(i, "Data {0}".format(i))
            else:
                self.qtgui_time_sink_x_0.set_line_label(i, labels[i])
            self.qtgui_time_sink_x_0.set_line_width(i, widths[i])
            self.qtgui_time_sink_x_0.set_line_color(i, colors[i])
            self.qtgui_time_sink_x_0.set_line_style(i, styles[i])
            self.qtgui_time_sink_x_0.set_line_marker(i, markers[i])
            self.qtgui_time_sink_x_0.set_line_alpha(i, alphas[i])

        self._qtgui_time_sink_x_0_win = sip.wrapinstance(self.qtgui_time_sink_x_0.qwidget(), Qt.QWidget)
        self.top_grid_layout.addWidget(self._qtgui_time_sink_x_0_win, 2, 0, 2, 2)
        for r in range(2, 4):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 2):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.qtgui_number_sink_0 = qtgui.number_sink(
            gr.sizeof_float,
            0.1,
            qtgui.NUM_GRAPH_HORIZ,
            1,
            None # parent
        )
        self.qtgui_number_sink_0.set_update_time(0.1)
        self.qtgui_number_sink_0.set_title("Angle of Arrival (deg)")

        labels = ['AoA', '', '', '', '',
            '', '', '', '', '']
        units = ['deg', '', '', '', '',
            '', '', '', '', '']
        colors = [("blue", "red"), ("black", "black"), ("black", "black"), ("black", "black"), ("black", "black"),
            ("black", "black"), ("black", "black"), ("black", "black"), ("black", "black"), ("black", "black")]
        factor = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]

        for i in range(1):
            self.qtgui_number_sink_0.set_min(i, 0)
            self.qtgui_number_sink_0.set_max(i, 180)
            self.qtgui_number_sink_0.set_color(i, colors[i][0], colors[i][1])
            if len(labels[i]) == 0:
                self.qtgui_number_sink_0.set_label(i, "Data {0}".format(i))
            else:
                self.qtgui_number_sink_0.set_label(i, labels[i])
            self.qtgui_number_sink_0.set_unit(i, units[i])
            self.qtgui_number_sink_0.set_factor(i, factor[i])

        self.qtgui_number_sink_0.enable_autoscale(False)
        self._qtgui_number_sink_0_win = sip.wrapinstance(self.qtgui_number_sink_0.qwidget(), Qt.QWidget)
        self.top_grid_layout.addWidget(self._qtgui_number_sink_0_win, 1, 0, 1, 2)
        for r in range(1, 2):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 2):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.qtgui_freq_sink_x_0 = qtgui.freq_sink_c(
            2048, #size
            window.WIN_BLACKMAN_hARRIS, #wintype
            center_freq, #fc
            sample_rate, #bw
            "Spectrum", #name
            2,
            None # parent
        )
        self.qtgui_freq_sink_x_0.set_update_time(0.1)
        self.qtgui_freq_sink_x_0.set_y_axis((-80), 0)
        self.qtgui_freq_sink_x_0.set_y_label('Relative Gain', 'dB')
        self.qtgui_freq_sink_x_0.set_trigger_mode(qtgui.TRIG_MODE_FREE, 0.0, 0, "")
        self.qtgui_freq_sink_x_0.enable_autoscale(False)
        self.qtgui_freq_sink_x_0.enable_grid(True)
        self.qtgui_freq_sink_x_0.set_fft_average(1.0)
        self.qtgui_freq_sink_x_0.enable_axis_labels(True)
        self.qtgui_freq_sink_x_0.enable_control_panel(False)
        self.qtgui_freq_sink_x_0.set_fft_window_normalized(False)



        labels = ['CH0', 'CH1', '', '', '',
            '', '', '', '', '']
        widths = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        colors = ["blue", "red", "green", "black", "cyan",
            "magenta", "yellow", "dark red", "dark green", "dark blue"]
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0, 1.0]

        for i in range(2):
            if len(labels[i]) == 0:
                self.qtgui_freq_sink_x_0.set_line_label(i, "Data {0}".format(i))
            else:
                self.qtgui_freq_sink_x_0.set_line_label(i, labels[i])
            self.qtgui_freq_sink_x_0.set_line_width(i, widths[i])
            self.qtgui_freq_sink_x_0.set_line_color(i, colors[i])
            self.qtgui_freq_sink_x_0.set_line_alpha(i, alphas[i])

        self._qtgui_freq_sink_x_0_win = sip.wrapinstance(self.qtgui_freq_sink_x_0.qwidget(), Qt.QWidget)
        self.top_grid_layout.addWidget(self._qtgui_freq_sink_x_0_win, 6, 0, 2, 2)
        for r in range(6, 8):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 2):
            self.top_grid_layout.setColumnStretch(c, 1)
        self._phase_cal_deg_range = qtgui.Range(-180, 180, 0.1, 0, 200)
        self._phase_cal_deg_win = qtgui.RangeWidget(self._phase_cal_deg_range, self.set_phase_cal_deg, "Phase Cal (deg)", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_grid_layout.addWidget(self._phase_cal_deg_win, 0, 1, 1, 1)
        for r in range(0, 1):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(1, 2):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.band_pass_filter_1 = filter.fir_filter_ccf(
            1,
            firdes.band_pass(
                1,
                sample_rate,
                (tone_freq - 10e3),
                (tone_freq + 10e3),
                5000,
                window.WIN_HAMMING,
                6.76))
        self.band_pass_filter_0 = filter.fir_filter_ccf(
            1,
            firdes.band_pass(
                1,
                sample_rate,
                (tone_freq - 10e3),
                (tone_freq + 10e3),
                5000,
                window.WIN_HAMMING,
                6.76))
        self.aoa_shift_phase_0 = aoa.shift_phase_multiple_hier(1)
        self.aoa_root_music_linear_array_0 = aoa.rootMUSIC_linear_array(antenna_spacing, 1, 2)
        self.aoa_music_lin_array_0 = aoa.MUSIC_lin_array(antenna_spacing, 1, 2, 1024)
        self.aoa_autocorrelate_0 = aoa.correlate(2, snapshot_size, 0, 0)
        self.analog_const_source_x_0 = analog.sig_source_f(0, analog.GR_CONST_WAVE, 0, 0, phase_cal_rad)


        ##################################################
        # Connections
        ##################################################
        self.connect((self.analog_const_source_x_0, 0), (self.aoa_shift_phase_0, 1))
        self.connect((self.aoa_autocorrelate_0, 0), (self.aoa_music_lin_array_0, 0))
        self.connect((self.aoa_autocorrelate_0, 0), (self.aoa_root_music_linear_array_0, 0))
        self.connect((self.aoa_music_lin_array_0, 0), (self.qtgui_vector_sink_f_0, 0))
        self.connect((self.aoa_root_music_linear_array_0, 0), (self.qtgui_number_sink_0, 0))
        self.connect((self.aoa_root_music_linear_array_0, 0), (self.qtgui_time_sink_x_0, 0))
        self.connect((self.aoa_shift_phase_0, 0), (self.aoa_autocorrelate_0, 1))
        self.connect((self.band_pass_filter_0, 0), (self.aoa_autocorrelate_0, 0))
        self.connect((self.band_pass_filter_1, 0), (self.aoa_shift_phase_0, 0))
        self.connect((self.soapy_bladerf_source_0, 0), (self.band_pass_filter_0, 0))
        self.connect((self.soapy_bladerf_source_0, 1), (self.band_pass_filter_1, 0))
        self.connect((self.soapy_bladerf_source_0, 0), (self.qtgui_freq_sink_x_0, 0))
        self.connect((self.soapy_bladerf_source_0, 1), (self.qtgui_freq_sink_x_0, 1))


    def closeEvent(self, event):
        self.settings = Qt.QSettings("gnuradio/flowgraphs", "aoa_estimation_bladerf")
        self.settings.setValue("geometry", self.saveGeometry())
        self.stop()
        self.wait()

        event.accept()

    def get_phase_cal_deg(self):
        return self.phase_cal_deg

    def set_phase_cal_deg(self, phase_cal_deg):
        self.phase_cal_deg = phase_cal_deg
        self.set_phase_cal_rad(self.phase_cal_deg * 3.14159265359 / 180.0)

    def get_tone_freq(self):
        return self.tone_freq

    def set_tone_freq(self, tone_freq):
        self.tone_freq = tone_freq
        self.band_pass_filter_0.set_taps(firdes.band_pass(1, self.sample_rate, (self.tone_freq - 10e3), (self.tone_freq + 10e3), 5000, window.WIN_HAMMING, 6.76))
        self.band_pass_filter_1.set_taps(firdes.band_pass(1, self.sample_rate, (self.tone_freq - 10e3), (self.tone_freq + 10e3), 5000, window.WIN_HAMMING, 6.76))

    def get_snapshot_size(self):
        return self.snapshot_size

    def set_snapshot_size(self, snapshot_size):
        self.snapshot_size = snapshot_size
        self.qtgui_time_sink_x_0.set_samp_rate(self.sample_rate/self.snapshot_size)

    def get_sample_rate(self):
        return self.sample_rate

    def set_sample_rate(self, sample_rate):
        self.sample_rate = sample_rate
        self.band_pass_filter_0.set_taps(firdes.band_pass(1, self.sample_rate, (self.tone_freq - 10e3), (self.tone_freq + 10e3), 5000, window.WIN_HAMMING, 6.76))
        self.band_pass_filter_1.set_taps(firdes.band_pass(1, self.sample_rate, (self.tone_freq - 10e3), (self.tone_freq + 10e3), 5000, window.WIN_HAMMING, 6.76))
        self.qtgui_freq_sink_x_0.set_frequency_range(self.center_freq, self.sample_rate)
        self.qtgui_time_sink_x_0.set_samp_rate(self.sample_rate/self.snapshot_size)

    def get_rx_gain(self):
        return self.rx_gain

    def set_rx_gain(self, rx_gain):
        self.rx_gain = rx_gain

    def get_phase_cal_rad(self):
        return self.phase_cal_rad

    def set_phase_cal_rad(self, phase_cal_rad):
        self.phase_cal_rad = phase_cal_rad
        self.analog_const_source_x_0.set_offset(self.phase_cal_rad)

    def get_center_freq(self):
        return self.center_freq

    def set_center_freq(self, center_freq):
        self.center_freq = center_freq
        self.qtgui_freq_sink_x_0.set_frequency_range(self.center_freq, self.sample_rate)
        self.soapy_bladerf_source_0.set_frequency(0, self.center_freq)
        self.soapy_bladerf_source_0.set_frequency(1, self.center_freq)

    def get_antenna_spacing(self):
        return self.antenna_spacing

    def set_antenna_spacing(self, antenna_spacing):
        self.antenna_spacing = antenna_spacing




def main(top_block_cls=aoa_estimation_bladerf, options=None):

    qapp = Qt.QApplication(sys.argv)

    tb = top_block_cls()

    tb.start()
    tb.flowgraph_started.set()

    tb.show()

    def sig_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()

        Qt.QApplication.quit()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    timer = Qt.QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    qapp.exec_()

if __name__ == '__main__':
    main()
