#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph (Headless)
# Title: BladeRF AoA Estimation (Root-MUSIC)
# Author: DoA Thesis Project
# Description: Real-time Direction of Arrival estimation using Root-MUSIC
# GNU Radio version: 3.10.12.0

from gnuradio import analog
from gnuradio import blocks
from gnuradio import filter
from gnuradio.filter import firdes
from gnuradio import gr
from gnuradio.fft import window
import sys
import signal
from argparse import ArgumentParser
from gnuradio.eng_arg import eng_float, intx
from gnuradio import eng_notation
from gnuradio import soapy
import gnuradio.aoa as aoa
import threading


class aoa_estimation_bladerf(gr.top_block):

    def __init__(self):
        gr.top_block.__init__(self, "BladeRF AoA Estimation (Root-MUSIC)", catch_exceptions=True)

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

        dev = 'driver=bladerf'
        stream_args = ''
        tune_args = ['', '']
        settings = ['', '']
        dev_args = ''

        self.soapy_bladerf_source_0 = soapy.source(dev, "fc32", 2, dev_args,
                                  stream_args, tune_args, settings)

        self.soapy_bladerf_source_0.set_sample_rate(0, sample_rate)
        self.soapy_bladerf_source_0.set_sample_rate(1, sample_rate)

        def __gr_bool(v):
            if isinstance(v, bool):
                return v
            return str(v).strip().lower() in ('1', 'true', 'yes', 'on')

        try:
            self.soapy_bladerf_source_0.set_dc_offset_mode(0,__gr_bool(False))
        except (ValueError, TypeError):
            pass
        try:
            self.soapy_bladerf_source_0.set_dc_offset_mode(1,__gr_bool(False))
        except (ValueError, TypeError):
            pass

        self.soapy_bladerf_source_0.set_dc_offset(0,0)
        self.soapy_bladerf_source_0.set_dc_offset(1,0)
        self.soapy_bladerf_source_0.set_iq_balance(0,0)
        self.soapy_bladerf_source_0.set_iq_balance(1,0)
        self.soapy_bladerf_source_0.set_gain_mode(0,False)
        self.soapy_bladerf_source_0.set_gain_mode(1,False)
        self.soapy_bladerf_source_0.set_frequency(0, center_freq)
        self.soapy_bladerf_source_0.set_frequency(1, center_freq)
        self.soapy_bladerf_source_0.set_frequency(0,"BB",0)
        self.soapy_bladerf_source_0.set_frequency(1,"BB",0)
        self.soapy_bladerf_source_0.set_frequency_correction(0,0)
        self.soapy_bladerf_source_0.set_frequency_correction(1,0)
        self.soapy_bladerf_source_0.set_antenna(0,'RX')
        self.soapy_bladerf_source_0.set_antenna(1,'RX')
        self.soapy_bladerf_source_0.set_bandwidth(0,0)
        self.soapy_bladerf_source_0.set_bandwidth(1,0)
        self.soapy_bladerf_source_0.set_gain(0,10)
        self.soapy_bladerf_source_0.set_gain(1,10)

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

        # File sinks for headless output
        self.aoa_file_sink = blocks.file_sink(gr.sizeof_float*1, '/home/petalinux/data/aoa_output.bin', False)
        self.aoa_file_sink.set_unbuffered(False)
        self.blocks_file_sink_0 = blocks.file_sink(gr.sizeof_float*1, '/home/petalinux/data/data.txt', False)
        self.blocks_file_sink_0.set_unbuffered(False)

        ##################################################
        # Connections
        ##################################################
        self.connect((self.analog_const_source_x_0, 0), (self.aoa_shift_phase_0, 1))
        self.connect((self.aoa_autocorrelate_0, 0), (self.aoa_music_lin_array_0, 0))
        self.connect((self.aoa_autocorrelate_0, 0), (self.aoa_root_music_linear_array_0, 0))
        self.connect((self.aoa_root_music_linear_array_0, 0), (self.aoa_file_sink, 0))
        self.connect((self.aoa_shift_phase_0, 0), (self.aoa_autocorrelate_0, 1))
        self.connect((self.band_pass_filter_0, 0), (self.aoa_autocorrelate_0, 0))
        self.connect((self.band_pass_filter_1, 0), (self.aoa_shift_phase_0, 0))
        self.connect((self.soapy_bladerf_source_0, 0), (self.band_pass_filter_0, 0))
        self.connect((self.soapy_bladerf_source_0, 1), (self.band_pass_filter_1, 0))

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

    def get_sample_rate(self):
        return self.sample_rate

    def set_sample_rate(self, sample_rate):
        self.sample_rate = sample_rate
        self.band_pass_filter_0.set_taps(firdes.band_pass(1, self.sample_rate, (self.tone_freq - 10e3), (self.tone_freq + 10e3), 5000, window.WIN_HAMMING, 6.76))
        self.band_pass_filter_1.set_taps(firdes.band_pass(1, self.sample_rate, (self.tone_freq - 10e3), (self.tone_freq + 10e3), 5000, window.WIN_HAMMING, 6.76))

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
        self.soapy_bladerf_source_0.set_frequency(0, self.center_freq)
        self.soapy_bladerf_source_0.set_frequency(1, self.center_freq)

    def get_antenna_spacing(self):
        return self.antenna_spacing

    def set_antenna_spacing(self, antenna_spacing):
        self.antenna_spacing = antenna_spacing


def main(top_block_cls=aoa_estimation_bladerf, options=None):
    tb = top_block_cls()
    tb.start()

    stop_event = threading.Event()

    def sig_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()
        stop_event.set()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    print("Flowgraph started. Press Ctrl+C to stop.")
    stop_event.wait()
    print("Flowgraph stopped.")

if __name__ == '__main__':
    main()
