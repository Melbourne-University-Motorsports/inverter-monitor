# PM100DX Inverter Monitor

Read-only live monitor for Cascadia / Rinehart PM100DX inverters.

Pick **one** live source: **RS232** or **CAN**. The window does not auto-connect.
Use the Source menu, or pass `--serial` / `--can`.

## Quick start

Install [`uv`](https://docs.astral.sh/uv/), then from this directory run the app.
`uv run` creates the venv, installs Python 3.10+ if needed, and installs the
project dependencies — there is no separate `pip install`.

```bash
# macOS — install uv (once)
curl -LsSf https://astral.sh/uv/install.sh | sh
# or: brew install uv
```

```powershell
# Windows — install uv (once, PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# or: winget install --id=astral-sh.uv -e
```

Open a new terminal so `uv` is on `PATH`, then:

```bash
uv run inverter-monitor
```

Choose **RS232** or **CAN** and press Start.

## Live sources

### RS232

USB–RS232 into the inverter. Polls the **Symbols** watch list with `rm` only
(no `wm`) at **57600 8N1**. Close RMS GUI first — the COM port is exclusive.

The list starts with EEPROM `CAN_ID_Offset` (`0x011D`), `VSM_State` (`0x0093`),
and the other status words. Search EEPROM and memory names on the Symbols tab
and add more. The toolbar **CAN ID offset** is editable so you can confirm it
against that EEPROM word before switching to CAN.

```bat
uv run inverter-monitor --serial COM3
```

```bash
uv run inverter-monitor --serial /dev/cu.usbserial-XXXX
```

### CAN

Subscribe-only python-can. Never transmits.

```bash
inverter-monitor --can socketcan --channel can0
inverter-monitor --can pcan --channel PCAN_USBBUS1
inverter-monitor --can slcan --channel /dev/cu.usbmodem-XXXX
```

CAN ID offset defaults to **0x0A0** (this inverter’s captured EEPROM value).
Override with `--id-offset 0` or another hex/decimal value (`0x0A0`, `160`).

CAN is the path that includes the full M170/M171 layout (relays, limit flags,
POST+RUN faults) without picking extra symbols.

## ADAM-4562 on macOS

The [ADAM-4562](https://www.advantech.com/en-us/support/details/driver?id=1-KQAW9C) is an **isolated USB–RS232** converter (Prolific **PL2303**), not a CAN adapter. Use it with **RS232**, not CAN.

Advantech’s official drivers are **Windows (including 10) and Linux only**. There is **no Advantech macOS driver**.

| OS | ADAM-4562 |
|----|-----------|
| Windows 10 | Supported (Advantech/Prolific VCP → `COMx`) |
| Linux | Supported (kernel `pl2303` → `/dev/ttyUSB*`) |
| macOS | **Not officially supported.** May enumerate if you install Prolific’s [PL2303 Serial](https://apps.apple.com/us/app/pl2303-serial/id1624835354?mt=12) App Store extension (macOS 11+), then look for `/dev/cu.PL2303*` or `/dev/cu.usbserial*`. Counterfeit PL2303 chips and Apple Silicon are common failure modes. |

For a Mac laptop, do not count on the ADAM-4562. Prefer Windows 10 for RS232, or a native CAN adapter for the CAN source.

## Other requirements

| Item | Detail |
|------|--------|
| Python | 3.10+ (`uv run` installs it if missing) |
| RS232 serial | 57600 8N1, no flow control |
| CAN bitrate | 500 kbit/s unless the car uses something else |
| RMS GUI | Windows-only vendor `.exe`. Do not open it at the same time as this app on the same COM port. |

## Without uv

You need Python 3.10+ already installed (`brew install python@3.12` on macOS,
`winget install Python.Python.3.12` on Windows).

```bash
# macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
inverter-monitor
```

```bat
REM Windows (cmd)
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
inverter-monitor
```

Same entry as `python -m inverter_monitor`.

## Window

- **Status strip** — VSM, enable, command mode, inverter mode, fault count
- **Overview** — speed, torque, DC bus, temps, flags (CAN), VSM description
- **Faults** — raw words + decoded bits (POST needs CAN)
- **Graphs** — speed, torque, DC V/I, motor/module temps
- **Symbols** — search EEPROM + memory (`defsyms`) and add/remove a watch list
- **Raw** — last frame per ID
- **States** — VSM / inverter-mode reference (descriptions follow live command mode: CAN wording by default, VSM wording when mode = 1)

## Decode tables

| File | Role |
|------|------|
| `data/reference_decode.yaml` | CAN layout, enums, 64 fault bits, SCI column map |
| `data/defsyms.yaml` | RMS GUI Memory View addresses from `defsyms_20221118_G3.txt` (identical to `20220617`) |
| `docs/rms-gui-memory-view.md` | Captured `rm` / `wm` grammar. Watch list is poll-set add/remove. Writes documented, not implemented. |
| `data/vsm_states.yaml` | VSM / inverter state descriptions |
| `data/faults.yaml` | Fault diagnostic text |

## Safety

RS232 polls with `rm` only. CAN only calls `bus.recv()`. No `wm` / EEPROM
commits, no M192/M193/M194 TX. Memory View writes are documented in
`docs/rms-gui-memory-view.md` and are not a feature.
