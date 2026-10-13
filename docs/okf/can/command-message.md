---
type: CAN Command Reference
title: Command message 0x0C0 (VCU to inverter)
description: Heartbeat torque/speed control word, safety interlocks, and sign convention. Transmit-only; the monitor never sends it.
tags: [can, command, safety, torque, pm100]
status: stable
generated: { by: cursor-agent/muse-spark-1.3, at: 2026-09-17T00:00:00Z }
sources:
  - id: can-protocol
    resource: ../../Source Documentation/CAN Protocol (V6_3).pdf
    title: Cascadia Motion CAN Protocol Rev 6.3 (2023-11-17)
---

# Command message (0x0C0)

Sent by the external controller **to** the inverter. 8 bytes, processed every
3 ms; broadcast at ≤500 ms intervals (10–50 ms typical for vehicles). Faster
than 3 ms buys nothing.[^can-protocol] **The monitor never transmits this.**

| Bytes | Signal | Encoding |
|-------|--------|----------|
| 0–1 | Torque command | Torque (N·m ×10); in Speed mode becomes feedforward to the speed regulator |
| 2–3 | Speed command | RPM; from v2048/651D also overrides Max-Speed EEPROM while in Torque mode |
| 4 | Direction | 0 Reverse (CW), 1 Forward (CCW) |
| 5.0 | Inverter enable | 0 off, 1 on |
| 5.1 | Discharge enable | 0 disable, 1 enable |
| 5.2 | Speed-mode override | 1 forces Torque→Speed (never Speed→Torque) |
| 6–7 | Commanded torque limit | 0 = use EEPROM motor/regen limits, else clamps both (added v1953; send 0 on older fw) |

## Safety interlocks

* **Enable lockout**: after power-up the inverter ignores Enable until it has
  seen a Disable — always send Disable first.[^can-protocol]
* **Enable switch** (`CAN Inverter Enable Switch Active`): when 1, DIN1 **and**
  the command bit must both be active; either off disables.[^can-protocol]
* **Sudden reversal**: flipping direction while enabled disables the inverter
  without a fault and re-arms lockout — Disable again before re-enabling.[^can-protocol]
* **Timeout**: if `CAN Command Message Active` = 1 and no command arrives
  within `CAN Timeout` (3 ms counts, e.g. 333 → 999 ms), the inverter latches
  RUN fault 43 (CAN Command Message Lost) and disables the motor. Last
  command is otherwise held.[^can-protocol]
* In CAN mode send commands **before** power-on/timeout expiry or clear the
  resulting fault at boot.[^can-protocol]

## Sign convention

Forward/CCW with positive torque drives motoring forward; reverse/CW mirrors
it. Mismatched torque/speed signs against the direction bit produce braking
or no motion depending on mode — validate on the bench before driving
wheels. (Full table: CAN Protocol §2.2.3.)[^can-protocol]

## What this does to VSM (CAN mode)

The p35 worked example opens with the inverter at **VSM 4, lockout set**:
Disable releases lockout (still VSM 4), Enable + 10 Nm moves it toward
Ready/Running, later torque updates just re-command the running machine, and
Disable-before-direction-change keeps the machine parked at 4 instead of
tripping the reversal guard.[^can-protocol] So on this bench: **VSM 4 means
"waiting for this message"** — full semantics in
[VSM, CAN-mode reading](/inverter/vsm.md#can-mode-reading-this-bench).

[^can-protocol]: CAN Protocol Rev 6.3 §2.2
