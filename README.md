# Rinehart Inverter Monitor

Live monitor for Cascadia / Rinehart PM100DZ inverters over **RS232**.

## Quick start

Install [`uv`](https://docs.astral.sh/uv/), then:

```bash
# macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
# or: brew install uv
```

```powershell
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# or: winget install --id=astral-sh.uv -e
```

```bash
uv run inverter-monitor
```

## Serial

| | |
|--|--|
| RS232 | 57600 8N1, no flow control. Close RMS GUI first. |
| Python | 3.10+ (`uv run` installs it if missing) |

## ADAM-4562

Isolated USB–RS232 (Prolific PL2303), not CAN. Advantech drivers are Windows and Linux only.

| OS | |
|----|--|
| Windows 10 | Advantech/Prolific VCP → `COMx` |
| Linux | kernel `pl2303` → `/dev/ttyUSB*` |
| macOS | No official driver. [PL2303 Serial](https://apps.apple.com/us/app/pl2303-serial/id1624835354?mt=12) may enumerate `/dev/cu.PL2303*` / `/dev/cu.usbserial*`. Counterfeit chips and Apple Silicon often fail. Prefer Windows 10 for RS232. |

## Without uv

Python 3.10+ (`brew install python@3.12` / `winget install Python.Python.3.12`).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
inverter-monitor
```

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
inverter-monitor
```

Same as `python -m inverter_monitor`.

## Data

| File | |
|------|--|
| `data/reference_decode.yaml` | CAN layout, enums, fault bits, SCI columns |
| `data/defsyms.yaml` | Memory View addresses (`defsyms_20221118_G3.txt`) |
| `docs/rms-gui-memory-view.md` | `rm` / `wm` grammar |
| `data/vsm_states.yaml` | VSM / inverter states |
| `data/faults.yaml` | Fault text |

## Safety

RS232 `rm`, plus `wm` for Clear Faults, Calibration Delay/Gamma (RAM), and Calibration Program EEPROM. Nothing else.
