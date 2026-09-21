"""CAN module health from the Gen 3 Memory View diagnostic registers.

Source: CAN Protocol Rev 6.3 §1.2 (Gen 3 only, pp. 10-13) — see
`data/can_status.yaml` for the bit maps and docs/okf/can/can-status.md for the
write-up. The monitor polls `CAN_Status` (0x00C8), `CAN_Faults` (0x00C9) and
the Tx/Rx error counters over RS232, then turns them into one of four levels so
the Faults page and status strip can show a plain "CAN degraded" flag instead
of raw bits.

Levels, in the order the rules are checked:

* ``fault`` — Bus Off (status 0x0080). The controller has stopped talking.
* ``warning`` — Error Warning (0x0020), Error Passive (0x0040), any latched
  CAN fault bit, or a Tx/Rx error counter at 96+.
* ``ok`` — both words read 0 and both counters are below 96.
* ``unknown`` — nothing fresh to read for the current feed.

Stuck At Dominant 1 (Faults word 0x0008) is deliberately not a trigger: it sets
on every power-up and reset until the bus shows a recessive bit, so on its own
it would cry wolf. It still appears in the reasons when other trouble is
present.
"""

from __future__ import annotations

from dataclasses import dataclass

from inverter_monitor.catalog import CanErrorCounter, CanStatusBit, Catalog
from inverter_monitor.store import StoreSnapshot, first_signal

BUS_OFF_MASK = 0x0080
ERROR_WARNING_MASK = 0x0020
ERROR_PASSIVE_MASK = 0x0040
# Stuck At Dominant 1 lives in the CAN *Faults* word, not the status word.
STUCK_DOMINANT_MASK = 0x0008

OK = "ok"
WARNING = "warning"
FAULT = "fault"
UNKNOWN = "unknown"

LEVEL_TONES = {
    OK: "ok",
    WARNING: "warn",
    FAULT: "fault",
    UNKNOWN: "dim",
}

LEVEL_LABELS = {
    OK: "CAN OK",
    WARNING: "CAN degraded",
    FAULT: "CAN bus off",
    UNKNOWN: "CAN —",
}

NO_FEED_NOTE = (
    "The CAN status registers are RS232 Memory View addresses "
    "(CAN_Status 0x00C8, CAN_Faults 0x00C9) — not available on this feed."
)
WAITING_NOTE = "No fresh CAN status reading yet."


@dataclass(frozen=True)
class CanHealth:
    level: str = UNKNOWN
    label: str = LEVEL_LABELS[UNKNOWN]
    note: str = NO_FEED_NOTE
    reasons: tuple[str, ...] = ()
    status_word: int | None = None
    fault_word: int | None = None
    counters: tuple[tuple[str, int], ...] = ()

    @property
    def tone(self) -> str:
        return LEVEL_TONES.get(self.level, "dim")

    @property
    def known(self) -> bool:
        return self.level != UNKNOWN

    @property
    def degraded(self) -> bool:
        return self.level in {WARNING, FAULT}


def _fresh_int(snapshot: StoreSnapshot, symbol: str) -> int | None:
    signal = first_signal(snapshot, symbol) if symbol else None
    if signal is None or signal.raw is None:
        return None
    if signal.stale(snapshot.now):
        return None
    return int(signal.raw)


def _fresh_counter(snapshot: StoreSnapshot, counter: CanErrorCounter) -> int | None:
    signal = first_signal(snapshot, counter.symbol)
    if signal is None or signal.raw is None or signal.stale(snapshot.now):
        return None
    value = int(signal.raw)
    return value if counter.maximum == 0 else min(value, counter.maximum)


def _bit_line(bit: CanStatusBit) -> str:
    description = bit.description.strip().replace("  ", " ")
    return f"{bit.name} — {description}" if description else bit.name


def _bit_by_mask(register, mask: int) -> CanStatusBit | None:
    for bit in register.bits:
        if bit.mask == mask:
            return bit
    return None


def evaluate_can_health(snapshot: StoreSnapshot, catalog: Catalog) -> CanHealth:
    """Level + explanations for the CAN module on this snapshot."""
    can_status = catalog.can_status
    status_register = can_status.register("CAN_Status")
    faults_register = can_status.register("CAN_Faults")
    if status_register is None or faults_register is None:
        return CanHealth()

    status_word = _fresh_int(snapshot, status_register.symbol)
    fault_word = _fresh_int(snapshot, faults_register.symbol)
    if status_word is None and fault_word is None:
        has_memory_view = any(key.startswith("MemoryView.") for key in snapshot.signals)
        return CanHealth(note=WAITING_NOTE if has_memory_view else NO_FEED_NOTE)

    counters: list[tuple[str, int]] = []
    hot_counters: list[CanErrorCounter] = []
    for counter in can_status.counters:
        value = _fresh_counter(snapshot, counter)
        if value is None:
            continue
        counters.append((counter.name, value))
        if counter.warn_at and value >= counter.warn_at:
            hot_counters.append(counter)

    # Triggering bits: Bus Off is a fault, Error Warning / Error Passive and any
    # latched CAN fault bit are warnings. Stuck At Dominant 1 is explained but
    # never triggers on its own (it sets on every power-up).
    warning_bits: list[CanStatusBit] = []
    fault_bits: list[CanStatusBit] = []
    if status_word is not None:
        bus_off = _bit_by_mask(status_register, BUS_OFF_MASK)
        if bus_off is not None and status_word & BUS_OFF_MASK:
            fault_bits.append(bus_off)
        for mask in (ERROR_WARNING_MASK, ERROR_PASSIVE_MASK):
            bit = _bit_by_mask(status_register, mask)
            if bit is not None and status_word & mask:
                warning_bits.append(bit)
    latched_bits: tuple[CanStatusBit, ...] = ()
    if fault_word is not None:
        latched_bits = tuple(
            bit
            for bit in faults_register.active_bits(fault_word)
            if bit.severity in {WARNING, FAULT} and bit.mask != STUCK_DOMINANT_MASK
        )

    if fault_bits:
        level = FAULT
    elif warning_bits or latched_bits or hot_counters:
        level = WARNING
    else:
        level = OK

    reasons: list[str] = [_bit_line(bit) for bit in (*fault_bits, *warning_bits, *latched_bits)]
    for counter in hot_counters:
        value = next(value for name, value in counters if name == counter.name)
        reasons.append(
            f"{counter.name.replace('_', ' ')} at {value} — the module flags a warning at "
            f"{counter.warn_at}."
        )
    if level != OK and fault_word is not None and fault_word & STUCK_DOMINANT_MASK:
        stuck = _bit_by_mask(faults_register, STUCK_DOMINANT_MASK)
        if stuck is not None:
            reasons.append(_bit_line(stuck))

    summary_bits = [
        bit.name
        for bit in (*fault_bits, *warning_bits, *latched_bits)
    ]
    if level == OK:
        note = "No CAN errors: status word clear, fault register clear, counters below 96."
    elif level == FAULT:
        note = "Bus off — no messages can be sent or received until the controller restarts itself."
    else:
        note = " · ".join(summary_bits) or "CAN errors reported on the bus."

    return CanHealth(
        level=level,
        label=LEVEL_LABELS[level],
        note=note,
        reasons=tuple(reasons),
        status_word=status_word,
        fault_word=fault_word,
        counters=tuple(counters),
    )
