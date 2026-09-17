---
type: Fault Reference
title: Fault codes message 0x0AB (M171), 64 bits
description: Complete POST (bytes 0-3) and RUN (bytes 4-7) fault bit map with blink, latch, and clear behavior.
tags: [can, m171, faults, post, run, pm100dx]
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

# Fault codes (0x0AB / M171)

Fast (≈100 Hz): bytes 0–3 = POST faults (power-up self-test, bits 0–31),
bytes 4–7 = RUN faults (bits 32–63). Each bit = 1 fault.[^can-protocol]
GUI path is Memory View → Check Faults; writing 0 to the Clear-Faults command
clears (see [diagnostics](/inverter/faults-diagnostics.md)).[^sw-manual]

## POST bits 0–31

| Bit | Fault | Byte value |
|-----|-------|------------|
| 0 | Hardware Gate/Desaturation (latching, needs power recycle) | B0 0x01 |
| 1 | HW Over-current | B0 0x02 |
| 2 | Accelerator shorted to ground | B0 0x04 |
| 3 | Accelerator open / shorted to 5 V | B0 0x08 |
| 4 | Current Sensor Low | B0 0x10 |
| 5 | Current Sensor High | B0 0x20 |
| 6 | Module Temperature Low | B0 0x40 |
| 7 | Module Temperature High | B0 0x80 |
| 8 | Control PCB Temperature Low | B1 0x01 |
| 9 | Control PCB Temperature High | B1 0x02 |
| 10 | Gate-drive PCB Temperature Low | B1 0x04 |
| 11 | Gate-drive PCB Temperature High | B1 0x08 |
| 12 | 5 V Sense Low | B1 0x10 |
| 13 | 5 V Sense High | B1 0x20 |
| 14 | 12 V Sense Low | B1 0x40 |
| 15 | 12 V Sense High | B1 0x80 |
| 16 | 2.5 V ref Low | B2 0x01 |
| 17 | 2.5 V ref High | B2 0x02 |
| 18 | 1.5 V ref Low | B2 0x04 |
| 19 | 1.5 V ref High | B2 0x08 |
| 20 | DC Bus High | B2 0x10 |
| 21 | DC Bus Low | B2 0x20 |
| 22 | Pre-charge Timeout | B2 0x40 |
| 23 | Pre-charge Voltage Failure | B2 0x80 |
| 24 | EEPROM Checksum Invalid | B3 0x01 |
| 25 | EEPROM Data Out of Range | B3 0x02 |
| 26 | **EEPROM Update Required (warning; NOT cleared by Clear Faults)** | B3 0x04 |
| 27 | HW DC-bus Over-Voltage at init (CAN Protocol) / Reserved (SWM V3.6) | B3 0x08 |
| 28 | Reserved (Gen3) / Gate-driver init (Gen5) | B3 0x10 |
| 29 | Reserved | B3 0x20 |
| 30 | Brake shorted to ground | B3 0x40 |
| 31 | Brake open / shorted to 5 V | B3 0x80 |

## RUN bits 32–63

| Bit | Fault | Byte value |
|-----|-------|------------|
| 32 | Motor Over-speed | B4 0x01 |
| 33 | SW Over-current (motor phase) | B4 0x02 |
| 34 | DC Bus Over-voltage (SW limit) | B4 0x04 |
| 35 | Inverter Over-temperature (module/GDB/PCB) | B4 0x08 |
| 36 | Accelerator shorted to ground | B4 0x10 |
| 37 | Accelerator open / shorted to 5 V | B4 0x20 |
| 38 | Direction Command Fault | B4 0x40 |
| 39 | Inverter Response Time-out | B4 0x80 |
| 40 | Hardware Gate/Desaturation (latching) | B5 0x01 |
| 41 | Hardware Over-current | B5 0x02 |
| 42 | DC Bus Under-voltage | B5 0x04 |
| 43 | CAN Command Message Lost (needs heartbeat while timeout armed) | B5 0x08 |
| 44 | Motor Over-temperature | B5 0x10 |
| 45–47 | Reserved | B5 0x20–0x80 |
| 48 | Brake shorted to ground | B6 0x01 |
| 49 | Brake open / shorted to 5 V | B6 0x02 |
| 50 | Module A Over-temperature | B6 0x04 |
| 51 | Module B Over-temperature | B6 0x08 |
| 52 | Module C Over-temperature | B6 0x10 |
| 53 | PCB Over-temperature | B6 0x20 |
| 54 | Gate-drive Board 1 Over-temperature | B6 0x40 |
| 55 | Gate-drive Board 2 Over-temperature | B6 0x80 |
| 56 | Gate-drive Board 3 Over-temperature | B7 0x01 |
| 57 | Current Sensor Fault | B7 0x02 |
| 58 | Reserved (Gen3) / Gate-driver Over-Voltage (Gen5) | B7 0x04 |
| 59 | HW DC-bus Over-Voltage (Gen3) / Reserved (Gen5) | B7 0x08 |
| 60 | Reserved (Gen3) / HW DC-bus Over-Voltage (Gen5) | B7 0x10 |
| 61 | Reserved | B7 0x20 |
| 62 | Resolver Not Connected | B7 0x40 |
| 63 | **Inverter Discharge Active (warning)** | B7 0x80 |

## Known doc conflicts (resolved)

* **Bit 63**: CAN Protocol p29 prints "Reserved"; SW Manual App. N and the
  fault-word table assign Discharge Active (warning). The monitor treats 63
  as the discharge warning.[^can-protocol][^sw-manual]
* **POST bit 27**: CAN Protocol names HW DC-bus OV at init; SWM V3.6 table
  prints Reserved. Shown with both readings above.[^can-protocol][^sw-manual]
* **RUN bit 50 mask**: SWM p37 prints `00400000` for bit 50, colliding with
  bit 54's mask — bit number is authoritative (expected `00040000`); several
  RUN Hi module/GDB faults are also marked not-on-Gen2.[^sw-manual]
* Unlisted names (`FWD_RVS_INVALID_STATE_FAULT`) appear in Wait-state prose
  but map to no bit — treated as direction-command fault 38.[^sw-manual]

[^can-protocol]: CAN Protocol Rev 6.3 §2.1, 0x0AB + POST/RUN tables
[^sw-manual]: Software User Manual Rev 3.6 §§9.1.3, 9.6, App. M/N, pp33/37–38
