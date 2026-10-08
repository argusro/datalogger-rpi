import os
import time

from flask import Flask, jsonify

import device as device_module

try:
    from flask_cors import CORS
except ImportError:
    CORS = None

app = Flask(__name__, static_folder="static", static_url_path="")
if CORS is not None:
    CORS(app)

_device = None
_device_error = None


def get_device():
    global _device, _device_error
    if _device is None:
        try:
            _device = device_module.create_device()
            _device_error = None
        except Exception as exc:
            _device_error = str(exc)
    return _device


@app.route("/api/inputs")
def api_inputs():
    dev = get_device()
    payload = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "device": device_module.DEVICE_NAME,
        "backend": getattr(dev, "name", "unavailable") if dev else "unavailable",
        "voltage_max": device_module.AI_VOLTAGE_MAX,
        "analog": [],
        "digital": [],
        "connected": False,
    }
    if dev is None:
        payload["error"] = _device_error or "device not initialised"
        return jsonify(payload), 503
    try:
        payload.update(dev.read_all())
        payload["connected"] = True
    except Exception as exc:
        payload["error"] = str(exc)
        return jsonify(payload), 503
    return jsonify(payload)


@app.route("/api/health")
def api_health():
    dev = get_device()
    return jsonify({
        "backend": getattr(dev, "name", "unavailable") if dev else "unavailable",
        "connected": dev is not None,
        "device": device_module.DEVICE_NAME,
    })


@app.route("/")
def index():
    return app.send_static_file("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("DATALOGGER_PORT", "5001")))
