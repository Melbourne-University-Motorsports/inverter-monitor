#!/usr/bin/env bash
# Install uv if needed, then start the monitor. Double-click run.command on macOS.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    export PATH="$HOME/.local/bin:$PATH"
  else
    echo "Installing uv…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi

if [[ "$(uname -s)" == Darwin ]]; then
  # Do not use an empty array here: macOS /bin/bash is 3.2, and `set -u`
  # treats `${#ports[@]}` as unbound when nothing is plugged in.
  found=
  shopt -s nullglob
  for _port in /dev/cu.PL2303* /dev/cu.usbserial* /dev/cu.usbmodem*; do
    found=1
    break
  done
  shopt -u nullglob
  if [[ -z "$found" ]]; then
    echo "No USB serial adapter detected. Plug in the ADAM-4562 if you want live RS232 — the app still starts."
    if [[ ! -d "/Applications/PL2303 Serial.app" && ! -d "/Applications/PL2303Serial.app" ]]; then
      echo "First time on this Mac? Install PL2303 Serial from the App Store, then plug the adapter in:"
      echo "  https://apps.apple.com/us/app/pl2303-serial/id1624835354?mt=12"
    fi
    echo
  fi
fi

echo "Starting inverter-monitor (first run may take a minute)…"
exec uv run inverter-monitor "$@"
