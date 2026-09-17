---
type: CAN Signal Reference
title: CAN data formats (scaling)
description: Unit scaling for every signal type on the PM CAN bus.
tags: [can, scaling, signals, pm100dx]
status: stable
generated: { by: cursor-agent/muse-spark-1.3, at: 2026-09-17T00:00:00Z }
sources:
  - id: can-protocol
    resource: ../../Source Documentation/CAN Protocol (V6_3).pdf
    title: Cascadia Motion CAN Protocol Rev 6.3 (2023-11-17)
---

# Data formats

Each message packs one or more items, scaled as below (CAN Protocol
§1.5).[^can-protocol] Signed multi-byte items are little-endian; apply the
signed 16-bit wrap before scaling (values above 32766/scale wrap by −65535/scale).

| Format | Encoding | Range |
|--------|----------|-------|
| Temperature | signed int, °C × 10 | −3276.8 … +3276.7 °C |
| Low Voltage | signed int, V × 100 | −327.68 … +327.67 V |
| Torque | signed int, N·m × 10 | −3276.8 … +3276.7 N·m |
| High Voltage | signed int, V × 10 | −3276.8 … +3276.7 V |
| Current | signed int, A × 10 | −3276.8 … +3276.7 A |
| Angle | signed int, deg × 10 | 0 … ±359.9° |
| Speed | signed int, RPM | −32768 … +32767 RPM |
| Boolean | unsigned byte | 0 / 1 |
| Frequency | signed int, Hz × 10 | −3276.8 … +3276.7 Hz |
| Power | signed int, kW × 10 | −3276.8 … +3276.7 kW |
| Flux | signed int, Wb × 1000 | −32.768 … 32.767 Wb |
| Prop. gain | unsigned, ×100 or ×10000 | 0–655.35 or 0–6.5535 |
| Integral gain | unsigned ×10000 | 0–6.5535 |
| Derivative gain | unsigned ×100 | 0–655.35 |
| LP filter gain | unsigned ×10000 | 0–6.5535 |
| Pressure | signed int, psi × 10 | −3276.8 … +3276.7 psi |
| ADC count | raw register | 0–4095 |
| Time / per-unit | counts + scale factor in the parameter description | — |

Modulation index is the notable exception: per-unit ×100 (divide by 100),
while Id/Iq commands in the same message stay ×10.[^can-protocol]

[^can-protocol]: CAN Protocol Rev 6.3 §1.5
