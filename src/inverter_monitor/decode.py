from __future__ import annotations

from dataclasses import dataclass

from inverter_monitor.catalog import Catalog, MessageDef, SignalDef
from inverter_monitor.memory_map import (
    MEMORY_CYCLE_MS,
    MEMORY_FRAME_ID,
    decode_raw,
    unpack_memory_frame,
)


class DecodeError(ValueError):
    pass


@dataclass(frozen=True)
class SignalUpdate:
    key: str
    message: str
    signal: str
    value: float | int | bool
    raw: int
    unit: str
    enum_name: str | None = None
    enum_description: str | None = None
    cycle_ms: int | None = None
    kind: str = "number"


def extract_raw(data: bytes, signal: SignalDef) -> int:
    if not signal.little_endian:
        raise DecodeError(f"Motorola/big-endian not supported for {signal.name}")
    raw = int.from_bytes(data.ljust(8, b"\x00")[:8], "little")
    mask = (1 << signal.length) - 1
    value = (raw >> signal.start) & mask
    if signal.signed and signal.length > 0 and value >= 1 << (signal.length - 1):
        value -= 1 << signal.length
    return value


def insert_raw(data: bytearray, signal: SignalDef, value: int) -> None:
    if not signal.little_endian:
        raise DecodeError(f"Motorola/big-endian not supported for {signal.name}")
    if len(data) < 8:
        data.extend(b"\x00" * (8 - len(data)))
    packed = int.from_bytes(bytes(data[:8]), "little")
    mask = (1 << signal.length) - 1
    packed &= ~(mask << signal.start)
    packed |= (value & mask) << signal.start
    data[:8] = packed.to_bytes(8, "little")


def physical_value(raw: int, signal: SignalDef) -> float | int | bool:
    if signal.kind == "bool":
        return bool(raw)
    scaled = raw * signal.factor + signal.offset
    if signal.factor == 1.0 and signal.offset == 0.0 and not signal.enum:
        return int(raw)
    return scaled


def pack_param_write(address: int, value: int) -> bytes:
    """M193 Read/Write Param Command: little-endian address, write=1, 16-bit data."""
    payload = bytearray(8)
    payload[0] = address & 0xFF
    payload[1] = (address >> 8) & 0xFF
    payload[2] = 1
    payload[4] = value & 0xFF
    payload[5] = (value >> 8) & 0xFF
    return bytes(payload)


def encode_physical(message: MessageDef, values: dict[str, float | int | bool]) -> bytes:
    payload = bytearray(8)
    by_name = {signal.name: signal for signal in message.signals}
    for name, physical in values.items():
        signal = by_name[name]
        if signal.kind == "bool":
            raw = 1 if physical else 0
        else:
            raw = int(round((float(physical) - signal.offset) / (signal.factor or 1.0)))
        insert_raw(payload, signal, raw)
    return bytes(payload)


SCI_FRAME_ID = 0x7E0
SCI_CYCLE_MS = 50
M193_PARAM_COMMAND_ID = 0x0C1
# Cascadia CAN Protocol: parameter 20, write 0. Inverter must be disabled first.
PARAM_CLEAR_FAULTS = 20

_MEMORY_ENUMS = {
    "VSM_State": "INV_VSM_State",
    "Inverter_Mode": "INV_Inverter_State",
}


def _memory_enum(name: str) -> str | None:
    if name in _MEMORY_ENUMS:
        return _MEMORY_ENUMS[name]
    if name.startswith("Inv_Cmd_Mode"):
        return "INV_Inverter_Command_Mode"
    return None


# 0-based SCI records mapped onto the same keys the CAN UI already reads.
# signed: interpret uint16 as two's complement before scaling.
_SCI_COLUMNS: tuple[tuple[int, str, str, str, float, str, bool], ...] = (
    # index, message, signal, unit, factor, kind, signed
    (1, "M163_Analog_Input_Voltages", "D1_Analog_Input_1", "V", 0.01, "number", False),
    (2, "M172_Torque_And_Timer_Info", "D2_Torque_Feedback", "Nm", 0.1, "number", True),
    (3, "M172_Torque_And_Timer_Info", "D1_Commanded_Torque", "Nm", 0.1, "number", True),
    (4, "M167_Voltage_Info", "D1_DC_Bus_Voltage", "V", 0.1, "number", True),
    (5, "M166_Current_Info", "D4_DC_Bus_Current", "A", 0.1, "number", True),
    (6, "M165_Motor_Position_Info", "D2_Motor_Speed", "rpm", 1.0, "number", True),
    (7, "M173_Modulation_And_Flux_Info", "D2_Flux_Weakening_Output", "A", 0.1, "number", True),
    (10, "M168_Flux_ID_IQ_Info", "D4_Iq", "A", 0.1, "number", True),
    (11, "M168_Flux_ID_IQ_Info", "D3_Id", "A", 0.1, "number", True),
    (13, "M173_Modulation_And_Flux_Info", "D1_Modulation_Index", "", 0.0001, "number", False),
    (14, "M160_Temperature_Set_1", "D1_Module_A", "degC", 0.1, "number", True),
    (15, "M162_Temperature_Set_3", "D3_Motor_Temperature", "degC", 0.1, "number", True),
    (16, "M171_Fault_Codes", "D3_Run_Fault_Lo", "", 1.0, "fault_word", False),
    (17, "M171_Fault_Codes", "D4_Run_Fault_Hi", "", 1.0, "fault_word", False),
    (18, "M162_Temperature_Set_3", "D4_Torque_Shudder", "Nm", 0.1, "number", True),
    (19, "M163_Analog_Input_Voltages", "D2_Analog_Input_2", "V", 0.01, "number", False),
)


def signed16(raw: int) -> int:
    value = raw & 0xFFFF
    return value - 65536 if value >= 32768 else value


def pack_sci_words(words: list[int]) -> bytes:
    payload = bytearray()
    for word in words[:20]:
        payload.extend((word & 0xFFFF).to_bytes(2, "little"))
    return bytes(payload.ljust(40, b"\x00"))


def unpack_sci_words(data: bytes) -> list[int]:
    words = []
    blob = data.ljust(40, b"\x00")
    for index in range(20):
        words.append(int.from_bytes(blob[index * 2 : index * 2 + 2], "little"))
    return words


def decode_sci_words(words: list[int]) -> list[SignalUpdate]:
    updates: list[SignalUpdate] = []
    for index, message, signal, unit, factor, kind, signed in _SCI_COLUMNS:
        if index >= len(words):
            continue
        raw = signed16(words[index]) if signed else (words[index] & 0xFFFF)
        value: float | int = raw if factor == 1.0 else raw * factor
        updates.append(
            SignalUpdate(
                key=f"{message}.{signal}",
                message=message,
                signal=signal,
                value=value,
                raw=raw,
                unit=unit,
                cycle_ms=SCI_CYCLE_MS,
                kind=kind,
            )
        )
    return updates


class Decoder:
    def __init__(self, catalog: Catalog, id_offset: int = 0) -> None:
        self.catalog = catalog
        self.id_offset = id_offset

    def decode_frame(self, arbitration_id: int, data: bytes) -> list[SignalUpdate]:
        if arbitration_id == SCI_FRAME_ID:
            return decode_sci_words(unpack_sci_words(data))
        if arbitration_id == MEMORY_FRAME_ID:
            return self._decode_memory(data)
        message = self.catalog.message_for(arbitration_id, self.id_offset)
        if message is None or not message.signals:
            return []
        updates: list[SignalUpdate] = []
        for signal in message.signals:
            raw = extract_raw(data, signal)
            value = physical_value(raw, signal)
            enum_name = None
            enum_description = None
            if signal.enum:
                entry = self.catalog.enums.get(signal.enum, {}).get(int(raw))
                if entry:
                    enum_name = entry.name
                    enum_description = entry.description
            updates.append(
                SignalUpdate(
                    key=f"{message.name}.{signal.name}",
                    message=message.name,
                    signal=signal.name,
                    value=value,
                    raw=raw,
                    unit=signal.unit,
                    enum_name=enum_name,
                    enum_description=enum_description,
                    cycle_ms=message.cycle_ms,
                    kind=signal.kind,
                )
            )
        return updates

    def _decode_memory(self, data: bytes) -> list[SignalUpdate]:
        unpacked = unpack_memory_frame(data)
        if unpacked is None:
            return []
        address, raw_u16 = unpacked
        symbol = self.catalog.memory_by_address.get(address)
        if symbol is None:
            return []
        value = decode_raw(symbol, raw_u16)
        raw_signed = raw_u16 & 0xFFFF
        if symbol.signed and raw_signed >= 0x8000:
            raw_signed -= 0x10000
        enum_name = None
        enum_description = None
        enum_id = _memory_enum(symbol.name)
        if enum_id:
            entry = self.catalog.enums.get(enum_id, {}).get(int(raw_signed))
            if entry:
                enum_name = entry.name
                enum_description = entry.description
        kind = "hex" if symbol.display == "hex" else "number"
        return [
            SignalUpdate(
                key=symbol.key,
                message="MemoryView",
                signal=symbol.name,
                value=value,
                raw=raw_signed,
                unit=symbol.unit,
                enum_name=enum_name,
                enum_description=enum_description,
                cycle_ms=MEMORY_CYCLE_MS,
                kind=kind,
            )
        ]
