from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget

from inverter_monitor.catalog import Catalog
from inverter_monitor.can_health import FAULT, evaluate_can_health
from inverter_monitor.feed import FeedState, feed_state
from inverter_monitor.store import (
    COMMAND_MODE_KEYS,
    StoreSnapshot,
    command_mode,
    first_signal,
    format_value,
    fresh_signal,
)
from inverter_monitor.ui.theme import CARD_MARGINS, set_tone, vsm_tone


class HexSpinBox(QSpinBox):
    """Integer spinner shown as 0x0A0-style hex."""

    def __init__(self, digits: int = 3, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._digits = digits
        self.setPrefix("0x")
        self.setDisplayIntegerBase(16)

    def textFromValue(self, value: int) -> str:  # noqa: N802
        return f"{int(value):0{self._digits}X}"

    def valueFromText(self, text: str) -> int:  # noqa: N802
        cleaned = text.strip()
        if cleaned.lower().startswith("0x"):
            cleaned = cleaned[2:]
        if not cleaned:
            return 0
        return int(cleaned, 16)


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")


class MetricCard(Card):
    def __init__(self, title: str, *keys: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.keys = keys
        self.key = keys[0] if keys else ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*CARD_MARGINS)
        self._title = QLabel(title)
        self._title.setObjectName("muted")
        self._value = QLabel("—")
        self._value.setObjectName("metric")
        self._unit = QLabel("")
        self._unit.setObjectName("unit")
        layout.addWidget(self._title)
        layout.addWidget(self._value)
        layout.addWidget(self._unit)
        layout.addStretch()

    def set_no_data(self, note: str = "") -> None:
        """Present the card as unknown without pretending 0 is a reading."""
        self._value.setText("—")
        self._unit.setText(note)
        set_tone(self._value, "dim")

    def update_from(self, snapshot: StoreSnapshot) -> None:
        signal = first_signal(snapshot, *self.keys) if self.keys else None
        if signal is None or signal.value is None:
            self.set_no_data()
            return
        if signal.stale(snapshot.now):
            # The last number is history; keep the card honest about it.
            self.set_no_data("no live data")
            return
        self._value.setText(format_value(signal, snapshot.now))
        self._unit.setText(signal.unit)
        set_tone(self._value, None)


class FlagChip(QLabel):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self._title = title
        self.setObjectName("flagChip")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_state(None)

    def set_state(self, on: bool | None) -> None:
        if on is None:
            tone, label = "dim", f"{self._title} —"
        elif on:
            alarm = self._title.upper() in {"BMS LIM", "MAX SPD", "LOW SPD", "LOCKOUT", "DISCHARGE"}
            tone, label = ("warn" if alarm else "ok"), f"{self._title} ON"
        else:
            tone, label = "dim", f"{self._title} off"
        self.setText(label)
        set_tone(self, tone)


class StatusStrip(Card):
    def __init__(self, catalog: Catalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self.setObjectName("strip")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(*CARD_MARGINS)

        self.vsm_id = QLabel("—")
        self.vsm_id.setObjectName("vsmId")
        self.vsm_name = QLabel("No data")
        self.vsm_name.setObjectName("vsmName")
        self.vsm_desc = QLabel("")
        self.vsm_desc.setObjectName("muted")
        self.vsm_desc.setWordWrap(True)

        vsm = QVBoxLayout()
        vsm.addWidget(self.vsm_name)
        vsm.addWidget(self.vsm_desc)

        self.enable = QLabel("ENABLE —")
        self.enable.setObjectName("enableState")
        self.mode = QLabel("MODE —")
        self.inv = QLabel("INVERTER —")
        self.source = QLabel("DISCONNECTED")
        self.faults = QLabel("FAULTS —")
        self.faults.setObjectName("faultCount")
        self.rate = QLabel("0 fps")
        for label in (self.enable, self.mode, self.inv, self.source, self.faults, self.rate):
            label.setAlignment(Qt.AlignmentFlag.AlignRight)

        right = QVBoxLayout()
        right.addWidget(self.enable)
        right.addWidget(self.mode)
        right.addWidget(self.inv)

        far = QVBoxLayout()
        far.addWidget(self.faults)
        far.addWidget(self.source)
        far.addWidget(self.rate)

        layout.addWidget(self.vsm_id)
        layout.addSpacing(12)
        layout.addLayout(vsm, 1)
        layout.addLayout(right)
        layout.addSpacing(24)
        layout.addLayout(far)

    def update_from(
        self,
        snapshot: StoreSnapshot,
        source_label: str,
        running: bool,
        lost_reason: str | None = None,
        feed: FeedState | None = None,
    ) -> None:
        feed = feed if feed is not None else feed_state(snapshot, running, lost_reason)
        if not feed.live:
            self._render_no_data(feed)
            return
        vsm = fresh_signal(
            snapshot,
            "M170_Internal_States.D1_VSM_State",
            "MemoryView.VSM_State",
        )
        state_id = int(vsm.raw) if vsm and vsm.raw is not None else None
        self.vsm_id.setText("—" if state_id is None else str(state_id))
        set_tone(self.vsm_id, vsm_tone(state_id))
        self.vsm_name.setText("No VSM yet" if vsm is None else (vsm.enum_name or f"State {state_id}"))
        if vsm and state_id is not None:
            state = self._catalog.vsm_states.get(state_id)
            if state is not None:
                description, _, _ = state.text(command_mode(snapshot))
                self.vsm_desc.setText(description)
            else:
                self.vsm_desc.setText(
                    vsm.enum_description or vsm.enum_name or f"VSM_State = {state_id}"
                )
        elif vsm:
            self.vsm_desc.setText(
                vsm.enum_description or vsm.enum_name or "VSM_State"
            )
        else:
            self.vsm_desc.setText("Waiting for VSM")
        enable = fresh_signal(
            snapshot,
            "M170_Internal_States.D6_Inverter_Enable_State",
            "MemoryView.Inverter_Enable",
        )
        lockout = fresh_signal(snapshot, "M170_Internal_States.D6_Inverter_Enable_Lockout")
        mode = fresh_signal(snapshot, *COMMAND_MODE_KEYS)
        inv = fresh_signal(
            snapshot,
            "M170_Internal_States.D2_Inverter_State",
            "MemoryView.Inverter_Mode",
        )
        if enable is None:
            self.enable.setText("ENABLE —")
            set_tone(self.enable, "dim")
        else:
            enabled = bool(enable.value)
            self.enable.setText("ENABLE ON" if enabled else "ENABLE off")
            set_tone(self.enable, "ok" if enabled else "dim")
            if lockout and lockout.value:
                self.enable.setText("ENABLE LOCKOUT")
                set_tone(self.enable, "fault")
        self.mode.setText(mode.enum_name.replace("_", " ") if mode and mode.enum_name else "MODE —")
        self.inv.setText(inv.enum_name.replace("_", " ") if inv and inv.enum_name else "INVERTER —")
        fault_count = len(snapshot.active_faults)
        can = evaluate_can_health(snapshot, self._catalog)
        text = f"FAULTS {fault_count}"
        tone = "fault" if fault_count else "ok"
        tooltip = ""
        if can.degraded:
            # Same element, no extra badge: POST/RUN faults keep the count, the
            # CAN module's own flag rides along in orange (or red when bus off).
            text = f"{text} · {'CAN BUS OFF' if can.level == FAULT else 'CAN DEGRADED'}"
            tone = "fault" if can.level == FAULT else "warn"
            tooltip = can.note
        self.faults.setText(text)
        set_tone(self.faults, tone)
        self.faults.setToolTip(tooltip)
        self.source.setText(source_label.upper())
        set_tone(self.source, None)
        self.rate.setText(f"{snapshot.frames_per_sec:.0f} fps")

    def _render_no_data(self, feed: FeedState) -> None:
        """No live feed: every status field reads as unknown, never as its last value."""
        self.vsm_id.setText("—")
        set_tone(self.vsm_id, "dim")
        self.vsm_name.setText("No data" if feed.connected else "Not connected")
        self.vsm_desc.setText(feed.reason)
        self.enable.setText("ENABLE —")
        set_tone(self.enable, "dim")
        self.mode.setText("MODE —")
        self.inv.setText("INVERTER —")
        self.faults.setText("FAULTS —")
        set_tone(self.faults, "dim")
        self.faults.setToolTip("")
        self.source.setText(feed.strip_text)
        set_tone(self.source, feed.tone)
        self.rate.setText("0 fps")
