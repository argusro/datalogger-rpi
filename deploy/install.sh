#!/bin/sh
set -e

HOME_DIR="${HOME:-/home/pi}"
SERVICE_SRC="$HOME_DIR/deploy/datalogger.service"

sudo cp "$SERVICE_SRC" /etc/systemd/system/datalogger.service
sudo systemctl daemon-reload
sudo systemctl enable datalogger.service
sudo systemctl restart datalogger.service

echo "Installed and started datalogger.service"
echo
echo "Now add deploy/nginx-datalogger.conf inside your nginx server block, e.g.:"
echo "  sudo nano /etc/nginx/sites-available/default"
echo "then:"
echo "  sudo nginx -t && sudo systemctl reload nginx"
echo
echo "Page: http://<pi-host>/datalogger/"
