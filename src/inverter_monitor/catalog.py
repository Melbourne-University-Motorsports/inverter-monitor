from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from inverter_monitor.memory_map import MemorySymbol, live_symbols, load_memory_symbols
from inverter_monitor.paths import data_dir


def parse_int(value: Any) -> int:
    if isinstance(value, str):
        return int(value, 0)
    return int(value)


@dataclass(frozen=True)
class EnumValue:
    name: str
    description: str = ""


@dataclass(frozen=True)
class SignalDef:
    name: str
    start: int
    length: int
    signed: bool = False
    little_endian: bool = True
    factor: float = 1.0
    offset: float = 0.0
    unit: str = ""
    enum: str | None = None
    kind: str = "number"


@dataclass(frozen=True)
class MessageDef:
    can_id: int
    name: str
    cycle_ms: int | None
    signals: tuple[SignalDef, ...]
    direction: str = "status"
    write_mode: bool = False


@dataclass(frozen=True)
class FaultBit:
    bit: int
    word: str
    word_bit: int
    name: str
    severity: str
    description: str = ""
    latching: bool = False
    notes: str = ""


@dataclass(frozen=True)
class VsmState:
    id: int
    name: str
    description: str
    entry: str = ""
    exit: str = ""
    conditions: tuple[str, ...] = ()
    lockouts: tuple[str, ...] = ()
    can_description: str = ""
    can_entry: str = ""
    can_exit: str = ""

    def text(self, command_mode: int | None) -> tuple[str, str, str]:
        """Effective (description, entry, exit) for a command mode.

        0 selects the CAN-mode wording, 1 the VSM-mode wording. Unknown
        mode defaults to CAN, the bench's primary mode. Fields without a
        CAN override fall back to the shared wording.
        """
        if command_mode == VSM_COMMAND_MODE:
            return (self.description, self.entry, self.exit)
        return (
            self.can_description or self.description,
            self.can_entry or self.entry,
            self.can_exit or self.exit,
        )


#: Inverter command modes (M170 D5_Inverter_Command_Mode, EEPROM 0x011B).
CAN_COMMAND_MODE = 0
VSM_COMMAND_MODE = 1


def mode_label(mode: int | None) -> str:
    """Human label for a command mode; unknown reads as CAN, the primary mode."""
    return "VSM mode" if mode == VSM_COMMAND_MODE else "CAN mode"


@dataclass
class Catalog:
    messages: dict[int, MessageDef]
    messages_by_name: dict[str, MessageDef]
    enums: dict[str, dict[int, EnumValue]]
    fault_bits: dict[int, FaultBit]
    vsm_states: dict[int, VsmState]
    inverter_states: dict[int, VsmState]
    memory_symbols: tuple[MemorySymbol, ...] = ()
    memory_by_address: dict[int, MemorySymbol] = field(default_factory=dict)

    def message_for(self, arbitration_id: int, id_offset: int = 0) -> MessageDef | None:
        return self.messages.get(arbitration_id - id_offset)


def _enum_value(raw: Any) -> EnumValue:
    if isinstance(raw, dict):
        return EnumValue(name=str(raw.get("name", "")), description=str(raw.get("description", "")))
    return EnumValue(name=str(raw))


def _signal(raw: dict[str, Any]) -> SignalDef:
    kind = str(raw.get("type", "number"))
    length = int(raw.get("len", 1 if kind == "bool" else raw["len"]))
    endian = str(raw.get("endian", "little")).lower()
    return SignalDef(
        name=str(raw["name"]),
        start=int(raw["start"]),
        length=length,
        signed=bool(raw.get("signed", False)),
        little_endian=endian != "big",
        factor=float(raw.get("factor", 1.0)),
        offset=float(raw.get("offset", 0.0)),
        unit=str(raw.get("unit", "") or ""),
        enum=raw.get("enum"),
        kind=kind,
    )


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _diagnostic_map(faults_doc: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for register in faults_doc.get("registers", []):
        for item in register.get("diagnostics", []):
            name = str(item.get("name", ""))
            description = str(item.get("description", ""))
            if name:
                mapping[_norm(name)] = description
    return mapping


def _match_description(name: str, diagnostics: dict[str, str]) -> str:
    key = _norm(name)
    if key in diagnostics:
        return diagnostics[key]
    for diag_key, description in diagnostics.items():
        if key in diag_key or diag_key in key:
            return description
    return ""


def _vsm_state(raw: dict[str, Any]) -> VsmState:
    notes = raw.get("notes") or {}
    conditions = notes.get("conditions") or []
    if isinstance(conditions, str):
        conditions = [conditions]
    return VsmState(
        id=int(raw["id"]),
        name=str(raw.get("name", f"State {raw['id']}")),
        description=str(raw.get("description", "")),
        entry=str(notes.get("entry") or ""),
        exit=str(notes.get("exit") or ""),
        conditions=tuple(str(item) for item in conditions),
        lockouts=tuple(str(item) for item in (raw.get("related_lockouts") or [])),
        can_description=str(raw.get("can_description") or ""),
        can_entry=str(raw.get("can_entry") or ""),
        can_exit=str(raw.get("can_exit") or ""),
    )


def load_catalog(root: Path | None = None) -> Catalog:
    base = root or data_dir()
    decode_doc = yaml.safe_load((base / "reference_decode.yaml").read_text())
    faults_doc = yaml.safe_load((base / "faults.yaml").read_text())
    vsm_doc = yaml.safe_load((base / "vsm_states.yaml").read_text())

    messages: dict[int, MessageDef] = {}
    messages_by_name: dict[str, MessageDef] = {}
    for raw in decode_doc.get("can_messages", []):
        can_id = parse_int(raw["id"])
        signals = tuple(_signal(item) for item in raw.get("signals") or [])
        message = MessageDef(
            can_id=can_id,
            name=str(raw["name"]),
            cycle_ms=raw.get("cycle_ms"),
            signals=signals,
            direction=str(raw.get("direction", "status")),
            write_mode=bool(raw.get("write_mode", False)),
        )
        messages[can_id] = message
        messages_by_name[message.name] = message

    enums: dict[str, dict[int, EnumValue]] = {}
    for enum_name, spec in (decode_doc.get("enums") or {}).items():
        values = spec.get("values") or spec
        parsed: dict[int, EnumValue] = {}
        if isinstance(values, dict):
            for key, value in values.items():
                parsed[int(key)] = _enum_value(value)
        enums[enum_name] = parsed

    diagnostics = _diagnostic_map(faults_doc)
    fault_bits: dict[int, FaultBit] = {}
    for raw in (decode_doc.get("fault_words") or {}).get("bits") or []:
        name = str(raw["name"])
        extra = str(raw.get("notes") or "")
        description = _match_description(name, diagnostics)
        if extra:
            description = f"{description} ({extra})".strip() if description else extra
        bit = int(raw["bit"])
        fault_bits[bit] = FaultBit(
            bit=bit,
            word=str(raw["word"]),
            word_bit=int(raw["word_bit"]),
            name=name,
            severity=str(raw.get("severity", "fault")),
            description=description,
            latching=bool(raw.get("latching", False)),
            notes=extra,
        )

    vsm_states = {item.id: item for item in (_vsm_state(raw) for raw in vsm_doc.get("states") or [])}
    inverter_states = {
        item.id: item
        for item in (_vsm_state(raw) for raw in (vsm_doc.get("inverter_states") or {}).get("states") or [])
    }

    # Prefer long-form manual names/descriptions on VSM IDs. The enum line is
    # shown before any mode is known, so it carries the CAN-leaning wording.
    vsm_enum = enums.get("INV_VSM_State", {})
    for state_id, state in vsm_states.items():
        description, _, _ = state.text(CAN_COMMAND_MODE)
        current = vsm_enum.get(state_id)
        if current:
            vsm_enum[state_id] = EnumValue(name=current.name, description=description or current.description)
        else:
            vsm_enum[state_id] = EnumValue(name=state.name, description=description)
    enums["INV_VSM_State"] = vsm_enum

    memory_symbols = load_memory_symbols(base)
    return Catalog(
        messages=messages,
        messages_by_name=messages_by_name,
        enums=enums,
        fault_bits=fault_bits,
        vsm_states=vsm_states,
        inverter_states=inverter_states,
        memory_symbols=memory_symbols,
        memory_by_address={item.address: item for item in memory_symbols},
    )


DEFAULT_GRAPH_KEYS = (
    "M165_Motor_Position_Info.D2_Motor_Speed",
    "M172_Torque_And_Timer_Info.D2_Torque_Feedback",
    "M172_Torque_And_Timer_Info.D1_Commanded_Torque",
    "M167_Voltage_Info.D1_DC_Bus_Voltage",
    "M166_Current_Info.D4_DC_Bus_Current",
    "M162_Temperature_Set_3.D3_Motor_Temperature",
    "M160_Temperature_Set_1.D1_Module_A",
)

# Same quantity on CAN and Memory View. Graphs / Overview look up both and
# RS232 polls the Memory View address without touching the Symbols list.
GRAPH_SIGNAL_ALIASES = (
    ("M165_Motor_Position_Info.D2_Motor_Speed", "MemoryView.Feedback_Speed_(RPM)"),
    ("M172_Torque_And_Timer_Info.D2_Torque_Feedback", "MemoryView.Feedback_Torque_(Nm)_x_10"),
    ("M172_Torque_And_Timer_Info.D1_Commanded_Torque", "MemoryView.Commanded_Torque_(Nm)_x_10"),
    ("M167_Voltage_Info.D1_DC_Bus_Voltage", "MemoryView.V_DC_Filtered_(Volts)_x_10"),
    ("M167_Voltage_Info.D3_VAB_Vd_Voltage", "MemoryView.Vab_Voltage_(Volts)_x_10"),
    ("M167_Voltage_Info.D4_VBC_Vq_Voltage", "MemoryView.Vbc_Voltage_(Volts)_x_10"),
    ("M166_Current_Info.D4_DC_Bus_Current", "MemoryView.I_DC_Filtered_(Amps)_x_10"),
    ("M162_Temperature_Set_3.D3_Motor_Temperature", "MemoryView.Motor_Temp_(C)_x_10"),
    ("M162_Temperature_Set_3.D4_Torque_Shudder", "MemoryView.Torque_Shudder_(Nm)_x_10"),
    ("M160_Temperature_Set_1.D1_Module_A", "MemoryView.Mod_A_Temp_(C)_x_10"),
    ("M160_Temperature_Set_1.D2_Module_B", "MemoryView.Mod_B_Temp_(C)_x_10"),
    ("M160_Temperature_Set_1.D3_Module_C", "MemoryView.Mod_C_Temp_(C)_x_10"),
    ("M161_Temperature_Set_2.D1_Control_Board_Temperature", "MemoryView.PCB_Temp_(C)_x_10"),
    ("M161_Temperature_Set_2.D2_RTD1_Temperature", "MemoryView.RTD1_Temp_(C)_x_10"),
    ("M161_Temperature_Set_2.D3_RTD2_Temperature", "MemoryView.RTD2_Temp_(C)_x_10"),
    ("M173_Modulation_And_Flux_Info.D1_Modulation_Index", "MemoryView.Modulation_Index"),
)

_GRAPH_ALIAS_FORWARD = dict(GRAPH_SIGNAL_ALIASES)
_GRAPH_ALIAS_REVERSE = {memory: can for can, memory in GRAPH_SIGNAL_ALIASES}
_MEMORY_GRAPH_GROUPS = frozenset({"Thermal", "Torque / Speed", "DC", "Analog"})


def graph_lookup_keys(key: str) -> tuple[str, ...]:
    alias = _GRAPH_ALIAS_FORWARD.get(key) or _GRAPH_ALIAS_REVERSE.get(key)
    if alias:
        return (key, alias)
    return (key,)


def graph_poll_addresses(catalog: Catalog, keys: Iterable[str]) -> tuple[int, ...]:
    """Memory View addresses to poll for the selected graph traces."""
    by_key = {symbol.key: symbol.address for symbol in catalog.memory_symbols}
    seen: set[int] = set()
    ordered: list[int] = []
    for key in keys:
        for candidate in graph_lookup_keys(key):
            address = by_key.get(candidate)
            if address is None or address in seen:
                continue
            seen.add(address)
            ordered.append(address)
    return tuple(ordered)


def graphable_keys(catalog: Catalog) -> list[str]:
    keys: list[str] = []
    aliased_memory = set(_GRAPH_ALIAS_FORWARD.values())
    for message in catalog.messages.values():
        if message.write_mode or not message.signals:
            continue
        for signal in message.signals:
            if signal.kind in {"bool", "fault_word"}:
                continue
            if signal.enum:
                continue
            keys.append(f"{message.name}.{signal.name}")
    for symbol in live_symbols(catalog.memory_symbols):
        if symbol.display != "dec" or symbol.group not in _MEMORY_GRAPH_GROUPS:
            continue
        if symbol.key in aliased_memory:
            continue
        keys.append(symbol.key)
    return keys
