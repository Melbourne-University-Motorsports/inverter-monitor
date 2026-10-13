---
type: CAN Signal Reference
title: Internal states message 0x0AA (M170)
description: Authoritative byte/bit map of the M170 internal-states broadcast, resolving the VSM bit-position conflict.
tags: [can, m170, vsm, relays, limits, pm100]
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

# Internal states (0x0AA / M170)

Fast (≈100 Hz) 8-byte broadcast. This layout is authoritative over the
mur-embedded `Cascadia_PM100DZ.dbc` reconstruction, which places VSM state at
bit 56 — the vendor DBC and CAN Protocol put **VSM state in byte 0**.[^can-protocol]

| Byte | Bits | Signal | Values |
|------|------|--------|--------|
| 0 | 0–7 | VSM state | 0 Start, 1 Pre-charge Init, 2 Pre-charge Active, 3 Pre-charge Complete, 4 Wait, 5 Ready, 6 Motor Running, 7 Blink Fault, 14 Shutdown-in-process (key-switch mode 1), 15 Recycle Power. 8–13 undefined. |
| 1 | 0–7 | PWM frequency (Gen5/CM, kHz) | 0 on PMxxx (not reported) |
| 2 | 0–7 | Inverter state | 0 Power-on, 1 Stop, 2 Open-loop, 3 Closed-loop, 4 Wait/start-delay, 5–7 internal, 8 Idle Run, 9 Idle Stop, 10–12 internal, 13–14 undefined gaps, 15 Default Stop |
| 3 | 0–5 | Relay 1–6 status | 1 = active (R1 precharge, R2 main, R3 OK, R4 fault, R5 pump, R6 fan) |
| 4 | 0 | Run mode | 0 Torque, 1 Speed |
| 4 | 1 | Self-sensing assist (Gen5/CM, select motors) | 0 disabled, 1 enabled |
| 4 | 5–7 | Active discharge state | 0 Disabled, 1 Enabled/waiting, 2 Speed check, 3 Active, 4 Complete |
| 5 | 0 | Command mode | 0 CAN, 1 VSM (expect 0 on this bench — if 1, the VCU's commands are ignored) |
| 5 | 4–7 | Rolling-counter expected value (Gen5/CM) | — |
| 6 | 0 | Inverter enable | 0 disabled, 1 enabled |
| 6 | 1 | Burst model mode (Gen5/CM) | 0 Stall, 1 High-speed |
| 6 | 6 | Start-mode latch (fw ≥2044) | 1 = start seen (VSM) |
| 6 | 7 | Enable lockout | 1 = must send Disable before Enable works |
| 7 | 0 | Direction | 1 Forward, 0 Reverse (enabled) / Stopped (disabled) |
| 7 | 1 | BMS active | 1 = BMS message received |
| 7 | 2 | BMS limiting torque | 1 = limiting |
| 7 | 3 | Max-speed limiting (Gen5/CM, Gen3 ≥2042) | 1 = limiting |
| 7 | 4 | Hot-spot limiting (Gen5/CM) | 1 = limiting |
| 7 | 5 | Low-speed limiting (Gen5/CM, Gen3 ≥2042) | 1 = limiting |
| 7 | 6 | Coolant-derating limiting (Gen5/CM) | 1 = limiting |
| 7 | 7 | Stall-burst limiting (Gen5/CM, select inverters) | 1 = limiting |

State names and transitions live in [VSM](/inverter/vsm.md) and
[inverter mode](/inverter/inverter-mode.md); limit-flag semantics for the
bench UI are summarized in [monitor mapping](/monitor/readout-mapping.md).

[^can-protocol]: CAN Protocol Rev 6.3 §2.1, 0x0AA definition
