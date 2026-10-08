#!/bin/sh
set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-/home/pi/datalogger}"

echo "Deploying datalogger from ${REPO_DIR} to ${DEST}"

sudo mkdir -p "${DEST}/static"
sudo cp "${REPO_DIR}/datalogger/app.py" "${DEST}/app.py"
sudo cp "${REPO_DIR}/datalogger/device.py" "${DEST}/device.py"
sudo cp "${REPO_DIR}/datalogger/static/index.html" "${DEST}/static/index.html"
sudo cp "${REPO_DIR}/deploy/datalogger.service" /etc/systemd/system/datalogger.service

sudo systemctl daemon-reload
sudo systemctl enable datalogger.service
sudo systemctl restart datalogger.service

echo "Installed datalogger.service."
echo "Add deploy/nginx-datalogger.conf inside the nginx server block, then run:"
echo "  sudo nginx -t && sudo systemctl reload nginx"
echo "Page:  http://<pi-host>/datalogger/"
echo "API :  http://<pi-host>/datalogger/api/inputs"
