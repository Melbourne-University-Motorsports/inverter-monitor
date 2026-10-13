---
type: State Machine Reference
title: Vehicle state machine (VSM_State)
description: All VSM states, POST checks, precharge sequence, and wait/ready/running flow.
tags: [vsm, states, precharge, pm100]
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

# Vehicle state machine

Tracked via `VSM_State` (Memory View 0x0093, M170 byte 0). Values 8–13 are
undefined gaps.[^sw-manual] **This bench runs CAN command mode
(`Inverter_Command_Mode` = 0), so read every state below through the
[CAN-mode lens](#can-mode-reading-this-bench) — pedal, key-switch, and brake
inputs have no effect there.**[^can-protocol]

| VSM | Name | Behavior |
|-----|------|----------|
| 0 | Start | Power-up init: I/O setup, load defaults, load EEPROM + factory cals, run POST |
| 1 | Pre-charge Init | Faults if DCV above SW OV threshold, else energizes precharge relay |
| 2 | Pre-charge Active | Waits for DC cap to charge within range |
| 3 | Pre-charge Complete | Final checks, then Wait |
| 4 | Wait | Key-switch/brake/forward-reverse interlocks (below) |
| 5 | Ready | Sends enable to inverter machine, waits for Inverter Ready flag |
| 6 | Motor Running | Normal operation |
| 7 | Blink Fault Code | Faulted; see [diagnostics](faults-diagnostics.md) |
| 14 | Shutdown in Process | Key-switch mode 1: key turned off, winding down |
| 15 | Recycle Power | EEPROM programmed — re-power required for values to take effect |

## CAN-mode reading (this bench) — derived

The vendor manual describes Wait/Ready/Running through VSM-mode inputs (key
switch, brake, FWD/REV). In CAN mode those inputs are inert — torque and
speed commands come from the 0x0C0 [command message](/can/command-message.md)
instead[^can-protocol] — so the same VSM values mean the following. This is
synthesis from the inert-inputs rule, the lockout/timeout rules, and the
worked startup sequence, which opens with the inverter sitting at VSM 4 with
lockout set[^can-protocol]; the vendor never prints it as one sentence.

* **VSM 4 (Wait) in CAN mode = waiting for a valid command sequence.** The
  precise gate is not "any torque value" but: a Disable command first (releases
  enable lockout), then Enable + direction + torque/speed via 0x0C0, repeated
  inside the timeout window.[^can-protocol]
* **VSM 4→5** happens when the enable sequence is accepted (lockout already
  cleared, no faults, timeout armed and fed).[^can-protocol]
* **VSM 5→6** when the inverter machine reports ready; a timeout here raises
  the inverter-response fault path.[^sw-manual]
* **Stuck at 4 checklist**: lockout still set (no Disable seen — send one;
  note lockout will not clear while faulted), no Enable bit, heartbeat slower
  than `CAN Timeout` (→ RUN fault 43, motor disabled), or a sudden direction
  flip re-disabled the inverter and re-armed lockout (Disable again before
  re-enabling).[^can-protocol]
* **VSM 0–3** behave the same in both modes (POST, precharge); **7/14/15** as
  tabulated.[^sw-manual]

## POST (in VSM 0)

Checks current sensors, accelerator, PCB/GDB/module temps, 5/12/2.5/1.5 V
rails, and latched HW gate/desat + over-current (cleared once, then
reported). A POST failure blinks the fault lamp **plus two quick blinks** to
distinguish it from RUN faults.[^sw-manual] Bits: [fault codes](/can/fault-codes.md).

## Precharge (VSM 1–3)

VDC-high at entry faults immediately (threshold is hard-coded per inverter,
not user-set). Otherwise R1 (precharge) pulls in; when the cap is in range,
R2 (main) pulls in and R1 drops. Bypass EEPROM skips straight to Wait.
Timeout/voltage-failure set POST bits 22–23.[^sw-manual]

## Wait (VSM 4)

* **Key-switch 0**: plain on/off ignition → power straight through when ON.[^sw-manual]
* **Key-switch 1**: traditional ignition — momentary START latches power
  until the switch turns off (which enters VSM 14).[^sw-manual]
* Brake must satisfy its EEPROM window; forward/reverse DINs are mutually
  exclusive (both/neither asserts the direction-command RUN fault path;
  prose name `FWD_RVS_INVALID_STATE_FAULT` has no dedicated bit).[^sw-manual]
* **In CAN mode none of the above applies** — see
  [CAN-mode reading](#can-mode-reading-this-bench): VSM 4 means waiting for
  the 0x0C0 Disable→Enable+torque sequence, not for pedals or key.[^can-protocol]

## Ready → Running (VSM 5–6)

Ready energizes the [inverter machine](inverter-mode.md) and waits for its
Ready flag; a timeout de-energizes back toward Wait/Fault. Running is steady
motoring/regen under torque/speed command.[^sw-manual] In CAN mode the
"energize" command is the 0x0C0 Enable bit — Ready is where the inverter
machine runs its start sequence (current-sensor test, flux/torque ramps)
before reporting ready.[^sw-manual][^can-protocol]

[^sw-manual]: Software User Manual Rev 3.6 §9, pp31–39
[^can-protocol]: CAN Protocol Rev 6.3 §§1.1 (VSM vs CAN mode), 2.2 (command message, lockout, timeout, sequence example)
