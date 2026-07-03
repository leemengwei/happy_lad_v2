#!/bin/bash
set -e

cd /home/feifeichouchou/happy_lad_v2
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export PULSE_SERVER="unix:${XDG_RUNTIME_DIR}/pulse/native"
/home/feifeichouchou/happy_lad_v2/.venv/bin/python -m app.main --config configs/cameras.yaml --host 0.0.0.0 --port 5000
