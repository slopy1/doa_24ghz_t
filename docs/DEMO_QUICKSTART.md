# Quick Demo Setup — DoA System

## 1. Power On

- Battery on (powers Cora via barrel jack, JP3 set to EXT)
- Powered USB hub on (BladeRF + FT232R/RS485 chain to display)
- Plug Ethernet cable between Cora and PC

## 2. Host PC Network Setup

```bash
sudo nmcli device set enp7s0 managed no
sudo ip addr add 192.168.1.1/24 dev enp7s0
```

## 3. Cora Serial Console (set static IP)

```bash
picocom -b 115200 /dev/ttyUSB1
```

On Cora:
```bash
sudo ip addr add 192.168.1.100/24 dev enx000a35001e53
```

Exit picocom: `Ctrl-A`, then `Ctrl-X`

## 4. Start nRF53 TX (Signal Source)

Plug nRF5340 into PC USB. Find the port:
```bash
ls /dev/ttyACM*
```

Connect:
```bash
picocom -b 115200 /dev/ttyACM0
```

Start transmitting at 2418 MHz (channel 19):
```
start_channel 19
output_power set 0
start_tx_modulated_carrier
```

To stop TX later:
```
cancel
```

Exit picocom: `Ctrl-A`, then `Ctrl-X`

## 5. Start DoA — Touch Screen Mode

```bash
ssh petalinux@192.168.1.100
sudo python3 /home/petalinux/doa/main.py
```

Use the ESP32 touch screen to CALIBRATE then ESTIMATE.

## 6. Start DoA — Web Dashboard Mode (Alternative)

```bash
ssh petalinux@192.168.1.100
sudo /etc/init.d/doa-controller start
```

Open browser: `http://192.168.1.100:8080`

## Teardown

1. Stop main.py or dashboard: `Ctrl-C` or `sudo /etc/init.d/doa-controller stop`
2. Stop nRF TX: `cancel` in picocom
3. Power off battery

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No route to host` | Re-run host PC network setup (step 2) |
| `picocom: Resource temporarily unavailable` | Previous picocom still open — find and close it |
| No `ttyUSB*` devices | Check USB cables are seated |
| `NO-CARRIER` on `ip addr show enp7s0` | Ethernet cable not plugged in |
| BladeRF not found | Check barrel jack power on BladeRF (needs external 5V 2A+) |
