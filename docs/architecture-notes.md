# Architecture Notes: Python/Qt Read-Only PM100DX Live Monitor

Practical design for a cross-platform monitor that subscribes to inverter CAN traffic, decodes with team/vendor tables, and stays **read-only by default**. Implementation lives in `src/inverter_monitor/`.

---

## Goals

1. Live view of PM100DX telemetry on CAN (primary) with optional log replay.
2. Human-readable **VSM state**, **inverter state**, relay/limit flags, and **named faults** (when bit map is added).
3. Safe for HV bench: no accidental EEPROM writes or command frames on startup.
4. Share transport patterns with existing [`candaptor`](../../candaptor) work (PySide6, python-can).

Non-goals for v1: firmware flash, C2000Prog, RMS GUI **writes** (`wm`, EEPROM commit), command TX.

RMS GUI Memory View **reads** (`rm` / `*AAAA=VVVV`) are documented in [`rms-gui-memory-view.md`](rms-gui-memory-view.md) from USBPcap of RMS GUI. Not wired as a live source yet. Watch-list add/remove is just changing which addresses the GUI polls.

---

## Recommended stack

| Layer | Choice | Why |
|-------|--------|-----|
| UI framework | **PySide6** | Already used in `candaptor`; LGPL-friendly; good macOS/Linux/Windows support |
| Alternative | PyQt6 | Equivalent API; prefer PySide6 unless org standard says otherwise |
| CAN I/O | **python-can** | SocketCAN, PCAN, serial/USB bridges; ASC/BLF log replay built-in |
| Plotting | **pyqtgraph** | High-rate time series (M176 @ 3 ms, M165–168 @ 10 ms); lower CPU than Qt Charts for many curves |
| Alternative charts | Qt Charts (`PySide6.QtCharts`) | Fine for a few slow gauges; awkward for multi-channel oscilloscope-style views |
| Decode tables | **YAML** ([`data/reference_decode.yaml`](../data/reference_decode.yaml)) + optional **cantools** for DBC import | YAML for enums and app-curated signals; cantools to ingest full vendor DBC when needed |
| Config | TOML or YAML project profile | Bus type, channel, ID offset, DBC path, replay file |
| Packaging | `uv` + optional PyInstaller | Matches `candaptor` workflow |

**Why not matplotlib (PM100DX pattern)?** Fine for offline log review; poor fit for live multi-signal UI and thread-safe updates.

---

## Module split

```
inverter-monitor/
├── data/reference_decode.yaml    # enums, message catalog, conflicts
├── profiles/                     # per-car: can iface, id offset, dbc variant
└── src/inverter_monitor/
    ├── transport/                # CAN + replay backends
    ├── decode/                   # frame → signals
    ├── state/                    # thread-safe store + staleness
    ├── ui/                       # Qt widgets (read-only)
    └── write/                    # OPTIONAL: M193/M194 — not imported by default
```

### 1. `transport`

**Responsibility:** Produce a stream of `(timestamp, arbitration_id, data)` regardless of source.

| Backend | Implementation |
|---------|----------------|
| Live SocketCAN | `can.interface.Bus(bustype="socketcan", channel="can0")` |
| USB CANdaptor | Reuse `candaptor.CANdaptor` serial protocol or python-can slcan if bridged |
| PCAN / vector | python-can interfaces for bench laptops |
| Log replay | `can.LogReader` (ASC, BLF, CSV) or custom parser for RealTerm serial captures |

**Interface (conceptual):**

```python
class FrameSource(Protocol):
    def frames(self) -> Iterator[CanFrame]: ...
    def close(self) -> None: ...
```

- Run reader on a **background thread**; push into a bounded queue.
- Replay mode: configurable speed (`1.0×`, `max`, stepped); emit wall-clock or log timestamps.
- Apply **ID offset** from profile (EEPROM `CAN_ID_Offset`) before decode.

### 2. `decode`

**Responsibility:** Map raw frames to typed signals using YAML + optional DBC.

**Loading YAML/JSON:**

1. Load `reference_decode.yaml` at startup (PyYAML).
2. Build lookup: `can_id → message definition → signal extractors`.
3. For each signal: `(start_bit, length, endian, signed, factor, offset, enum)`.
4. Apply **signed 16-bit wrap** where DBC uses `@1-` and team scripts use PM100DX `norm()` rules.
5. Resolve enums to `{value, name, description}` for UI.

**Optional cantools path:**

```python
db = cantools.database.load_file("20210505 RMS PM and RM CAN DB.dbc")
msg = db.get_message_by_frame_id(arbitration_id)
decoded = msg.decode(data)
```

Use cantools for bring-up; export merged subset to YAML for stable, reviewable diffs. Keep YAML as **source of truth for enums and UI labels** (DBC `VAL_` strings are verbose and inconsistent across Gen5 vs PM).

**Fault decode:** Expand M171 words with `fault_words.bits` in [`data/reference_decode.yaml`](../data/reference_decode.yaml) (64 POST/RUN bits from Software User Manual V3.6). Full diagnostic text stays in [`data/faults.yaml`](../data/faults.yaml). Show raw hex beside the decoded active list.

### 3. `state` (store)

**Responsibility:** Single writer from transport thread; many readers on UI thread.

- Key: `(message_name, signal_name)` or flat dotted keys `M165.D2_Motor_Speed`.
- Store: `value`, `raw`, `unit`, `enum_label`, `last_seen_monotonic`, `update_count`.
- **Staleness:** compare age to DBC `cycle_ms × 3`; gray out or flag missing fast frames.
- **Aggregates:** derive power, |I|, limit-flag summary without recomputing in widgets.
- Thread safety: `queue.SimpleQueue` of decode updates → drain in Qt timer (~20–50 ms) or `QMutex` + snapshot copy.

**Do not** let widgets parse CAN directly.

### 4. `ui` (read-only)

**Responsibility:** Present state store; no transport/decode logic.

Suggested panels:

| Panel | Content | Update rate |
|-------|---------|-------------|
| Status bar | VSM name + description, inverter state, enable, command mode, discharge state | 100 ms class |
| Motion | Speed, torque cmd/fb, optional M176 fast duplicates | 10–50 ms redraw |
| Electrical | DC V/I, modulation, Iq/Id | 10 ms |
| Thermal | Module/PCB/motor temps | 100 ms |
| Faults | Active fault list + post/run words | on change + 100 ms |
| IO | Relays, DIN map (from M164/M170) | 100 ms |
| Trace | pyqtgraph selected signals | configurable history window |

Colors/alarms (reuse concepts, improve clarity):

- VSM **Blink_Fault_Code (7)** → red banner.
- Non-zero M171 → red fault panel with enumerated bits (when available).
- Stale fast frame → amber "M176 missing" if enabled in EEPROM but not seen.
- Limit flags on M170 (BMS torque, max speed, low speed) → yellow indicators.

### 5. `write` (isolated — future EEPROM / command mode)

**Not imported by default entry point.**

- Separate package or `inverter_monitor.write` gated by CLI flag `--enable-write` + env `INVERTER_MONITOR_ALLOW_WRITE=1`.
- Implements M193/M194 parameter read/write only; never auto-sent.
- Unit tests mock bus; integration tests require explicit hardware fixture marker.
- Read-only builds can omit module from PyInstaller spec.

This mirrors safety pattern: default CLI opens **subscribe-only** bus filters (no TX queue) unless write module loaded.

---

## Live CAN + log replay without hardware

| Mode | How |
|------|-----|
| ASC/BLF replay | python-can `LogReader` feeding same `FrameSource` interface |
| Team RealTerm log | Parser for 20-column hex format in YAML → synthesize pseudo-frames **or** separate "serial replay" decode path into same state store |
| Simulated bus | Script emits periodic frames from YAML definitions for UI dev |
| vcan | `tools/bench/can_up.sh` pattern from mur-embedded; `candapter` send in loopback |

**One code path:** transport produces frames; decode/state/UI identical for live and replay. UI shows "REPLAY" badge and log timeline scrubber when not live.

---

## Configuration profile example (future)

```yaml
# profiles/pm100dx_gen3.yaml
bus:
  interface: socketcan
  channel: can0
  bitrate: 500000
id_offset: 0x0A0      # EEPROM CAN_ID_Offset (Memory View 0x011D); this car is 0x00A0
extended_id: false
decode:
  primary: ../data/reference_decode.yaml
  dbc_fallback: "path/to/20210505 RMS PM and RM CAN DB.dbc"
fast_message_expected: true   # M176 enabled
```

---

## Data rates → UI budgeting

| Class | Period | Messages | UI treatment |
|-------|--------|----------|--------------|
| Fast | 3 ms | M176 | Ring buffer ~10 s; downsample for display if >60 FPS |
| Medium | 10 ms | M165–M168, M163–M164, M172, M173 | Primary traces |
| Slow | 100 ms | M160–M162, M170, M171, M169 | Labels/gauges; log on change |

Power-on timer (M172) increments every 3 ms — use for bus health, not as primary clock.

---

## Risks and jank to avoid

1. **Wrong DBC variant** — J1939 extended vs 11-bit, Gen5 vs 2021 PM, ID offset. Profile must be explicit; show raw ID in debug pane.
2. **mur-embedded reconstructed DBC** — M170 VSM at bit 56 is wrong vs official bit 0. Use RMS vendor DBC.
3. **Serial vs CAN confusion** — PM100DX_Dashboard columns are serial-stream fields, not CAN payloads. Do not feed RealTerm logs through CAN decode without a mapping layer.
4. **PM100DX column 18 bug** — shudder vs brake; validate against defsyms before copying scaling.
5. **Unsigned/signed mistakes** — torque, speed, currents use signed 16-bit with wrap; apply before scaling.
6. **TX on connect** — some adapters send config frames; keep read-only path subscribe-only.
7. **Fault hex without bits** — operators ignore `Run_Hi`; invest in manual bit map once.
8. **Matplotlib-style full file reload** — never block UI on I/O.
9. **Write leakage** — guard command message construction behind explicit module + double confirmation in UI.

---

## Suggested implementation order

1. Transport + replay (ASC + vcan smoke test).
2. YAML loader + decode for M170, M171, M165, M167, M172, M176.
3. State store + staleness.
4. Minimal Qt window: VSM banner, speed/torque/DCV, fault hex.
5. pyqtgraph traces for fast signals.
6. RealTerm serial replay adapter (regression vs `capture.txt`).
7. Fault bit map is already in YAML — wire named list + raw hex in the Faults tab.
8. Optional write module (out of scope until requested).

---

## Related local assets

- [`candaptor/candaptor/gui.py`](../../candaptor/candaptor/gui.py) — PySide6 CAN table UI, threading model, ID stats.
- [`mur-embedded/protocol/dbc/vendor/Cascadia_PM100DZ.dbc`](../../mur-embedded/protocol/dbc/vendor/Cascadia_PM100DZ.dbc) — cross-check only; prefer RMS DBC.
- Cloned research copies: `/tmp/rms-dashboard-research/PM100DX_Dashboard`, `/tmp/rms-dashboard-research/RMS-Software`.
