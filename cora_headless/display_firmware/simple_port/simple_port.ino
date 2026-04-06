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
#define CORA_SERIAL Serial1
#define CORA_RX_PIN 15
#define CORA_TX_PIN 16

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

struct AppState {
    SystemState state = STATE_DISCONNECTED;
    float currentAoA = 90.0;
    float calibrationPhase = 0.0;
    bool hasCalibration = false;
    String lastError = "";
    String selectedAlgo = "ROOTMUSIC";
    unsigned long lastHeartbeat = 0;
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
static lv_obj_t* label_cal_value;
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
    }
    else if (msgType == "CAL") {
        g_state.calibrationPhase = msgData.toFloat();
        g_state.hasCalibration = true;
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
        } else if (msgData == "Stopped") {
            g_state.state = STATE_IDLE;
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
        String cmd = "ESTIMATE:" + g_state.selectedAlgo;
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
    lv_obj_set_size(control_panel, 180, 300);
    lv_obj_align(control_panel, LV_ALIGN_RIGHT_MID, -20, 0);
    lv_obj_set_style_bg_color(control_panel, lv_color_hex(0x16213e), 0);
    lv_obj_set_style_border_width(control_panel, 0, 0);
    lv_obj_set_layout(control_panel, LV_LAYOUT_FLEX);
    lv_obj_set_flex_flow(control_panel, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(control_panel, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_all(control_panel, 10, 0);
    lv_obj_set_style_pad_row(control_panel, 10, 0);

    // Algorithm dropdown
    lv_obj_t* algo_label = lv_label_create(control_panel);
    lv_label_set_text(algo_label, "Algorithm:");
    lv_obj_set_style_text_color(algo_label, lv_color_hex(0xaaaaaa), 0);

    dropdown_algo = lv_dropdown_create(control_panel);
    lv_dropdown_set_options(dropdown_algo, "ROOTMUSIC\nMUSIC\nMVDR\nPHASEDIFF");
    lv_obj_set_width(dropdown_algo, 150);
    lv_obj_add_event_cb(dropdown_algo, dropdown_algo_cb, LV_EVENT_VALUE_CHANGED, NULL);

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
    lv_obj_set_size(info_panel, 180, 200);
    lv_obj_align(info_panel, LV_ALIGN_LEFT_MID, 20, 0);
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

    // Update calibration display
    if (g_state.hasCalibration) {
        char cal_str[32];
        snprintf(cal_str, sizeof(cal_str), "%.2f deg", g_state.calibrationPhase);
        lv_label_set_text(label_cal_value, cal_str);
        lv_obj_set_style_text_color(label_cal_value, lv_color_hex(0x2ecc71), 0);
    } else {
        lv_label_set_text(label_cal_value, "Not calibrated");
        lv_obj_set_style_text_color(label_cal_value, lv_color_hex(0xffaa00), 0);
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
    Serial.begin(115200);   // USB CDC — for debug/programming only
    CORA_SERIAL.begin(115200, SERIAL_8N1, CORA_RX_PIN, CORA_TX_PIN);  // UART1 to Cora Z7

    // Load persistent settings
    preferences.begin("doa", false);
    g_state.calibrationPhase = preferences.getFloat("cal_phase", 0.0);
    g_state.hasCalibration = (g_state.calibrationPhase != 0.0);
    g_state.selectedAlgo = preferences.getString("algo", "ROOTMUSIC");

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
    if (g_state.selectedAlgo == "MUSIC") {
        lv_dropdown_set_selected(dropdown_algo, 1);
    } else if (g_state.selectedAlgo == "MVDR") {
        lv_dropdown_set_selected(dropdown_algo, 2);
    } else if (g_state.selectedAlgo == "PHASEDIFF") {
        lv_dropdown_set_selected(dropdown_algo, 3);
    }

    lvgl_port_unlock();

    // Request initial status after a brief delay (wait for Cora to enumerate USB)
    delay(2000);
    sendCommand("STATUS");
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

    // Periodically check connection health
    static unsigned long lastConnectionCheck = 0;
    if (millis() - lastConnectionCheck > 1000) {
        checkConnection();
        lastConnectionCheck = millis();
    }

    // LVGL timer is handled by lvgl_port's own FreeRTOS task - no need to call
    // lv_timer_handler() here. Just yield to other tasks.
    delay(5);
}
