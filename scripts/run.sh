#!/bin/bash
set -e

cd /home/feifeichouchou/happy_lad_v2
UID_NUM="$(id -u)"
export XDG_RUNTIME_DIR="/run/user/${UID_NUM}"

# Reboot race: /run/user/<uid> may not be ready when this system service starts.
for _ in $(seq 1 30); do
  [ -d "${XDG_RUNTIME_DIR}" ] && break
  sleep 1
done

# Fallback runtime dir to keep audio stack functional even if /run/user/<uid> is late.
if [ ! -d "${XDG_RUNTIME_DIR}" ]; then
  export XDG_RUNTIME_DIR="/tmp/runtime-${UID_NUM}"
  mkdir -p "${XDG_RUNTIME_DIR}"
  chmod 700 "${XDG_RUNTIME_DIR}" || true
fi

# Wait for udev aliases to appear after reboot.
for _ in $(seq 1 30); do
  [ -e /dev/video-cam0 ] && [ -e /dev/video-cam1 ] && break
  sleep 1
done

export PULSE_SERVER="unix:${XDG_RUNTIME_DIR}/pulse/native"
/home/feifeichouchou/happy_lad_v2/.venv/bin/python -m app.main --config configs/cameras.yaml --host 0.0.0.0 --port 5000
