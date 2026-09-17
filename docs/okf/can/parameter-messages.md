---
type: CAN Parameter Reference
title: Parameter messages 0x0C1/0x0C2 and address map
description: Read/write parameter wire format, command parameters, and the EEPROM parameter map. Write path is documented, not implemented.
tags: [can, parameters, eeprom, relays, pm100dx]
status: stable
generated: { by: cursor-agent/muse-spark-1.3, at: 2026-09-17T00:00:00Z }
sources:
  - id: can-protocol
    resource: ../../Source Documentation/CAN Protocol (V6_3).pdf
    title: Cascadia Motion CAN Protocol Rev 6.3 (2023-11-17)
---

# Parameter messages (0x0C1 / 0x0C2)

Read/write access to controller parameters. 0x0C1 is VCU→inverter, 0x0C2 is
the response.[^can-protocol] **Documented for decode context only — the
monitor never transmits.**

## Wire format

0x0C1 command: bytes 0–1 parameter address (uint), byte 2 R/W (0 read,
1 write), byte 3 reserved, bytes 4–5 data (per [data formats](data-formats.md)),
bytes 6–7 reserved. Data shorter than 4 bytes packs from byte 4 upward.[^can-protocol]

0x0C2 response: same address echo (0,0 = unknown address), byte 2 write-success
(0/1), data in bytes 4–5.[^can-protocol]

## Address ranges

| Range | Category | Notes |
|-------|----------|-------|
| 0–99 | General command/monitor | Includes relay control, flux, resolver, fault clear (below) |
| 100–499 | User EEPROM | Writable only while motor is **not** enabled; stored to NVM immediately; mostly effective after power recycle (yellow-highlighted subset is immediate) |

## Command parameters (0–99)

| Addr | Name | Notes |
|------|------|-------|
| 1 | Relay command | `0xAA00` normal run; `0x55nn` external relay control, byte 4 bit n = relay n+1 (e.g. `0x5504` = relay 3; `0x5503` = R1+R2). Gen3 has 6 relays, Gen2 4, RM100 2. Anything ≠0x55 in byte 5 exits to normal run (default 0xAA). |
| 10 | Flux command | Induction motors |
| 11 | Resolver PWM delay (0–6250, default 1100) | A/D timing calibration |
| 12 | Gamma adjust (deg) | Resolver field alignment; defaults per motor type |
| 20 | Fault clear | Write 0 clears active faults, CAN and VSM mode |
| 21 | Set PWM frequency (6–24, Gen5/CM) | Overrides EEPROM until power cycle |
| 22 | AIN pull-up control (0–7, CM) | Bits 0–2 = AIN1–3 pull-ups |
| 23 | Shudder gain control (fw ≥2048/651D) | 0 disables; >0 enables (if EEPROM-enabled) and sets Kp = data/100 |
| 30 | OBD2 enable (0–8) | Mailbox offset, see [special modes](special-modes.md) |
| 31 | Diag-data trigger (fw ≥651E) | Non-zero dumps diag data over CAN |

## EEPROM parameters (100–499, selected)

Full table: CAN Protocol §2.3.4; GUI names/addresses: [EEPROM guide](/inverter/eeprom.md).

* Motor: 150 motor set, 151 resolver delay, 152 gamma, 154–157 sin/cos offsets.
* System: 140 precharge bypass, 142 run mode (0 torque/1 speed), 143 command
  mode (0 CAN/1 VSM), 149 key-switch, 170 relay state, 173 discharge, 174 serial.
* CAN: 141 offset, 144 extended, 171 J1939, 145 terminator, 146 timeout-active,
  147 bitrate, 148/237 active-msgs Lo/Hi, 158 diag-tx, 159 DIN1 enable-switch,
  172 timeout (3 ms counts), 177 OBD2, 178 BMS, 233/234 slave ID/dir, 235/236
  fast/slow rates (fw 2025+), 238–240 Gen5/CM debounce tuning.
* Current/voltage/thermal/accel/torque/speed/shudder/brake groups: 100–193 as
  listed in §2.3.4.3–§2.3.4.10; 153/194–198/200–201 reserved (factory).

[^can-protocol]: CAN Protocol Rev 6.3 §2.3
