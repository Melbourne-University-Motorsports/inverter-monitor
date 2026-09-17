# PDF Extract Notes — Cascadia Motion Software User Manual V3.6

**Source:** `/Users/rrxie/Downloads/Software User Manual (V3_6) For Inverter.pdf`  
**Revision:** 3.6 (1/14/2021)  
**Publisher:** Cascadia Motion (formerly Rinehart Motion Systems)

## Protocol version

- Manual revision **3.6**; firmware/GUI versioning is per Firmware Release Package (SWRP), not a single CAN protocol version in this document.

## Default bitrates / transports

| Transport | Settings | Pages |
|-----------|----------|-------|
| RS232 SCI data acquisition | 57600 baud, 8 data bits, no parity, 1 stop bit, no flow control | 18 |
| RS232 RMS GUI | COM port auto-configured by GUI; no manual baud setup required | 22 |
| RS232 C2PROG firmware programming | 57600 baud, 8N1 | 14 |
| CAN | **Not specified in this manual.** Appendix C refers to separate **CAN Protocol** document. | 47 |

## How faults are reported

- **Fault word:** POST faults occupy CAN bytes **0–3** (bits 0–31); RUN faults occupy bytes **4–7** (bits 32–63). Bit maps on pages 33, 37–38.
- **Legacy symbols removed:** `post_fault_hi`, `post_fault_lo`, `run_fault_hi`, `run_fault_lo`.
- **GUI:** Memory View → Check Faults button; Clear Faults sets Clear Faults Command to **0**.
- **Fault indicator:** Blinks one fault; POST priority over RUN; POST followed by two quick blinks. Blink count maps to fault (Appendices M/N).
- **Warnings (distinct):** EEPROM Update Required (POST bit 26); Inverter Discharge Active (RUN bit 63).
- **Latching:** Hardware Gate/Desaturation (POST & RUN) requires power recycle; EEPROM Update Required not cleared by Clear Faults.

## EEPROM / parameter flashing feasibility

- EEPROM parameters programmable via **RMS GUI** (RS232) or **CAN Parameter message** (details in CAN Protocol doc, not this manual).
- After firmware reflash: **EEPROM Update Required** warning; user must accept/update parameters.
- After EEPROM programming: VSM enters **Recycle Power State (15)**; controller must be re-powered.
- GUI can save/load EEPROM value files; Program EEPROM command writes to non-volatile memory.

## Key section page index

| Topic | Pages |
|-------|-------|
| SCI broadcast parameters | 18–19 |
| Data format multipliers | 20 |
| RMS GUI / EEPROM guide | 22–24 |
| Vehicle State Machine | 31–39 |
| POST fault bit table | 33 |
| RUN fault bit table | 37–38 |
| Appendix C CAN config | 47 (empty — external doc) |
| GUI monitored parameters | 72–74 |
| POST fault diagnostics | 76–77 |
| RUN fault diagnostics | 78–80 |

## Ambiguous / missing from this manual

1. **CAN message IDs**, broadcast cycle times, endianness, and per-signal start bits — deferred to **CAN Protocol** document.
2. **Appendix C** contains no parameter table (only a reference to CAN Protocol).
3. **Section 11 / 11.4** referenced for VSM_State and Inverter_Mode but not present in revision 3.6 TOC.
4. **FWD_RVS_INVALID_STATE_FAULT** named in Wait State text but not mapped to fault word bits.
5. **Clear Faults Command** GUI/CAN address not listed (behavior only).
6. **Heartbeat command message** referenced for CAN mode fault 43; message ID/format not in this manual.
7. VSM state IDs **8–13** and inverter state IDs **13–14** are undefined gaps in numbering.
8. Run fault table Module A bit value shows `00400000` on page 37 for bit 50 — verify against hardware revision; adjacent bits use sequential hex masks.

## Recommended follow-up documents

- CAN Protocol (Cascadia Motion)
- Inverter Discharge Process Manual
- Motor-specific setup manuals (Motor_Type_EEPROM)
- Firmware Release Package default symbols file (`defsyms_yyyymmdd.txt`)
