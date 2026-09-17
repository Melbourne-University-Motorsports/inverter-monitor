---
type: Serial Protocol Reference
title: SCI RS232 broadcast (data acquisition)
description: 57600 8N1 20-word hex broadcast and column map. Listen-only; the monitor never configures it.
tags: [serial, sci, rs232, telemetry, pm100dx]
status: stable
generated: { by: cursor-agent/muse-spark-1.3, at: 2026-09-17T00:00:00Z }
sources:
  - id: sw-manual
    resource: ../../Source Documentation/Software User Manual (V3_6) For Inverter.pdf
    title: Cascadia Motion Software User Manual Rev 3.6 (2021-01-14)
---

# SCI serial broadcast

Inverter-unsolicited ~20-word hex line over RS232 at **57600 8N1, no flow
control** (RealTerm or equivalent). This is **not** the Memory View
request/response protocol ([memory view](memory-view.md)) and **not** CAN
payloads — do not mix the three decodes.[^sw-manual]

| # | Field | Scale |
|---|-------|-------|
| 1 | Power-on timer low word | ÷3 → ms |
| 2 | Accel-pot filtered | V ×100 |
| 3 | Torque feedback | N·m ×10, signed |
| 4 | Torque command | N·m ×10 |
| 5 | DC voltage | V ×10 |
| 6 | DC current | A ×10 |
| 7 | Motor speed | RPM, signed |
| 8 | Flux-weakening output | A ×10 |
| 9 | Motor voltage magnitude | Vpk ×10 |
| 10–11 | Iq cmd / feedback | A ×10, signed |
| 12–13 | Id cmd / feedback | A ×10, signed |
| 14 | Modulation index | ÷10000 |
| 15 | Inverter (module) temp | °C ×10 |
| 16 | Motor temp | °C ×10 |
| 17–18 | Run fault lo / hi | raw hex (alarm if hi ≠ 0) |
| 19 | Torque shudder | N·m ×10 |
| 20 | Brake pot | V ×100 |

Signed fields use the 16-bit wrap (`norm()`): raw > 32766/scale wraps by
−65535/scale. Column 19/20 overlap is a known team-script bug (shudder vs
brake share index 18) — verify against defsyms before trusting brake
readings.[^sw-manual]

[^sw-manual]: Software User Manual Rev 3.6 §3, pp18–19
