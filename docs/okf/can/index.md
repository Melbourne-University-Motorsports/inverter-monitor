# CAN

* [Transport](transport.md) — CAN 2.0A/2.0B framing, baud, ID offset, J1939, rates
* [Data formats](data-formats.md) — per-signal scaling table
* [Broadcast catalog](broadcast-catalog.md) — 0x0A0–0x0AF, 0x0B0, 0x0B1 byte layouts
* [Internal states (0x0AA)](internal-states.md) — authoritative M170 bit map
* [Fault codes (0x0AB)](fault-codes.md) — 64 POST/RUN fault bits
* [CAN status registers](can-status.md) — CAN_Status 0x00C8 / CAN_Faults 0x00C9, error counters, Gen 5-only watch items
* [Command message (0x0C0)](command-message.md) — VCU→inverter control + safety
* [Parameter messages (0x0C1/0x0C2)](parameter-messages.md) — command + EEPROM addresses
* [Special modes](special-modes.md) — OBD2, Orion BMS, slave, rolling counter, diagnostics
