# DataLogger_Rpi

Datalogger service for a Raspberry Pi Zero reading a National Instruments
**USB-6008** over USB. It exposes the current values of all **8 analog inputs**
(single-ended AI0..AI7) and **8 digital inputs** (P0.0..P0.7) through a small web
page at `/datalogger`.

The existing device status site in the home directory (`www/`, Flask API on
port 5000 + nginx) is not part of this repository and is left untouched. The
datalogger runs as its own Flask service on port 5001.

## Repository layout

```
datalogger/
  app.py                 Flask API (/api/inputs, /api/health)
  device.py              Pluggable device layer (mock / nidaqmx)
  requirements.txt
  static/index.html      The /datalogger page
deploy/
  datalogger.service     systemd unit
  nginx-datalogger.conf  nginx location snippet
  install.sh             One-time install of the systemd service
  update.sh              Pull the latest code and restart the service
```

On the device the repository is checked out **directly into the home directory**,
so `~/datalogger` and `~/deploy` are the live files (no extra clone folder). See
[Deploy on the Raspberry Pi](#deploy-on-the-raspberry-pi).

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

Instead of cloning into a `datalogger-rpi` folder, the repository is checked out
with the **home directory as the git work tree**, so `~/datalogger` and
`~/deploy` appear directly in the home directory. Git metadata lives in the
hidden `~/.datalogger-rpi.git`, and a sparse checkout keeps everything else
(README, etc.) out of the home directory.

Run these once on the device:

```sh
git clone --bare https://github.com/argusro/datalogger-rpi.git "$HOME/.datalogger-rpi.git"

git --git-dir="$HOME/.datalogger-rpi.git" --work-tree="$HOME" config core.bare false
git --git-dir="$HOME/.datalogger-rpi.git" --work-tree="$HOME" config status.showUntrackedFiles no
git --git-dir="$HOME/.datalogger-rpi.git" --work-tree="$HOME" config branch.main.remote origin
git --git-dir="$HOME/.datalogger-rpi.git" --work-tree="$HOME" config branch.main.merge refs/heads/main
git --git-dir="$HOME/.datalogger-rpi.git" --work-tree="$HOME" sparse-checkout set --no-cone datalogger deploy
git --git-dir="$HOME/.datalogger-rpi.git" --work-tree="$HOME" checkout
```

Then install the service and wire up nginx:

```sh
sh ~/deploy/install.sh
```

Add `~/deploy/nginx-datalogger.conf` inside the existing nginx `server {}` block
(e.g. in `/etc/nginx/sites-available/default`) and reload nginx:

```sh
sudo nginx -t && sudo systemctl reload nginx
```

Open `http://<pi-host>/datalogger/`.

### Updating

```sh
sh ~/deploy/update.sh
```

This runs `git pull` against the home work tree and restarts the service.

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
