---
type: Serial Protocol Reference
title: Memory View RS232 protocol, reverse-engineered (rm/wm)
description: USBPcap-derived request/response grammar, checksum, session flow, watch-list and write findings, and how the monitor implements it.
tags: [serial, memory-view, rms-gui, rs232, reverse-engineering, pm100dx]
status: stable
generated: { by: cursor-agent/muse-spark-1.3, at: 2026-09-17T00:00:00Z }
sources:
  - id: memview-captures
    resource: ../../rms-gui-memory-view.md
    title: RMS GUI Memory View protocol notes (USBPcap yuh/yuh2/yuh3/yuh4 via ADAM-4562)
  - id: sw-manual
    resource: ../../Source Documentation/Software User Manual (V3_6) For Inverter.pdf
    title: Cascadia Motion Software User Manual Rev 3.6 (2021-01-14)
---

# Memory View protocol (reverse-engineered)

Opening Memory View moves the inverter off the [SCI broadcast](sci-serial.md)
onto this poll/response grammar over the same COM port (exclusive with RMS
GUI). Addresses are the `defsyms` map ([EEPROM guide](eeprom.md),
`data/defsyms.yaml`). Derived from USBPcap of RMS GUI on Windows 10 through
an ADAM-4562 (Prolific PL2303): `yuh.pcapng` (connect + default poll),
`yuh2.pcapng` (watch add/remove), `yuh3.pcapng` (RAM write + EEPROM
commit), `yuh4 (1).pcapng` (Memory Values Gamma −8/−10).[^memview-captures]

## Framing

ASCII. Commands end CR (`\r`); read replies end LF+CR (`\n\r`). Address and
value are 4 hex digits each plus 2 checksum digits. GUI transmits lowercase;
the inverter replies uppercase.[^memview-captures]

| Direction | Form | Example |
|-----------|------|---------|
| Host read | `rmAAAACC\r` | `rm009355\r` (VSM_State 0x0093) |
| Read reply | `*AAAA=VVVVCC\n\r` | `*0093=000409\n\r` → value `0x0004` |
| Host write | `wmAAAA=VVVVCC\r` | `wm0117=000551\r` (DC_UnderVolt_Thresh = 5) |
| Write ACK | `RAE` | success, no value |

Checksum = 8-bit two's complement of the ASCII bytes **before** the checksum
digits, both directions — verify a reply the same way (`checksum("*0093=0004")`
must equal its trailing `09`); drop mismatches.[^memview-captures]

```python
def checksum(prefix: str) -> str:
    return f"{(-sum(prefix.encode('ascii'))) & 0xFF:02x}"

# checksum("rm0093") == "55"      ->  rm009355\r
# checksum("wm0117=0005") == "51" ->  wm0117=000551\r
```

In code: `memory_map.read_command` / `write_command` build the frames,
`parse_read_reply` enforces the `*AAAA=VVVVCC` shape **and** the checksum
before a reply is accepted.[^memview-captures]

## Line settings

57600 8N1, no flow control (no XON/XOFF, RTS/CTS, DSR/DTR), 50 ms read
timeout, 200 ms write timeout with a 300 ms wait for `RAE` — same
`SerialMemoryViewSource` settings as the SCI listener, one port at a
time.[^memview-captures]

## Connect sequence (all three captures)

1. Retry `rm0050` (`#Code_Version_YYYY`) until it answers — observed
   `0x2022`.[^memview-captures]
2. Read `0x0051` (`#Code_Version_MMDD` = `0x1118`, 18 Nov) and `0x0052`
   (`#SW_Version` = `0x204C`); matches `defsyms_20221118_G3.txt`.[^memview-captures]
3. Walk ~100 EEPROM/info addresses once (serial number, motor type, CAN
   EEPROM, pedal maps, …). The monitor reproduces this as a **one-shot dump**
   interleaved with the live round-robin (`MemoryPoller`: one dump address,
   then one watch address, alternating).[^memview-captures]
4. Settle into the status loop `0x0050, 0x0058, 0x0057, 0x005A, 0x0059`.[^memview-captures]

`0x0057`–`0x005A` are unmapped in the G3 defsyms and always read 0 in the
captures; the original note filed them as heartbeat/fault slots. They are now
resolved as the GUI's **POST/Run fault words** (Lo 0x0057, Hi 0x0058, Lo
0x0059, Hi 0x005A) — the monitor's default watch set and Check-Faults path
read them as such.[^memview-captures] `0x011C` is likewise unmapped; the GUI
reads it once on connect (`0x5B9F`).[^memview-captures]

## Watch list (yuh2) — no opcode

No subscribe/stream-on/watch command exists: the watch list **is** the set of
`rm` addresses in the round-robin. Adding a symbol starts its `rm`s; removing
stops them silently.[^memview-captures]

| Order | Address | Symbol | Outcome |
|-------|---------|--------|---------|
| add | `0x0073` | `Sin_corr_(V)_x_100` | Polled ~23×, then removed |
| add | `0x0099` | `Feedback_Torque_(Nm)_x_10` | Stayed |
| add | `0x0098` | `Commanded_Torque_(Nm)_x_10` | Stayed |
| add | `0x0093` | `VSM_State` | Stayed, value 4 (Wait) |
| remove | `0x0073` | `Sin_corr_(V)_x_100` | Dropped, no unsubscribe frame |
| add | `0x0094` | `Inverter_Enable` | Stayed, value 0 |

End-of-capture loop: `0x0050, 0x0058, 0x0057, 0x005A, 0x0059, 0x0099, 0x0098,
0x0093, 0x0094`.[^memview-captures] In code this is `WatchList.add/remove`
(membership only) + `MemoryPoller` round-robin; the monitor's default watches
are VSM 0x0093, enable 0x0094, mode 0x0092, and the four fault words above
(EEPROM symbols are snapshot/one-shot, never polled).[^memview-captures]

## Writes (yuh2, yuh3, yuh4 findings)

Recorded so watch traffic is never confused with write traffic.

* **RAM write**: `wmAAAA=VVVV` → `RAE`, often followed by `rm` of the same
  address. yuh2: `wm0002=0000` twice (`0x0002` unmapped in defsyms, readback
  0, never joined the loop). yuh3: `wm0117=0000` ×5 (`DC_UnderVolt_Thresh`,
  already 0) then `wm0117=0005` — readback became 5 (0.5 V at ×10), a **RAM
  only** change. `Gamma_Adjust_EEPROM` stayed `0xFFF8` (−8) the whole session;
  RAM Gamma Adjust `0x0010` was never polled or written in yuh3.[^memview-captures]
* **yuh4 (1)**: ADAM/Prolific bulk OUT ep2 / IN ep3, ~81 s, 5 `wm` / 5 `RAE`.
  Memory Values Gamma Adjust `0x0010`: `fff8` (−8) twice, `fff6` (−10) twice,
  `fff8` (−8) once. Readback matched. EEPROM dump at start: gamma EEPROM −8,
  delay EEPROM 50, DC undervolt 0, `EEprom_State` 5. No `wm0000`/`wm0001`, no
  VSM/enable poll (Memory Values tab). Original `yuh4.pcapng` is still USB
  mass-storage `USBC`/`USBS` — ignore it.[^memview-captures]
* **EEPROM commit**: `wm0000=5a0f` → `RAE`, `wm0001=0059` → `RAE`, then
  `EEprom_State` (0x0056) 5→7. Immediately afterwards **every** EEPROM read
  returned zero (serial `0x0113` `0x0665`→0, gamma EEPROM −8→0, `0x0117` 5→0).
  Capture ended at state 7. That 5→0 on DC undervolt is the same blank-read
  window, not a confirmed “program 0 and it stuck”. yuh3 never `rm`’d VSM
  `0x0093` / enable `0x0094` (EEPROM-tab dump only). Treat zeros while state
  is 7 as busy, not as a wipe.[^memview-captures]

## What the monitor sends

* `rm` polls for the watch list + one-shot EEPROM/info dump (above).
* `wm` is queued through `enqueue_write` and waits for `RAE`. Allowed today:
  **Clear Faults** `wm0002=0000` (Faults tab, confirmed); Calibration-tab RAM
  writes of `Resolver_Delay_Command` (`0x0005`) and `Gamma_Adjust_(Deg)_x_10`
  (`0x0010`); Calibration **Program EEPROM** copies those Memory Values into
  `0x0118` / `0x011A` then the yuh3 pair `wm0000=5a0f` / `wm0001=0059` (Wait,
  enable off, confirm). Other EEPROM parameters are not written.[^memview-captures]

## SCI vs Memory View

| | SCI broadcast | Memory View (this concept) |
|--|---------------|----------------------------|
| Who talks | Inverter alone, ~20 hex words/line | GUI polls, inverter answers |
| VSM | Absent from the row | `rm0093` |
| EEPROM map | No | `defsyms.yaml` addresses |
| Faults | Raw hi/lo words only | Named words 0x0057–0x005A + Check Faults |
| Port | Same COM, 57600 8N1 | Exclusive with RMS GUI |

[^memview-captures]: docs/rms-gui-memory-view.md; src/inverter_monitor/memory_map.py, serial_memory.py
[^sw-manual]: Software User Manual Rev 3.6 §§5–7
