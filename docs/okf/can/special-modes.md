---
type: CAN Feature Reference
title: Special CAN modes (OBD2, BMS, slave, rolling counter, diagnostics)
description: Optional bus features outside the core broadcast/command/parameter set.
tags: [can, obd2, bms, slave, rolling-counter, diagnostics, pm100dx]
status: stable
generated: { by: cursor-agent/muse-spark-1.3, at: 2026-09-17T00:00:00Z }
sources:
  - id: can-protocol
    resource: ../../Source Documentation/CAN Protocol (V6_3).pdf
    title: Cascadia Motion CAN Protocol Rev 6.3 (2023-11-17)
---

# Special modes

## OBD2 (fw ≥19B3)

Vehicle-specific OBD2 subset for phone/dongle tools (validated with OBDLink LX
+ Torque app). No DTC responses — only enhanced Mode `0x22` queries. Every
Memory-View item is reachable via custom PIDs (spreadsheet from support).
Enable with `CAN_OBD2_Enable_EEPROM` 1–7 (offset; use 1 unless multiple
inverters share the bus).[^can-protocol]

## Orion BMS (fw ≥19B3)

Listens for Orion BMS frames and derates torque from pack current/voltage
limits (estimated DC current, not measured). Enable with `CAN BMS Limit
Enable`; status surfaces on M170 byte 7 bits 1–2 (BMS active / limiting
torque).[^can-protocol]

## Slave operation (fw ≥19BB)

One master decides torque; the slave mirrors its command message at ~10 ms
regardless of fast/slow rates. Set master's `CAN Slave Cmd ID` to slave offset
− 0x20 (0 disables; e.g. slave 0x1A0 → master 0x1C0), `CAN Slave Dir` 0 = same
/ 1 = opposite direction, and keep slave-mailbox bit (Hi-word bit 6 / addr-237
bit 22) set.[^can-protocol]

## Rolling counter (Gen5/CM)

4-bit counter in M170 byte 5 bits 4–7 guards against replayed/lost commands.
Tuning: 238 max (default 20; 0 disables), 239 up-count (default 5), 240
down-count; GUI 0x1B8/0x1B9 and monitor words `CAN_Rolling_Count_Flag`
(0x9D), `CAN_Debounce_Count` (0x9E). Single miss increments, clean messages
decrement; fault at max.[^can-protocol]

## CAN diagnostics

* Gen3 shadow registers: **status** bits TM/RM/PDA/CCE/SMA/warning/error-passive/
  bus-off (real-time, 3 ms) and latched **fault** bits ACKE/SE/CRCE/SA1/BE/FE
  (clear by writing 4 to Clear Faults).[^can-protocol]
* Gen5/CM GUI words: bus-off, error-passive, error-warning, last-error code
  (0 none, 1 stuff, 2 form, 3 ack, 4 bit-1, 5 bit-0, 6 CRC), Tx counter
  (0–255 wrap), Rx counter (0–127, decrements on clean Rx). Auto-restart from
  bus-off is enabled.[^can-protocol]

[^can-protocol]: CAN Protocol Rev 6.3 §§1.2–1.3, 2.4–2.7
