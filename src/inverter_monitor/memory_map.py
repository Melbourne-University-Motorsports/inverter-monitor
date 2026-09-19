from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from inverter_monitor.paths import data_dir

MEMORY_FRAME_ID = 0x7E1
# One address around the RS232 round-robin (status + Overview). 3× this is the stale window.
MEMORY_CYCLE_MS = 2500
DEFAULT_CAN_ID_OFFSET = 0x0A0
CAN_ID_OFFSET_ADDRESS = 0x011D
VSM_STATE_ADDRESS = 0x0093
INVERTER_MODE_ADDRESS = 0x0092
INVERTER_ENABLE_ADDRESS = 0x0094
INV_CMD_MODE_ADDRESS = 0x011B
# CAN module diagnostics (CAN Protocol Rev 6.3 §1.2, Gen 3 only). Shadow
# registers of the microcontroller CAN module, read over the same rm protocol.
CAN_STATUS_ADDRESS = 0x00C8
CAN_FAULTS_ADDRESS = 0x00C9
CAN_TX_ERROR_ADDRESS = 0x00CC
CAN_RX_ERROR_ADDRESS = 0x00CD
# Peak Tx error count — a post-run witness, readable from the Symbols tab rather
# than worth a permanent slot in the Faults round-robin.
CAN_TX_ERROR_MAX_ADDRESS = 0x008B

# RMS GUI default poll slots (yuh captures). Not in G3 defsyms; Check Faults reads these.
POST_FAULT_LO_ADDRESS = 0x0057
POST_FAULT_HI_ADDRESS = 0x0058
RUN_FAULT_LO_ADDRESS = 0x0059
RUN_FAULT_HI_ADDRESS = 0x005A
# GUI Command parameter immediately before Run_Command (0x0003). Captured wm0002=0000.
CLEAR_FAULTS_ADDRESS = 0x0002

FEEDBACK_SPEED_ADDRESS = 0x0097
COMMANDED_TORQUE_ADDRESS = 0x0098
FEEDBACK_TORQUE_ADDRESS = 0x0099
DC_VOLTAGE_ADDRESS = 0x00AD
DC_CURRENT_ADDRESS = 0x00AF
MOTOR_TEMP_ADDRESS = 0x00A3
MOD_A_TEMP_ADDRESS = 0x0091
DISCHARGE_STATE_ADDRESS = 0x0087
DIN_ADDRESSES = (0x009B, 0x009C, 0x009A, 0x00B8, 0x00B1, 0x00B2, 0x005B, 0x005E)
RLY_ADDRESSES = (0x00B4, 0x00B5, 0x00B3, 0x00BB)

# Always-visible strip + Faults / States. Other tabs overlay a larger set.
STATUS_WATCH_ADDRESSES = (
    VSM_STATE_ADDRESS,
    INVERTER_ENABLE_ADDRESS,
    INVERTER_MODE_ADDRESS,
    INV_CMD_MODE_ADDRESS,
    POST_FAULT_LO_ADDRESS,
    POST_FAULT_HI_ADDRESS,
    RUN_FAULT_LO_ADDRESS,
    RUN_FAULT_HI_ADDRESS,
)

# Faults tab overlay: the CAN module's own status/fault words and error counters
# (Gen 3 CAN Protocol §1.2). Kept off STATUS_WATCH_ADDRESSES so the always-on
# status loop stays short — the Faults tab is where CAN health is read.
CAN_STATUS_WATCH_ADDRESSES = (
    CAN_STATUS_ADDRESS,
    CAN_FAULTS_ADDRESS,
    CAN_TX_ERROR_ADDRESS,
    CAN_RX_ERROR_ADDRESS,
)

# Overview / Raw, and the Symbols “reload default” list.
# Graphs overlays the selected traces; EEPROM is a one-shot dump on connect.
DEFAULT_WATCH_ADDRESSES = (
    VSM_STATE_ADDRESS,
    INVERTER_ENABLE_ADDRESS,
    INVERTER_MODE_ADDRESS,
    POST_FAULT_LO_ADDRESS,
    POST_FAULT_HI_ADDRESS,
    RUN_FAULT_LO_ADDRESS,
    RUN_FAULT_HI_ADDRESS,
    FEEDBACK_SPEED_ADDRESS,
    COMMANDED_TORQUE_ADDRESS,
    FEEDBACK_TORQUE_ADDRESS,
    DC_VOLTAGE_ADDRESS,
    DC_CURRENT_ADDRESS,
    MOTOR_TEMP_ADDRESS,
    MOD_A_TEMP_ADDRESS,
    DISCHARGE_STATE_ADDRESS,
    *DIN_ADDRESSES,
    *RLY_ADDRESSES,
)

# RMS GUI EEPROM page ids (defsyms column 6), then Memory View section names.
EEPROM_GROUP_NAMES = {
    0: "Motor / Resolver",
    1: "Control",
    2: "Current",
    3: "Voltage",
    5: "Torque",
    6: "Identity",
    7: "Speed",
    8: "CAN",
    9: "Thermal",
    10: "Accel",
    11: "Brake",
    12: "Shudder",
}

SECTION_GROUP_NAMES = {
    "EEPROM Parameters": "",
    "Monitored Parameters - Resolver/Encoder": "Resolver",
    "Monitored Parameters - Temperatures": "Thermal",
    "Monitored Parameters - Torque & Speed": "Torque / Speed",
    "Monitored Parameters - DC Voltage & Current": "DC",
    "Monitored Parameters - VSM IOs": "VSM / IO",
    "Monitored Parameters - EEPROM Data": "EEPROM status",
    "Monitored Parameters - Timers & Counters": "Timers",
    "Info Parameters - factory programmed, DO NOT attempt to modify": "Firmware",
    "Debug Parameters - not displayed on GUI": "Debug",
    "Analog Input Raw ADC Values": "Analog",
    "GUI Command Parameters": "Commands",
}

EEPROM_GROUP_ORDER = (
    "Identity",
    "Firmware",
    "Motor / Resolver",
    "Control",
    "CAN",
    "Current",
    "Voltage",
    "Torque",
    "Speed",
    "Thermal",
    "Accel",
    "Brake",
    "Shudder",
    "EEPROM status",
)

LIVE_GROUP_ORDER = (
    "Resolver",
    "Torque / Speed",
    "DC",
    "Thermal",
    "VSM / IO",
    "Timers",
    "Debug",
    "Analog",
    "Commands",
)

_SCALE_SUFFIX = re.compile(r"_x_(\d+)\s*$", re.IGNORECASE)
_UNIT_PARENS = re.compile(r"\(([^)]+)\)")

_EXTRA_INFO = (
    ("Code_Version_YYYY", 0x0050, "hex"),
    ("Code_Version_MMDD", 0x0051, "hex"),
    ("SW_Version", 0x0052, "hex"),
)

_EXTRA_FAULT_WORDS = (
    ("Post_Fault_Lo", POST_FAULT_LO_ADDRESS),
    ("Post_Fault_Hi", POST_FAULT_HI_ADDRESS),
    ("Run_Fault_Lo", RUN_FAULT_LO_ADDRESS),
    ("Run_Fault_Hi", RUN_FAULT_HI_ADDRESS),
)


@dataclass(frozen=True)
class MemorySymbol:
    name: str
    address: int
    section: str
    kind: str
    value_type: str
    display: str
    writable: bool
    unit: str
    factor: float
    signed: bool
    gui_group: int = 6
    group: str = ""

    @property
    def key(self) -> str:
        return f"MemoryView.{self.name}"

    @property
    def address_text(self) -> str:
        return f"0x{self.address:04X}"

    @property
    def haystack(self) -> str:
        return " ".join(
            (
                self.name,
                self.section,
                self.kind,
                self.group,
                self.display,
                self.address_text,
                f"{self.address:04x}",
                f"{self.address:x}",
                str(self.address),
            )
        ).lower()

    @property
    def snapshot(self) -> bool:
        return self.kind in {"eeprom", "info"} or self.name.startswith("EEprom_")


def _unique_addresses(addresses: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for address in addresses:
        value = int(address)
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


class WatchList:
    """Addresses the user is monitoring on the Symbols tab."""

    def __init__(self, addresses: Iterable[int] = ()) -> None:
        self._lock = threading.Lock()
        self._addresses: list[int] = []
        self.replace(addresses)

    def replace(self, addresses: Iterable[int]) -> None:
        ordered = _unique_addresses(addresses)
        with self._lock:
            self._addresses = ordered

    def add(self, address: int) -> None:
        with self._lock:
            if address not in self._addresses:
                self._addresses.append(int(address))

    def remove(self, address: int) -> None:
        with self._lock:
            self._addresses = [item for item in self._addresses if item != address]

    def contains(self, address: int) -> bool:
        with self._lock:
            return address in self._addresses

    def addresses(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(self._addresses)


@dataclass(frozen=True)
class DumpProgress:
    done: int
    total: int
    active: bool

    @property
    def remaining(self) -> int:
        return max(self.total - self.done, 0)


class MemoryPoller:
    """Round-robin live watches, with a one-shot dump that interleaves between them."""

    def __init__(self, watch: WatchList) -> None:
        self.watch = watch
        self._lock = threading.Lock()
        self._oneshot: list[int] = []
        self._oneshot_index = 0
        self._watch_index = 0
        self._watch_turn = False
        self._active: tuple[int, ...] | None = None

    def set_active_addresses(self, addresses: Iterable[int] | None) -> None:
        """Poll these instead of the Symbols watch list. None follows the watch list."""
        ordered = None if addresses is None else tuple(_unique_addresses(addresses))
        with self._lock:
            self._active = ordered
            self._watch_index = 0

    def poll_addresses(self) -> tuple[int, ...]:
        with self._lock:
            if self._active is not None:
                return self._active
        return self.watch.addresses()

    def start_dump(self, addresses: Iterable[int]) -> None:
        ordered = _unique_addresses(addresses)
        with self._lock:
            self._oneshot = ordered
            self._oneshot_index = 0
            self._watch_turn = False

    def dump_progress(self) -> DumpProgress:
        with self._lock:
            total = len(self._oneshot)
            done = min(self._oneshot_index, total)
            return DumpProgress(done=done, total=total, active=done < total)

    def request_read(self, address: int) -> None:
        """Queue a single one-shot read without discarding an active dump."""
        with self._lock:
            self._oneshot.insert(self._oneshot_index, int(address))

    def next_address(self) -> int | None:
        watches = self.poll_addresses()
        with self._lock:
            has_dump = self._oneshot_index < len(self._oneshot)
            if has_dump and not self._watch_turn:
                address = self._oneshot[self._oneshot_index]
                self._oneshot_index += 1
                self._watch_turn = bool(watches)
                return address
            self._watch_turn = False
        if not watches:
            return None
        with self._lock:
            address = watches[self._watch_index % len(watches)]
            self._watch_index += 1
            return address


def classify_section(section: str) -> str:
    text = section.lower()
    if text.startswith("eeprom"):
        return "eeprom"
    if "info parameter" in text:
        return "info"
    if "gui command" in text:
        return "command"
    return "memory"


def classify_group(section: str, kind: str, gui_group: int, name: str) -> str:
    if kind == "eeprom":
        return EEPROM_GROUP_NAMES.get(gui_group, f"Group {gui_group}")
    if name.startswith("EEprom_"):
        return "EEPROM status"
    if kind == "info":
        return "Firmware"
    mapped = SECTION_GROUP_NAMES.get(section)
    if mapped:
        return mapped
    if " - " in section:
        return section.split(" - ", 1)[1]
    return section or "Other"


def snapshot_symbols(symbols: Iterable[MemorySymbol]) -> list[MemorySymbol]:
    return [symbol for symbol in symbols if symbol.snapshot]


def live_symbols(symbols: Iterable[MemorySymbol]) -> list[MemorySymbol]:
    return [symbol for symbol in symbols if not symbol.snapshot]


def snapshot_addresses(symbols: Iterable[MemorySymbol]) -> tuple[int, ...]:
    return tuple(symbol.address for symbol in snapshot_symbols(symbols))


def _unit_and_factor(name: str) -> tuple[str, float]:
    factor = 1.0
    scale = _SCALE_SUFFIX.search(name)
    if scale:
        factor = 1.0 / float(scale.group(1))
    unit = ""
    match = _UNIT_PARENS.search(name)
    if match:
        inner = match.group(1)
        unit = inner.split(")_")[0].split("_")[0]
        if unit.lower() in {"c", "degc"}:
            unit = "°C"
        elif unit.lower() == "deg":
            unit = "deg"
    return unit, factor


def _symbol(raw: dict[str, Any], section: str) -> MemorySymbol:
    name = str(raw["name"])
    unit, factor = _unit_and_factor(name)
    value_type = str(raw.get("type", "uint"))
    kind = classify_section(section)
    gui_group_raw = raw.get("gui_group", 6)
    gui_group = int(gui_group_raw) if str(gui_group_raw).isdigit() else 6
    return MemorySymbol(
        name=name,
        address=int(str(raw["address"]), 0),
        section=section,
        kind=kind,
        value_type=value_type,
        display=str(raw.get("display", "dec")),
        writable=bool(raw.get("writable", False)),
        unit=unit,
        factor=factor,
        signed=value_type == "int",
        gui_group=gui_group,
        group=classify_group(section, kind, gui_group, name),
    )


def load_memory_symbols(root: Path | None = None) -> tuple[MemorySymbol, ...]:
    path = (root or data_dir()) / "defsyms.yaml"
    doc = yaml.safe_load(path.read_text())
    symbols: list[MemorySymbol] = []
    seen: set[int] = set()
    for block in doc.get("sections") or []:
        section = str(block.get("section") or "Unknown")
        for raw in block.get("symbols") or []:
            item = _symbol(raw, section)
            if item.address in seen:
                continue
            seen.add(item.address)
            symbols.append(item)
    info_section = "Info Parameters - factory programmed, DO NOT attempt to modify"
    for name, address, display in _EXTRA_INFO:
        if address in seen:
            continue
        seen.add(address)
        symbols.append(
            MemorySymbol(
                name=name,
                address=address,
                section=info_section,
                kind="info",
                value_type="uint",
                display=display,
                writable=False,
                unit="",
                factor=1.0,
                signed=False,
                gui_group=6,
                group=classify_group(info_section, "info", 6, name),
            )
        )
    fault_section = "Monitored Parameters - VSM IOs"
    for name, address in _EXTRA_FAULT_WORDS:
        if address in seen:
            continue
        seen.add(address)
        symbols.append(
            MemorySymbol(
                name=name,
                address=address,
                section=fault_section,
                kind="memory",
                value_type="uint",
                display="hex",
                writable=False,
                unit="",
                factor=1.0,
                signed=False,
                gui_group=6,
                group=classify_group(fault_section, "memory", 6, name),
            )
        )
    return tuple(sorted(symbols, key=lambda item: (item.kind != "eeprom", item.address, item.name)))


def search_symbols(
    symbols: Iterable[MemorySymbol],
    query: str,
    kind: str | None = None,
) -> list[MemorySymbol]:
    tokens = [token.lower() for token in query.split() if token.strip()]
    wanted = None if not kind or kind == "all" else kind.lower()
    matches: list[MemorySymbol] = []
    for symbol in symbols:
        if wanted == "eeprom" and symbol.kind != "eeprom":
            continue
        if wanted == "memory" and symbol.kind == "eeprom":
            continue
        haystack = symbol.haystack
        if tokens and not all(token in haystack for token in tokens):
            continue
        matches.append(symbol)
    return matches


def checksum_prefix(prefix: str) -> str:
    return f"{(-sum(prefix.encode('ascii'))) & 0xFF:02x}"


def read_command(address: int) -> bytes:
    body = f"rm{address:04x}"
    return f"{body}{checksum_prefix(body)}\r".encode("ascii")


def write_command(address: int, value: int) -> bytes:
    body = f"wm{address:04x}={value & 0xFFFF:04x}"
    return f"{body}{checksum_prefix(body)}\r".encode("ascii")


def parse_read_reply(line: str) -> tuple[int, int] | None:
    text = line.strip().strip("\r")
    match = re.fullmatch(r"\*([0-9A-Fa-f]{4})=([0-9A-Fa-f]{4})([0-9A-Fa-f]{2})", text)
    if not match:
        return None
    prefix = f"*{match.group(1)}={match.group(2)}"
    if checksum_prefix(prefix).lower() != match.group(3).lower():
        return None
    return int(match.group(1), 16), int(match.group(2), 16)


def decode_raw(symbol: MemorySymbol, raw_u16: int) -> int | float | str:
    raw = raw_u16 & 0xFFFF
    if symbol.signed and raw >= 0x8000:
        raw -= 0x10000
    if symbol.display == "ascii":
        low = raw & 0xFF
        return chr(low) if 32 <= low < 127 else raw
    if symbol.factor != 1.0:
        return raw * symbol.factor
    return raw


def _signed_value(symbol: MemorySymbol, raw_u16: int) -> int:
    raw = int(raw_u16) & 0xFFFF
    if symbol.signed and raw >= 0x8000:
        raw -= 0x10000
    return raw


def edit_unit(symbol: MemorySymbol) -> str:
    """Obvious unit suffix for the edit box, or "" when the name carries none.

    The defsyms paren token is noisy ("(Trq=0_Spd=1)", "(Lo_Word)"), so only
    recognised measurement units are returned; anything else falls back to a
    plain number box.
    """
    if symbol.display != "dec":
        return ""
    token = symbol.unit.strip().lower()
    if not token:
        return ""
    if token.startswith("volt") or token in {"v", "vx10"}:
        return "V"
    if token.startswith("amp") or token == "a":
        return "A"
    if token.startswith("nm"):
        return "Nm"
    if token.startswith("rpm"):
        return "RPM" if "sec" not in token else "RPM/s"
    if token == "°c":
        return "°C"
    if token == "deg":
        return "deg"
    if token == "wb":
        return "Wb"
    if "count" in token or token == "adc":
        return "counts"
    if token.startswith("ahr") or token == "ah":
        return "Ah"
    if "ms" in token:
        return "ms"
    if token.startswith("sec") or token == "s":
        return "s"
    if token.startswith("hz"):
        return "Hz"
    if "kbps" in token:
        return "kbps"
    return ""


def engineering_decimals(symbol: MemorySymbol) -> int:
    """Fixed decimal places that round-trip raw <-> engineering text."""
    if symbol.factor >= 1.0:
        return 0
    decimals = 0
    scaled = 1.0
    while decimals < 6 and scaled > symbol.factor + 1e-12:
        scaled /= 10.0
        decimals += 1
    return decimals


def format_engineering(symbol: MemorySymbol, raw_u16: int) -> str:
    """Engineering text for the units edit box (no unit suffix)."""
    value = _signed_value(symbol, raw_u16) * symbol.factor
    return f"{value:.{engineering_decimals(symbol)}f}"


def _engineering_range(symbol: MemorySymbol) -> tuple[float, float]:
    lo, hi = (-32768, 32767) if symbol.signed else (0, 65535)
    return lo * symbol.factor, hi * symbol.factor


def parse_engineering(symbol: MemorySymbol, text: str) -> int:
    """Parse units text into the raw word to flash. Raises ValueError."""
    cleaned = text.strip()
    unit = edit_unit(symbol)
    if unit and cleaned.lower().endswith(unit.lower()):
        cleaned = cleaned[: -len(unit)].strip()
    try:
        value = float(cleaned)
    except ValueError:
        raise ValueError(f"“{text.strip()}” is not a number.") from None
    raw = round(value / symbol.factor)
    lo, hi = (-32768, 32767) if symbol.signed else (0, 65535)
    if raw < lo or raw > hi:
        lo_eng, hi_eng = _engineering_range(symbol)
        decimals = engineering_decimals(symbol)
        suffix = f" {unit}" if unit else ""
        raise ValueError(
            f"Must be between {lo_eng:.{decimals}f}{suffix} "
            f"and {hi_eng:.{decimals}f}{suffix}."
        )
    return int(raw) & 0xFFFF


def parse_raw_word(symbol: MemorySymbol, text: str) -> int:
    """Parse the raw-decimal edit box into the word to flash. Raises ValueError."""
    cleaned = text.strip().lower().removeprefix("0x")
    base = 16 if text.strip().lower().startswith("0x") else 10
    try:
        value = int(cleaned, base)
    except ValueError:
        raise ValueError(f"“{text.strip()}” is not a whole number.") from None
    lo, hi = (-32768, 32767) if symbol.signed else (0, 65535)
    if value < lo or value > hi:
        raise ValueError(f"Must be a whole number between {lo} and {hi}.")
    return int(value) & 0xFFFF


def pack_memory_frame(address: int, raw_u16: int) -> bytes:
    return bytes((address & 0xFF, (address >> 8) & 0xFF, raw_u16 & 0xFF, (raw_u16 >> 8) & 0xFF))


def unpack_memory_frame(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4:
        return None
    address = data[0] | (data[1] << 8)
    raw = data[2] | (data[3] << 8)
    return address, raw
