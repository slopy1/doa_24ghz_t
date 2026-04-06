#!/usr/bin/env python3
"""Quick USB-UART serial diagnostic (FT232RL adapter)."""
import serial
import time

PORT = "/dev/ttyUSB0"
BAUD = 115200

print(f"Opening {PORT}...")
s = serial.Serial(PORT, BAUD, timeout=2)
s.dtr = True
s.rts = True
time.sleep(0.5)

# Send something to ESP32
print("Sending STATUS:IDLE to ESP32...")
s.write(b"STATUS:IDLE\n")
s.flush()

# Try to read response
print("Waiting for data from ESP32 (5 seconds)...")
end = time.time() + 5
while time.time() < end:
    if s.in_waiting:
        data = s.readline()
        print(f"  RX: {data}")
    time.sleep(0.1)

if not s.in_waiting:
    print("No data received from ESP32.")

s.close()
print("Done.")
