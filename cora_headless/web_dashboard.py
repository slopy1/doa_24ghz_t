#!/usr/bin/env python3
"""
web_dashboard.py - Web-Based Dashboard for Cora Z7 Headless DoA System

Replaces the Waveshare ESP32-S3 serial display with a browser-based dashboard
served over HTTP. Combines:
  - HTTP server (Python stdlib) on port 8080
  - DoA controller logic (state machine, process manager, calibration store)
  - Embedded HTML/CSS/JS single-page dashboard (no external dependencies)
  - JSON API endpoints for commands
  - Server-Sent Events (SSE) for real-time AoA streaming

Usage:
    python3 web_dashboard.py [--port 8080] [--host 0.0.0.0]

    Then open http://<cora-ip>:8080 in a browser.

Author: DoA Thesis Project
Date: 2026
"""

import http.server
import json
import threading
import subprocess
import signal
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime
from enum import Enum
from typing import Optional, Callable
from urllib.parse import urlparse

# =============================================================================
# Configuration
# =============================================================================

class Config:
    """System configuration constants."""
    SCRIPT_DIR = Path(__file__).parent
    DATA_DIR = SCRIPT_DIR / "data"
    LOG_DIR = SCRIPT_DIR / "logs"
    CAL_FILE = DATA_DIR / "calibration.json"

    CALIBRATION_SCRIPT = SCRIPT_DIR / "phase_calibration_headless.py"
    ESTIMATION_SCRIPT = SCRIPT_DIR / "aoa_estimation_headless.py"

    WARMUP_TIME = 30
    CAL_DURATION = 10
    ESTIMATION_INTERVAL = 0.1
    SAMPLE_RATE = 1e6


class SystemState(Enum):
    IDLE = "IDLE"
    CALIBRATING = "CALIBRATING"
    ESTIMATING = "ESTIMATING"
    ERROR = "ERROR"


# =============================================================================
# Calibration Storage
# =============================================================================

class CalibrationStore:
    """Manages persistent storage of calibration data."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if self.filepath.exists():
            try:
                with open(self.filepath, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {
            "phase_offset_deg": 0.0,
            "timestamp": None,
        }

    def _save(self):
        with open(self.filepath, 'w') as f:
            json.dump(self._data, f, indent=2)

    @property
    def phase_offset_deg(self) -> float:
        return self._data.get("phase_offset_deg", 0.0)

    @phase_offset_deg.setter
    def phase_offset_deg(self, value: float):
        self._data["phase_offset_deg"] = value
        self._data["timestamp"] = datetime.now().isoformat()
        self._save()

    def is_valid(self) -> bool:
        return self._data.get("timestamp") is not None

    @property
    def timestamp(self) -> Optional[str]:
        return self._data.get("timestamp")


# =============================================================================
# Process Manager
# =============================================================================

class ProcessManager:
    """Manages GNU Radio subprocess execution."""

    def __init__(self):
        self.current_process: Optional[subprocess.Popen] = None
        self.output_callback: Optional[Callable[[str], None]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self, script_path: Path, args: list = None,
              output_callback: Callable[[str], None] = None) -> bool:
        if self.is_running():
            return False
        if not script_path.exists():
            return False

        self.output_callback = output_callback
        self._stop_event.clear()

        cmd = [sys.executable, str(script_path)]
        if args:
            cmd.extend(args)

        try:
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._reader_thread = threading.Thread(
                target=self._read_output, daemon=True
            )
            self._reader_thread.start()
            return True
        except Exception as e:
            print(f"Failed to start process: {e}")
            return False

    def _read_output(self):
        while not self._stop_event.is_set() and self.current_process:
            try:
                line = self.current_process.stdout.readline()
                if line and self.output_callback:
                    self.output_callback(line.strip())
                elif not line and self.current_process.poll() is not None:
                    break
            except Exception:
                break

    def stop(self):
        self._stop_event.set()
        if self.current_process:
            self.current_process.terminate()
            try:
                self.current_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.current_process.kill()
            self.current_process = None

    def is_running(self) -> bool:
        return (self.current_process is not None and
                self.current_process.poll() is None)


# =============================================================================
# DoA Controller
# =============================================================================

class DoAController:
    """Central controller for the DoA system."""

    def __init__(self):
        self.state = SystemState.IDLE
        self.calibration = CalibrationStore(Config.CAL_FILE)
        self.process_mgr = ProcessManager()
        self.last_aoa: Optional[float] = None
        self.algorithm = "ROOTMUSIC"
        self.progress = 0
        self.error_msg: Optional[str] = None

        self._lock = threading.Lock()
        self._sse_clients: list = []
        self._sse_lock = threading.Lock()

        Config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        Config.LOG_DIR.mkdir(parents=True, exist_ok=True)

    def log(self, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        print(log_line)
        log_file = Config.LOG_DIR / f"{datetime.now().strftime('%Y%m%d')}.log"
        try:
            with open(log_file, 'a') as f:
                f.write(log_line + "\n")
        except IOError:
            pass

    # -- SSE ------------------------------------------------------------------

    def register_sse_client(self, wfile):
        with self._sse_lock:
            self._sse_clients.append(wfile)

    def unregister_sse_client(self, wfile):
        with self._sse_lock:
            try:
                self._sse_clients.remove(wfile)
            except ValueError:
                pass

    def _broadcast_sse(self, event: str, data):
        """Send an SSE event to all connected clients."""
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        encoded = payload.encode("utf-8")
        dead = []
        with self._sse_lock:
            for wfile in self._sse_clients:
                try:
                    wfile.write(encoded)
                    wfile.flush()
                except Exception:
                    dead.append(wfile)
            for d in dead:
                try:
                    self._sse_clients.remove(d)
                except ValueError:
                    pass

    def _broadcast_status(self):
        self._broadcast_sse("status", {
            "state": self.state.value,
            "algorithm": self.algorithm,
            "calibration": self.calibration.phase_offset_deg,
            "calValid": self.calibration.is_valid(),
            "calTimestamp": self.calibration.timestamp,
            "lastAoA": self.last_aoa,
            "progress": self.progress,
            "error": self.error_msg,
        })

    # -- Commands -------------------------------------------------------------

    def get_status(self) -> dict:
        with self._lock:
            return {
                "state": self.state.value,
                "algorithm": self.algorithm,
                "calibration": self.calibration.phase_offset_deg,
                "calValid": self.calibration.is_valid(),
                "calTimestamp": self.calibration.timestamp,
                "lastAoA": self.last_aoa,
                "progress": self.progress,
                "error": self.error_msg,
            }

    def start_calibration(self) -> dict:
        with self._lock:
            if self.state not in (SystemState.IDLE, SystemState.ERROR):
                return {"ok": False, "error": f"Cannot calibrate in state {self.state.value}"}

            self.state = SystemState.CALIBRATING
            self.progress = 0
            self.error_msg = None

        self.log("Starting calibration")
        self._broadcast_status()

        def on_output(line: str):
            # Forward every line to the console log
            self._broadcast_sse("log", {"text": line})

            if line.startswith("PHASE:"):
                try:
                    phase_deg = float(line.split(":")[1])
                    with self._lock:
                        self.calibration.phase_offset_deg = phase_deg
                    self._broadcast_sse("cal", {"value": phase_deg})
                except ValueError:
                    pass
            elif line.startswith("PROGRESS:"):
                try:
                    pct = int(line.split(":")[1])
                    with self._lock:
                        self.progress = pct
                    self._broadcast_sse("progress", {"value": pct})
                except ValueError:
                    pass
            elif line.startswith("ERROR:"):
                msg = line.split(":", 1)[1]
                with self._lock:
                    self.error_msg = msg
                self._broadcast_sse("error", {"message": msg})

        def run_cal():
            if self.process_mgr.start(Config.CALIBRATION_SCRIPT, output_callback=on_output):
                while self.process_mgr.is_running():
                    time.sleep(0.1)
                with self._lock:
                    self.state = SystemState.IDLE
                    self.progress = 100
                self.log(f"Calibration complete: {self.calibration.phase_offset_deg}°")
            else:
                with self._lock:
                    self.state = SystemState.ERROR
                    self.error_msg = "Failed to start calibration script"
                self._broadcast_sse("error", {"message": self.error_msg})
            self._broadcast_status()

        threading.Thread(target=run_cal, daemon=True).start()
        return {"ok": True}

    def start_estimation(self, algo: str = None) -> dict:
        with self._lock:
            if self.state == SystemState.ESTIMATING:
                return {"ok": False, "error": "Already estimating"}
            if not self.calibration.is_valid():
                return {"ok": False, "error": "No valid calibration. Run calibration first."}

            algo = (algo or self.algorithm).upper()
            if algo not in ("ROOTMUSIC", "MUSIC", "MVDR", "PHASEDIFF"):
                return {"ok": False, "error": f"Unknown algorithm '{algo}'"}

            self.algorithm = algo
            self.state = SystemState.ESTIMATING
            self.error_msg = None

        self.log(f"Starting estimation with {algo}")
        self._broadcast_status()

        def on_output(line: str):
            # Forward every line to the console log
            self._broadcast_sse("log", {"text": line})

            if line.startswith("AOA:"):
                try:
                    aoa_deg = float(line.split(":")[1])
                    with self._lock:
                        self.last_aoa = aoa_deg
                    self._broadcast_sse("aoa", {"value": aoa_deg})
                except ValueError:
                    pass
            elif line.startswith("ERROR:"):
                msg = line.split(":", 1)[1]
                with self._lock:
                    self.error_msg = msg
                self._broadcast_sse("error", {"message": msg})

        def run_est():
            args = [
                f"--cal={self.calibration.phase_offset_deg}",
                f"--algo={self.algorithm}",
            ]
            if self.process_mgr.start(Config.ESTIMATION_SCRIPT, args=args,
                                       output_callback=on_output):
                while self.process_mgr.is_running():
                    time.sleep(0.1)
                with self._lock:
                    if self.state == SystemState.ESTIMATING:
                        self.state = SystemState.IDLE
            else:
                with self._lock:
                    self.state = SystemState.ERROR
                    self.error_msg = "Failed to start estimation script"
                self._broadcast_sse("error", {"message": self.error_msg})
            self._broadcast_status()

        threading.Thread(target=run_est, daemon=True).start()
        return {"ok": True}

    def stop_operation(self) -> dict:
        with self._lock:
            self.process_mgr.stop()
            self.state = SystemState.IDLE
            self.error_msg = None
        self.log("Operation stopped by user")
        self._broadcast_status()
        return {"ok": True}

    def set_calibration(self, value: float) -> dict:
        if not -180 <= value <= 180:
            return {"ok": False, "error": "Phase must be between -180 and 180 degrees"}
        with self._lock:
            self.calibration.phase_offset_deg = value
        self.log(f"Manual calibration set: {value}°")
        self._broadcast_sse("cal", {"value": value})
        self._broadcast_status()
        return {"ok": True}


# =============================================================================
# HTTP Request Handler
# =============================================================================

# Shared controller instance (set in main)
controller: Optional[DoAController] = None


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    """Handles HTTP requests for the dashboard."""

    # Silence per-request log lines
    def log_message(self, format, *args):
        pass

    # -- Routing --------------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/":
            self._serve_dashboard()
        elif path == "/api/status":
            self._json_response(controller.get_status())
        elif path == "/api/stream":
            self._serve_sse()
        else:
            self._json_response({"error": "Not found"}, code=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        body = self._read_body()

        if path == "/api/calibrate":
            self._json_response(controller.start_calibration())
        elif path == "/api/estimate":
            algo = body.get("algo") if body else None
            self._json_response(controller.start_estimation(algo))
        elif path == "/api/stop":
            self._json_response(controller.stop_operation())
        elif path == "/api/set_cal":
            if not body or "value" not in body:
                self._json_response({"ok": False, "error": "Missing 'value'"}, code=400)
                return
            try:
                val = float(body["value"])
            except (ValueError, TypeError):
                self._json_response({"ok": False, "error": "Invalid number"}, code=400)
                return
            self._json_response(controller.set_calibration(val))
        else:
            self._json_response({"error": "Not found"}, code=404)

    # -- Helpers --------------------------------------------------------------

    def _read_body(self) -> Optional[dict]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _json_response(self, data: dict, code: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_dashboard(self):
        body = DASHBOARD_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        controller.register_sse_client(self.wfile)

        # Send initial status
        try:
            status = controller.get_status()
            payload = f"event: status\ndata: {json.dumps(status)}\n\n"
            self.wfile.write(payload.encode("utf-8"))
            self.wfile.flush()
        except Exception:
            controller.unregister_sse_client(self.wfile)
            return

        # Keep connection alive until client disconnects
        try:
            while True:
                time.sleep(1)
                # Send keepalive comment
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except Exception:
            pass
        finally:
            controller.unregister_sse_client(self.wfile)


# =============================================================================
# Threaded HTTP Server
# =============================================================================

class ThreadedHTTPServer(http.server.HTTPServer):
    """HTTP server that handles each request in a new thread."""
    allow_reuse_address = True
    daemon_threads = True

    def process_request(self, request, client_address):
        t = threading.Thread(target=self._handle, args=(request, client_address),
                             daemon=True)
        t.start()

    def _handle(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


# =============================================================================
# Dashboard HTML
# =============================================================================

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DoA Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#1a1a2e;color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;display:flex;flex-direction:column;align-items:center;min-height:100vh;padding:16px}
h1{font-size:1.1rem;color:#8888cc;margin-bottom:12px;letter-spacing:.05em}

/* Status bar */
.status-bar{display:flex;align-items:center;gap:8px;margin-bottom:16px;font-size:.9rem}
.status-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.status-dot.idle{background:#4ecca3}
.status-dot.calibrating{background:#f0c040}
.status-dot.estimating{background:#4e9af5}
.status-dot.error{background:#e04050}

/* Gauge */
.gauge-container{position:relative;width:320px;height:200px;margin-bottom:12px}
.gauge-container svg{width:100%;height:100%}
.arc-bg{fill:none;stroke:#2a2a4a;stroke-width:18;stroke-linecap:round}
.arc-fg{fill:none;stroke:#4ecca3;stroke-width:18;stroke-linecap:round;transition:stroke-dashoffset .15s ease}
.tick line{stroke:#444;stroke-width:1}
.tick text{fill:#888;font-size:9px;text-anchor:middle}
.needle{stroke:#e04050;stroke-width:2.5;stroke-linecap:round;transition:transform .15s ease;transform-origin:160px 180px}

/* Angle readout */
.angle-readout{text-align:center;margin-bottom:16px}
.angle-value{font-size:3.2rem;font-weight:700;color:#fff;font-variant-numeric:tabular-nums}
.angle-unit{font-size:1.2rem;color:#888;margin-left:2px}

/* Controls */
.controls{display:flex;gap:10px;flex-wrap:wrap;justify-content:center;margin-bottom:16px}
.btn{border:none;border-radius:6px;padding:10px 22px;font-size:.95rem;font-weight:600;cursor:pointer;transition:opacity .15s}
.btn:active{opacity:.7}
.btn:disabled{opacity:.35;cursor:not-allowed}
.btn-cal{background:#3a6ece;color:#fff}
.btn-est{background:#2e8b57;color:#fff}
.btn-stop{background:#c0392b;color:#fff}

/* Algorithm selector */
.algo-row{display:flex;align-items:center;gap:8px;margin-bottom:16px;font-size:.9rem}
.algo-row select{background:#2a2a4a;color:#e0e0e0;border:1px solid #444;border-radius:4px;padding:4px 8px;font-size:.9rem}

/* Info panel */
.info{background:#16213e;border-radius:8px;padding:12px 18px;width:100%;max-width:380px;font-size:.85rem;line-height:1.7}
.info-label{color:#888}
.info-value{color:#ccc;float:right}

/* Manual cal */
.cal-row{display:flex;align-items:center;gap:6px;margin-top:10px;justify-content:center}
.cal-row input{width:80px;background:#2a2a4a;color:#e0e0e0;border:1px solid #444;border-radius:4px;padding:4px 6px;font-size:.85rem;text-align:right}
.cal-row button{background:#555;color:#ddd;border:none;border-radius:4px;padding:4px 10px;font-size:.8rem;cursor:pointer}

/* Progress bar */
.progress-bar{width:100%;max-width:320px;height:6px;background:#2a2a4a;border-radius:3px;margin-bottom:12px;overflow:hidden;display:none}
.progress-bar.active{display:block}
.progress-fill{height:100%;background:#f0c040;border-radius:3px;transition:width .3s ease;width:0%}

/* Error banner */
.error-banner{background:#5a1a1a;color:#ff8888;border-radius:6px;padding:8px 14px;font-size:.85rem;margin-bottom:12px;display:none;max-width:380px;width:100%;word-break:break-word}
.error-banner.visible{display:block}

/* Console log */
.console-container{width:100%;max-width:380px;margin-top:12px}
.console-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
.console-header span{font-size:.8rem;color:#888}
.console-header button{background:none;border:none;color:#666;font-size:.75rem;cursor:pointer}
.console-log{background:#0d1117;border:1px solid #2a2a4a;border-radius:6px;padding:8px 10px;font-family:'Courier New',monospace;font-size:.75rem;line-height:1.5;height:160px;overflow-y:auto;color:#8b949e;word-break:break-all}
.console-log .log-phase{color:#4ecca3;font-weight:700}
.console-log .log-progress{color:#f0c040}
.console-log .log-error{color:#ff6b6b}
.console-log .log-aoa{color:#4e9af5}
.console-log .log-comment{color:#666}

/* History sparkline */
.history-container{width:100%;max-width:380px;margin-top:12px}
.history-container canvas{width:100%;height:80px;border-radius:6px;background:#16213e}
</style>
</head>
<body>

<h1>2.4 GHz DIRECTION OF ARRIVAL</h1>

<div class="status-bar">
  <div class="status-dot idle" id="statusDot"></div>
  <span id="statusText">Connecting...</span>
</div>

<div class="error-banner" id="errorBanner"></div>

<div class="progress-bar" id="progressBar">
  <div class="progress-fill" id="progressFill"></div>
</div>

<div class="gauge-container">
  <svg viewBox="0 0 320 200" id="gaugeSvg"></svg>
</div>

<div class="angle-readout">
  <span class="angle-value" id="angleValue">---</span><span class="angle-unit">&deg;</span>
</div>

<div class="algo-row">
  <label for="algoSelect">Algorithm:</label>
  <select id="algoSelect">
    <option value="ROOTMUSIC">Root-MUSIC</option>
    <option value="MUSIC">MUSIC</option>
    <option value="MVDR">MVDR</option>
    <option value="PHASEDIFF">Phase Diff</option>
  </select>
</div>

<div class="controls">
  <button class="btn btn-cal" id="btnCal" onclick="doCalibrate()">CALIBRATE</button>
  <button class="btn btn-est" id="btnEst" onclick="doEstimate()">ESTIMATE</button>
  <button class="btn btn-stop" id="btnStop" onclick="doStop()">STOP</button>
</div>

<div class="info" id="infoPanel">
  <div><span class="info-label">Calibration:</span><span class="info-value" id="calValue">0.00&deg;</span></div>
  <div><span class="info-label">Cal time:</span><span class="info-value" id="calTime">never</span></div>
  <div><span class="info-label">Algorithm:</span><span class="info-value" id="infoAlgo">ROOTMUSIC</span></div>
</div>

<div class="cal-row">
  <label style="font-size:.85rem;color:#888">Set cal:</label>
  <input type="number" id="calInput" step="0.1" min="-180" max="180" value="0">
  <button onclick="doSetCal()">&crarr;</button>
</div>

<div class="console-container">
  <div class="console-header">
    <span>Console</span>
    <button onclick="clearConsole()">clear</button>
  </div>
  <div class="console-log" id="consoleLog"></div>
</div>

<div class="history-container">
  <canvas id="historyCanvas" height="80"></canvas>
</div>

<script>
// ── State ──────────────────────────────────────────────────────
let currentState = 'IDLE';
let aoaHistory = [];
const MAX_HISTORY = 200;

// ── Gauge setup ────────────────────────────────────────────────
(function initGauge(){
  const svg = document.getElementById('gaugeSvg');
  const cx=160, cy=180, r=140;
  // Arc from 180° to 0° (left to right, top half)
  function polarToCart(deg){
    const rad = deg * Math.PI/180;
    return [cx + r*Math.cos(rad), cy - r*Math.sin(rad)];
  }
  // Background arc (180° sweep, from left to right)
  const [x1,y1]=polarToCart(180);
  const [x2,y2]=polarToCart(0);
  const bgPath = `M${x1},${y1} A${r},${r} 0 0,1 ${x2},${y2}`;

  let html = `<path class="arc-bg" d="${bgPath}"/>`;
  html += `<path class="arc-fg" id="arcFg" d="${bgPath}" stroke-dasharray="0 9999"/>`;

  // Tick marks every 30°
  for(let a=0; a<=180; a+=30){
    const rad = (180-a)*Math.PI/180;
    const ox=cx+r*Math.cos(rad), oy=cy-r*Math.sin(rad);
    const ix=cx+(r-14)*Math.cos(rad), iy=cy-(r-14)*Math.sin(rad);
    const tx=cx+(r+14)*Math.cos(rad), ty=cy-(r+14)*Math.sin(rad);
    html += `<g class="tick"><line x1="${ix}" y1="${iy}" x2="${ox}" y2="${oy}"/>`;
    html += `<text x="${tx}" y="${ty+3}">${a}</text></g>`;
  }

  // Needle
  html += `<line class="needle" id="needle" x1="${cx}" y1="${cy}" x2="${cx}" y2="${cy-r+20}"/>`;
  // Center dot
  html += `<circle cx="${cx}" cy="${cy}" r="5" fill="#e04050"/>`;

  svg.innerHTML = html;
})();

function setGaugeAngle(deg){
  // deg: 0-180 DoA angle
  deg = Math.max(0, Math.min(180, deg));

  // Needle rotation: 0° → point left (180° svg), 180° → point right (0° svg)
  const svgAngle = -(180 - deg); // rotation from 12 o'clock
  const needle = document.getElementById('needle');
  const cx=160, cy=180, r=120;
  const rad = (180-deg)*Math.PI/180;
  const nx = cx + r*Math.cos(rad);
  const ny = cy - r*Math.sin(rad);
  needle.setAttribute('x2', nx);
  needle.setAttribute('y2', ny);

  // Arc fill: fraction of 180° sweep
  const arcLen = Math.PI * 140; // half circumference
  const fill = (deg/180) * arcLen;
  const fg = document.getElementById('arcFg');
  fg.setAttribute('stroke-dasharray', `${fill} ${arcLen}`);
}

// ── SSE ────────────────────────────────────────────────────────
let evtSource = null;
function connectSSE(){
  if(evtSource) evtSource.close();
  evtSource = new EventSource('/api/stream');

  evtSource.addEventListener('status', e => {
    const d = JSON.parse(e.data);
    applyStatus(d);
  });

  evtSource.addEventListener('aoa', e => {
    const d = JSON.parse(e.data);
    updateAoA(d.value);
  });

  evtSource.addEventListener('cal', e => {
    const d = JSON.parse(e.data);
    document.getElementById('calValue').textContent = d.value.toFixed(2) + '\u00b0';
  });

  evtSource.addEventListener('progress', e => {
    const d = JSON.parse(e.data);
    setProgress(d.value);
  });

  evtSource.addEventListener('log', e => {
    const d = JSON.parse(e.data);
    appendConsole(d.text);
  });

  evtSource.addEventListener('error', e => {
    try{
      const d = JSON.parse(e.data);
      showError(d.message);
    }catch(_){}
  });

  evtSource.onerror = () => {
    document.getElementById('statusText').textContent = 'Disconnected';
    document.getElementById('statusDot').className = 'status-dot error';
    setTimeout(connectSSE, 3000);
  };
}
connectSSE();

// ── UI updates ─────────────────────────────────────────────────
function applyStatus(d){
  currentState = d.state;
  const dot = document.getElementById('statusDot');
  const txt = document.getElementById('statusText');

  const stateMap = {
    IDLE:        ['idle',        'Ready'],
    CALIBRATING: ['calibrating', 'Calibrating...'],
    ESTIMATING:  ['estimating',  'Estimating'],
    ERROR:       ['error',       'Error'],
  };
  const [cls, label] = stateMap[d.state] || ['idle','Unknown'];
  dot.className = 'status-dot ' + cls;
  txt.textContent = label;

  document.getElementById('infoAlgo').textContent = d.algorithm;
  document.getElementById('algoSelect').value = d.algorithm;
  document.getElementById('calValue').textContent = d.calibration.toFixed(2) + '\u00b0';

  if(d.calTimestamp){
    const t = new Date(d.calTimestamp);
    document.getElementById('calTime').textContent = t.toLocaleTimeString();
  }

  if(d.lastAoA !== null && d.lastAoA !== undefined){
    updateAoA(d.lastAoA);
  }

  // Button states
  const busy = d.state === 'CALIBRATING' || d.state === 'ESTIMATING';
  document.getElementById('btnCal').disabled = busy;
  document.getElementById('btnEst').disabled = d.state === 'CALIBRATING';
  document.getElementById('btnStop').disabled = !busy;

  // Progress bar
  if(d.state === 'CALIBRATING'){
    setProgress(d.progress);
    document.getElementById('progressBar').classList.add('active');
  } else {
    document.getElementById('progressBar').classList.remove('active');
  }

  // Error
  if(d.error){
    showError(d.error);
  } else {
    hideError();
  }
}

function updateAoA(val){
  val = parseFloat(val);
  if(isNaN(val)) return;
  document.getElementById('angleValue').textContent = val.toFixed(1);
  setGaugeAngle(val);
  aoaHistory.push(val);
  if(aoaHistory.length > MAX_HISTORY) aoaHistory.shift();
  drawHistory();
}

function setProgress(pct){
  document.getElementById('progressFill').style.width = pct + '%';
  if(pct > 0){
    document.getElementById('progressBar').classList.add('active');
  }
}

function showError(msg){
  const el = document.getElementById('errorBanner');
  el.textContent = msg;
  el.classList.add('visible');
}
function hideError(){
  document.getElementById('errorBanner').classList.remove('visible');
}

// ── Console log ────────────────────────────────────────────────
const MAX_CONSOLE_LINES = 200;
function appendConsole(text){
  const el = document.getElementById('consoleLog');
  const line = document.createElement('div');

  // Color-code by prefix
  if(text.startsWith('PHASE:'))       line.className = 'log-phase';
  else if(text.startsWith('PROGRESS:')) line.className = 'log-progress';
  else if(text.startsWith('ERROR:'))   line.className = 'log-error';
  else if(text.startsWith('AOA:'))     line.className = 'log-aoa';
  else if(text.startsWith('#'))        line.className = 'log-comment';

  line.textContent = text;
  el.appendChild(line);

  // Trim old lines
  while(el.children.length > MAX_CONSOLE_LINES){
    el.removeChild(el.firstChild);
  }

  // Auto-scroll to bottom
  el.scrollTop = el.scrollHeight;
}
function clearConsole(){
  document.getElementById('consoleLog').innerHTML = '';
}

// ── History sparkline ──────────────────────────────────────────
function drawHistory(){
  const canvas = document.getElementById('historyCanvas');
  const ctx = canvas.getContext('2d');
  const W = canvas.width = canvas.offsetWidth * (window.devicePixelRatio || 1);
  const H = canvas.height = 80 * (window.devicePixelRatio || 1);
  ctx.clearRect(0,0,W,H);

  if(aoaHistory.length < 2) return;

  ctx.strokeStyle = '#4ecca3';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  const n = aoaHistory.length;
  for(let i=0;i<n;i++){
    const x = (i/(MAX_HISTORY-1))*W;
    const y = H - (aoaHistory[i]/180)*H;
    if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
  }
  ctx.stroke();

  // Y-axis labels
  ctx.fillStyle = '#555';
  ctx.font = `${10 * (window.devicePixelRatio||1)}px sans-serif`;
  ctx.fillText('180\u00b0', 2, 12*(window.devicePixelRatio||1));
  ctx.fillText('0\u00b0', 2, H - 2);
}

// ── API calls ──────────────────────────────────────────────────
function post(url, body){
  return fetch(url, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: body ? JSON.stringify(body) : undefined,
  }).then(r=>r.json());
}

function doCalibrate(){
  hideError();
  post('/api/calibrate');
}
function doEstimate(){
  hideError();
  const algo = document.getElementById('algoSelect').value;
  post('/api/estimate', {algo});
}
function doStop(){
  post('/api/stop');
}
function doSetCal(){
  const v = parseFloat(document.getElementById('calInput').value);
  if(isNaN(v)){showError('Invalid number'); return;}
  post('/api/set_cal', {value: v});
}

// Init gauge to center
setGaugeAngle(90);
</script>
</body>
</html>
"""


# =============================================================================
# Entry Point
# =============================================================================

def main():
    global controller

    parser = argparse.ArgumentParser(description="DoA Web Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    args = parser.parse_args()

    controller = DoAController()
    controller.log(f"Starting web dashboard on {args.host}:{args.port}")

    server = ThreadedHTTPServer((args.host, args.port), DashboardHandler)

    def shutdown(signum, frame):
        print("\nShutting down...")
        controller.process_mgr.stop()
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"Dashboard: http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
