---
type: CAN Diagnostics
title: CAN module status and fault registers (Gen 3)
description: Bit maps for CAN_Status 0x00C8 and CAN_Faults 0x00C9, the Tx/Rx error counters, the Gen 5/CM-only watch items, and the monitor's "CAN degraded" flag.
tags: [can, diagnostics, memory-view, gen3, pm100dx]
status: stable
generated: { by: hermes-agent, at: 2026-09-19T00:00:00Z }
sources:
  - id: can-protocol
    resource: ../../Source Documentation/CAN Protocol (V6_3).pdf
    title: Cascadia Motion CAN Protocol Rev 6.3 (2023-11-17)
  - id: sw-manual
    resource: ../../Source Documentation/Software User Manual (V3_6) For Inverter.pdf
    title: Cascadia Motion Software User Manual Rev 3.6 (2021-01-14)
---

# CAN status and fault registers

§1.2 of the CAN Protocol (pp. 10–13, **Gen 3 only**) documents two shadow
registers of the microcontroller CAN module plus the error counters. They are
read over RS232 **Memory View** — ordinary `rm` symbols, not CAN broadcasts —
and they are the only place the inverter reports *how* the CAN bus is doing.[^can-protocol]

Addresses come from the G3 defsyms (`data/defsyms.yaml`); bit meanings from
§1.2. The same subjects exist on **Gen 5/CM** as separate GUI watch items
(§1.3) — see [below](#gen-5cm-only-watch-items).

## CAN_Status — `0x00C8` (`MemoryView.CAN_Status`)

Live shadow of the status register, refreshed every 3 ms.

| Mask | Bit | Severity | Meaning |
|------|-----|----------|---------|
| 0x0001 | Transmit Mode | info | Module is transmitting a message (1) / idle (0) |
| 0x0002 | Receive Mode | info | Module is receiving a message (1) / idle (0) |
| 0x0004 | Power Down Acknowledge | info | Module entered power-down mode |
| 0x0008 | Change Configuration Enable | info | CPU has write access to the CAN config registers |
| 0x0010 | Suspend Mode Acknowledge | info | Debugger attached; suspend mode entered |
| 0x0020 | **Error Warning (EW)** | warning | An error counter reached the warning level of **96** |
| 0x0040 | **Error Passive (EP)** | warning | Transmit error counter reached **128**; the node has gone error-passive |
| 0x0080 | **Bus Off (BO)** | fault | Transmit error counter reached **256**; nothing can be sent or received |

Bus Off: auto bus-on is enabled, so the controller restarts itself after
128 × 11 recessive bits and the error counters are cleared once it leaves
bus-off.[^can-protocol]

## CAN_Faults — `0x00C9` (`MemoryView.CAN_Faults`)

Sticky shadow of the fault register: a bit that sets stays readable until
Clear Faults is sent — the same `wm0002=0000` button that clears POST/RUN
faults. A latched bit here does **not** stop the bus by itself.

| Mask | Bit | Severity | Meaning |
|------|-----|----------|---------|
| 0x01 | Acknowledge Error (ACKE) | warning | No acknowledge received for a transmitted frame |
| 0x02 | Stuff Error (SE) | warning | Stuff-bit error on the bus |
| 0x04 | CRC Error (CRCE) | warning | Frame received with a wrong CRC |
| 0x08 | Stuck At Dominant 1 (SA1) | info | Set after reset / bus-off until a recessive bit is seen |
| 0x10 | Bit Error (BE) | warning | Received bit ≠ transmitted bit, or dominant sent / recessive received |
| 0x20 | Form Error (FE) | warning | A fixed-form bit field carried the wrong level |

SA1 is 1 on every power-up by design, so it is explained but never used on its
own to raise the monitor's flag.

## Error counters

| Symbol | Address | Max | Warn at | Meaning |
|--------|---------|-----|---------|---------|
| `CAN_Tx_Error_Counter` | `0x00CC` | 255 | 96 | Errors while **sending**; wraps to 0 after 255. 128 → error-passive, 256 → bus-off |
| `CAN_Rx_Error_Counter` | `0x00CD` | 127 | 96 | Errors while **receiving**; counts back down per good frame |
| `CAN_Tx_Error_Counter_(Max)` | `0x008B` | 255 | 96 | Highest transmit count seen — a post-run witness |

## Gen 5/CM-only watch items

§1.3 lists these as standalone RMS GUI watch items on **Gen 5/CM**
controllers. They are not the Gen 3 register map above and this monitor does
not poll them:

`CAN_Status_Bus_Off`, `CAN_Status_Error_Passive`, `CAN_Status_Error_Warning`,
`CAN_Status_Last_Error_Code` (0 none, 1 stuff, 2 form, 3 ack, 4 bit-1,
5 bit-0, 6 CRC), `CAN_Tx_Error_Counter`, `CAN_Rx_Error_Counter`.

## Undocumented

`CANES_Low` `0x00CA` and `CANES_High` `0x00CB` sit next to the CAN block in the
G3 defsyms. Neither PDF describes them; the name suggests a CAN
error-status pair. Not decoded — do not guess at their bits.

## What the monitor does

`data/can_status.yaml` carries the maps above; `can_health.py` turns them into
one level, and the Faults tab polls `0x00C8`, `0x00C9`, `0x00CC`, `0x00CD`
while it is open (see [readout mapping](/monitor/readout-mapping.md)).

| Level | Shown as | Rule |
|-------|----------|------|
| fault | `CAN bus off` (red) | Bus Off 0x0080 set |
| warning | `CAN degraded` (orange) | EW 0x0020 / EP 0x0040, any latched warning bit in CAN_Faults, or Tx/Rx counter ≥ 96 |
| ok | `CAN OK` (green) | Both words read 0 and both counters < 96 |
| unknown | `CAN —` | Nothing fresh for this feed (e.g. connected over CAN, where these RS232 registers do not exist) |

Where it appears: a chip + one-line reason + the raw words on the **Faults
tab** (click the chip for the per-bit explanations), and the status strip's
existing `FAULTS` element appends `· CAN DEGRADED` (orange) or `· CAN BUS OFF`
(red) — no separate badge. Nothing is shown while the level is unknown, so a
CAN-source session does not report a false CAN problem.

## Doc conflicts

* CAN Protocol p. 12 prints "setting Clear Fault Command to **04**". The
  trailing `4` is that page's footnote marker; Software User Manual §11.6.2 and
  the monitor's Clear Faults path both write **0** to `0x0002`.

[^can-protocol]: CAN Protocol Rev 6.3 §1.2 (Gen 3 only) pp. 10–13, §1.3 (Gen 5/CM only) p. 13
[^sw-manual]: Software User Manual Rev 3.6 §11.6.2 (Clear Faults Command)
