/**
 * doa_display_firmware.ino - Waveshare ESP32-S3-Touch-LCD-4.3 Display Firmware
 *
 * This firmware runs on the Waveshare display and provides the user interface
 * for the portable DoA estimation system. It communicates with the Cora Z7
 * over UART to send commands and display results.
 *
 * Hardware:
 *   - Waveshare ESP32-S3-Touch-LCD-4.3 (800x480 capacitive touch, GT911)
 *   - USB CDC serial connection to Cora Z7 via USB-C (through powered USB hub)
 *
 * Features:
 *   - Touch interface for calibration and estimation control
 *   - Real-time AoA display with arc gauge visualization
 *   - Status indicators and error display
 *   - Persistent settings storage (calibration, algorithm)
 *
 * Serial Protocol (to/from Cora Z7 via USB CDC):
 *   TX Commands: CALIBRATE, ESTIMATE, ESTIMATE:<algo>, STATUS, STOP, etc.
 *   RX Responses: OK:<msg>, AOA:<angle>, CAL:<phase>, STATUS:<state>, ERROR:<msg>
 *
 * Dependencies (Arduino Library Manager):
 *   - ESP32_Display_Panel (Espressif)
 *   - LVGL (v8.x)
 *
 * Board setting in Arduino IDE:
 *   - Board: "ESP32S3 Dev Module"
 *   - PSRAM: "OPI PSRAM"
 *   - Flash Size: "16MB (128Mb)"
 *   - Partition Scheme: "16M Flash (3MB APP/9.9MB FATFS)"
 *   - USB CDC On Boot: "Enabled"
 *
 * Author: DoA Thesis Project
 * Date: 2026
 */

#include <Arduino.h>
#include <esp_display_panel.hpp>

#include <lvgl.h>
#include "lvgl_v8_port.h"

#include <Preferences.h>

using namespace esp_panel::drivers;
using namespace esp_panel::board;

// =============================================================================
// Configuration
// =============================================================================

// UART1 serial via PH2.0 connector for communication with Cora Z7
// Connected via FT232RL USB-UART adapter → powered USB hub → Cora Z7
// GPIO15 = RX, GPIO16 = TX
#define CORA_SERIAL Serial  // USB CDC — full duplex, no RS485 echo
#define CORA_RX_PIN 43
#define CORA_TX_PIN 44

#define SCREEN_WIDTH    800
#define SCREEN_HEIGHT   480
#define UART_BUFFER_SIZE 256
#define AOA_MIN         0
#define AOA_MAX         180

// =============================================================================
// Global State
// =============================================================================

enum SystemState {
    STATE_DISCONNECTED,
    STATE_IDLE,
    STATE_CALIBRATING,
    STATE_ESTIMATING,
    STATE_ERROR
};

// Circular buffer for std-dev calculation
#define STDEV_WINDOW 20

struct AppState {
    SystemState state = STATE_DISCONNECTED;
    float currentAoA = 90.0;
    float calibrationPhase = 0.0;
    bool hasCalibration = false;
    bool calFromPrefs = false;  // true if cal loaded from flash, not freshly measured
    String lastError = "";
    String selectedAlgo = "ROOTMUSIC";
    String selectedFilter = "none";
    String selectedLabel = "";
    unsigned long lastHeartbeat = 0;

    // Run stats
    unsigned long runStartMs = 0;
    uint32_t sampleCount = 0;
    float aoaHistory[STDEV_WINDOW];
    int aoaHistoryIdx = 0;
    int aoaHistoryCount = 0;
};

AppState g_state;
Preferences preferences;

// UART buffer
char uartBuffer[UART_BUFFER_SIZE];
int uartBufferPos = 0;

// =============================================================================
// LVGL UI Elements
// =============================================================================

static lv_obj_t* label_status;
static lv_obj_t* label_connection;
static lv_obj_t* arc_aoa;
static lv_obj_t* label_aoa_value;
static lv_obj_t* btn_calibrate;
static lv_obj_t* btn_estimate;
static lv_obj_t* btn_stop;
static lv_obj_t* dropdown_algo;
static lv_obj_t* dropdown_filter;
static lv_obj_t* dropdown_label;
static lv_obj_t* label_cal_value;
static lv_obj_t* label_current_label;
static lv_obj_t* label_run_timer;
static lv_obj_t* label_sample_count;
static lv_obj_t* label_stdev;
static lv_obj_t* msgbox_error = nullptr;

// =============================================================================
// Forward Declarations
// =============================================================================

void sendCommand(const char* cmd);
void parseResponse(const char* line);
void updateUI();
void createUI();
void showError(const char* msg);

// =============================================================================
// Serial Communication (UART1 via FT232RL to Cora Z7)
// =============================================================================

float computeStdDev() {
    if (g_state.aoaHistoryCount < 2) return 0.0;
    int n = min(g_state.aoaHistoryCount, STDEV_WINDOW);
    float sum = 0, sumSq = 0;
    for (int i = 0; i < n; i++) {
        sum += g_state.aoaHistory[i];
        sumSq += g_state.aoaHistory[i] * g_state.aoaHistory[i];
    }
    float mean = sum / n;
    float variance = (sumSq / n) - (mean * mean);
    return (variance > 0) ? sqrt(variance) : 0.0;
}

void resetRunStats() {
    g_state.runStartMs = millis();
    g_state.sampleCount = 0;
    g_state.aoaHistoryIdx = 0;
    g_state.aoaHistoryCount = 0;
}

void sendCommand(const char* cmd) {
    CORA_SERIAL.println(cmd);
    CORA_SERIAL.flush();
}



void processSerial() {
    while (CORA_SERIAL.available()) {
        char c = CORA_SERIAL.read();

        if (c == '\n' || c == '\r') {
            if (uartBufferPos > 0) {
                uartBuffer[uartBufferPos] = '\0';
                parseResponse(uartBuffer);
                uartBufferPos = 0;
            }
        } else if (uartBufferPos < UART_BUFFER_SIZE - 1) {
            uartBuffer[uartBufferPos++] = c;
        }
    }
}

void parseResponse(const char* line) {
    String response = String(line);
    g_state.lastHeartbeat = millis();

    int colonPos = response.indexOf(':');
    String msgType = (colonPos > 0) ? response.substring(0, colonPos) : response;
    String msgData = (colonPos > 0) ? response.substring(colonPos + 1) : "";

    if (msgType == "AOA") {
        g_state.currentAoA = msgData.toFloat();
        g_state.state = STATE_ESTIMATING;
        // Track run stats
        g_state.sampleCount++;
        g_state.aoaHistory[g_state.aoaHistoryIdx] = g_state.currentAoA;
        g_state.aoaHistoryIdx = (g_state.aoaHistoryIdx + 1) % STDEV_WINDOW;
        if (g_state.aoaHistoryCount < STDEV_WINDOW) g_state.aoaHistoryCount++;
    }
    else if (msgType == "CAL") {
        g_state.calibrationPhase = msgData.toFloat();
        g_state.hasCalibration = true;
        g_state.calFromPrefs = false;  // freshly measured
        preferences.putFloat("cal_phase", g_state.calibrationPhase);
    }
    else if (msgType == "STATUS") {
        if (msgData == "READY" || msgData == "IDLE") {
            g_state.state = STATE_IDLE;
        } else if (msgData == "CALIBRATING") {
            g_state.state = STATE_CALIBRATING;
        } else if (msgData == "ESTIMATING") {
            g_state.state = STATE_ESTIMATING;
        } else if (msgData == "ERROR") {
            g_state.state = STATE_ERROR;
        }
    }
    else if (msgType == "OK") {
        if (msgData.startsWith("Starting calibration")) {
            g_state.state = STATE_CALIBRATING;
        } else if (msgData.startsWith("Starting estimation")) {
            g_state.state = STATE_ESTIMATING;
            resetRunStats();
        } else if (msgData == "Stopped") {
            g_state.state = STATE_IDLE;
        } else if (msgData.startsWith("Label set to ")) {
            g_state.selectedLabel = msgData.substring(13);
        } else if (msgData == "Label cleared") {
            g_state.selectedLabel = "";
        }
    }
    else if (msgType == "DONE") {
        if (g_state.state == STATE_CALIBRATING) {
            g_state.state = STATE_IDLE;
        }
    }
    else if (msgType == "ERROR") {
        g_state.lastError = msgData;
        g_state.state = STATE_ERROR;
        lvgl_port_lock(-1);
        showError(msgData.c_str());
        lvgl_port_unlock();
    }
    else if (msgType == "PROGRESS") {
        // Could update a progress bar during calibration
    }

    lvgl_port_lock(-1);
    updateUI();
    lvgl_port_unlock();
}

void checkConnection() {
    if (millis() - g_state.lastHeartbeat > 3000) {
        if (g_state.state != STATE_DISCONNECTED) {
            g_state.state = STATE_DISCONNECTED;
            lvgl_port_lock(-1);
            updateUI();
            lvgl_port_unlock();
        }
        sendCommand("STATUS");
    }
}

// =============================================================================
// UI Event Handlers
// =============================================================================

static void btn_calibrate_cb(lv_event_t* e) {
    if (g_state.state == STATE_IDLE || g_state.state == STATE_ERROR) {
        sendCommand("CALIBRATE");
    }
}

static void btn_estimate_cb(lv_event_t* e) {
    if (g_state.state == STATE_IDLE || g_state.state == STATE_ERROR) {
        String cmd = "ESTIMATE:" + g_state.selectedAlgo + ":" + g_state.selectedFilter;
        sendCommand(cmd.c_str());
    }
}

static void btn_stop_cb(lv_event_t* e) {
    sendCommand("STOP");
}

static void dropdown_algo_cb(lv_event_t* e) {
    lv_obj_t* dropdown = lv_event_get_target(e);
    char buf[32];
    lv_dropdown_get_selected_str(dropdown, buf, sizeof(buf));
    g_state.selectedAlgo = String(buf);
    preferences.putString("algo", g_state.selectedAlgo);
}

static void dropdown_filter_cb(lv_event_t* e) {
    lv_obj_t* dropdown = lv_event_get_target(e);
    char buf[32];
    lv_dropdown_get_selected_str(dropdown, buf, sizeof(buf));
    g_state.selectedFilter = String(buf);
    preferences.putString("filter", g_state.selectedFilter);
}

static void dropdown_label_cb(lv_event_t* e) {
    lv_obj_t* dropdown = lv_event_get_target(e);
    uint16_t sel = lv_dropdown_get_selected(dropdown);
    char buf[32];
    lv_dropdown_get_selected_str(dropdown, buf, sizeof(buf));

    if (sel == 0) {
        // "(No Label)" selected — clear it
        g_state.selectedLabel = "";
        sendCommand("LABEL:");
    } else {
        g_state.selectedLabel = String(buf);
        String cmd = "LABEL:" + g_state.selectedLabel;
        sendCommand(cmd.c_str());
    }
    preferences.putString("label", g_state.selectedLabel);
}

static void msgbox_close_cb(lv_event_t* e) {
    lv_msgbox_close(msgbox_error);
    msgbox_error = nullptr;
    if (g_state.state == STATE_ERROR) {
        g_state.state = STATE_IDLE;
    }
}

void showError(const char* msg) {
    if (msgbox_error != nullptr) {
        lv_msgbox_close(msgbox_error);
    }
    static const char* btns[] = {"OK", ""};
    msgbox_error = lv_msgbox_create(NULL, "Error", msg, btns, false);
    lv_obj_add_event_cb(msgbox_error, msgbox_close_cb, LV_EVENT_VALUE_CHANGED, NULL);
    lv_obj_center(msgbox_error);
}

// =============================================================================
// UI Creation
// =============================================================================

void createUI() {
    lv_obj_t* screen_main = lv_scr_act();
    lv_obj_set_style_bg_color(screen_main, lv_color_hex(0x1a1a2e), 0);

    // ----- Status Bar (top) -----
    lv_obj_t* status_bar = lv_obj_create(screen_main);
    lv_obj_set_size(status_bar, SCREEN_WIDTH, 50);
    lv_obj_set_pos(status_bar, 0, 0);
    lv_obj_set_style_bg_color(status_bar, lv_color_hex(0x16213e), 0);
    lv_obj_set_style_border_width(status_bar, 0, 0);
    lv_obj_set_style_radius(status_bar, 0, 0);

    label_status = lv_label_create(status_bar);
    lv_label_set_text(label_status, "DoA Estimator");
    lv_obj_set_style_text_color(label_status, lv_color_hex(0xffffff), 0);
    lv_obj_set_style_text_font(label_status, &lv_font_montserrat_20, 0);
    lv_obj_align(label_status, LV_ALIGN_LEFT_MID, 10, 0);

    label_connection = lv_label_create(status_bar);
    lv_label_set_text(label_connection, "Disconnected");
    lv_obj_set_style_text_color(label_connection, lv_color_hex(0xff6b6b), 0);
    lv_obj_align(label_connection, LV_ALIGN_RIGHT_MID, -10, 0);

    // ----- AoA Display (center) -----
    lv_obj_t* aoa_container = lv_obj_create(screen_main);
    lv_obj_set_size(aoa_container, 400, 300);
    lv_obj_align(aoa_container, LV_ALIGN_CENTER, 0, -20);
    lv_obj_set_style_bg_color(aoa_container, lv_color_hex(0x1f4068), 0);
    lv_obj_set_style_border_width(aoa_container, 2, 0);
    lv_obj_set_style_border_color(aoa_container, lv_color_hex(0x4a90d9), 0);
    lv_obj_set_style_radius(aoa_container, 15, 0);

    // Arc gauge for angle
    arc_aoa = lv_arc_create(aoa_container);
    lv_obj_set_size(arc_aoa, 250, 250);
    lv_obj_center(arc_aoa);
    lv_arc_set_rotation(arc_aoa, 180);
    lv_arc_set_bg_angles(arc_aoa, 0, 180);
    lv_arc_set_range(arc_aoa, AOA_MIN, AOA_MAX);
    lv_arc_set_value(arc_aoa, 90);
    lv_obj_remove_style(arc_aoa, NULL, LV_PART_KNOB);
    lv_obj_set_style_arc_color(arc_aoa, lv_color_hex(0x4a90d9), LV_PART_INDICATOR);
    lv_obj_set_style_arc_width(arc_aoa, 20, LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(arc_aoa, lv_color_hex(0x2d3a4a), LV_PART_MAIN);
    lv_obj_set_style_arc_width(arc_aoa, 20, LV_PART_MAIN);
    lv_obj_clear_flag(arc_aoa, LV_OBJ_FLAG_CLICKABLE);

    // Numeric angle display
    label_aoa_value = lv_label_create(aoa_container);
    lv_label_set_text(label_aoa_value, "90.0 deg");
    lv_obj_set_style_text_color(label_aoa_value, lv_color_hex(0xffffff), 0);
    lv_obj_set_style_text_font(label_aoa_value, &lv_font_montserrat_48, 0);
    lv_obj_align(label_aoa_value, LV_ALIGN_CENTER, 0, 50);

    // Direction labels
    lv_obj_t* label_left = lv_label_create(aoa_container);
    lv_label_set_text(label_left, "0");
    lv_obj_set_style_text_color(label_left, lv_color_hex(0xaaaaaa), 0);
    lv_obj_align(label_left, LV_ALIGN_BOTTOM_LEFT, 30, -20);

    lv_obj_t* label_center = lv_label_create(aoa_container);
    lv_label_set_text(label_center, "90 (Broadside)");
    lv_obj_set_style_text_color(label_center, lv_color_hex(0xaaaaaa), 0);
    lv_obj_align(label_center, LV_ALIGN_TOP_MID, 0, 20);

    lv_obj_t* label_right = lv_label_create(aoa_container);
    lv_label_set_text(label_right, "180");
    lv_obj_set_style_text_color(label_right, lv_color_hex(0xaaaaaa), 0);
    lv_obj_align(label_right, LV_ALIGN_BOTTOM_RIGHT, -30, -20);

    // ----- Control Panel (right side) -----
    lv_obj_t* control_panel = lv_obj_create(screen_main);
    lv_obj_set_size(control_panel, 180, 370);
    lv_obj_align(control_panel, LV_ALIGN_RIGHT_MID, -20, 10);
    lv_obj_set_style_bg_color(control_panel, lv_color_hex(0x16213e), 0);
    lv_obj_set_style_border_width(control_panel, 0, 0);
    lv_obj_set_layout(control_panel, LV_LAYOUT_FLEX);
    lv_obj_set_flex_flow(control_panel, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(control_panel, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_all(control_panel, 10, 0);
    lv_obj_set_style_pad_row(control_panel, 10, 0);

    // Label dropdown (campaign angle)
    lv_obj_t* lbl_label = lv_label_create(control_panel);
    lv_label_set_text(lbl_label, "Label:");
    lv_obj_set_style_text_color(lbl_label, lv_color_hex(0xaaaaaa), 0);

    dropdown_label = lv_dropdown_create(control_panel);
    lv_dropdown_set_options(dropdown_label, "(No Label)\n50deg\n70deg\n90deg\n110deg\n130deg");
    lv_obj_set_width(dropdown_label, 150);
    lv_obj_add_event_cb(dropdown_label, dropdown_label_cb, LV_EVENT_VALUE_CHANGED, NULL);

    // Algorithm dropdown
    lv_obj_t* algo_label = lv_label_create(control_panel);
    lv_label_set_text(algo_label, "Algorithm:");
    lv_obj_set_style_text_color(algo_label, lv_color_hex(0xaaaaaa), 0);

    dropdown_algo = lv_dropdown_create(control_panel);
    lv_dropdown_set_options(dropdown_algo,
        "ROOTMUSIC\nMUSIC\nMVDR\nPHASEDIFF\n"
        "FPGA:ROOTMUSIC\nFPGA:MUSIC\nFPGA:MVDR\nFPGA:PHASEDIFF");
    lv_obj_set_width(dropdown_algo, 150);
    lv_obj_add_event_cb(dropdown_algo, dropdown_algo_cb, LV_EVENT_VALUE_CHANGED, NULL);

    // Filter dropdown
    lv_obj_t* filter_label = lv_label_create(control_panel);
    lv_label_set_text(filter_label, "Filter:");
    lv_obj_set_style_text_color(filter_label, lv_color_hex(0xaaaaaa), 0);

    dropdown_filter = lv_dropdown_create(control_panel);
    lv_dropdown_set_options(dropdown_filter, "none\nbandpass\nlowpass");
    lv_obj_set_width(dropdown_filter, 150);
    lv_obj_add_event_cb(dropdown_filter, dropdown_filter_cb, LV_EVENT_VALUE_CHANGED, NULL);

    // Calibrate button
    btn_calibrate = lv_btn_create(control_panel);
    lv_obj_set_size(btn_calibrate, 150, 50);
    lv_obj_set_style_bg_color(btn_calibrate, lv_color_hex(0x4a90d9), 0);
    lv_obj_add_event_cb(btn_calibrate, btn_calibrate_cb, LV_EVENT_CLICKED, NULL);
    lv_obj_t* label_cal = lv_label_create(btn_calibrate);
    lv_label_set_text(label_cal, "CALIBRATE");
    lv_obj_center(label_cal);

    // Estimate button
    btn_estimate = lv_btn_create(control_panel);
    lv_obj_set_size(btn_estimate, 150, 50);
    lv_obj_set_style_bg_color(btn_estimate, lv_color_hex(0x2ecc71), 0);
    lv_obj_add_event_cb(btn_estimate, btn_estimate_cb, LV_EVENT_CLICKED, NULL);
    lv_obj_t* label_est = lv_label_create(btn_estimate);
    lv_label_set_text(label_est, "ESTIMATE");
    lv_obj_center(label_est);

    // Stop button
    btn_stop = lv_btn_create(control_panel);
    lv_obj_set_size(btn_stop, 150, 50);
    lv_obj_set_style_bg_color(btn_stop, lv_color_hex(0xe74c3c), 0);
    lv_obj_add_event_cb(btn_stop, btn_stop_cb, LV_EVENT_CLICKED, NULL);
    lv_obj_t* label_stop = lv_label_create(btn_stop);
    lv_label_set_text(label_stop, "STOP");
    lv_obj_center(label_stop);

    // ----- Info Panel (left side) -----
    lv_obj_t* info_panel = lv_obj_create(screen_main);
    lv_obj_set_size(info_panel, 180, 320);
    lv_obj_align(info_panel, LV_ALIGN_LEFT_MID, 20, 10);
    lv_obj_set_style_bg_color(info_panel, lv_color_hex(0x16213e), 0);
    lv_obj_set_style_border_width(info_panel, 0, 0);
    lv_obj_set_layout(info_panel, LV_LAYOUT_FLEX);
    lv_obj_set_flex_flow(info_panel, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_all(info_panel, 10, 0);

    lv_obj_t* cal_title = lv_label_create(info_panel);
    lv_label_set_text(cal_title, "Calibration:");
    lv_obj_set_style_text_color(cal_title, lv_color_hex(0xaaaaaa), 0);

    label_cal_value = lv_label_create(info_panel);
    lv_label_set_text(label_cal_value, "Not calibrated");
    lv_obj_set_style_text_color(label_cal_value, lv_color_hex(0xffaa00), 0);
    lv_obj_set_style_text_font(label_cal_value, &lv_font_montserrat_20, 0);

    // CAL +/- buttons: fine (±1) and coarse (±5)
    lv_obj_t* cal_btn_row1 = lv_obj_create(info_panel);
    lv_obj_set_size(cal_btn_row1, 150, 36);
    lv_obj_set_style_bg_opa(cal_btn_row1, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(cal_btn_row1, 0, 0);
    lv_obj_set_style_pad_all(cal_btn_row1, 0, 0);
    lv_obj_set_layout(cal_btn_row1, LV_LAYOUT_FLEX);
    lv_obj_set_flex_flow(cal_btn_row1, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(cal_btn_row1, LV_FLEX_ALIGN_SPACE_EVENLY, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

    lv_obj_t* btn_m5 = lv_btn_create(cal_btn_row1);
    lv_obj_set_size(btn_m5, 34, 28);
    lv_obj_set_style_bg_color(btn_m5, lv_color_hex(0x8e44ad), 0);
    lv_obj_add_event_cb(btn_m5, [](lv_event_t* e) { sendCommand("ADJUST_CAL:-5"); }, LV_EVENT_CLICKED, NULL);
    lv_obj_t* lbl_m5 = lv_label_create(btn_m5);
    lv_label_set_text(lbl_m5, "-5");
    lv_obj_center(lbl_m5);

    lv_obj_t* btn_m1 = lv_btn_create(cal_btn_row1);
    lv_obj_set_size(btn_m1, 34, 28);
    lv_obj_set_style_bg_color(btn_m1, lv_color_hex(0x8e44ad), 0);
    lv_obj_add_event_cb(btn_m1, [](lv_event_t* e) { sendCommand("ADJUST_CAL:-1"); }, LV_EVENT_CLICKED, NULL);
    lv_obj_t* lbl_m1 = lv_label_create(btn_m1);
    lv_label_set_text(lbl_m1, "-1");
    lv_obj_center(lbl_m1);

    lv_obj_t* btn_p1 = lv_btn_create(cal_btn_row1);
    lv_obj_set_size(btn_p1, 34, 28);
    lv_obj_set_style_bg_color(btn_p1, lv_color_hex(0x8e44ad), 0);
    lv_obj_add_event_cb(btn_p1, [](lv_event_t* e) { sendCommand("ADJUST_CAL:+1"); }, LV_EVENT_CLICKED, NULL);
    lv_obj_t* lbl_p1 = lv_label_create(btn_p1);
    lv_label_set_text(lbl_p1, "+1");
    lv_obj_center(lbl_p1);

    lv_obj_t* btn_p5 = lv_btn_create(cal_btn_row1);
    lv_obj_set_size(btn_p5, 34, 28);
    lv_obj_set_style_bg_color(btn_p5, lv_color_hex(0x8e44ad), 0);
    lv_obj_add_event_cb(btn_p5, [](lv_event_t* e) { sendCommand("ADJUST_CAL:+5"); }, LV_EVENT_CLICKED, NULL);
    lv_obj_t* lbl_p5 = lv_label_create(btn_p5);
    lv_label_set_text(lbl_p5, "+5");
    lv_obj_center(lbl_p5);

    lv_obj_t* label_title = lv_label_create(info_panel);
    lv_label_set_text(label_title, "Label:");
    lv_obj_set_style_text_color(label_title, lv_color_hex(0xaaaaaa), 0);
    lv_obj_set_style_pad_top(label_title, 10, 0);

    label_current_label = lv_label_create(info_panel);
    lv_label_set_text(label_current_label, "(none)");
    lv_obj_set_style_text_color(label_current_label, lv_color_hex(0x4a90d9), 0);
    lv_obj_set_style_text_font(label_current_label, &lv_font_montserrat_20, 0);

    // Run timer
    lv_obj_t* timer_title = lv_label_create(info_panel);
    lv_label_set_text(timer_title, "Run Time:");
    lv_obj_set_style_text_color(timer_title, lv_color_hex(0xaaaaaa), 0);
    lv_obj_set_style_pad_top(timer_title, 10, 0);

    label_run_timer = lv_label_create(info_panel);
    lv_label_set_text(label_run_timer, "--");
    lv_obj_set_style_text_color(label_run_timer, lv_color_hex(0xffffff), 0);
    lv_obj_set_style_text_font(label_run_timer, &lv_font_montserrat_20, 0);

    // Sample count
    lv_obj_t* count_title = lv_label_create(info_panel);
    lv_label_set_text(count_title, "Samples:");
    lv_obj_set_style_text_color(count_title, lv_color_hex(0xaaaaaa), 0);
    lv_obj_set_style_pad_top(count_title, 6, 0);

    label_sample_count = lv_label_create(info_panel);
    lv_label_set_text(label_sample_count, "--");
    lv_obj_set_style_text_color(label_sample_count, lv_color_hex(0xffffff), 0);
    lv_obj_set_style_text_font(label_sample_count, &lv_font_montserrat_20, 0);

    // Std-dev indicator
    lv_obj_t* stdev_title = lv_label_create(info_panel);
    lv_label_set_text(stdev_title, "Std Dev:");
    lv_obj_set_style_text_color(stdev_title, lv_color_hex(0xaaaaaa), 0);
    lv_obj_set_style_pad_top(stdev_title, 6, 0);

    label_stdev = lv_label_create(info_panel);
    lv_label_set_text(label_stdev, "--");
    lv_obj_set_style_text_color(label_stdev, lv_color_hex(0xffffff), 0);
    lv_obj_set_style_text_font(label_stdev, &lv_font_montserrat_20, 0);
}

// =============================================================================
// UI Update
// =============================================================================

void updateUI() {
    // Update connection status
    switch (g_state.state) {
        case STATE_DISCONNECTED:
            lv_label_set_text(label_connection, "Disconnected");
            lv_obj_set_style_text_color(label_connection, lv_color_hex(0xff6b6b), 0);
            break;
        case STATE_IDLE:
            lv_label_set_text(label_connection, "Ready");
            lv_obj_set_style_text_color(label_connection, lv_color_hex(0x2ecc71), 0);
            break;
        case STATE_CALIBRATING:
            lv_label_set_text(label_connection, "Calibrating...");
            lv_obj_set_style_text_color(label_connection, lv_color_hex(0xf1c40f), 0);
            break;
        case STATE_ESTIMATING:
            lv_label_set_text(label_connection, "Running");
            lv_obj_set_style_text_color(label_connection, lv_color_hex(0x2ecc71), 0);
            break;
        case STATE_ERROR:
            lv_label_set_text(label_connection, "Error");
            lv_obj_set_style_text_color(label_connection, lv_color_hex(0xe74c3c), 0);
            break;
    }

    // Update AoA display
    lv_arc_set_value(arc_aoa, (int)g_state.currentAoA);
    char aoa_str[16];
    snprintf(aoa_str, sizeof(aoa_str), "%.1f deg", g_state.currentAoA);
    lv_label_set_text(label_aoa_value, aoa_str);

    // Update calibration display (yellow if from saved prefs, green if fresh)
    if (g_state.hasCalibration) {
        char cal_str[32];
        snprintf(cal_str, sizeof(cal_str), "%.2f deg", g_state.calibrationPhase);
        lv_label_set_text(label_cal_value, cal_str);
        if (g_state.calFromPrefs) {
            lv_obj_set_style_text_color(label_cal_value, lv_color_hex(0xffaa00), 0);  // yellow = stale
        } else {
            lv_obj_set_style_text_color(label_cal_value, lv_color_hex(0x2ecc71), 0);  // green = fresh
        }
    } else {
        lv_label_set_text(label_cal_value, "Not calibrated");
        lv_obj_set_style_text_color(label_cal_value, lv_color_hex(0xff6b6b), 0);
    }

    // Update run timer
    if (g_state.state == STATE_ESTIMATING && g_state.runStartMs > 0) {
        unsigned long elapsed = (millis() - g_state.runStartMs) / 1000;
        char timer_str[16];
        snprintf(timer_str, sizeof(timer_str), "%lu:%02lu", elapsed / 60, elapsed % 60);
        lv_label_set_text(label_run_timer, timer_str);
    } else {
        lv_label_set_text(label_run_timer, "--");
    }

    // Update sample count
    if (g_state.state == STATE_ESTIMATING) {
        char count_str[16];
        snprintf(count_str, sizeof(count_str), "%lu", (unsigned long)g_state.sampleCount);
        lv_label_set_text(label_sample_count, count_str);
    } else {
        lv_label_set_text(label_sample_count, "--");
    }

    // Update std-dev (color: green < 5°, yellow 5-10°, red > 10°)
    if (g_state.state == STATE_ESTIMATING && g_state.aoaHistoryCount >= 2) {
        float sd = computeStdDev();
        char sd_str[16];
        snprintf(sd_str, sizeof(sd_str), "%.1f deg", sd);
        lv_label_set_text(label_stdev, sd_str);
        if (sd < 5.0) {
            lv_obj_set_style_text_color(label_stdev, lv_color_hex(0x2ecc71), 0);  // green
        } else if (sd < 10.0) {
            lv_obj_set_style_text_color(label_stdev, lv_color_hex(0xf1c40f), 0);  // yellow
        } else {
            lv_obj_set_style_text_color(label_stdev, lv_color_hex(0xe74c3c), 0);  // red
        }
    } else {
        lv_label_set_text(label_stdev, "--");
        lv_obj_set_style_text_color(label_stdev, lv_color_hex(0xffffff), 0);
    }

    // Update label display
    if (g_state.selectedLabel.length() > 0) {
        lv_label_set_text(label_current_label, g_state.selectedLabel.c_str());
        lv_obj_set_style_text_color(label_current_label, lv_color_hex(0x2ecc71), 0);
    } else {
        lv_label_set_text(label_current_label, "(none)");
        lv_obj_set_style_text_color(label_current_label, lv_color_hex(0x4a90d9), 0);
    }

    // Enable/disable buttons based on state
    bool can_start = (g_state.state == STATE_IDLE || g_state.state == STATE_ERROR);
    bool is_running = (g_state.state == STATE_CALIBRATING || g_state.state == STATE_ESTIMATING);

    if (can_start) {
        lv_obj_clear_state(btn_calibrate, LV_STATE_DISABLED);
        lv_obj_clear_state(btn_estimate, LV_STATE_DISABLED);
    } else {
        lv_obj_add_state(btn_calibrate, LV_STATE_DISABLED);
        lv_obj_add_state(btn_estimate, LV_STATE_DISABLED);
    }

    if (is_running) {
        lv_obj_clear_state(btn_stop, LV_STATE_DISABLED);
    } else {
        lv_obj_add_state(btn_stop, LV_STATE_DISABLED);
    }
}

// =============================================================================
// Setup & Loop
// =============================================================================

void setup() {
    Serial.begin(115200);   // USB CDC — comms to Cora Z7 (full duplex)

    // Load persistent settings
    preferences.begin("doa", false);
    g_state.calibrationPhase = preferences.getFloat("cal_phase", 0.0);
    g_state.hasCalibration = (g_state.calibrationPhase != 0.0);
    g_state.calFromPrefs = g_state.hasCalibration;  // yellow until freshly calibrated
    g_state.selectedAlgo = preferences.getString("algo", "ROOTMUSIC");
    g_state.selectedFilter = preferences.getString("filter", "none");
    g_state.selectedLabel = preferences.getString("label", "");

    // Initialize board (LCD + touch + backlight + IO expander)
    Board *board = new Board();
    board->init();

#if LVGL_PORT_AVOID_TEARING_MODE
    // Configure frame buffers for anti-tearing
    auto lcd = board->getLCD();
    lcd->configFrameBufferNumber(LVGL_PORT_DISP_BUFFER_NUM);
#if ESP_PANEL_DRIVERS_BUS_ENABLE_RGB && CONFIG_IDF_TARGET_ESP32S3
    auto lcd_bus = lcd->getBus();
    if (lcd_bus->getBasicAttributes().type == ESP_PANEL_BUS_TYPE_RGB) {
        static_cast<BusRGB *>(lcd_bus)->configRGB_BounceBufferSize(lcd->getFrameWidth() * 10);
    }
#endif
#endif

    assert(board->begin());

    // Initialize LVGL via the port layer (handles display flush, touch read, tick, task)
    lvgl_port_init(board->getLCD(), board->getTouch());

    // Create our UI (must hold the LVGL mutex)
    lvgl_port_lock(-1);

    createUI();

    // Set saved algorithm in dropdown
    // Order: ROOTMUSIC(0) MUSIC(1) MVDR(2) PHASEDIFF(3)
    //        FPGA:ROOTMUSIC(4) FPGA:MUSIC(5) FPGA:MVDR(6) FPGA:PHASEDIFF(7)
    const char* algoOptions[] = {
        "ROOTMUSIC", "MUSIC", "MVDR", "PHASEDIFF",
        "FPGA:ROOTMUSIC", "FPGA:MUSIC", "FPGA:MVDR", "FPGA:PHASEDIFF"
    };
    for (int i = 0; i < 8; i++) {
        if (g_state.selectedAlgo == algoOptions[i]) {
            lv_dropdown_set_selected(dropdown_algo, i);
            break;
        }
    }

    // Set saved filter in dropdown
    // Order: none(0) bandpass(1) lowpass(2)
    if (g_state.selectedFilter == "bandpass") {
        lv_dropdown_set_selected(dropdown_filter, 1);
    } else if (g_state.selectedFilter == "lowpass") {
        lv_dropdown_set_selected(dropdown_filter, 2);
    }

    // Set saved label in dropdown
    if (g_state.selectedLabel == "50deg") {
        lv_dropdown_set_selected(dropdown_label, 1);
    } else if (g_state.selectedLabel == "70deg") {
        lv_dropdown_set_selected(dropdown_label, 2);
    } else if (g_state.selectedLabel == "90deg") {
        lv_dropdown_set_selected(dropdown_label, 3);
    } else if (g_state.selectedLabel == "110deg") {
        lv_dropdown_set_selected(dropdown_label, 4);
    } else if (g_state.selectedLabel == "130deg") {
        lv_dropdown_set_selected(dropdown_label, 5);
    }

    lvgl_port_unlock();

    // Request initial status after a brief delay (wait for Cora to enumerate USB)
    delay(2000);
    sendCommand("STATUS");

    // Sync saved label to Cora
    if (g_state.selectedLabel.length() > 0) {
        String cmd = "LABEL:" + g_state.selectedLabel;
        sendCommand(cmd.c_str());
    }
}

void loop() {
    // Debug heartbeat - remove after testing
    static unsigned long lastDebug = 0;
    if (millis() - lastDebug > 2000) {
        CORA_SERIAL.println("HEARTBEAT");
        CORA_SERIAL.flush();
        lastDebug = millis();
    }

    // Process incoming serial data from Cora (UART1 via FT232RL)
    processSerial();

    // Periodically check connection health and refresh timer
    static unsigned long lastConnectionCheck = 0;
    if (millis() - lastConnectionCheck > 1000) {
        checkConnection();
        // Refresh timer/stats display every second while estimating
        if (g_state.state == STATE_ESTIMATING) {
            lvgl_port_lock(-1);
            updateUI();
            lvgl_port_unlock();
        }
        lastConnectionCheck = millis();
    }

    // LVGL timer is handled by lvgl_port's own FreeRTOS task - no need to call
    // lv_timer_handler() here. Just yield to other tasks.
    delay(5);
}
