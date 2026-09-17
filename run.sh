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
  shopt -s nullglob
  ports=(/dev/cu.PL2303* /dev/cu.usbserial* /dev/cu.usbmodem*)
  shopt -u nullglob
  if [[ ${#ports[@]} -eq 0 ]]; then
    echo "No USB serial port found. For the ADAM-4562, install PL2303 Serial:"
    echo "  https://apps.apple.com/us/app/pl2303-serial/id1624835354?mt=12"
    echo
  fi
fi

echo "Starting inverter-monitor (first run may take a minute)…"
exec uv run inverter-monitor "$@"
