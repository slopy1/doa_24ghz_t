#!/usr/bin/env python3
"""Quick test: send STATUS over /dev/ttyUSB0 and listen for response."""
import os, time

DEV = "/dev/ttyUSB0"
os.chmod(DEV, 0o666)

fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY)

# Set baud rate via stty (simpler than termios on BusyBox)
os.system(f"stty -F {DEV} 115200 raw -echo")
time.sleep(0.1)

# Send
os.write(fd, b"STATUS\n")
print("Sent: STATUS")

# Listen for 3 seconds
print("Listening...")
end = time.time() + 3
while time.time() < end:
    try:
        data = os.read(fd, 256)
        if data:
            print(f"Got: {data}")
    except BlockingIOError:
        pass
    time.sleep(0.05)

os.close(fd)
print("Done")
