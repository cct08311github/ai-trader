#!/usr/bin/env bash
set -euo pipefail

# Simple healthcheck for Tailscale + local services

echo "[tailscale] status:" 
tailscale status --json >/dev/null && echo "OK" || (echo "FAIL" && exit 1)

echo "[serve] status:" 
tailscale serve status || true

echo "[listen] web 3000:" 
lsof -nP -iTCP:3000 -sTCP:LISTEN || true

echo "[listen] api 8080:" 
lsof -nP -iTCP:8080 -sTCP:LISTEN || true
