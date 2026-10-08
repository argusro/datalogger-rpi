# DataLogger_Rpi

Datalogger service for a Raspberry Pi Zero reading a National Instruments
**USB-6008** over USB. It exposes the current values of all **8 analog inputs**
(single-ended AI0..AI7) and **8 digital inputs** (P0.0..P0.7) through a small web
page at `/datalogger`.

The existing status site under `www/` (Flask API on port 5000 + nginx) is left
untouched. The datalogger runs as its own Flask service on port 5001.

## Repository layout

```
datalogger/
  app.py              Flask API (/api/inputs, /api/health)
  device.py           Pluggable device layer (mock / nidaqmx)
  requirements.txt
  static/index.html   The /datalogger page
deploy/
  datalogger.service  systemd unit
  nginx-datalogger.conf  nginx location snippet
  deploy.sh           Copies files to the Pi and restarts the service
www/                  Existing device status service (unchanged)
```

## Hardware note (important)

The USB-6008 is normally driven by **NI-DAQmx**, which is **x86-only** and does
**not exist for ARM**, so `nidaqmx` / `PyDAQmx` cannot run on a Raspberry Pi
Zero. Reading the hardware from the Pi therefore requires a userspace `libusb`
driver that speaks the USB-6008 protocol directly.

Until that driver is in place, the service runs a **mock backend** that produces
synthetic values, so the page and API are fully functional for development and
wiring of the inputs. The device layer is pluggable so a real driver can be
dropped in without touching the API or the page.

Backends (`DATALOGGER_BACKEND`):

| Value     | Behaviour                                                        |
|-----------|------------------------------------------------------------------|
| `auto`    | Uses `nidaqmx` if importable, otherwise falls back to `mock`.    |
| `mock`    | Synthetic values (default on the Pi Zero).                       |
| `nidaqmx` | Real device via the `nidaqmx` package (only where DAQmx exists). |

## Configuration (environment variables)

| Variable              | Default | Meaning                                   |
|-----------------------|---------|-------------------------------------------|
| `DATALOGGER_BACKEND`  | `auto`  | `auto`, `mock`, or `nidaqmx`.             |
| `DATALOGGER_PORT`     | `5001`  | Flask listen port.                        |
| `AI_COUNT`            | `8`     | Number of analog channels.                |
| `DI_COUNT`            | `8`     | Number of digital channels.               |
| `NI_DEVICE`           | `Dev1`  | NI-DAQmx device name (nidaqmx backend).   |
| `AI_VOLTAGE_MAX`      | `10.0`  | Full-scale voltage used for the AI bar.   |

## Run locally (development)

```sh
python -m pip install -r datalogger/requirements.txt
python datalogger/app.py
# open http://localhost:5001/
```

With the mock backend you should see AI0..AI7 drifting and DI0..DI7 counting in
binary.

## Deploy on the Raspberry Pi

Dependencies are already present on the device (Python, Flask, flask-cors). The
page is served by nginx.

```sh
git clone <this-repo> ~/DataLogger_Rpi
cd ~/DataLogger_Rpi
sh deploy/deploy.sh
```

Then add `deploy/nginx-datalogger.conf` inside the existing nginx `server {}`
block (e.g. in `/etc/nginx/sites-available/default`) and reload nginx:

```sh
sudo nginx -t && sudo systemctl reload nginx
```

Open `http://<pi-host>/datalogger/`.

### Updating

```sh
cd ~/DataLogger_Rpi
git pull
sh deploy/deploy.sh
```

## API

`GET /datalogger/api/inputs`

```json
{
  "timestamp": "2026-10-08 12:00:00",
  "device": "Dev1",
  "backend": "mock",
  "voltage_max": 10.0,
  "analog": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
  "digital": [false, true, false, true, false, false, false, false],
  "connected": true
}
```

`GET /datalogger/api/health` returns the backend and connection state.

## Roadmap

- [ ] Userspace `libusb` driver for the USB-6008 (analog + digital inputs).
- [ ] Optional logging/history and sampling-rate configuration.
