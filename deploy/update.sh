#!/bin/sh
set -e

HOME_DIR="${HOME:-/home/pi}"
GIT_DIR="${DATALOGGER_GIT_DIR:-$HOME_DIR/.datalogger-rpi.git}"

git --git-dir="$GIT_DIR" --work-tree="$HOME_DIR" pull --ff-only
sudo systemctl restart datalogger.service

echo "Updated datalogger and restarted datalogger.service"
