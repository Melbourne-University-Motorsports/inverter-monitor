---
type: Monitor Mapping
title: inverter-monitor readout mapping and write contract
description: How the repo maps OKF concepts to decode tables and UI, and which writes are allowed.
tags: [monitor, mapping, safety, pm100dx]
status: stable
generated: { by: cursor-agent/muse-spark-1.3, at: 2026-09-17T00:00:00Z }
sources:
  - id: can-protocol
    resource: ../../Source Documentation/CAN Protocol (V6_3).pdf
    title: Cascadia Motion CAN Protocol Rev 6.3 (2023-11-17)
  - id: sw-manual
    resource: ../../Source Documentation/Software User Manual (V3_6) For Inverter.pdf
    title: Cascadia Motion Software User Manual Rev 3.6 (2021-01-14)
---

# Readout mapping

`inverter-monitor` is a live monitor: pick one source (RS232 or
CAN), no auto-connect, close RMS GUI first (COM port is exclusive).

## Sources

* **RS232** (`--serial`): polls the active tab’s address set with `rm` at
  57600 8N1. `wm` is Clear Faults (`wm0002=0000`, Faults tab, confirmed),
  Calibration RAM writes of Delay Command `0x0005` / Gamma Adjust `0x0010`,
  and Calibration Program EEPROM (`0x0118`/`0x011A` then `wm0000=5a0f` /
  `wm0001=0059`). See [Memory View](/inverter/memory-view.md).
* **CAN** (`--can`, subscribe-only `bus.recv()`): default offset **0x0A0**
  (this car's EEPROM value), overridable via `--id-offset`. 500 kbit/s
  default. M170/M171 give relays, limit flags, POST+RUN faults with no
  extra symbol picks; see [transport](/can/transport.md) and
  [broadcast catalog](/can/broadcast-catalog.md).

## Decode tables

| File | OKF concept | Role |
|------|-------------|------|
| `data/reference_decode.yaml` | [broadcast](/can/broadcast-catalog.md), [M170](/can/internal-states.md), [M171](/can/fault-codes.md) | CAN layout, enums, 64 fault bits, SCI column map |
| `data/defsyms.yaml` | [EEPROM](/inverter/eeprom.md) | G3 Memory-View addresses |
| `data/vsm_states.yaml` | [VSM](/inverter/vsm.md), [inverter mode](/inverter/inverter-mode.md) | State descriptions |
| `data/faults.yaml` | [diagnostics](/inverter/faults-diagnostics.md) | Fault text |
| `profiles/default.yaml` | [transport](/can/transport.md) | Bus, channel, offset |

## UI mapping

Status strip (VSM/enable/command-mode/inverter-mode/fault count) ←
[internal states](/can/internal-states.md), with the VSM one-liner following
live command mode (CAN wording unless mode = 1); Overview (speed/torque/DC/temps/flags)
← [broadcast](/can/broadcast-catalog.md); Faults (raw + decoded, POST needs
CAN) ← [fault codes](/can/fault-codes.md); Graphs ← M165–M168/M172/M176;
Symbols ← [Memory View](/inverter/memory-view.md) watch list; Calibration ←
resolver delay / gamma RAM iteration, optional EEPROM persist; Raw ← last
frame per ID; States ← [VSM](/inverter/vsm.md) with per-mode descriptions
(`VsmState.text()`: M170 command-mode bit, else `0x011B` EEPROM word, else CAN).

Operator rule of thumb (CAN mode): **VSM 4 on the status strip means the
inverter is waiting for the VCU's command sequence** (Disable to clear
lockout, then Enable + direction + torque inside the timeout window) — not
for pedals or key. If it sits at 4, check command TX, lockout (M170 byte 6
bit 7), and faults before touching anything else.

## Write contract

Never transmitted: other EEPROM parameter writes, M192 command frames, or CAN
parameter writes except Clear Faults
([command](/can/command-message.md), [parameters](/can/parameter-messages.md)).
RS232 may `wm` Clear Faults (`0x0002`), Calibration RAM Delay/Gamma
(`0x0005` / `0x0010`), and Calibration Program EEPROM (`0x0118` / `0x011A`
then `0x0000`/`0x0001`).
Staleness rule: flag fast frames missing past 3× cycle time. Open question:
confirm RealTerm brake column vs shudder (see [SCI](/inverter/sci-serial.md))
before trusting brake readings.
