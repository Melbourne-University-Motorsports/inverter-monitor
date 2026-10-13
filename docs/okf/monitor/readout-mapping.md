---
type: Monitor Mapping
title: inverter-monitor readout mapping and write contract
description: How the repo maps OKF concepts to symbol tables and UI, and which writes are allowed.
tags: [monitor, mapping, safety, pm100]
status: stable
generated: { by: cursor-agent/muse-spark-1.3, at: 2026-09-17T00:00:00Z }
sources:
  - id: sw-manual
    resource: ../../Source Documentation/Software User Manual (V3_6) For Inverter.pdf
    title: Cascadia Motion Software User Manual Rev 3.6 (2021-01-14)
---

# Readout mapping and write contract

`inverter-monitor` is a live monitor and configuration tool over **RS232**
Memory View (`--serial`). Close RMS GUI first (COM port is exclusive).

## Transport

* **RS232** (`--serial`): polls the active tab’s address set with `rm` at
  57600 8N1. `wm` writes are supported for Clear Faults (`wm0002=0000`, Faults tab),
  Calibration RAM writes of Delay Command `0x0005` / Gamma Adjust `0x0010`,
  Calibration Program EEPROM (`0x0118`/`0x011A` then `wm0000=5a0f` / `wm0001=0059`),
  and EEPROM-tab **Push to inverter** (per-word parameter write then commit).
  See [Memory View](/inverter/memory-view.md).

## Definition tables

| File | OKF concept | Role |
|------|-------------|------|
| `data/defsyms.yaml` | [EEPROM](/inverter/eeprom.md) | G3 Memory-View addresses and metadata |
| `data/vsm_states.yaml` | [VSM](/inverter/vsm.md), [inverter mode](/inverter/inverter-mode.md) | State descriptions |
| `data/faults.yaml` | [diagnostics](/inverter/faults-diagnostics.md) | Diagnostic text for faults |
| `data/reference_decode.yaml` | [M171](/inverter/faults-diagnostics.md) | 64-bit fault bitfield definitions, SCI column map |

## UI mapping

- **Status strip** (VSM/enable/command-mode/inverter-mode/fault count) ← VSM 0x0093, enable 0x0094, mode 0x0092, fault words 0x0057–0x005A.
- **Overview** (speed/torque/DC/temps/flags) ← Memory View live telemetry.
- **Faults** (raw + decoded fault bits) ← 64-bit fault registers with Clear Faults button.
- **Graphs** ← time-series plotting of watched variables.
- **Symbols** ← [Memory View](/inverter/memory-view.md) custom watch list.
- **EEPROM** ← grouped parameter tree from `data/defsyms.yaml`, with in-place cell editing, engineering unit conversions, diff staging, and guarded push-to-inverter dialog.
- **Calibration** ← resolver delay / gamma RAM iteration, optional EEPROM persist.
- **Raw** ← last frame per address.
- **States** ← [VSM](/inverter/vsm.md) and Inverter Mode descriptions.

## Write contract

* **RS232 Memory View**:
  - Continuous reading via `rm`.
  - Allowed write commands (`wm`):
    - **Clear Faults**: `wm0002=0000` from the Faults tab with operator confirmation.
    - **Calibration RAM Tuning**: `wm0005=VVVV` (Delay Command) and `wm0010=VVVV` (Gamma Adjust) for live tuning.
    - **Calibration EEPROM Commit**: Copies Delay/Gamma into `0x0118`/`0x011A` and commits via `wm0000=5a0f` / `wm0001=0059`.
    - **EEPROM Push to Inverter**: Flashes modified EEPROM parameters in the EEPROM tab. Requires safety interlocks (**VSM Wait 4** and **Inverter Disabled 0**) and explicit confirmation of staged changes in a modal diff dialog before programming non-volatile memory.
