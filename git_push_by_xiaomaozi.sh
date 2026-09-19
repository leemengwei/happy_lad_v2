#!/usr/bin/env bash
set -euo pipefail

# Push Git through the SOCKS tunnel provided by the album server.
# The SSH password is intentionally never stored in this script.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VPN_HOST="root@192.168.0.110"
SOCKS_ADDR="127.0.0.1:1080"

if ! command -v sshpass >/dev/null 2>&1; then
  echo "错误：未安装 sshpass" >&2
  exit 1
fi
if ! command -v proxychains4 >/dev/null 2>&1; then
  echo "错误：未安装 proxychains4" >&2
  exit 1
fi

if [[ -z "${SSHPASS:-}" ]]; then
  read -r -s -p "SSH 密码: " SSHPASS
  echo
  export SSHPASS
fi

TUNNEL_PID=""
cleanup() {
  if [[ -n "$TUNNEL_PID" ]] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

SSHPASS="$SSHPASS" sshpass -e ssh \
  -o StrictHostKeyChecking=no \
  -o ExitOnForwardFailure=yes \
  -N -D "$SOCKS_ADDR" "$VPN_HOST" &
TUNNEL_PID=$!

for _ in {1..20}; do
  if proxychains4 -q curl -fsS --max-time 2 https://github.com >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "错误：SOCKS 隧道启动失败" >&2
    exit 1
  fi
  sleep 0.5
done

cd "$REPO_ROOT"
proxychains4 git push "$@"
