---
type: CAN Transport
title: PM CAN transport, addressing, and rates
description: Framing, baud, ID-offset/J1939 addressing, and broadcast rates for PM/RM/Gen5/CM controllers.
tags: [can, transport, addressing, pm100dx]
status: stable
generated: { by: cursor-agent/muse-spark-1.3, at: 2026-09-17T00:00:00Z }
sources:
  - id: can-protocol
    resource: ../../Source Documentation/CAN Protocol (V6_3).pdf
    title: Cascadia Motion CAN Protocol Rev 6.3 (2023-11-17)
---

# Transport

Controller family: PM, RM, PM Gen 5, CM share one CAN protocol; some features
are generation-gated.[^can-protocol]

## Physical / framing

* Two CAN interfaces; only **CAN A** is used, CAN B is reserved.[^can-protocol]
* Conforms to **CAN 2.0A (11-bit)** and **2.0B (29-bit)**.[^can-protocol]
* Every message: **DLC = 8**, **little-endian** (LSB at lowest address).[^can-protocol]
* Example command encoding (CAN speed mode, 500 RPM, torque 30 Nm): bytes
  `44 1 244 1 0 1 0 0` — torque 300 = 1×256+44 in bytes 0–1, speed 500 =
  1×256+244 in bytes 2–3, direction byte 4, enable byte 5.[^can-protocol]
* At 250 kbps an 89-bit frame caps the bus at ~2808 msgs/s.[^can-protocol]

## Baud and termination

* EEPROM baud options: 125 / 250 / 500 / 1000 kbps; **default 250**. Change
  needs a power reset (bus speed is latched at CAN-module init).[^can-protocol]
* **PM**: user-configurable 120 Ω terminator via EEPROM (default active).
  **RM**: no built-in terminator (parameter has no effect). **CM**: terminator
  via external wiring, see hardware manual.[^can-protocol]
* This repo's bench default is **500 kbit/s** unless the car uses otherwise
  (see [monitor mapping](/monitor/readout-mapping)).

## Addressing

* **CAN ID Offset** (default **0x0A0**): start of a contiguous ID block.
  11-bit range 0–0x7C0, default block 0x0A0–0x0CF. 29-bit range
  0–0xFFC0. Essential with >1 controller — blocks must not overlap.[^can-protocol]
* **Extended ID** EEPROM bit: 0 = standard 11-bit, 1 = extended 29-bit.[^can-protocol]
* **J1939 option** (needs extended = 1): fixed Priority 3, Data Page 0,
  PDU Format 0xFF, PDU Specific = CAN ID Offset, Source Address 0x01 both
  directions. With offset 0xA0, broadcasts go out as `0xCFFA0xx01` and the
  heartbeat command is sent as `0xCFFC001`.[^can-protocol]

## Broadcast rates

* Rate groups are set by `CAN_Fast_Msg_Rate_EEPROM_(ms)` (default 10) and
  `CAN_Slow_Msg_Rate_EEPROM_(ms)` (default 100). The send loop ticks every
  **3 ms**, so a 10 ms setting actually lands near 12 ms; never set below
  3 ms. Setting a group rate to **0 disables the whole group**.[^can-protocol]
* Fixed-rate exceptions: [0x0AF diagnostic data](broadcast-catalog.md) at
  100 Hz, [0x0B0 high-speed message](broadcast-catalog.md) at ~333 Hz (3 ms),
  slave command at ~10 ms.[^can-protocol]
* Bus priority decides actual spacing when many messages trigger together —
  expect jitter.[^can-protocol]

## Enabling / disabling broadcasts

* `CAN Active Messages Lo Word` (param addr **148**) gates 0x0A0–0x0AF bit by
  bit (1 = enabled, default all on). Hi Word (addr 237) should stay **0xFFFF**;
  use **0xFFFE** to turn the 0x0B0 high-speed message **on** (bit 0 is
  inverted: 0 = on).[^can-protocol]
* Worked example: to silence Temperatures #1–#3, write Lo Word with bits 0–2
  cleared (byte 4 = 0xF8 instead of 0xFF) via the parameter message; byte 4
  bit 5 = motor position (0xDF clears it), byte 5 covers flux → diag data,
  bytes 6–7 cover slave/BMS/OBD2/U2C/parameter/command mailboxes and should
  be left alone.[^can-protocol] Full bit map is in
  [broadcast catalog](broadcast-catalog.md).

[^can-protocol]: CAN Protocol Rev 6.3 §§1–2.1
