from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from inverter_monitor.calibration import (
    CALIBRATION_WATCH_ADDRESSES,
    DEFAULT_RESOLVER_DELAY,
    DEFAULT_TARGET_RPM,
    DIRECTION_MIN_RPM,
    EEPROM_COMMIT_COMMAND,
    EEPROM_COMMIT_UNLOCK,
    EEPROM_STATE_BUSY,
    GAMMA_ADJUST_ADDRESS,
    GAMMA_ADJUST_EEPROM_ADDRESS,
    RESOLVER_DELAY_COMMAND_ADDRESS,
    RESOLVER_DELAY_EEPROM_ADDRESS,
    CalibrationReading,
    clamp_delay,
    encode_u16,
    gamma_converged,
    gamma_follows_forward,
    gamma_goal_x10,
    inferred_forward,
    next_gamma_adjust,
    read_calibration,
    speeds_agree,
    write_blocked_reason,
)
from inverter_monitor.store import StoreSnapshot
from inverter_monitor.ui.theme import CARD_MARGINS, PAGE_MARGINS, set_tone
from inverter_monitor.ui.widgets import Card, FlagChip


def _how_to(*steps: str) -> QVBoxLayout:
    box = QVBoxLayout()
    box.setContentsMargins(0, 4, 0, 12)
    box.setSpacing(4)
    for index, step in enumerate(steps, start=1):
        label = QLabel(f"{index}.  {step}")
        label.setWordWrap(True)
        box.addWidget(label)
    return box


def _counts(value: int | None) -> str:
    return "not reading" if value is None else str(value)


def _deg_x10(value: int | None) -> str:
    if value is None:
        return "not reading"
    return f"{value}  ({value / 10:.1f}°)"


class _CountsCard(Card):
    """Shows the RMS GUI integer (900, not 90.0°), so the procedure numbers match."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*CARD_MARGINS)
        heading = QLabel(title)
        heading.setObjectName("muted")
        self._value = QLabel("—")
        self._value.setObjectName("metric")
        self._note = QLabel("")
        self._note.setObjectName("unit")
        layout.addWidget(heading)
        layout.addWidget(self._value)
        layout.addWidget(self._note)
        layout.addStretch()

    def set_counts(self, value: int | None, note: str = "") -> None:
        missing = value is None
        self._value.setText("—" if missing else str(value))
        self._note.setText("not available on this source" if missing else note)
        set_tone(self._value, "dim" if missing else None)


class _SessionStrip(Card):
    """Live Memory Values vs EEPROM. No lecture — the two columns are the point."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*CARD_MARGINS)
        layout.setSpacing(6)
        self.summary = QLabel("Memory Values vs EEPROM")
        self.summary.setObjectName("muted")
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(2)
        now_h = QLabel("Now")
        saved_h = QLabel("Saved")
        now_h.setObjectName("muted")
        saved_h.setObjectName("muted")
        delay_h = QLabel("Delay")
        gamma_h = QLabel("Gamma")
        self.delay_now = QLabel("not reading")
        self.delay_ee = QLabel("not reading")
        self.gamma_now = QLabel("not reading")
        self.gamma_ee = QLabel("not reading")
        self.delay_note = QLabel("")
        self.gamma_note = QLabel("")
        self.delay_note.setObjectName("muted")
        self.gamma_note.setObjectName("muted")
        grid.addWidget(now_h, 0, 1)
        grid.addWidget(saved_h, 0, 2)
        grid.addWidget(delay_h, 1, 0)
        grid.addWidget(self.delay_now, 1, 1)
        grid.addWidget(self.delay_ee, 1, 2)
        grid.addWidget(self.delay_note, 1, 3)
        grid.addWidget(gamma_h, 2, 0)
        grid.addWidget(self.gamma_now, 2, 1)
        grid.addWidget(self.gamma_ee, 2, 2)
        grid.addWidget(self.gamma_note, 2, 3)
        grid.setColumnStretch(3, 1)
        layout.addWidget(self.summary)
        layout.addLayout(grid)

    def update_from(self, reading: CalibrationReading) -> None:
        self.delay_now.setText(_counts(reading.delay_command))
        self.delay_ee.setText(_counts(reading.delay_eeprom))
        self.gamma_now.setText(_deg_x10(reading.gamma_adjust_x10))
        self.gamma_ee.setText(_deg_x10(reading.gamma_eeprom_x10))
        self.delay_note.setText(_match_note(reading.delay_matches_eeprom()))
        self.gamma_note.setText(_match_note(reading.gamma_matches_eeprom()))


def _match_note(match: bool | None) -> str:
    if match is True:
        return "same"
    if match is False:
        return "differs"
    return ""


class _StepPage(QWidget):
    def __init__(self, title: str, *steps: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        heading = QLabel(title)
        heading.setObjectName("vsmName")
        inner = QVBoxLayout()
        inner.setContentsMargins(16, 8, 12, 0)
        inner.addWidget(heading)
        if steps:
            inner.addLayout(_how_to(*steps))
        self.body = QVBoxLayout()
        inner.addLayout(self.body)
        inner.addStretch()
        wrap = QWidget()
        wrap.setLayout(inner)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(wrap)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)


class CalibrationPage(QWidget):
    """Guided resolver calibration. Iterate in RAM; EEPROM is an optional last persist."""

    ram_write_requested = Signal(int, int)
    eeprom_commit_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rs232 = False
        self._reading = CalibrationReading()
        self._motion: deque[tuple[int, int]] = deque(maxlen=24)
        self._peak_cos: int | None = None
        self._peak_delay: int | None = None
        self._pending_delay: int | None = None
        self._next_gamma: int | None = None
        self._delta_at_gamma_write: int | None = None
        self._history: list[str] = []

        self.steps = QListWidget()
        self.steps.setFixedWidth(200)
        for label in (
            "1. Setup",
            "2. Resolver delay",
            "3. Direction",
            "4. Gamma adjust",
            "5. EEPROM last",
        ):
            QListWidgetItem(label, self.steps)
        self.steps.setCurrentRow(0)

        self.stack = QStackedWidget()
        self.setup_page = self._build_setup()
        self.delay_page = self._build_delay()
        self.direction_page = self._build_direction()
        self.gamma_page = self._build_gamma()
        self.save_page = self._build_save()
        for page in (
            self.setup_page,
            self.delay_page,
            self.direction_page,
            self.gamma_page,
            self.save_page,
        ):
            self.stack.addWidget(page)
        self.steps.currentRowChanged.connect(self.stack.setCurrentIndex)

        self.session = _SessionStrip()
        self.write_status = QLabel("")
        self.write_status.setWordWrap(True)
        self.write_status.hide()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.steps)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.addWidget(self.session)
        root.addWidget(splitter, 1)
        root.addWidget(self.write_status)
        self._refresh_delay_skip()

    def poll_addresses(self) -> tuple[int, ...]:
        return CALIBRATION_WATCH_ADDRESSES

    @property
    def next_gamma(self) -> int | None:
        return self._next_gamma

    def _build_setup(self) -> _StepPage:
        page = _StepPage(
            "Setup",
            "Start RS232. Wait, enable off.",
            "Motor free to turn. HV phases still connected.",
            "You spin it. The inverter is not driving.",
        )
        self.source_banner = QLabel("Start RS232.")
        self.source_banner.setWordWrap(True)
        self.state_banner = QLabel("")
        self.state_banner.setWordWrap(True)
        self.state_banner.hide()
        self.skip_delay = QCheckBox("SIN/COS encoder — skip resolver delay")
        self.skip_delay.toggled.connect(self._refresh_delay_skip)
        page.body.addWidget(self.source_banner)
        page.body.addWidget(self.state_banner)
        page.body.addWidget(self.skip_delay)
        return page

    def _build_delay(self) -> _StepPage:
        page = _StepPage(
            "Resolver delay",
            "Rotate until Cos corr peaks.",
            "Hold it at that angle.",
            "Nudge delay until Cos corr is highest. 1100 is the usual start.",
        )
        self.cos_card = _CountsCard("Cos corr ×100")
        self.sin_card = _CountsCard("Sin corr ×100")
        self.delay_live = _CountsCard("Delay command")
        row = QHBoxLayout()
        row.addWidget(self.cos_card)
        row.addWidget(self.sin_card)
        row.addWidget(self.delay_live)
        self.peak_label = QLabel("No peak yet")
        self.peak_label.setObjectName("muted")
        self.set_1100_btn = QPushButton("Start at 1100")
        self.set_1100_btn.clicked.connect(lambda: self._write_delay(DEFAULT_RESOLVER_DELAY))
        self.use_peak_btn = QPushButton("Use peak")
        self.use_peak_btn.clicked.connect(self._use_peak_delay)
        self.reset_peak_btn = QPushButton("Reset peak")
        self.reset_peak_btn.clicked.connect(self._reset_peak)
        self._delay_write_buttons = [self.set_1100_btn, self.use_peak_btn]
        nudges = QHBoxLayout()
        for delta in (-100, -10, -1, 1, 10, 100):
            btn = QPushButton(f"{delta:+d}")
            btn.clicked.connect(lambda _checked=False, step=delta: self._nudge_delay(step))
            nudges.addWidget(btn)
            self._delay_write_buttons.append(btn)
        tools = QHBoxLayout()
        tools.addWidget(self.set_1100_btn)
        tools.addWidget(self.use_peak_btn)
        tools.addWidget(self.reset_peak_btn)
        tools.addStretch()
        page.body.addLayout(row)
        page.body.addWidget(self.peak_label)
        page.body.addLayout(nudges)
        page.body.addLayout(tools)
        return page

    def _build_direction(self) -> _StepPage:
        page = _StepPage(
            "Direction",
            "Hand-turn to find forward (speed positive).",
            "Gamma should climb in that direction.",
            "Then a drill, about 300 RPM or more.",
        )
        self.speed_card = _CountsCard("Feedback speed RPM")
        self.voltage_speed_card = _CountsCard("Voltage feedback speed")
        self.gamma_resolver_card = _CountsCard("Gamma resolver ×10")
        row = QHBoxLayout()
        row.addWidget(self.speed_card)
        row.addWidget(self.voltage_speed_card)
        row.addWidget(self.gamma_resolver_card)
        self.forward_chip = FlagChip("FORWARD")
        self.gamma_dir_chip = FlagChip("GAMMA FOLLOWS")
        self.speed_match_chip = FlagChip("SPEEDS AGREE")
        chips = QHBoxLayout()
        chips.addWidget(self.forward_chip)
        chips.addWidget(self.gamma_dir_chip)
        chips.addWidget(self.speed_match_chip)
        chips.addStretch()
        self.direction_detail = QLabel("")
        self.direction_detail.setWordWrap(True)
        self.direction_detail.hide()
        page.body.addLayout(row)
        page.body.addLayout(chips)
        page.body.addWidget(self.direction_detail)
        return page

    def _build_gamma(self) -> _StepPage:
        page = _StepPage(
            "Gamma adjust",
            "Spin up to about 1000 RPM and hold.",
            "Hit Next.",
            "Keep spinning. Hit Next again until Converged.",
        )
        self.delta_card = _CountsCard("Delta resolver ×10")
        self.gamma_card = _CountsCard("Gamma adjust ×10")
        self.gamma_speed_card = _CountsCard("Speed RPM")
        row = QHBoxLayout()
        row.addWidget(self.delta_card)
        row.addWidget(self.gamma_card)
        row.addWidget(self.gamma_speed_card)
        self.forward_radio = QRadioButton("Forward  (+900)")
        self.reverse_radio = QRadioButton("Reverse  (−900)")
        self.forward_radio.setChecked(True)
        self.direction_group = QButtonGroup(self)
        self.direction_group.addButton(self.forward_radio)
        self.direction_group.addButton(self.reverse_radio)
        self.forward_radio.toggled.connect(self._gamma_goal_changed)
        dirs = QHBoxLayout()
        dirs.addWidget(self.forward_radio)
        dirs.addWidget(self.reverse_radio)
        dirs.addStretch()
        self.target_rpm = QSpinBox()
        self.target_rpm.setRange(100, 8000)
        self.target_rpm.setValue(DEFAULT_TARGET_RPM)
        self.target_rpm.valueChanged.connect(self._refresh_gamma_proposal)
        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target RPM"))
        target_row.addWidget(self.target_rpm)
        target_row.addStretch()
        self.gamma_status = QLabel("Waiting for Delta and Gamma.")
        self.gamma_status.setObjectName("muted")
        self.gamma_status.setWordWrap(True)
        self.gamma_converged_chip = FlagChip("CONVERGED")
        self.apply_gamma_btn = QPushButton("Next")
        self.apply_gamma_btn.setObjectName("primary")
        self.apply_gamma_btn.setEnabled(False)
        self.apply_gamma_btn.clicked.connect(self._apply_gamma)
        apply_row = QHBoxLayout()
        apply_row.addWidget(self.apply_gamma_btn)
        apply_row.addWidget(self.gamma_converged_chip)
        apply_row.addStretch()
        self.gamma_log = QTextEdit()
        self.gamma_log.setReadOnly(True)
        self.gamma_log.setMaximumHeight(120)
        page.body.addLayout(row)
        page.body.addLayout(dirs)
        page.body.addLayout(target_row)
        page.body.addWidget(self.gamma_status)
        page.body.addLayout(apply_row)
        page.body.addWidget(self.gamma_log)
        return page

    def _build_save(self) -> _StepPage:
        page = _StepPage(
            "EEPROM",
            "Only if Delay and Gamma need to survive a power cycle.",
            "Wait, enable off, then Program EEPROM.",
            "After: Recycle Power → off 20–30 s → on.",
        )
        self.ram_vs_eeprom = QLabel("Start RS232.")
        self.ram_vs_eeprom.setWordWrap(True)
        self.program_btn = QPushButton("Program EEPROM")
        self.program_btn.setObjectName("danger")
        self.program_btn.setEnabled(False)
        self.program_btn.clicked.connect(self.eeprom_commit_requested.emit)
        page.body.addWidget(self.ram_vs_eeprom)
        page.body.addWidget(self.program_btn)
        return page

    def _refresh_delay_skip(self) -> None:
        skip = self.skip_delay.isChecked()
        item = self.steps.item(1)
        if item is not None:
            item.setText("2. Resolver delay (skip)" if skip else "2. Resolver delay")
        self.delay_page.setEnabled(not skip)

    def _current_delay(self) -> int:
        if self._pending_delay is not None:
            return clamp_delay(self._pending_delay)
        if self._reading.delay_command is not None:
            return clamp_delay(self._reading.delay_command)
        return DEFAULT_RESOLVER_DELAY

    def _nudge_delay(self, step: int) -> None:
        self._write_delay(self._current_delay() + step)

    def _write_delay(self, value: int) -> None:
        delay = clamp_delay(value)
        self._pending_delay = delay
        self.ram_write_requested.emit(RESOLVER_DELAY_COMMAND_ADDRESS, encode_u16(delay))

    def _use_peak_delay(self) -> None:
        if self._peak_delay is None:
            self.write_status.setText("No peak yet.")
            set_tone(self.write_status, "warn")
            self.write_status.show()
            return
        self._write_delay(self._peak_delay)

    def _reset_peak(self) -> None:
        self._peak_cos = None
        self._peak_delay = None
        self.peak_label.setText("Peak cleared")

    def _forward_selected(self) -> bool:
        return self.forward_radio.isChecked()

    def _gamma_goal_changed(self) -> None:
        self._delta_at_gamma_write = None
        self._refresh_gamma_proposal()

    def _gamma_step(self) -> tuple[int | None, str]:
        reading = self._reading
        delta, _source = reading.delta_for_gamma(self.target_rpm.value())
        old = reading.gamma_adjust_x10
        if old is None or delta is None:
            return None, "wait"
        goal = gamma_goal_x10(self._forward_selected())
        nxt = next_gamma_adjust(old, delta, goal)
        if gamma_converged(delta, goal):
            return nxt, "done"
        speed = reading.speed_rpm
        if speed is None or abs(speed) < DIRECTION_MIN_RPM:
            return nxt, "spin"
        if self._delta_at_gamma_write is not None and delta == self._delta_at_gamma_write:
            return nxt, "hold"
        return nxt, "go"

    def _refresh_gamma_proposal(self) -> None:
        nxt, reason = self._gamma_step()
        self._next_gamma = nxt
        if nxt is None:
            self.apply_gamma_btn.setText("Next")
        else:
            self.apply_gamma_btn.setText(f"Next  →  {nxt}")
        notes = {
            "wait": "Waiting for Delta and Gamma.",
            "spin": f"Spin near {self.target_rpm.value()} RPM.",
            "hold": "Keep spinning.",
            "go": "",
            "done": "",
        }
        self.gamma_status.setText(notes.get(reason, ""))
        self.gamma_status.setVisible(bool(notes.get(reason, "")))
        blocked = write_blocked_reason(
            self._reading.vsm, self._reading.enable, self._reading.inverter_mode
        )
        self.apply_gamma_btn.setEnabled(self._rs232 and blocked is None and reason == "go")

    def _apply_gamma(self) -> None:
        nxt, reason = self._gamma_step()
        if nxt is None or reason != "go":
            return
        delta, _source = self._reading.delta_for_gamma(self.target_rpm.value())
        self._delta_at_gamma_write = delta
        self.ram_write_requested.emit(GAMMA_ADJUST_ADDRESS, encode_u16(nxt))
        self._refresh_gamma_proposal()

    def note_write(self, address: int, value: int) -> None:
        signed = value if value < 0x8000 else value - 0x10000
        if address == GAMMA_ADJUST_ADDRESS:
            line = f"Gamma ← {signed}"
        elif address == RESOLVER_DELAY_COMMAND_ADDRESS:
            line = f"Delay ← {value}"
        elif address == GAMMA_ADJUST_EEPROM_ADDRESS:
            line = f"EEPROM Gamma ← {signed}"
        elif address == RESOLVER_DELAY_EEPROM_ADDRESS:
            line = f"EEPROM Delay ← {value}"
        elif address == EEPROM_COMMIT_UNLOCK[0]:
            line = "EEPROM unlock"
        elif address == EEPROM_COMMIT_COMMAND[0]:
            line = "EEPROM program"
        else:
            line = f"Write 0x{address:04X} ← {value}"
        self._history.append(line)
        self.gamma_log.setPlainText("\n".join(self._history[-12:]))

    def set_write_status(self, error: str | None, ok: bool, *, kind: str = "ram") -> None:
        if error:
            self.write_status.setText(error)
            set_tone(self.write_status, "fault")
            self.write_status.show()
            return
        if ok and kind == "eeprom":
            self.write_status.setText("Programming.")
            set_tone(self.write_status, "ok")
            self.write_status.show()
            return
        if ok:
            self.write_status.setText("Written.")
            set_tone(self.write_status, "ok")
            self.write_status.show()
            return
        self.write_status.hide()
        set_tone(self.write_status, None)

    def update_from(self, snapshot: StoreSnapshot, source: str, rs232: bool) -> None:
        self._rs232 = rs232
        reading = read_calibration(snapshot)
        self._reading = reading
        if source == "RS232" and rs232:
            self.source_banner.hide()
        elif source == "RS232":
            self.source_banner.setText("Start RS232")
            set_tone(self.source_banner, "warn")
            self.source_banner.show()
        else:
            self.source_banner.setText("Writes need RS232")
            set_tone(self.source_banner, "warn")
            self.source_banner.show()

        blocked = write_blocked_reason(reading.vsm, reading.enable, reading.inverter_mode)
        if blocked:
            self.state_banner.setText(blocked)
            set_tone(self.state_banner, "fault")
            self.state_banner.show()
        else:
            self.state_banner.hide()
            set_tone(self.state_banner, None)

        for btn in self._delay_write_buttons:
            btn.setEnabled(rs232 and blocked is None)

        self._update_delay_metrics(reading)
        self._update_direction(reading)
        self._update_gamma(reading)
        self._update_save(reading)
        self.session.update_from(reading)

    def _update_delay_metrics(self, reading: CalibrationReading) -> None:
        self.cos_card.set_counts(reading.cos_corr_x100)
        self.sin_card.set_counts(reading.sin_corr_x100)
        self.delay_live.set_counts(reading.delay_command)
        if self._pending_delay is not None and reading.delay_command == self._pending_delay:
            self._pending_delay = None
        if (
            reading.cos_corr_x100 is not None
            and reading.delay_command is not None
            and (self._peak_cos is None or reading.cos_corr_x100 > self._peak_cos)
        ):
            self._peak_cos = reading.cos_corr_x100
            self._peak_delay = reading.delay_command
        if self._peak_cos is None:
            self.peak_label.setText("No peak yet")
        else:
            self.peak_label.setText(f"Peak {self._peak_cos} at delay {self._peak_delay}")

    def _update_direction(self, reading: CalibrationReading) -> None:
        self.speed_card.set_counts(reading.speed_rpm)
        self.voltage_speed_card.set_counts(reading.voltage_speed_rpm)
        self.gamma_resolver_card.set_counts(reading.gamma_resolver_x10)
        forward = inferred_forward(reading.speed_rpm)
        self.forward_chip.set_state(forward)
        if (
            reading.speed_rpm is not None
            and reading.gamma_resolver_x10 is not None
            and abs(reading.speed_rpm) >= 5
        ):
            self._motion.append((reading.speed_rpm, reading.gamma_resolver_x10))
        follows = gamma_follows_forward(list(self._motion))
        self.gamma_dir_chip.set_state(follows)
        match_text = speeds_agree(reading.speed_rpm, reading.voltage_speed_rpm)
        if match_text.endswith("agree."):
            match_state: bool | None = True
        elif "Waiting" in match_text or "RS232" in match_text or "Spin faster" in match_text:
            match_state = None
        else:
            match_state = False
        self.speed_match_chip.set_state(match_state)
        bits: list[str] = []
        if match_state is False or "Spin faster" in match_text:
            bits.append(match_text)
        if follows is False:
            bits.append("Gamma does not follow forward.")
        text = " ".join(bits)
        self.direction_detail.setText(text)
        self.direction_detail.setVisible(bool(text))

    def _update_gamma(self, reading: CalibrationReading) -> None:
        delta, source = reading.delta_for_gamma(self.target_rpm.value())
        self.delta_card.set_counts(delta, source)
        self.gamma_card.set_counts(reading.gamma_adjust_x10)
        self.gamma_speed_card.set_counts(reading.speed_rpm)
        goal = gamma_goal_x10(self._forward_selected())
        self.gamma_converged_chip.set_state(None if delta is None else gamma_converged(delta, goal))
        self._refresh_gamma_proposal()

    def _update_save(self, reading: CalibrationReading) -> None:
        busy = reading.eeprom_state == EEPROM_STATE_BUSY
        eeprom_blocked = write_blocked_reason(
            reading.vsm, reading.enable, reading.inverter_mode, kind="eeprom"
        )
        have_ram = reading.delay_command is not None and reading.gamma_adjust_x10 is not None
        can_program = self._rs232 and eeprom_blocked is None and have_ram and not busy
        if busy:
            status = "Programming."
        elif not self._rs232:
            status = "Start RS232."
        elif eeprom_blocked:
            status = eeprom_blocked
        elif not have_ram:
            status = "Waiting for Delay and Gamma."
        else:
            status = ""
        self.ram_vs_eeprom.setText(status)
        self.ram_vs_eeprom.setVisible(bool(status))
        self.program_btn.setEnabled(can_program)
        self.program_btn.setToolTip(status)
