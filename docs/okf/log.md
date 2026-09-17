# PM100DX Bundle Update Log

## 2026-09-17
* **Update**: Expanded `inverter/memory-view.md` with the full reverse-engineered
  RS232 findings (USBPcap `yuh/yuh2/yuh3` framing, checksum, connect sequence,
  watch-list timeline, RAM/EEPROM write captures) and how the monitor implements
  them (`MemoryPoller`/`WatchList`, fault-word resolution of 0x0057–0x005A,
  Clear-Faults-only `wm` contract). Corrected `monitor/readout-mapping.md`
  (`rm` polls + Clear Faults `wm`, not `rm`-only).
* **Update**: Documented VSM 4 in CAN mode as "waiting for a valid command
  sequence" (Disable→Enable+torque, derived from the inert-inputs rule plus
  the lockout/timeout/sequence-example sections — flagged as synthesis, not a
  vendor quote) and skewed `vsm.md`, `command-message.md`,
  `internal-states.md`, and `readout-mapping.md` toward CAN mode, the bench's
  primary mode.
* **Update**: UI carries two VSM description sets (`data/vsm_states.yaml`
  `can_*` fields, `VsmState.text()`): strip, Overview detail, and States tab
  follow live command mode (M170 bit → `0x011B` EEPROM → CAN default).
  and `Software User Manual (V3_6) For Inverter.pdf` (2021-01-14), superseding
  the partial `docs/pdf-extract-notes.md`. Added full broadcast catalog
  (0x0A0–0x0B1), command/parameter byte layouts, 64-fault map, VSM/inverter
  states, SCI + Memory View serial protocols, EEPROM map, and monitor mapping.
