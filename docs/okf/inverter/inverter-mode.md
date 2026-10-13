---
type: State Machine Reference
title: Inverter mode, discharge, relays, and outputs
description: Inverter_Mode states, active-discharge sequence, relay map, and fan/pump behavior.
tags: [inverter-mode, discharge, relays, pm100]
status: stable
generated: { by: cursor-agent/muse-spark-1.3, at: 2026-09-17T00:00:00Z }
sources:
  - id: sw-manual
    resource: ../../Source Documentation/Software User Manual (V3_6) For Inverter.pdf
    title: Cascadia Motion Software User Manual Rev 3.6 (2021-01-14)
  - id: can-protocol
    resource: ../../Source Documentation/CAN Protocol (V6_3).pdf
    title: Cascadia Motion CAN Protocol Rev 6.3 (2023-11-17)
---

# Inverter mode

`Inverter_Mode` (Memory View 0x0092, M170 byte 2). DBC labels 4–7/10–12
"internal" — names below are the manual's.[^sw-manual]

| Mode | Name | Notes |
|------|------|-------|
| 0 | Power-up | Precharge/power state |
| 1 | Stop | Not running |
| 2 | Open Loop | Test only |
| 3 | Closed Loop | Normal |
| 4 | Start delay | Small pre-start delay |
| 5 | Current-sensor test | Flux ramp + regulators on |
| 6 | Closed-loop torque | Torque regulator on |
| 7 | Torque ramp | Starting torque ramp |
| 8 | Idle Run | Running normally |
| 9 | Idle Stop | Stopped |
| 10 | Ramp off torque | Torque ramp down |
| 11 | Ramp off flux | Flux ramp down |
| 12 | All ramps off | Shutoff |
| 15 | Default Stop | Default |

## Active discharge (M170 byte 4 bits 5–7)

0 Disabled, 1 Enabled/waiting, 2 Speed check, 3 Active, 4 Complete. RUN bit
63 mirrors "Discharge Active" as a warning. Full process: Inverter Discharge
Process manual; enable via EEPROM 173 / 0x0C0 byte 5.1.[^can-protocol]

## Relays (M170 byte 3)

Bit 0 R1 precharge, 1 R2 main, 2 R3 OK, 3 R4 fault, 4 R5, 5 R6. Default
`Relay_Output_State_EEPROM` (0x012C) **0x000C** preserves legacy OK/fault
outputs. From fw 1984 in VSM mode, R5 = pump (on while enabled) and R6 = fan
(on per thermal logic) automatically.[^sw-manual]

## Speed/torque shaping

Torque capability derates against motor-temp line (Full→Zero torque temps),
max-speed ramp (zero at Max×1.02), and regen fade/break speeds — see
[EEPROM guide](eeprom.md). Shudder compensation (Kp/TCLAMP/filter/fade
speeds) targets low-speed driveline resonance; brake switch vs pot behavior
also lives there.[^sw-manual]

[^sw-manual]: Software User Manual Rev 3.6 §§9.4–9.5, App. B/G–K
[^can-protocol]: CAN Protocol Rev 6.3 §2.1 (0x0AA)
