#!/bin/bash
set -e

UID_NUM="$(id -u)"
export XDG_RUNTIME_DIR="/run/user/${UID_NUM}"
if [ ! -d "${XDG_RUNTIME_DIR}" ]; then
  export XDG_RUNTIME_DIR="/tmp/runtime-${UID_NUM}"
  mkdir -p "${XDG_RUNTIME_DIR}"
  chmod 700 "${XDG_RUNTIME_DIR}" || true
fi

BT_SPEAKER_MAC="84:26:7A:3E:49:F2"
BT_SINK_NAME="bluez_sink.84_26_7A_3E_49_F2.a2dp_sink"
BT_TARGET_VOLUME="25%"
BASE_SLEEP_SECONDS=8
MAX_SLEEP_SECONDS=30

ensure_pulse() {
  if ! systemctl --user --quiet is-active pulseaudio.service; then
    systemctl --user start pulseaudio.service >/dev/null 2>&1 || true
    sleep 1
  fi

  if ! systemctl --user --quiet is-active pulseaudio.service; then
    return 1
  fi

  return 0
}

is_bt_connected() {
  bluetoothctl info "${BT_SPEAKER_MAC}" 2>/dev/null | grep -q "Connected: yes"
}

ensure_bt_connected() {
  if is_bt_connected; then
    return 0
  fi

  bluetoothctl power on >/dev/null 2>&1 || true
  bluetoothctl scan off >/dev/null 2>&1 || true
  timeout 8 bluetoothctl connect "${BT_SPEAKER_MAC}" >/dev/null 2>&1 || true
  is_bt_connected
}

wait_for_sink() {
  local j
  for j in $(seq 1 10); do
    if pactl list short sinks 2>/dev/null | grep -q "^.*${BT_SINK_NAME}"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

ensure_bt_audio() {
  if ! ensure_pulse; then
    return 1
  fi

  if ! ensure_bt_connected; then
    return 1
  fi

  if wait_for_sink; then
    pactl set-default-sink "${BT_SINK_NAME}" >/dev/null 2>&1 || true
    pactl set-sink-volume "${BT_SINK_NAME}" "${BT_TARGET_VOLUME}" >/dev/null 2>&1 || true
    return 0
  fi

  return 1
}

sleep_seconds="${BASE_SLEEP_SECONDS}"
while true; do
  if ensure_bt_audio; then
    sleep_seconds="${BASE_SLEEP_SECONDS}"
  else
    sleep_seconds=$((sleep_seconds * 2))
    if [ "${sleep_seconds}" -gt "${MAX_SLEEP_SECONDS}" ]; then
      sleep_seconds="${MAX_SLEEP_SECONDS}"
    fi
  fi
  sleep "${sleep_seconds}"
done
