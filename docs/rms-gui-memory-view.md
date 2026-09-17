# RMS GUI Memory View protocol

Captured on Windows 10 through an ADAM-4562 (Prolific PL2303) while RMS GUI had the COM port. USBPcap files: `yuh.pcapng` (connect + default poll), `yuh2.pcapng` (watch list add/remove), `yuh3.pcapng` (RAM write + EEPROM commit).

This is **not** the SCI 20-word ASCII broadcast. Opening Memory View switches the inverter onto this request/response grammar. Addresses are the `defsyms` Memory View map in `data/defsyms.yaml`.

**Not an EEPROM write feature.** The monitor can **search and watch** symbols (Symbols tab) and poll them with `rm` via **RS232**. Writes (`wm`, addresses `0x0000`/`0x0001`/`0x0002`) stay documented only — do not wire them into the monitor.

## Framing

ASCII, CR-terminated commands, LF+CR-terminated read replies. 16-bit address and 16-bit value as 4 hex digits. Two hex checksum digits. GUI uses lowercase on TX; inverter replies with uppercase.

| Direction | Form | Example |
|-----------|------|---------|
| Host read | `rmAAAACC\r` | `rm009355\r` |
| Inverter read reply | `*AAAA=VVVVCC\n\r` | `*0093=000409\n\r` → value `0x0004` |
| Host write | `wmAAAA=VVVVCC\r` | `wm0117=000551\r` |
| Inverter write reply | `RAE` | success ACK; no value |

Checksum is the 8-bit two’s complement of the ASCII bytes **before** the checksum digits:

```python
def checksum(prefix: str) -> str:
    return f"{(-sum(prefix.encode('ascii'))) & 0xFF:02x}"

# read  VSM_State (0x0093)
# checksum("rm0093") == "55"  →  rm009355\r
# write DC_UnderVolt_Thresh = 5
# checksum("wm0117=0005") == "51"  →  wm0117=000551\r
```

Same rule for replies: `checksum("*0093=0004")` matches the last two characters of `*0093=000409`.

No subscribe, stream-on, or watch-list opcode exists. The GUI’s watch list **is** the set of `rm` addresses in the current round-robin.

## Connect (yuh, yuh2, yuh3)

Every session starts the same way:

1. Retry `rm0050` (commented defsyms `#Code_Version_YYYY`) until it answers. Observed `0x2022`.
2. Read `#Code_Version_MMDD` `0x0051` = `0x1118` (18 Nov) and `#SW_Version` `0x0052` = `0x204C`. Matches `defsyms_20221118_G3.txt`.
3. Walk ~100 EEPROM / info addresses once (serial number, motor type, CAN EEPROM, pedal maps, …).
4. Sit in a **status loop**: `0x0050`, `0x0058`, `0x0057`, `0x005A`, `0x0059`.

`0x0057`–`0x005A` are not in the G3 defsyms file. In these captures they always read `0`. Treat them as GUI heartbeat / fault-word slots until a capture names them.

`0x011C` is also unmapped; GUI reads it on connect (`0x5B9F`).

## Watch list (yuh2)

Adding a graph/watch symbol means that address starts appearing in the loop next to the status words. Removing it means those `rm`s simply stop. No extra command.

yuh2 timeline (after the EEPROM dump):

| Order | Address | Symbol | What happened |
|-------|---------|--------|----------------|
| add | `0x0073` | `Sin_corr_(V)_x_100` | Polled ~23 times, then **removed** |
| add | `0x0099` | `Feedback_Torque_(Nm)_x_10` | Stayed until end of capture |
| add | `0x0098` | `Commanded_Torque_(Nm)_x_10` | Stayed |
| add | `0x0093` | `VSM_State` | Stayed; value `4` (`VSM_Wait`) |
| remove | `0x0073` | `Sin_corr_(V)_x_100` | Dropped from the round-robin; no unsubscribe frame |
| add | `0x0094` | `Inverter_Enable` | Stayed; value `0` |

End-of-capture loop:

```text
0x0050, 0x0058, 0x0057, 0x005A, 0x0059,
0x0099, 0x0098, 0x0093, 0x0094
```

A later Memory View client should treat “watch X” as “include `rm` of X in the poll set” and “unwatch X” as “omit it”. Do not send `wm` for that.

## Writes (yuh2, yuh3) — document only

Not a product feature. Observed so we do not confuse it with watch-list traffic.

### RAM write

`wmAAAA=VVVV` then `RAE`, then the GUI often `rm`s the same address.

- yuh2: `wm0002=0000` twice. `0x0002` is not in defsyms. Immediate readback `0`. Not added to the watch loop (only those two readbacks).
- yuh3: `wm0117=0000` five times (`DC_UnderVolt_Thresh_EEPROM`, already 0), then `wm0117=0005`. Readback became **5** (`0.5 V` at ×10). That is a **RAM** change: EEPROM state stayed `5`.

### EEPROM commit

Near the end of yuh3, after the RAM value was 5:

```text
wm0000=5a0f
RAE
wm0001=0059
RAE
rm0056  →  EEprom_State  5 → 7
```

`0x5A0F` / `0x0059` look like a two-word save/unlock, not user parameters. Immediately afterwards several EEPROM reads returned **zero** (serial number `0x0113` went `0x0665` → `0`, and `0x0117` read back as **0** again). Capture ended with `EEprom_State = 7`. Likely busy/reload, or the save did not keep the RAM value — do not treat this as a known-good flash sequence.

Do not implement `wm`, `0x0000`, or `0x0001` in the monitor.

## How this sits next to SCI

| | SCI broadcast | Memory View (this doc) |
|--|---------------|------------------------|
| Who talks | Inverter alone, ~20 hex words / line | GUI polls; inverter answers |
| VSM | Not in the 20-word row | `rm0093` |
| EEPROM map | No | `defsyms.yaml` addresses |
| Port | Same ADAM COM, 57600 8N1 in practice | Exclusive with RMS GUI |

The read-only app today listens to SCI or CAN only. A future Memory View source would open the port itself, send `rm` for a chosen watch list, and never send `wm`.
