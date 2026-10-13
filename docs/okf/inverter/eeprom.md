---
type: EEPROM Reference
title: EEPROM parameter guide (GUI addresses)
description: Appendix parameter groups with GUI addresses, ranges, and the CAN subgroup pointer.
tags: [eeprom, parameters, calibration, pm100]
status: stable
generated: { by: cursor-agent/muse-spark-1.3, at: 2026-09-17T00:00:00Z }
sources:
  - id: sw-manual
    resource: ../../Source Documentation/Software User Manual (V3_6) For Inverter.pdf
    title: Cascadia Motion Software User Manual Rev 3.6 (2021-01-14)
---

# EEPROM guide

Program via `inverter-monitor` EEPROM tab (RS232 Memory View) or RMS GUI (RS232).
After reflash expect POST 26 (EEPROM Update Required); after programming VSM
enters 15 (Recycle Power). GUI/monitor saves and manages values. Motor-Type manuals
give per-motor defaults. Addresses below are GUI/Memory-View hex.[^sw-manual]

| Group | Key params |
|-------|------------|
| Motor (A) | `Motor_Type_EEPROM` 0x0119 (0–255, selects motor + defaults) |
| System (B) | Serial 0x0113; precharge bypass 0x0115; accel-flip 0x0114; run/cmd mode; key-switch 0x012B (0 simple / 1 momentary-START); relay state 0x012C (keep **0x000C**); precharge/main/relay truth tables in manual |
| CAN (C) | Parameter addresses 0x011D–0x0124 (baud, ID offset) |
| Current (D) | Iq limit 0x0101, Id limit, Ia/Ib offsets (2048 = 0 A, auto-calibrated) |
| Voltage/Flux (E) | DC limit 0x0104 (0–10000), hysteresis, under-volt, flux constant |
| Temperature (F) | Inv limit 0x0106 (−40–125 °C), motor limit, full/zero torque temps, RTD select + G3 calibration (factory) |
| Accel/Torque (G) | Pedal low/max/hi 0x010B–0x010C (1–500), flip, motor/regen/brake torque limits, temp/speed derate lines |
| Speed (H) | Overspeed (fault), max speed (cap → torque→0, zero at ×1.02), regen fade, break speed, PID + rate limit (100–5100 RPM) |
| PID (I) | Torque/speed Kp/Ki/Kd/Klp with ×100/×10000 entry scaling |
| Shudder (J) | Enable 0x0134, Kp 0x0135 (0.1–50), TCLAMP, filter freq, fade speeds |
| Brake (K) | Mode 0x013A (0 switch/DIN3, 1 pot, 2 switch/DIN7), low/min/max/hi 0x013B–0x013E, regen ramp 0x0133, flip, bypass |
| Display (L) | Watch symbols: run cmd/mode, VSM, enable, direction, speeds/torques, DC, temps, relays, DINs, faults, status words |

Monitor-relevant glance addresses: VSM 0x0093, Inverter_Mode 0x0092, Enable
0x0094, direction 0x0095, speeds/torques 0x0097–0x0099, VDC 0x00AD, IDC 0x00AF,
discharge 0x0087, last-run-fault 0x005D, limit-flags 0x005C, status/faults
0x00C8/0x00C9.[^sw-manual]

## Inverter Monitor EEPROM workflow

1. **Read & Dump**: On RS232 connection, the monitor automatically walks all
   EEPROM parameters in the background to build the baseline table.
2. **Edit & Validate**: Values can be edited in engineering units or hex. Changes
   are validated against acceptable ranges and marked dirty with visual highlighting.
3. **Review & Push**: Clicking **Push to inverter** opens a diff confirmation modal
   listing each modified address. The push sequence enforces that the inverter is
   in **VSM Wait (4)** and **Inverter Disabled (0)** before transmitting individual
   `wm` frames and issuing the EEPROM commit command pair (`wm0000=5a0f` / `wm0001=0059`).

[^sw-manual]: Software User Manual Rev 3.6 §§5–7, App. A–L
