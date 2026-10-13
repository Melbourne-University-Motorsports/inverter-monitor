# Architecture Notes: PM100 Live Monitor & Configuration Tool

Design and architecture for the cross-platform telemetry monitor and parameter configuration tool for Cascadia Motion / Rinehart **PM100** series inverters (PM100, PM100DX, PM100DZ, etc.) over **RS232** (Memory View). Implementation lives in `src/inverter_monitor/`.

---

## Goals

1. **Live Serial Telemetry**: Live telemetry over **RS232** Memory View (`rm` round-robin polling).
2. **Comprehensive Diagnostics**: Human-readable **VSM state**, **inverter mode**, relay/limit flags, **64-bit POST/RUN active faults**, and communication/hardware status registers.
3. **Guarded Parameter & Calibration Writes**:
   - **Clear Faults**: Direct fault clearing command (`wm0002=0000`) over Memory View.
   - **Resolver Calibration**: Real-time RAM iteration of resolver Delay Command (`0x0005`) and Gamma Adjust (`0x0010`) via `wm`, with optional EEPROM commit (`0x0118`/`0x011A`).
   - **EEPROM Parameter Management**: Structured parameter tree from `defsyms`, engineering unit conversions, change staging, and safe **Push to Inverter** sequence.
4. **Safety-First Architecture**:
   - RS232 writes enforce interlocks (VSM Wait state 4 and Inverter Disabled 0) and explicit user confirmation dialogs before flashing.
5. **Cross-Platform & Modern Stack**: Runs seamlessly on macOS, Linux, and Windows using PySide6 and pyqtgraph.

---

## Technical Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| UI framework | **PySide6** (Qt 6) | Native cross-platform performance, rich widgets, LGPL license |
| Serial I/O | **pyserial** | Direct cross-platform serial communication (ADAM-4562, FTDI, Prolific) |
| Plotting | **pyqtgraph** | High-performance time series rendering for live telemetry |
| Symbol Definitions | **YAML** (`defsyms.yaml`, `vsm_states.yaml`, `faults.yaml`) | Human-readable, version-controlled definitions for memory symbols, faults, and states |
| Environment | **uv** | Fast, reproducible virtual environments and dependency management |

---

## Architecture & Module Split

```text
inverter-monitor/
├── data/                         # Symbol catalogs and definitions
│   ├── defsyms.yaml              # G3 Memory View addresses & parameter metadata
│   ├── vsm_states.yaml           # VSM and Inverter Mode descriptions
│   ├── faults.yaml               # Diagnostic explanations for POST/RUN faults
│   └── reference_decode.yaml     # Diagnostic bitfield definitions & legacy SCI map
└── src/inverter_monitor/
    ├── transport.py              # Frame abstractions and background FramePump
    ├── serial_memory.py          # RS232 Memory View client (rm/wm, RAE ACK, checksums)
    ├── serial_sci.py             # RS232 legacy 20-word ASCII broadcast listener
    ├── memory_map.py             # Memory symbol mapping, conversions, framing
    ├── store.py                  # Thread-safe telemetry store (InverterStore)
    ├── feed.py                   # Transport-independent signal feeding & status
    ├── calibration.py            # Resolver delay/gamma calibration state machine
    ├── simulate.py               # DemoSource synthetic traffic for offline use
    ├── cli.py                    # Command-line interface & argument parser
    └── ui/                       # PySide6 user interface
        ├── main_window.py        # Main window, transport lifecycle, status strip
        ├── overview.py           # Unified telemetry dashboard
        ├── faults.py             # Active fault decoding and Clear Faults
        ├── graphs.py             # Multi-signal pyqtgraph real-time charts
        ├── symbols.py            # Memory View symbol tree & custom watch list
        ├── eeprom.py             # Parameter editor, diff reviewer, Push to Inverter
        ├── calibration.py        # Resolver calibration UI & EEPROM commit
        ├── raw.py                # Raw frame monitor table
        └── states.py             # VSM & Inverter Mode state breakdown
```

### 1. Transport Layer (`transport.py`, `serial_memory.py`, `serial_sci.py`)

- **Frame Source Abstraction**: `FrameSource` produces frames:
  - `SerialMemoryViewSource`: Implements the reverse-engineered request/response protocol (`rm`/`wm`) at 57600 8N1. Background thread polls active watch addresses and processes write queues.
  - `SerialSCISource`: Passive listener for legacy 20-word serial broadcast.
  - `DemoSource`: Synthetic simulation generator for development without hardware.
- **Background FramePump**: Dedicated worker thread dispatches frames into a thread-safe `SimpleQueue`.

### 2. Protocol & Framing Layer (`memory_map.py`)

- **Memory View Framing**:
  - Request: `rmAAAACC\r` (where `CC` is two's complement checksum).
  - Response: `*AAAA=VVVVCC\n\r` verified against response checksum.
  - Write: `wmAAAA=VVVVCC\r` expecting `RAE` acknowledgment.

### 3. State Store (`store.py`, `feed.py`)

- **InverterStore**:
  - Centralized, thread-safe repository storing signal snapshots (`value`, `raw`, `unit`, `timestamp`, `update_count`).
  - Tracks signal staleness and connection health.

### 4. User Interface (`ui/`)

- **Status Strip**: Persistent top banner displaying current source, VSM state, inverter enable status, and active fault count.
- **Overview**: Real-time cards for vehicle dynamics (speed, torque cmd/feedback), electricals (DC voltage/current, AC currents), temperatures, and status flags.
- **Faults**:
  - Active POST and RUN faults decoded with plain-language root-cause explanations.
  - **Clear Faults** button issuing `wm0002=0000`.
- **Graphs**: Multi-signal time-series plotting using pyqtgraph with signal search and channel selection.
- **Symbols**: Memory View symbol inspection with manual watch list management.
- **EEPROM**:
  - Hierarchical parameter tree grouped by subsystem (Motor, System, Current, Voltage, Thermal, Accel, Speed, PID, etc.).
  - Cell editing with real-time range and unit validation.
  - Staged diff view highlighting unsaved changes.
  - Guarded **Push to Inverter** action with safety validation dialog.
- **Calibration**: Dedicated resolver calibration wizard allowing interactive tuning of Delay Command and Gamma Adjust in RAM, with optional permanent EEPROM programming.
- **Raw & States**: Frame inspection table and deep-dive state machine reference.

---

## Safety & Write Management

Writing to inverter memory on high-voltage test benches requires strict isolation and validation:

| Operation | Protocol | Target | Safety Preconditions & Safeguards |
|-----------|----------|--------|-----------------------------------|
| **Clear Faults** | `wm0002=0000` | RS232 RAM | Operator confirmation dialog. |
| **Resolver Tuning** | `wm0005=VVVV`, `wm0010=VVVV` | RS232 RAM | Real-time RAM iteration; values revert on power cycle unless committed. |
| **Calibration Commit** | `wm0118=VVVV`, `wm011A=VVVV` + commit pair | RS232 EEPROM | Requires explicit operator action in Calibration tab; commits delay and gamma. |
| **EEPROM Push** | `wmAAAA=VVVV` per word + commit pair (`wm0000=5a0f`, `wm0001=0059`) | RS232 EEPROM | **Interlocks enforced**: VSM must be in Wait (4) and Inverter Disabled (0). Full diff dialog shown for review before execution. Progress bar tracks per-word writes. |
