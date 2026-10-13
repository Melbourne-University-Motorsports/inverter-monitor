from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field

from inverter_monitor.catalog import Catalog, FaultBit, graph_lookup_keys
from inverter_monitor.decode import SignalUpdate


@dataclass
class SignalSnapshot:
    key: str
    message: str
    signal: str
    value: float | int | bool | None
    raw: int | None
    unit: str
    enum_name: str | None = None
    enum_description: str | None = None
    last_seen: float = 0.0
    cycle_ms: int | None = None
    kind: str = "number"
    update_count: int = 0

    def age(self, now: float) -> float:
        if not self.last_seen:
            return math.inf
        return now - self.last_seen

    def stale(self, now: float, multiplier: float = 3.0) -> bool:
        if self.cycle_ms is None:
            return self.age(now) > 1.0
        return self.age(now) > (self.cycle_ms / 1000.0) * multiplier


@dataclass(frozen=True)
class FaultEvent:
    timestamp: float
    bit: int
    name: str
    severity: str
    active: bool


@dataclass
class StoreSnapshot:
    now: float
    signals: dict[str, SignalSnapshot]
    frames: dict[int, "RawFrame"]
    active_faults: tuple[FaultBit, ...]
    fault_history: tuple[FaultEvent, ...]
    post_word: int
    run_word: int
    frame_count: int
    frames_per_sec: float


@dataclass
class RawFrame:
    arbitration_id: int
    name: str
    data: bytes
    last_seen: float
    count: int
    period_s: float | None = None


class InverterStore:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self._lock = threading.Lock()
        self._signals: dict[str, SignalSnapshot] = {}
        self._frames: dict[int, RawFrame] = {}
        self._fault_history: list[FaultEvent] = []
        self._active_bits: set[int] = set()
        self._post_word = 0
        self._run_word = 0
        self._frame_count = 0
        self._recent_frames: list[float] = []

    def apply_frame(
        self,
        arbitration_id: int,
        data: bytes,
        updates: list[SignalUpdate],
        now: float | None = None,
        name: str = "",
    ) -> None:
        now = now if now is not None else time.monotonic()
        with self._lock:
            existing = self._frames.get(arbitration_id)
            period = None
            if existing:
                period = now - existing.last_seen
            self._frames[arbitration_id] = RawFrame(
                arbitration_id=arbitration_id,
                name=name or (existing.name if existing else ""),
                data=bytes(data),
                last_seen=now,
                count=(existing.count + 1) if existing else 1,
                period_s=period,
            )
            self._frame_count += 1
            self._recent_frames.append(now)
            cutoff = now - 1.0
            self._recent_frames = [stamp for stamp in self._recent_frames if stamp >= cutoff]
            for update in updates:
                current = self._signals.get(update.key)
                self._signals[update.key] = SignalSnapshot(
                    key=update.key,
                    message=update.message,
                    signal=update.signal,
                    value=update.value,
                    raw=update.raw,
                    unit=update.unit,
                    enum_name=update.enum_name,
                    enum_description=update.enum_description,
                    last_seen=now,
                    cycle_ms=update.cycle_ms,
                    kind=update.kind,
                    update_count=(current.update_count + 1) if current else 1,
                )
            self._refresh_faults(now)

    def _value(self, *keys: str) -> int:
        for key in keys:
            item = self._signals.get(key)
            if item is None or item.raw is None:
                continue
            return int(item.raw) & 0xFFFF
        return 0

    def _refresh_faults(self, now: float) -> None:
        post_lo = self._value("M171_Fault_Codes.D1_Post_Fault_Lo", "MemoryView.Post_Fault_Lo")
        post_hi = self._value("M171_Fault_Codes.D2_Post_Fault_Hi", "MemoryView.Post_Fault_Hi")
        run_lo = self._value("M171_Fault_Codes.D3_Run_Fault_Lo", "MemoryView.Run_Fault_Lo")
        run_hi = self._value("M171_Fault_Codes.D4_Run_Fault_Hi", "MemoryView.Run_Fault_Hi")
        post = (post_hi << 16) | post_lo
        run = (run_hi << 16) | run_lo
        self._post_word = post
        self._run_word = run
        packed = post | (run << 32)
        new_bits = {bit for bit in self.catalog.fault_bits if packed & (1 << bit)}
        appeared = new_bits - self._active_bits
        cleared = self._active_bits - new_bits
        wall = time.time()
        for bit in sorted(appeared):
            spec = self.catalog.fault_bits[bit]
            self._fault_history.append(
                FaultEvent(wall, bit, spec.name, spec.severity, True)
            )
        for bit in sorted(cleared):
            spec = self.catalog.fault_bits[bit]
            self._fault_history.append(
                FaultEvent(wall, bit, spec.name, spec.severity, False)
            )
        if len(self._fault_history) > 400:
            self._fault_history = self._fault_history[-400:]
        self._active_bits = new_bits

    def snapshot(self, now: float | None = None) -> StoreSnapshot:
        now = now if now is not None else time.monotonic()
        with self._lock:
            active = tuple(
                self.catalog.fault_bits[bit]
                for bit in sorted(self._active_bits)
                if bit in self.catalog.fault_bits
            )
            # Prune against `now` here, not only when a frame arrives: otherwise
            # the rate freezes at its last value the moment the source goes
            # quiet, and "the inverter stopped talking" never becomes visible.
            recent = [stamp for stamp in self._recent_frames if stamp >= now - 1.0]
            self._recent_frames = recent
            return StoreSnapshot(
                now=now,
                signals=dict(self._signals),
                frames=dict(self._frames),
                active_faults=active,
                fault_history=tuple(self._fault_history[-80:]),
                post_word=self._post_word,
                run_word=self._run_word,
                frame_count=self._frame_count,
                frames_per_sec=float(len(recent)),
            )


def get_signal(snapshot: StoreSnapshot, key: str) -> SignalSnapshot | None:
    return snapshot.signals.get(key)


def first_signal(snapshot: StoreSnapshot, *keys: str) -> SignalSnapshot | None:
    """Return the first live signal among keys, else the first stale hit."""
    stale_hit: SignalSnapshot | None = None
    for key in keys:
        signal = snapshot.signals.get(key)
        if signal is None:
            continue
        if not signal.stale(snapshot.now):
            return signal
        if stale_hit is None:
            stale_hit = signal
    return stale_hit


def fresh_signal(snapshot: StoreSnapshot, *keys: str) -> SignalSnapshot | None:
    """Like first_signal, but None when every candidate is stale.

    Live status widgets use this so a value that stopped arriving is shown as
    unknown rather than as the last number the inverter happened to send.
    """
    signal = first_signal(snapshot, *keys)
    if signal is None or signal.stale(snapshot.now):
        return None
    return signal


#: Store keys reporting the inverter command mode (0 = CAN, 1 = VSM): live
#: M170 bit first, RS232 EEPROM word as fallback.
COMMAND_MODE_KEYS = (
    "M170_Internal_States.D5_Inverter_Command_Mode",
    "MemoryView.Inv_Cmd_Mode_EEPROM(CAN=0_VSM=1)",
)


def command_mode(snapshot: StoreSnapshot) -> int | None:
    """Return 0 for CAN mode, 1 for VSM mode, or None when unknown."""
    signal = first_signal(snapshot, *COMMAND_MODE_KEYS)
    if signal is None or signal.raw is None:
        return None
    try:
        return int(signal.raw) & 1
    except (TypeError, ValueError):
        return None


def format_value(signal: SignalSnapshot | None, now: float) -> str:
    if signal is None or signal.value is None:
        return "—"
    if signal.stale(now):
        prefix = ""
    else:
        prefix = ""
    if signal.enum_name:
        return f"{signal.raw}  {signal.enum_name}"
    if signal.kind == "bool":
        return "ON" if signal.value else "OFF"
    if signal.kind == "hex":
        raw = 0 if signal.raw is None else int(signal.raw) & 0xFFFF
        return f"0x{raw:04X}"
    if isinstance(signal.value, float):
        abs_value = abs(signal.value)
        digits = 1 if abs_value >= 10 else 2
        return f"{signal.value:.{digits}f}"
    return str(signal.value)


def mechanical_power_kw(snapshot: StoreSnapshot) -> float | None:
    speed = fresh_signal(snapshot, *graph_lookup_keys("M165_Motor_Position_Info.D2_Motor_Speed"))
    torque = fresh_signal(
        snapshot,
        *graph_lookup_keys("M172_Torque_And_Timer_Info.D2_Torque_Feedback"),
    )
    if speed is None or torque is None:
        return None
    if not isinstance(speed.value, (int, float)) or not isinstance(torque.value, (int, float)):
        return None
    return abs(torque.value * speed.value * 2.0 * math.pi / 60.0) / 1000.0
