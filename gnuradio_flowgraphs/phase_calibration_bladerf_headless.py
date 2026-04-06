#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph (Headless)
# Title: BladeRF Phase Calibration
# Author: DoA Thesis Project
# Description: Measures phase offset between RX channels using wired calibration
# GNU Radio version: 3.10.12.0

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
import threading


class phase_calibration_bladerf(gr.top_block):

    def __init__(self):
        gr.top_block.__init__(self, "BladeRF Phase Calibration", catch_exceptions=True)

        ##################################################
        # Variables
        ##################################################
        self.tone_freq = tone_freq = 50e3
        self.sample_rate = sample_rate = 1e6
        self.rx_gain = rx_gain = 40
        self.center_freq = center_freq = 2.41995e9
        self.avg_length = avg_length = 100000

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

        self.blocks_multiply_const_vxx_0 = blocks.multiply_const_ff((180.0/3.14159265359))
        self.blocks_multiply_conjugate_cc_0 = blocks.multiply_conjugate_cc(1)
        self.blocks_moving_average_xx_0 = blocks.moving_average_cc(avg_length, 1.0/avg_length, 4000, 1)
        self.blocks_file_sink_0 = blocks.file_sink(gr.sizeof_float*1, '/home/petalinux/data/data.txt', False)
        self.blocks_file_sink_0.set_unbuffered(False)
        self.blocks_complex_to_arg_0 = blocks.complex_to_arg(1)
        self.band_pass_filter_1 = filter.fir_filter_ccf(
            1,
            firdes.band_pass(
                1,
                sample_rate,
                (tone_freq - 5e3),
                (tone_freq + 5e3),
                2000,
                window.WIN_HAMMING,
                6.76))
        self.band_pass_filter_0 = filter.fir_filter_ccf(
            1,
            firdes.band_pass(
                1,
                sample_rate,
                (tone_freq - 5e3),
                (tone_freq + 5e3),
                2000,
                window.WIN_HAMMING,
                6.76))

        ##################################################
        # Connections
        ##################################################
        self.connect((self.band_pass_filter_0, 0), (self.blocks_multiply_conjugate_cc_0, 0))
        self.connect((self.band_pass_filter_1, 0), (self.blocks_multiply_conjugate_cc_0, 1))
        self.connect((self.blocks_complex_to_arg_0, 0), (self.blocks_multiply_const_vxx_0, 0))
        self.connect((self.blocks_moving_average_xx_0, 0), (self.blocks_complex_to_arg_0, 0))
        self.connect((self.blocks_multiply_conjugate_cc_0, 0), (self.blocks_moving_average_xx_0, 0))
        self.connect((self.blocks_multiply_const_vxx_0, 0), (self.blocks_file_sink_0, 0))
        self.connect((self.soapy_bladerf_source_0, 0), (self.band_pass_filter_0, 0))
        self.connect((self.soapy_bladerf_source_0, 1), (self.band_pass_filter_1, 0))

    def get_tone_freq(self):
        return self.tone_freq

    def set_tone_freq(self, tone_freq):
        self.tone_freq = tone_freq
        self.band_pass_filter_0.set_taps(firdes.band_pass(1, self.sample_rate, (self.tone_freq - 5e3), (self.tone_freq + 5e3), 2000, window.WIN_HAMMING, 6.76))
        self.band_pass_filter_1.set_taps(firdes.band_pass(1, self.sample_rate, (self.tone_freq - 5e3), (self.tone_freq + 5e3), 2000, window.WIN_HAMMING, 6.76))

    def get_sample_rate(self):
        return self.sample_rate

    def set_sample_rate(self, sample_rate):
        self.sample_rate = sample_rate
        self.band_pass_filter_0.set_taps(firdes.band_pass(1, self.sample_rate, (self.tone_freq - 5e3), (self.tone_freq + 5e3), 2000, window.WIN_HAMMING, 6.76))
        self.band_pass_filter_1.set_taps(firdes.band_pass(1, self.sample_rate, (self.tone_freq - 5e3), (self.tone_freq + 5e3), 2000, window.WIN_HAMMING, 6.76))

    def get_rx_gain(self):
        return self.rx_gain

    def set_rx_gain(self, rx_gain):
        self.rx_gain = rx_gain

    def get_center_freq(self):
        return self.center_freq

    def set_center_freq(self, center_freq):
        self.center_freq = center_freq
        self.soapy_bladerf_source_0.set_frequency(0, self.center_freq)
        self.soapy_bladerf_source_0.set_frequency(1, self.center_freq)

    def get_avg_length(self):
        return self.avg_length

    def set_avg_length(self, avg_length):
        self.avg_length = avg_length
        self.blocks_moving_average_xx_0.set_length_and_scale(self.avg_length, 1.0/self.avg_length)


def main(top_block_cls=phase_calibration_bladerf, options=None):
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
