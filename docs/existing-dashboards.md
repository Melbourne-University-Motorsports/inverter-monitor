# Existing Rensselaer Motorsport Inverter Dashboards

Research date: 2026-09-16. Sources cloned to `/tmp/rms-dashboard-research/` for analysis (not committed).

## Local workspace context

`/Users/rrxie/dev/GitHub` is a multi-repo workspace. Neither target repo was cloned locally before this research.

| Path | Relevance |
|------|-----------|
| [`candaptor`](https://github.com/RensselaerMotorsport/candaptor) (local) | PySide6 + USB-serial CAN bridge; good transport reference for live CAN |
| [`mur-embedded/protocol/dbc/vendor/Cascadia_PM100DZ.dbc`](../../mur-embedded/protocol/dbc/vendor/Cascadia_PM100DZ.dbc) | Reconstructed PM100DZ DBC; **conflicts with official RMS DBC on M170 layout** — do not treat as authoritative |

---

## 1. PM100DX_Dashboard

**Repo:** [RensselaerMotorsport/PM100DX_Dashboard](https://github.com/RensselaerMotorsport/PM100DX_Dashboard)

### What it is

A small **Python + matplotlib** post-processing viewer for **logged serial telemetry**, not a live CAN dashboard.

| Aspect | Detail |
|--------|--------|
| Language | Python 3.12 |
| GUI | matplotlib (`pyplot`, 2×2 subplots, Stop button) |
| Dependencies | `matplotlib`, `pandas`, `numpy` (no `requirements.txt` in repo) |
| Entry point | [`main.py`](https://github.com/RensselaerMotorsport/PM100DX_Dashboard/blob/main/main.py) |
| Data file | `capture.txt` (and `Archive/Test *.txt`) |

### How data is obtained

**Transport: log file replay only.**

- Input is a **space-separated hex text log** exported from **RealTerm** while the official **RMS GUI** streams inverter parameters over **USB serial (COM port)**.
- `main.py` re-reads the entire file in a loop (`plt.pause(500)`), so it is neither live nor incremental.
- No SocketCAN, no python-can, no UDP, no direct inverter connection.

Capture format (header + rows):

```
Power_On_Lo_Word Accel Torque_Feedback Torque_Command DC_Voltage DC_Current Motor_Speed ...
F99F 0005 FFF9 0000 0004 0000 0000 0000 ...
```

- Row 1: column names (matches RMS GUI monitored-parameter names, abbreviated).
- Row 2: skipped (`LIM = 3` skips first 3 lines — row 2 appears to be a sentinel `00 0000 ...`).
- 20 hex fields per row; column 0 is power-on timer low word (÷3 → ms timestamp per code comment).

### What it monitors (plotted vs parsed)

| Signal | Column | Scale in code | Plotted? |
|--------|--------|---------------|----------|
| Time | 0 | ÷3 ms | x-axis index |
| Accel pot | 1 | ÷100 V | Yes (ax2) |
| Torque feedback | 2 | ÷10 Nm, signed | Yes (ax1) |
| Torque command | 3 | ÷10 Nm | Parsed, not plotted |
| DC bus voltage | 4 | ÷10 V | Title only (ax3) |
| DC bus current | 5 | ÷10 A | Parsed, not plotted |
| Motor speed | 6 | RPM, signed | Yes (ax1) |
| Flux weakening | 7 | ÷10 A | Parsed |
| Motor voltage (peak) | 8 | ÷10 V | Parsed |
| Iq command/feedback | 9–10 | ÷10 A, signed | Parsed |
| Id command/feedback | 11–12 | ÷10 A, signed | Parsed |
| Modulation index | 13 | ÷10000 | Parsed |
| Inverter (module) temp | 14 | ÷10 °C | Commented out |
| Motor temp | 15 | ÷10 °C | Parsed |
| Run fault lo / hi | 16–17 | raw hex | **Prints "FAULT" if hi ≠ 0** |
| Torque shudder | 18 | ÷10 Nm | Parsed |
| Brake pot | 18 | ÷100 V | **Bug: same column as shudder** |

Derived: output power `|FT × speed × 2π/60|`, current magnitude, apparent power — computed but not all plotted.

### CAN / decode artifacts

**None in this repo.** Scaling and column order are hard-coded in `main.py`; they align with RMS `defsyms` naming but there is no DBC or YAML.

### UX patterns

**Reuse conceptually:**
- Signed 16-bit normalization (`norm()`: values > 32766/scale wrap by subtracting 65535/scale).
- Focus on speed, torque, accel, DCV, output power for dyno/bench review.
- Fault hi word as a coarse alarm.

**Avoid:**
- Re-reading whole log file every 500 ms.
- Overloading one column (shudder vs brake).
- Raw fault words with no bit decode (only prints when hi ≠ 0).
- No VSM state, relay status, or named faults.
- Matplotlib as a live monitor (no threading, no transport abstraction).

---

## 2. RMS-Software (PM100 / GUI / CAN Tools)

**Repo:** [RensselaerMotorsport/RMS-Software](https://github.com/RensselaerMotorsport/RMS-Software) (vendor bundle: firmware, docs, closed GUI, DBCs, flash tools)

### What it is

Official **Cascadia Motion / Rensselaer Motorsport** software distribution. The **live dashboard** is a **Windows binary**, not source code.

| Component | Path | Role |
|-----------|------|------|
| RMS GUI | [`PM100/GUI/RMS GUI 148.exe`](https://github.com/RensselaerMotorsport/RMS-Software/tree/main/PM100/GUI) | Primary live monitor + parameter tool |
| Parameter map | [`PM100/GUI/defsyms_20231107_G3.txt`](https://github.com/RensselaerMotorsport/RMS-Software/blob/main/PM100/GUI/defsyms_20231107_G3.txt) | EEPROM + monitored parameter addresses |
| Waveform logs | `PM100/GUI/WLD_*.csv`, `4-26-24_HV_Test_Bench.txt` | Exported snapshots / time series |
| CAN DBC (PM100DX) | [`Tools/CAN Tools/PM and RM series DBC files/20210505 RMS PM and RM CAN DB.dbc`](https://github.com/RensselaerMotorsport/RMS-Software/blob/main/Tools/CAN%20Tools/PM%20and%20RM%20series%20DBC%20files/20210505%20RMS%20PM%20and%20RM%20CAN%20DB.dbc) | **Authoritative 11-bit PM100 CAN decode** |
| CAN DBC (Gen5 / iM) | `Tools/CAN Tools/CM and Gen5 control card DBC files/`, `iM225.../` | Newer hardware variants, J1939 offset variants |
| Flash / EEPROM | `Tools/C2000Prog/`, GUI + param messages M193/M194 | **Note for later — do not implement in read-only monitor** |
| RealTerm | `Tools/RealTerm/` | Serial capture helper used with GUI |
| Documentation | `PM100/Documentation/*.pdf` | CAN protocol, user manual, diag data, calibration |

### How live data is obtained

**Primary transport: USB serial (COM port) proprietary parameter protocol.**

Evidence: waveform exports include `# Com Port : com3` ([`WLD_100DX_20240505_001623.csv`](https://github.com/RensselaerMotorsport/RMS-Software/blob/main/PM100/GUI/WLD_100DX_20240505_001623.csv)).

The GUI reads/writes **parameter addresses** defined in `defsyms_*.txt` (e.g. `VSM_State @ 0x0093`, `Feedback_Speed_(RPM) @ 0x0097`). This is **parallel to but not the same as** listening on CAN.

**Secondary / bus-side:** When the inverter is on CAN, telemetry uses messages in the DBC (IDs 0xA0–0xB0, 0xC0–0xC2, etc.). The GUI bundle includes DBCs for Vector/CAN tools; the closed GUI may also reflect CAN-reflected parameters internally, but the captured team workflow (RealTerm → PM100DX_Dashboard) is **serial streaming**.

**Not used in these repos:** SocketCAN scripts, python-can, UDP telemetry, or open-source GUI code.

### Libraries / stack

| Layer | Stack |
|-------|-------|
| RMS GUI | Closed Windows `.exe` (+ legacy `gtk+-2.8.9-setup-1.exe` in Tools) |
| CAN tooling | Vector DBC format; compatible with PCAN, CANalyzer, etc. |
| Flash | TI C2000Prog (`C2Prog`, `C2oooProg`) |
| Team log analysis | RealTerm + PM100DX matplotlib script |

### What the RMS GUI monitors (from defsyms + sample exports)

**VSM / state:** `VSM_State`, `Inverter_Mode`, `Inverter_Enable`, `Vehicle_Direction`, DIN1–8, relay outputs, precharge/main contactor status, discharge state.

**Motion:** commanded/feedback speed & torque, torque shudder, modulation index, IQ/ID (debug group), flux terms.

**Electrical:** DC voltage/current filtered, phase currents, Vab/Vbc, over-current/over-voltage SW limits.

**Thermal:** module A/B/C, PCB, gate drivers, RTDs, motor temp, oil temp/pressure.

**Faults (GUI parameter space):** `Last_Run_Fault`, `CAN_Faults`, `Limit_Flags`, fault output pins — **not the same as decoding M171 bitfields in the UI samples reviewed**.

**CAN bus (when using DBC decode):** full message set in [`20210505 RMS PM and RM CAN DB.dbc`](https://github.com/RensselaerMotorsport/RMS-Software/blob/main/Tools/CAN%20Tools/PM%20and%20RM%20series%20DBC%20files/20210505%20RMS%20PM%20and%20RM%20CAN%20DB.dbc) — temperatures, currents, voltages, internal states, fault words, fast torque/speed frame, BMS limit, U2C DCDC, diag buffer M175, EEPROM param M193/M194.

Sample WLD snapshot ([`WLD_100DX_20240505_001623.csv`](https://github.com/RensselaerMotorsport/RMS-Software/blob/main/PM100/GUI/WLD_100DX_20240505_001623.csv)): `VSM_State=4` (wait), `VSM_Accel_Filtered=5`, DIN brake on, DC V ×10 = 3 (0.3 V filtered — likely precharge idle), many debug currents/flux at zero.

### Telemetry rates

**CAN (from DBC `GenMsgCycleTime`, ms):**

| Rate | Messages |
|------|----------|
| **3** | M176 Fast Info (when enabled via EEPROM `CAN_ACTIVE_MSGS` hi word 0xFFFE) |
| **5** | M192 Command (VCU → inverter) |
| **10** | M165–M168, M163–M164, M172 torque/timer |
| **100** | M160–M162 temps, M170 internal states, M171 faults, M169 ref voltages |

Comments: power-on timer in M172 updates every **3 ms**; default fast message period **3 ms**; slow messages **100 ms** unless overridden by `CAN_Fast_Msg_Rate_EEPROM` / `CAN_Slow_Msg_Rate_EEPROM` ([`defsyms_20231107_G3.txt`](https://github.com/RensselaerMotorsport/RMS-Software/blob/main/PM100/GUI/defsyms_20231107_G3.txt)).

**Serial stream (RealTerm captures):** roughly **50–70 ms** between rows (inferred from power-on timer deltas in [`PM100DX_Dashboard/capture.txt`](https://github.com/RensselaerMotorsport/PM100DX_Dashboard/blob/main/capture.txt)); slower than CAN fast frame.

### EEPROM / flashing / parameter tools (future, isolated)

| Tool | Purpose |
|------|---------|
| RMS GUI | Read/write EEPROM parameters, run commands, waveform log export |
| M193 / M194 CAN | Parameter read/write on bus (addresses 100–499) |
| `defsyms_*.txt` | Parameter address + type map |
| C2000Prog | Control-card / inverter firmware flash |
| Diagnostic data | M175 + [`Download Diagnostic Data`](https://github.com/RensselaerMotorsport/RMS-Software/tree/main/PM100/Documentation/Download%20Diagnostic%20Data) viewer |

### UX patterns (RMS GUI + artifacts)

**Worth reusing:**
- Grouping: VSM/IO, motion, electrical, thermal, faults, CAN status.
- VSM state as a first-class indicator (numeric in exports — names come from DBC `VAL_` tables).
- Waveform log export for post-run review.
- Explicit firmware/hardware metadata in log headers.

**Avoid / improve:**
- Closed Windows-only GUI for a Linux/macOS bench setup.
- Fault words shown as hex (`Last_Run_Fault`) without bit names in exported CSVs.
- Dual path confusion (serial parameters vs CAN frames) without documenting which path a view uses.
- Gen2 vs Gen3 parameter sheets (`defsyms_*_G2.txt` vs `_G3.txt`) — pick hardware-matched map.

---

## Side-by-side comparison

| | PM100DX_Dashboard | RMS GUI + CAN DBC |
|--|-------------------|-------------------|
| **Live?** | No (file replay) | Yes (serial to inverter) |
| **Transport** | RealTerm text log | USB serial COM; CAN on vehicle bus |
| **Decode source** | Hard-coded in `main.py` | `defsyms` (serial) + DBC (CAN) |
| **VSM names** | Not shown | In DBC; numeric only in CSV exports |
| **Fault decode** | Hi word ≠ 0 → print | Hex params; DBC says "see user manual" per bit |
| **Graphs** | Speed, torque, accel, power | Full GUI (unknown widgets); WLD CSV export |
| **Write path** | None | EEPROM, commands, flash tools |

---

## What to reuse for `inverter-monitor`

1. **CAN decode:** [`20210505 RMS PM and RM CAN DB.dbc`](https://github.com/RensselaerMotorsport/RMS-Software/blob/main/Tools/CAN%20Tools/PM%20and%20RM%20series%20DBC%20files/20210505%20RMS%20PM%20and%20RM%20CAN%20DB.dbc) as primary; check Gen5/iM DBC if hardware differs.
2. **Enums:** VSM, inverter state, discharge state from DBC `VAL_` entries → [`data/reference_decode.yaml`](../data/reference_decode.yaml).
3. **Scaling/sign:** PM100DX `norm()` rules for signed 16-bit fields.
4. **Transport options:** python-can SocketCAN + optional [`candaptor`](../../candaptor) USB bridge (already PySide6).
5. **Log replay:** ASC/BLF/CSV CAN logs **and** RealTerm serial format for regression against `capture.txt`.
6. **Parameter tooling boundary:** keep M193/M194 / defsyms behind a separate write-capable module; default read-only CAN subscribe only.

---

## Gaps neither dashboard fills well

- **Named fault bits** for M171 Post/Run fault lo/hi — now in [`data/faults.yaml`](../data/faults.yaml) / [`data/reference_decode.yaml`](../data/reference_decode.yaml) from Software User Manual V3.6.
- **Live CAN monitor** with VSM description text and relay/limit flags in one view.
- **Cross-platform** Python/Qt tool integrated with team CANdaptor stack.
- **M170 limit flags** present in newer Gen5 DBC (hot spot, coolant derating, stall burst) but absent from 2021 PM100DX DBC — verify against actual firmware.
- **CAN ID offset / J1939** variants (EEPROM `CAN_ID_Offset`, extended ID DBCs) — must configure per car.
