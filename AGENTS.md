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
