---
type: Fault Reference
title: Fault diagnostics (blink codes, latch, clear)
description: How faults present, blink priority, latching faults, and the clear procedure.
tags: [faults, diagnostics, blink-codes, pm100dx]
status: stable
generated: { by: cursor-agent/muse-spark-1.3, at: 2026-09-17T00:00:00Z }
sources:
  - id: sw-manual
    resource: ../../Source Documentation/Software User Manual (V3_6) For Inverter.pdf
    title: Cascadia Motion Software User Manual Rev 3.6 (2021-01-14)
---

# Fault diagnostics

Bit map: [fault codes](/can/fault-codes.md). Legacy `post_fault_hi/lo` and
`run_fault_hi/lo` symbols are removed — read M171 / Check Faults instead.[^sw-manual]

## Presentation

* VSM 7 (Blink Fault Code) + fault lamp. **POST outranks RUN**; the lamp
  blinks the count for one fault at a time.[^sw-manual]
* POST pattern = blink count **+ two quick blinks**; RUN = blink count
  only.[^sw-manual]
* Blink numbers are coarse (many faults share "1" or "2", e.g. all
  over-temps blink 1, all rail faults blink 2) — always confirm the exact bit
  in M171.[^sw-manual]

## Latch and clear

* **Latching**: HW Gate/Desaturation (POST 0 / RUN 40) needs a **power
  recycle**.[^sw-manual]
* **Not clearable**: POST 26 EEPROM Update Required — reflash/re-accept
  EEPROM instead; programming EEPROM drops VSM into 15 (Recycle Power).[^sw-manual]
* **Clearable**: write 0 to the Clear-Faults command (GUI button / CAN
  parameter addr 20). CAN shadow-fault register clears by writing 4.[^sw-manual]
* **Warnings vs faults**: POST 26 (EEPROM update) and RUN 63 (discharge
  active) are warnings, not shutdown faults.[^sw-manual]

[^sw-manual]: Software User Manual Rev 3.6 §§9.1.3, 9.6–9.8, App. M/N
