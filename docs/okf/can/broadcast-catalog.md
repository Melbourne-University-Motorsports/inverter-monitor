---
type: CAN Catalog
title: Broadcast message catalog (0x0A0–0x0B1)
description: Address, rate, enable bit, and byte layout of every inverter broadcast message at default offset 0x0A0.
tags: [can, broadcast, catalog, pm100]
status: stable
generated: { by: cursor-agent/muse-spark-1.3, at: 2026-09-17T00:00:00Z }
sources:
  - id: can-protocol
    resource: ../../Source Documentation/CAN Protocol (V6_3).pdf
    title: Cascadia Motion CAN Protocol Rev 6.3 (2023-11-17)
---

# Broadcast catalog

Broadcasts are sent continuously in VSM and CAN command mode. Addresses below
assume the default offset 0x0A0; add the EEPROM offset otherwise.[^can-protocol]
Slow = `CAN_Slow_Msg_Rate` group (≈10 Hz), Fast = `CAN_Fast_Msg_Rate` group
(≈100 Hz). See [transport](transport.md) for rate physics and the Lo/Hi enable words.

| Addr | Rate | Content | Lo-word bit |
|------|------|---------|-------------|
| 0x0A0 | Slow | Temperatures #1 | 0x0001 |
| 0x0A1 | Slow | Temperatures #2 | 0x0002 |
| 0x0A2 | Slow | Temperatures #3 + torque shudder | 0x0004 |
| 0x0A3 | Fast | Analog input voltages | 0x0008 |
| 0x0A4 | Fast | Digital input status | 0x0010 |
| 0x0A5 | Fast | Motor position info | 0x0020 |
| 0x0A6 | Fast | Current info | 0x0040 |
| 0x0A7 | Fast | Voltage info | 0x0080 |
| 0x0A8 | Fast | Flux info | 0x0100 |
| 0x0A9 | Slow | Internal voltages | 0x0200 |
| 0x0AA | Fast | [Internal states](internal-states.md) | 0x0400 |
| 0x0AB | Fast | [Fault codes](fault-codes.md) | 0x0800 |
| 0x0AC | Fast | Torque + power-on timer | 0x1000 |
| 0x0AD | Fast | Modulation + flux weakening | 0x2000 |
| 0x0AE | Slow | Firmware info | 0x4000 |
| 0x0AF | 100 Hz fixed | Diagnostic data (see Download Diagnostic Data manual) | 0x8000 |
| 0x0B0 | 333 Hz fixed | High-speed message (needs Hi word = 0xFFFE, v2042+) | Hi bit 0 (inverted) |
| 0x0B1 | Fast | Torque capability (v652D+) | Hi-adjacent 0x0002 |

## Byte layouts

Scales resolve via [data formats](data-formats.md).

**0x0A0 Temperatures #1** — bytes 0–1 Module A, 2–3 Module B, 4–5 Module C,
6–7 gate-driver board (all Temperature).[^can-protocol]

**0x0A1 Temperatures #2** — 0–1 control board, 2–3 RTD #1, 4–5 RTD #2, 6–7
stall-burst model temperature on Gen5/CM, else RTD #3 (Gen 2).[^can-protocol]

**0x0A2 Temperatures #3 + shudder** — 0–1 coolant (Gen5/CM) / RTD #4 (Gen 2),
2–3 hot spot (Gen5/CM) / RTD #5 (Gen 2), 4–5 motor temperature, 6–7 torque
shudder (Torque).[^can-protocol]

**0x0A3 Analog inputs** — before firmware 1995: four 16-bit Low-Voltage
inputs. From 1995: six **10-bit** fields packed at bits 0–9, 10–19, 20–29,
32–41, 42–51, 52–61. Gen5/CM with iM-225 motor has its own variant —
check firmware before decoding.[^can-protocol]

**0x0A4 Digital inputs** — one Boolean byte each: DIN1 forward, DIN2 reverse,
DIN3 brake, DIN4 REGEN-disable, DIN5 ignition, DIN6 start, DIN7 valet,
DIN8.[^can-protocol]

**0x0A5 Motor position** — 0–1 electrical angle (Angle), 2–3 motor speed
(RPM), 4–5 electrical output frequency (Frequency), 6–7 delta-resolver
filtered angle (±180°; 270° reads as −90°).[^can-protocol]

**0x0A6 Currents** — 0–1 phase A, 2–3 phase B, 4–5 phase C, 6–7 DC bus
(calculated), all Current.[^can-protocol]

**0x0A7 Voltages** — 0–1 DC bus, 2–3 output (peak line-neutral, calculated),
4–5 VAB when disabled / Vd when enabled, 6–7 VBC when disabled / Vq when
enabled (all High Voltage).[^can-protocol]

**0x0A8 Flux** — 0–1 flux command, 2–3 flux feedback (Flux, induction motors
only), 4–5 Id feedback, 6–7 Iq feedback (Current).[^can-protocol]

**0x0A9 Internal voltages** — 0–1 1.5 V ref, 2–3 2.5 V ref, 4–5 5.0 V ref,
6–7 12 V system (all Low Voltage).[^can-protocol]

**0x0AC Torque + timer** — 0–1 commanded torque, 2–3 torque feedback
(Torque); 4–7 power-on timer in **3 ms counts** (rolls over in ~5 months,
resets at power-on — useful as a reboot witness).[^can-protocol]

**0x0AD Modulation + flux** — 0–1 modulation index (÷100), 2–3 flux-weakening
output (Current), 4–5 Id command, 6–7 Iq command (Current).[^can-protocol]

**0x0AE Firmware** — 0–1 EEPROM version / project code (factory), 2–3
software version (major.minor), 4–5 date MMDD, 6–7 date YYYY.[^can-protocol]

**0x0B0 High-speed** — 0–1 torque command, 2–3 torque feedback (Torque), 4–5
motor speed (RPM), 6–7 DC bus (High Voltage).[^can-protocol]

**0x0B1 Torque capability** — 0–1 available torque (Torque); bytes 2–7
reserved.[^can-protocol]

Internal states and faults have their own concepts:
[0x0AA internal states](internal-states.md),
[0x0AB fault codes](fault-codes.md).

[^can-protocol]: CAN Protocol Rev 6.3 §2.1
