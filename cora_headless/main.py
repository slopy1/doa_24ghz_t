#!/usr/bin/env python3
"""
main.py - UART Command Listener for Cora Z7 Headless DoA System

This script runs on the Cora Z7 at boot and listens for commands from the 
Waveshare ESP32-S3-Touch-LCD-4.3 display via UART. It dispatches commands
to the appropriate GNU Radio scripts for calibration and DoA estimation.

Hardware Setup:
    - Cora Z7 UART pins connected to Waveshare display UART pins
    - BladeRF 2.0 connected via USB (limited to 6 MSPS due to USB 2.0)

Protocol:
    Commands (from Display → Cora):
        CALIBRATE           - Run phase calibration routine
        ESTIMATE            - Run DoA estimation with current calibration
        ESTIMATE:<algo>     - Run specific algorithm (MUSIC, ROOTMUSIC, MVDR, PHASEDIFF)
        STATUS              - Report current system status
        GET_CAL             - Return current calibration coefficient
        SET_CAL:<value>     - Manually set calibration coefficient (degrees)
        STOP                - Stop any running estimation
        SHUTDOWN            - Safe shutdown sequence
    
    Responses (from Cora → Display):
        OK:<message>        - Command acknowledged
        ERROR:<message>     - Command failed
        CAL:<value>         - Calibration coefficient in degrees
        AOA:<value>         - Estimated angle of arrival in degrees
        STATUS:<state>      - Current system state
        DONE                - Operation completed

Author: DoA Thesis Project
Date: 2026
"""

import serial
import subprocess
import threading
import signal
import sys
import json
import time
from pathlib import Path
from datetime import datetime
from enum import Enum
from typing import Optional, Callable

# =============================================================================
# Configuration
# =============================================================================

class Config:
    """System configuration constants."""
    
    # UART Settings
    UART_PORT = "/dev/ttyUSB0"  # FT232RL USB-UART adapter from Waveshare PH2.0 header
    UART_BAUD = 115200
    UART_TIMEOUT = 0.1  # seconds
    
    # File Paths
    SCRIPT_DIR = Path(__file__).parent
    DATA_DIR = SCRIPT_DIR / "data"
    LOG_DIR = SCRIPT_DIR / "logs"
    CAL_FILE = DATA_DIR / "calibration.json"
    
    # Script Paths (GNU Radio generated Python scripts)
    CALIBRATION_SCRIPT = SCRIPT_DIR / "phase_calibration_headless.py"
    ESTIMATION_SCRIPT = SCRIPT_DIR / "aoa_estimation_headless.py"
    ESTIMATION_FPGA_SCRIPT = SCRIPT_DIR / "aoa_estimation_fpga_v2.py"
    
    # Operational Parameters
    WARMUP_TIME = 30  # seconds to wait for BladeRF thermal stability
    CAL_DURATION = 10  # seconds to collect calibration data
    ESTIMATION_INTERVAL = 0.1  # seconds between AoA reports
    
    # Sample Rate (limited by USB 2.0 bandwidth)
    SAMPLE_RATE = 1e6  # 1 MSPS (conservative for USB 2.0)


class SystemState(Enum):
    """System state machine states."""
    IDLE = "IDLE"
    WARMING_UP = "WARMING_UP"
    CALIBRATING = "CALIBRATING"
    ESTIMATING = "ESTIMATING"
    ERROR = "ERROR"
    SHUTTING_DOWN = "SHUTTING_DOWN"


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
        """Load calibration data from file."""
        if self.filepath.exists():
            try:
                with open(self.filepath, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {
            "phase_offset_deg": 0.0,
            "timestamp": None,
            "gain_setting": None,
            "frequency_hz": None
        }
    
    def _save(self):
        """Save calibration data to file."""
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
    
    def update(self, phase_deg: float, gain: int = None, freq_hz: float = None):
        """Update calibration with full context."""
        self._data["phase_offset_deg"] = phase_deg
        self._data["timestamp"] = datetime.now().isoformat()
        if gain is not None:
            self._data["gain_setting"] = gain
        if freq_hz is not None:
            self._data["frequency_hz"] = freq_hz
        self._save()
    
    def is_valid(self) -> bool:
        """Check if calibration exists and is recent."""
        return self._data.get("timestamp") is not None


# =============================================================================
# Data Logging
# =============================================================================

class DataLogger:
    """Per-run CSV logger for DoA estimation results.

    Thread-safe: log_row() and close() may be called concurrently from the
    ProcessManager reader thread and the main command thread.

    Crash-safe: file is line-buffered and flushed after each row, so a kill
    mid-run preserves all rows written up to that point.

    Sidecar JSON metadata is written on close() with the calibration value,
    duration, row count, and effective sample rate.
    """

    def __init__(self, data_dir: Path, mode: str, algo: str,
                 label: str = "", calibration_deg: float = 0.0):
        data_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        parts = ["aoa"]
        if label:
            parts.append(label)
        parts.extend([mode, algo, ts])
        base = "_".join(parts)
        self.csv_path = data_dir / f"{base}.csv"
        self.meta_path = data_dir / f"{base}.json"
        self._mode = mode
        self._algo = algo
        self._label = label
        self._cal = calibration_deg
        self._lock = threading.Lock()
        self._fh = None
        self._rows = 0
        self._start = time.time()

    def open(self) -> bool:
        """Open CSV file and write header. Returns True on success."""
        try:
            self._fh = open(self.csv_path, "w", buffering=1)  # line-buffered
            self._fh.write("timestamp,aoa_deg,algo,mode\n")
            self._fh.flush()
            return True
        except OSError:
            self._fh = None
            return False

    def log_row(self, aoa_deg: float) -> None:
        """Append one AOA reading with current timestamp."""
        with self._lock:
            if self._fh is None:
                return
            try:
                ts = datetime.now().isoformat()
                self._fh.write(f"{ts},{aoa_deg:.1f},{self._algo},{self._mode}\n")
                self._rows += 1
            except OSError:
                pass  # disk full / fd closed — drop silently rather than crash

    def close(self) -> tuple:
        """Close CSV, write sidecar JSON. Returns (rows, duration_s)."""
        with self._lock:
            if self._fh is None:
                return (self._rows, 0.0)
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
        duration = time.time() - self._start
        try:
            meta = {
                "csv": self.csv_path.name,
                "mode": self._mode,
                "algorithm": self._algo,
                "label": self._label,
                "calibration_deg": self._cal,
                "start_iso": datetime.fromtimestamp(self._start).isoformat(),
                "duration_s": round(duration, 2),
                "rows": self._rows,
                "rate_hz": round(self._rows / duration, 2) if duration > 0 else 0.0,
            }
            with open(self.meta_path, "w") as f:
                json.dump(meta, f, indent=2)
        except OSError:
            pass
        return (self._rows, duration)


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
        """Start a GNU Radio script as subprocess."""
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
                bufsize=1
            )
            
            # Start output reader thread
            self._reader_thread = threading.Thread(
                target=self._read_output,
                daemon=True
            )
            self._reader_thread.start()
            
            return True
            
        except Exception as e:
            print(f"Failed to start process: {e}")
            return False
    
    def _read_output(self):
        """Read subprocess output and invoke callback."""
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
        """Stop the current subprocess."""
        self._stop_event.set()
        if self.current_process:
            self.current_process.terminate()
            try:
                self.current_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.current_process.kill()
            self.current_process = None
    
    def is_running(self) -> bool:
        """Check if a subprocess is currently running."""
        return (self.current_process is not None and 
                self.current_process.poll() is None)


# =============================================================================
# Main Controller
# =============================================================================

class DoAController:
    """Main controller for the headless DoA system."""
    
    def __init__(self):
        self.state = SystemState.IDLE
        self.serial: Optional[serial.Serial] = None
        self.calibration = CalibrationStore(Config.CAL_FILE)
        self.process_mgr = ProcessManager()
        self._running = True
        self._last_aoa = None
        self.data_logger: Optional[DataLogger] = None
        self.experiment_label = ""

        # Ensure directories exist
        Config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        Config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    def setup_serial(self, retries: int = 5, delay: float = 3.0) -> bool:
        """Initialize UART connection with retry on USB glitches."""
        for attempt in range(retries):
            try:
                self.serial = serial.Serial(
                    port=Config.UART_PORT,
                    baudrate=Config.UART_BAUD,
                    timeout=Config.UART_TIMEOUT
                )
                self.log(f"UART opened on {Config.UART_PORT}")
                return True
            except (serial.SerialException, TimeoutError, OSError) as e:
                self.log(f"UART open attempt {attempt+1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(delay)
        self.log("Failed to open UART after all retries")
        return False
    
    def send(self, message: str):
        """Send message to display via UART."""
        if self.serial and self.serial.is_open:
            try:
                self.serial.write(f"{message}\n".encode('utf-8'))
                self.serial.flush()
            except (serial.SerialException, TimeoutError, OSError):
                pass  # Will be caught by main loop reconnect
            self.log(f"TX: {message}")
    
    def log(self, message: str):
        """Log message to console and file."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        print(log_line)
        
        log_file = Config.LOG_DIR / f"{datetime.now().strftime('%Y%m%d')}.log"
        with open(log_file, 'a') as f:
            f.write(log_line + "\n")
    
    # -------------------------------------------------------------------------
    # Command Handlers
    # -------------------------------------------------------------------------
    
    def handle_command(self, cmd: str):
        """Parse and dispatch incoming command."""
        cmd = cmd.strip().upper()
        
        if not cmd:
            return
        
        self.log(f"RX: {cmd}")
        
        # Parse command and optional argument
        if ':' in cmd:
            cmd_name, cmd_arg = cmd.split(':', 1)
        else:
            cmd_name, cmd_arg = cmd, None
        
        # Dispatch
        handlers = {
            "CALIBRATE": self.cmd_calibrate,
            "ESTIMATE": self.cmd_estimate,
            "STATUS": self.cmd_status,
            "GET_CAL": self.cmd_get_cal,
            "SET_CAL": self.cmd_set_cal,
            "LABEL": self.cmd_label,
            "STOP": self.cmd_stop,
            "SHUTDOWN": self.cmd_shutdown,
        }
        
        # Ignore heartbeat from display (no response needed)
        if cmd_name == "HEARTBEAT":
            return

        # Ignore echoed responses — these are our own TX messages bouncing back.
        # Response formats: STATUS:IDLE, OK:..., ERROR:..., AOA:..., CAL:..., DONE, PROGRESS:...
        # Only bare STATUS (no arg) is a valid command from the display.
        RESPONSE_ONLY = {"OK", "AOA", "CAL", "PROGRESS", "DONE"}
        if cmd_name in RESPONSE_ONLY:
            return
        if cmd_name == "ERROR" and cmd_arg is not None:
            return
        if cmd_name == "STATUS" and cmd_arg is not None:
            return  # STATUS:IDLE etc. is an echo; bare STATUS is a real query

        handler = handlers.get(cmd_name)
        if handler:
            try:
                handler(cmd_arg)
            except Exception as e:
                self.send(f"ERROR:{e}")
                self.log(f"Command error: {e}")
        else:
            self.send(f"ERROR:Unknown command '{cmd_name}'")
    
    def cmd_calibrate(self, arg: str = None):
        """Run phase calibration routine."""
        if self.state not in (SystemState.IDLE, SystemState.ERROR):
            self.send(f"ERROR:Cannot calibrate in state {self.state.value}")
            return
        
        self.state = SystemState.CALIBRATING
        self.send("OK:Starting calibration")
        
        def on_output(line: str):
            # Parse calibration script output for phase value
            if line.startswith("PHASE:"):
                try:
                    phase_deg = float(line.split(":")[1])
                    self.calibration.phase_offset_deg = phase_deg
                    self.send(f"CAL:{phase_deg:.2f}")
                except ValueError:
                    pass
            elif line.startswith("ERROR:"):
                self.send(line)
        
        if self.process_mgr.start(Config.CALIBRATION_SCRIPT, 
                                   output_callback=on_output):
            # Wait for calibration to complete
            while self.process_mgr.is_running():
                time.sleep(0.1)
            
            self.state = SystemState.IDLE
            self.send("DONE")
            self.log(f"Calibration complete: {self.calibration.phase_offset_deg}°")
        else:
            self.state = SystemState.ERROR
            self.send("ERROR:Failed to start calibration script")
    
    def cmd_estimate(self, algo: str = None):
        """Start DoA estimation.

        Supported algo values:
            ROOTMUSIC, MUSIC, MVDR, PHASEDIFF — ARM-only (NumPy)
            FPGA, FPGA:ROOTMUSIC, FPGA:MUSIC, etc. — FPGA-accelerated
        """
        if self.state == SystemState.ESTIMATING:
            self.send("ERROR:Already estimating")
            return

        if not self.calibration.is_valid():
            self.send("ERROR:No valid calibration. Run CALIBRATE first.")
            return

        self.state = SystemState.ESTIMATING

        # Check if FPGA mode requested
        use_fpga = False
        if algo and algo.upper().startswith("FPGA"):
            use_fpga = True
            # Parse FPGA:ALGO or just FPGA (defaults to ROOTMUSIC)
            parts = algo.split(":", 1) if ":" in algo else [algo]
            algo = parts[1] if len(parts) > 1 else "ROOTMUSIC"
        else:
            algo = algo or "ROOTMUSIC"

        mode = "FPGA" if use_fpga else "ARM"
        mode_str = f"FPGA+{algo}" if use_fpga else algo

        # Resolve the effective label for this run. A file at
        # Config.DATA_DIR / "current_label.txt" takes precedence over the
        # UART-set label — this lets operators set campaign labels via
        # `echo 50deg > .../current_label.txt` without a display button.
        # The file persists across runs (operator updates it between angles).
        effective_label = self.experiment_label
        label_file = Config.DATA_DIR / "current_label.txt"
        if label_file.exists():
            try:
                raw = label_file.read_text().strip()
                if raw:
                    effective_label = ''.join(
                        c if c.isalnum() or c in '-_' else '_' for c in raw
                    )
            except OSError:
                pass

        # Open per-run CSV logger (sidecar JSON written on close)
        self.data_logger = DataLogger(
            data_dir=Config.DATA_DIR,
            mode=mode,
            algo=algo,
            label=effective_label,
            calibration_deg=self.calibration.phase_offset_deg,
        )
        if self.data_logger.open():
            self.log(f"CSV opened: {self.data_logger.csv_path}")
        else:
            self.log(f"WARNING: could not open CSV at {self.data_logger.csv_path}")
            self.data_logger = None

        self.send(f"OK:Starting estimation with {mode_str}")

        def on_output(line: str):
            # Parse estimation script output for AoA value
            if line.startswith("AOA:"):
                try:
                    aoa_deg = float(line.split(":")[1])
                    self._last_aoa = aoa_deg
                    self.send(f"AOA:{aoa_deg:.1f}")
                    if self.data_logger:
                        self.data_logger.log_row(aoa_deg)
                except ValueError:
                    pass
            elif line.startswith("ERROR:"):
                self.send(line)

        script = Config.ESTIMATION_FPGA_SCRIPT if use_fpga else Config.ESTIMATION_SCRIPT
        args = [
            f"--cal={self.calibration.phase_offset_deg}",
            f"--algo={algo}"
        ]

        if not self.process_mgr.start(script, args=args,
                                       output_callback=on_output):
            self.state = SystemState.ERROR
            self.send("ERROR:Failed to start estimation script")
    
    def cmd_status(self, arg: str = None):
        """Report current system status."""
        # Detect orphaned ESTIMATING state (subprocess died without STOP)
        if (self.state == SystemState.ESTIMATING
                and not self.process_mgr.is_running()):
            self.log("Estimation subprocess exited unexpectedly")
            if self.data_logger:
                rows, duration = self.data_logger.close()
                csv_name = self.data_logger.csv_path.name
                self.log(
                    f"CSV closed (subprocess exit): {csv_name} "
                    f"({rows} rows, {duration:.1f}s)"
                )
                self.data_logger = None
            self.state = SystemState.IDLE

        self.send(f"STATUS:{self.state.value}")
        if self._last_aoa is not None:
            self.send(f"AOA:{self._last_aoa:.1f}")
        if self.calibration.is_valid():
            self.send(f"CAL:{self.calibration.phase_offset_deg:.2f}")
    
    def cmd_get_cal(self, arg: str = None):
        """Return current calibration coefficient."""
        self.send(f"CAL:{self.calibration.phase_offset_deg:.2f}")
    
    def cmd_set_cal(self, arg: str):
        """Manually set calibration coefficient."""
        if arg is None:
            self.send("ERROR:SET_CAL requires value (e.g., SET_CAL:-12.5)")
            return
        
        try:
            phase_deg = float(arg)
            if not -180 <= phase_deg <= 180:
                self.send("ERROR:Phase must be between -180 and 180 degrees")
                return
            
            self.calibration.phase_offset_deg = phase_deg
            self.send(f"OK:Calibration set to {phase_deg:.2f}°")
            self.log(f"Manual calibration set: {phase_deg}°")
            
        except ValueError:
            self.send(f"ERROR:Invalid phase value '{arg}'")

    def cmd_label(self, arg: str = None):
        """Set experiment label prepended to future CSV filenames.

        Usage:
            LABEL:50deg  - set label, applies to subsequent ESTIMATE runs
            LABEL:       - clear label
            LABEL        - report current label
        """
        if arg is None:
            current = self.experiment_label or "(none)"
            self.send(f"OK:LABEL={current}")
            return
        # Sanitize: keep alphanumerics, dash, underscore; everything else becomes _
        raw = arg.strip()
        label = ''.join(c if c.isalnum() or c in '-_' else '_' for c in raw)
        self.experiment_label = label
        if label:
            self.send(f"OK:Label set to {label}")
            self.log(f"Experiment label: {label}")
        else:
            self.send("OK:Label cleared")
            self.log("Experiment label cleared")

    def cmd_stop(self, arg: str = None):
        """Stop current operation."""
        if self.process_mgr.is_running():
            self.process_mgr.stop()

        # Close the per-run CSV logger if one is open
        if self.data_logger:
            rows, duration = self.data_logger.close()
            csv_name = self.data_logger.csv_path.name
            if duration > 0:
                rate = rows / duration
                self.log(
                    f"CSV closed: {csv_name} "
                    f"({rows} rows, {duration:.1f}s, {rate:.1f} Hz)"
                )
            else:
                self.log(f"CSV closed: {csv_name} ({rows} rows)")
            self.data_logger = None

        self.state = SystemState.IDLE
        self.send("OK:Stopped")
        self.log("Operation stopped by user")
    
    def cmd_shutdown(self, arg: str = None):
        """Initiate safe shutdown."""
        self.state = SystemState.SHUTTING_DOWN
        self.send("OK:Shutting down")
        self.log("Shutdown requested")
        
        # Stop any running processes
        self.process_mgr.stop()
        
        # Give time for message to be sent
        time.sleep(0.5)
        
        # Trigger system shutdown
        self._running = False
        # os.system("sudo shutdown -h now")  # Uncomment for actual shutdown
    
    # -------------------------------------------------------------------------
    # Main Loop
    # -------------------------------------------------------------------------
    
    def run(self):
        """Main event loop."""
        self.log("DoA Controller starting...")
        
        if not self.setup_serial():
            # Fall back to stdin for testing without hardware
            self.log("Using stdin for testing (no UART)")
            self._run_stdin_mode()
            return
        
        self.send("STATUS:READY")

        # Accumulator for partial UART reads. USB/CP210x can deliver a single
        # line across multiple read() calls, so we buffer bytes and only
        # dispatch on complete newline-terminated lines. See framing bug notes.
        rx_buf = b""

        while self._running:
            try:
                if not (self.serial and self.serial.is_open):
                    time.sleep(0.1)
                    continue
                # Read whatever is available (at least 1 byte, blocks up to
                # UART_TIMEOUT). Do NOT gate on in_waiting — that causes
                # partial-line reads.
                chunk = self.serial.read(self.serial.in_waiting or 1)
                if chunk:
                    rx_buf += chunk
                    while b"\n" in rx_buf:
                        raw, rx_buf = rx_buf.split(b"\n", 1)
                        line = raw.decode('utf-8', errors='ignore').strip()
                        if line:
                            self.handle_command(line)

            except (serial.SerialException, TimeoutError, OSError) as e:
                self.log(f"Serial error: {e} — attempting reconnect...")
                # Discard any partial line — it's from the dead port.
                rx_buf = b""
                # Close the broken port
                try:
                    if self.serial:
                        self.serial.close()
                except Exception:
                    pass
                self.serial = None
                # Wait for USB to stabilize, then reconnect
                time.sleep(3)
                if self.setup_serial(retries=3, delay=2.0):
                    self.log("UART reconnected")
                    self.send("STATUS:READY")
                else:
                    self.log("UART reconnect failed, retrying in 5s...")
                    time.sleep(5)

            except KeyboardInterrupt:
                self.log("Interrupted by user")
                break
        
        self.cleanup()
    
    def _run_stdin_mode(self):
        """Run in stdin mode for testing without hardware."""
        print("Enter commands (CALIBRATE, ESTIMATE, STATUS, etc.):")
        
        while self._running:
            try:
                cmd = input("> ")
                self.handle_command(cmd)
            except (EOFError, KeyboardInterrupt):
                break
        
        self.cleanup()
    
    def cleanup(self):
        """Clean up resources on exit."""
        self.log("Cleaning up...")
        self.process_mgr.stop()
        if self.data_logger:
            rows, duration = self.data_logger.close()
            self.log(
                f"CSV closed on shutdown: {self.data_logger.csv_path.name} "
                f"({rows} rows, {duration:.1f}s)"
            )
            self.data_logger = None
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.log("Shutdown complete")


# =============================================================================
# Entry Point
# =============================================================================

def signal_handler(signum, frame):
    """Handle termination signals."""
    print("\nReceived signal, shutting down...")
    sys.exit(0)


def main():
    """Entry point."""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    controller = DoAController()
    controller.run()


if __name__ == "__main__":
    main()
