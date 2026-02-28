#!/usr/bin/env bash
set -euo pipefail

# Local exposure check: ensure ports are NOT listening on non-loopback
# Requires: lsof

fail=0
for port in 3000 8080; do
  echo "Checking port $port ..."
  # Grab LISTEN sockets and their local addresses
  out=$(lsof -nP -iTCP:${port} -sTCP:LISTEN 2>/dev/null || true)
  if [[ -z "$out" ]]; then
    echo "  - Not listening"
    continue
  fi
  echo "$out" | tail -n +2 | awk '{print $9}' | while read -r addr; do
    # Example addr: 127.0.0.1:3000 or *:3000
    if [[ "$addr" == *"*:"* ]] || [[ "$addr" == 0.0.0.0:* ]] || [[ "$addr" == "[::]"* ]]; then
      echo "  [FAIL] $port is exposed on wildcard address: $addr"
      fail=1
    elif [[ "$addr" != 127.0.0.1:* ]] && [[ "$addr" != "[::1]:"* ]]; then
      echo "  [WARN] $port listening on non-loopback: $addr"
      fail=1
    else
      echo "  [OK] $addr"
    fi
  done

done

exit $fail
