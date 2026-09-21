# Agent notes

## UX (high priority)

This UI is used by people who should not need to know CAN IDs, Memory View addresses, or what a watch list is. Avoiding confusion from non-technical users is a **high priority** — on par with decode correctness.

- A dash, hollow relay, or grey chip must not look like “the car is idle / everything is off” when the app simply is not reading that signal.
- RS232 and CAN are different feeds. If the current source has the same quantity under another name, show it. Do not leave Overview / Graphs / the status strip blank because the widget is hardcoded to the other transport.
- Do not require a user to open Symbols and add watches just to make the home screen work. The default RS232 poll set should cover what Overview, Faults, and the status strip already display.
- Prefer a short plain-language reason (“not available over RS232 — use CAN”) over an unexplained `—`.
- Prefer **one Overview that adapts to the source** (same cards, CAN and Memory View names; hide what this source cannot show). Split into two pages only when the *job* is different — live telemetry vs EEPROM programming — not because the transport names differ.
- Tabs may swap the RS232 poll set in the background so Overview, Faults, Graphs, and the status strip stay fresh without depending on the Symbols list. Keep the user’s Symbols watch list intact and put it back on the wire when they return to that tab — Symbols is a manual monitor, not the place that configures other pages. Offer a way to reload the default watch list.

When in doubt, ask: would a teammate who has never seen `defsyms` think the inverter is dead, or that the app is broken?

## CAN health (Faults page + status strip)

The inverter reports how its own CAN module is doing in two RAM shadow registers that you read with the ordinary `rm` protocol (they are **not** CAN broadcast frames and not in the 0x0A0–0x0B1 broadcast catalog):

| Item | Address | Meaning |
|------|---------|---------|
| `CAN_Status` | **0x00C8** | Live shadow of the CAN module status register (3 ms) |
| `CAN_Faults` | **0x00C9** | Sticky shadow of the CAN fault register — bits stay readable until Clear Faults |
| `CAN_Tx_Error_Counter` | **0x00CC** | Send errors, wraps at 255. 96 = warning, 128 = error-passive, 256 = bus-off |
| `CAN_Rx_Error_Counter` | **0x00CD** | Receive errors, max 127, counts down per good frame |
| `CAN_Tx_Error_Counter_(Max)` | **0x008B** | Highest Tx count seen — a post-run witness |

Bit maps and severities live in `data/can_status.yaml` (source: CAN Protocol Rev 6.3 §1.2 pp. 10–13, **Gen 3 only**). The Gen 5/CM-only §1.3 watch items (`CAN_Status_Bus_Off` etc.) are not this hardware and are not polled.

Rules:

* **Bus Off** (0x0080) is a red fault; **Error Warning** (0x0020), **Error Passive** (0x0040), any latched warning bit in `CAN_Faults` (0x0001–0x0020 except SA1), or a counter ≥ 96 is an orange `CAN degraded`.
* **Stuck At Dominant 1** (0x0008 in `CAN_Faults`) sets on every power-up by design — annotate it when other trouble exists but never trigger on it alone.
* If the current feed has no `MemoryView.*` signals (e.g. CAN source), the level is unknown and the UI stays quiet instead of showing a false CAN problem. Memory View running but registers not yet polled → “No fresh CAN status reading yet.”
