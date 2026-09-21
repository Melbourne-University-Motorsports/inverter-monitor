from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from inverter_monitor.catalog import Catalog, FaultBit
from inverter_monitor.can_health import evaluate_can_health
from inverter_monitor.store import StoreSnapshot, get_signal
from inverter_monitor.ui.theme import (
    ACCENT,
    BORDER,
    CARD_MARGINS,
    DIM,
    FAULT,
    OK,
    PAGE_MARGINS,
    PANEL_ALT,
    TEXT,
    WARN,
    mono_font,
    set_tone,
)
from inverter_monitor.ui.widgets import Card

_BIT_ROLE = Qt.ItemDataRole.UserRole
_FAULT_FEED_KEYS = (
    "M171_Fault_Codes.D1_Post_Fault_Lo",
    "M171_Fault_Codes.D3_Run_Fault_Lo",
    "MemoryView.Post_Fault_Lo",
    "MemoryView.Run_Fault_Lo",
)
_LABEL_W = 46
_HEX_W = 78
_BIT_SIZE = 13
_BIT_GAP = 3
_BANK_GAP = 10
_ROW_H = 26
# Rows the Active list shows before it starts scrolling — the list must not
# reserve space it has no rows for.
_ACTIVE_ROWS_VISIBLE = 8


def _severity_color(severity: str) -> str:
    if severity == "warning":
        return WARN
    if severity == "info":
        return DIM
    return FAULT


def _bank(bit: int | FaultBit) -> str:
    number = bit.bit if isinstance(bit, FaultBit) else bit
    return "POST" if number < 32 else "RUN"


def _counter_label(name: str) -> str:
    short = name.removeprefix("CAN_").replace("_Error_Counter", "")
    return short.replace("_(Max)", " (max)") or name


def _can_value_text(health) -> str:
    """Labeled raw words and error counters, e.g. 'Status 0020h · Faults (sticky) 0003h · Tx 12'."""
    if not health.known:
        return ""
    parts: list[str] = []
    if health.status_word is not None:
        parts.append(f"Status {health.status_word:04X}h")
    if health.fault_word is not None:
        parts.append(f"Faults (sticky) {health.fault_word:04X}h")
    parts.extend(f"{_counter_label(name)} {value}" for name, value in health.counters)
    return "   ".join(parts)


class FaultBitMap(QWidget):
    """Two-row POST/RUN map. Color is the severity; the table does not need a Sev column."""

    bit_clicked = Signal(int)

    def __init__(self, catalog: Catalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self._active: frozenset[int] = frozenset()
        self._selected: int | None = None
        self._hover: int | None = None
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(_ROW_H * 2 + 8)
        self.setMinimumWidth(_LABEL_W + 32 * (_BIT_SIZE + _BIT_GAP) + _BANK_GAP + _HEX_W)

    def set_state(self, active: set[int] | frozenset[int], selected: int | None) -> None:
        next_active = frozenset(active)
        if next_active == self._active and selected == self._selected:
            return
        self._active = next_active
        self._selected = selected
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        packed_post = 0
        packed_run = 0
        for bit in self._active:
            if bit < 32:
                packed_post |= 1 << bit
            elif bit < 64:
                packed_run |= 1 << (bit - 32)
        self._paint_row(painter, 0, "POST", 0, packed_post)
        self._paint_row(painter, 1, "RUN", 32, packed_run)
        painter.end()

    def _paint_row(self, painter: QPainter, row: int, label: str, origin: int, word: int) -> None:
        y = 4 + row * _ROW_H
        painter.setPen(QColor(DIM))
        painter.setFont(mono_font(11))
        painter.drawText(QRect(0, y, _LABEL_W, _ROW_H), Qt.AlignmentFlag.AlignVCenter, label)
        for index in range(32):
            bit = origin + index
            rect = self._bit_rect(row, index)
            spec = self._catalog.fault_bits.get(bit)
            active = bit in self._active
            if active and spec:
                fill = QColor(_severity_color(spec.severity))
            elif spec and spec.severity == "info":
                fill = QColor(BORDER)
            else:
                fill = QColor(PANEL_ALT)
            painter.setBrush(QBrush(fill))
            if bit == self._selected:
                painter.setPen(QPen(QColor(TEXT), 1.5))
            elif bit == self._hover:
                painter.setPen(QPen(QColor(ACCENT), 1))
            else:
                painter.setPen(QPen(QColor(BORDER), 1))
            painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(QColor(FAULT if word else OK))
        painter.setFont(mono_font(12))
        hex_x = self._hex_x()
        painter.drawText(
            QRect(hex_x, y, _HEX_W, _ROW_H),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            f"{word:08X}",
        )

    def _hex_x(self) -> int:
        return _LABEL_W + 32 * (_BIT_SIZE + _BIT_GAP) + _BANK_GAP

    def _bit_rect(self, row: int, index: int) -> QRect:
        bank = 1 if index >= 16 else 0
        col = index % 16
        x = _LABEL_W + bank * (16 * (_BIT_SIZE + _BIT_GAP) + _BANK_GAP) + col * (_BIT_SIZE + _BIT_GAP)
        y = 4 + row * _ROW_H + (_ROW_H - _BIT_SIZE) // 2
        return QRect(x, y, _BIT_SIZE, _BIT_SIZE)

    def _bit_at(self, pos) -> int | None:
        for row in range(2):
            for index in range(32):
                if self._bit_rect(row, index).contains(pos):
                    return row * 32 + index
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        bit = self._bit_at(event.position().toPoint())
        if bit is not None:
            self.bit_clicked.emit(bit)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        bit = self._bit_at(event.position().toPoint())
        if bit == self._hover:
            return
        self._hover = bit
        spec = self._catalog.fault_bits.get(bit) if bit is not None else None
        if spec:
            extra = " · active" if bit in self._active else ""
            latch = " · latching" if spec.latching else ""
            self.setToolTip(f"{_bank(spec)} bit {spec.bit}  {spec.name}{latch}{extra}")
        else:
            self.setToolTip("")
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        self._hover = None
        self.update()
        super().leaveEvent(event)


class _CanChip(QLabel):
    """Clickable CAN chip — clicking puts the full annotated text into the
    parent page's detail pane."""

    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: ARG002
        self.clicked.emit()
        super().mousePressEvent(event)


class _CanStatusSection(Card):
    """The CAN module's own card: heading + chip + one-line summary + raw words.

    Kept terse by design — detailed explanations are one click away on the chip
    (which routes the full annotated text into the detail pane) rather than
    living in the always-on card.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*CARD_MARGINS)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("CAN FAULTS (Gen 3 Memory View)")
        self.title.setObjectName("muted")
        head.addWidget(self.title, 1)
        self.hint = QLabel("click chip for details")
        self.hint.setObjectName("muted")
        head.addWidget(self.hint)
        layout.addLayout(head)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.chip = _CanChip("CAN —")
        self.chip.setObjectName("flagChip")
        self.chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.chip)
        top.addStretch(1)
        self.values = QLabel("")
        self.values.setFont(mono_font(11))
        set_tone(self.values, "dim")
        top.addWidget(self.values)
        layout.addLayout(top)
        # The summary gets the card's full width — sharing the chip row squeezed
        # it into a three-word column.
        self.note = QLabel("")
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)



class FaultsPage(QWidget):
    clear_requested = Signal()

    def __init__(self, catalog: Catalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self._snapshot: StoreSnapshot | None = None
        self._connected = False
        self._selected_bit: int | None = None
        self._active_ids: tuple[int, ...] = ()
        self._history_key: tuple[tuple[float, int, bool], ...] = ()
        self._can_health = None

        self.headline = QLabel("NO DATA")
        self.headline.setObjectName("faultHeadline")
        set_tone(self.headline, "dim")
        self.counts = QLabel("")
        self.counts.setObjectName("muted")
        self.counts.setWordWrap(True)

        self.live_label = QLabel("Live")
        self.live_label.setObjectName("liveBadge")
        set_tone(self.live_label, "ok")
        self.auto_refresh = QCheckBox("Auto-refresh")
        self.auto_refresh.setChecked(True)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setVisible(False)
        self.clear_btn = QPushButton("Clear faults")
        self.clear_btn.setObjectName("danger")
        self.clear_btn.setEnabled(False)
        self.command_status = QLabel("")
        set_tone(self.command_status, "dim")

        tools = QHBoxLayout()
        tools.addWidget(self.live_label)
        tools.addWidget(self.auto_refresh)
        tools.addWidget(self.refresh_btn)
        tools.addWidget(self.clear_btn)

        head = QHBoxLayout()
        title = QVBoxLayout()
        title.addWidget(self.headline)
        title.addWidget(self.counts)
        head.addLayout(title, 1)
        head.addLayout(tools)

        self.bitmap = FaultBitMap(catalog)
        self.map_heading = QLabel("INVERTER FAULTS (POST / RUN)")
        self.map_heading.setObjectName("muted")

        self.can_section = _CanStatusSection()

        map_card = Card()
        map_layout = QVBoxLayout(map_card)
        map_layout.setContentsMargins(*CARD_MARGINS)
        map_layout.addWidget(self.map_heading)
        map_layout.addWidget(self.bitmap)
        map_layout.addStretch(1)
        map_layout.addWidget(self.command_status)

        # Inverter faults and CAN faults are separate subsystems — one card each
        # rather than one card with a CAN block bolted to the bottom.
        cards = QHBoxLayout()
        cards.setSpacing(8)
        cards.addWidget(map_card, 3)
        cards.addWidget(self.can_section, 2)

        self.active = QTableWidget(0, 3)
        self.active.setHorizontalHeaderLabels(["", "Name", "Bit"])
        self.active.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.active.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.active.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.active.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.active.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.active.verticalHeader().setVisible(False)
        self.active.setShowGrid(False)
        self.active.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.empty = QLabel("No active inverter faults.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setObjectName("emptyState")
        set_tone(self.empty, "ok")

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText(
            "Click a bit in the map or the CAN chip to see the explanation here."
        )

        self.history = QTableWidget(0, 3)
        self.history.setHorizontalHeaderLabels(["Time", "", "Name"])
        self.history.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.history.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.history.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.history.verticalHeader().setVisible(False)
        self.history.setShowGrid(False)
        self.history.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.history.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Left column: the active list only ever takes the height its rows need
        # (see _fit_active_height) and the log below it absorbs the slack.
        # Right column: one full-height Details pane, so a 5-bullet CAN or bit
        # explanation reads without a scrollbar.
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)
        active_title = QLabel("Active")
        active_title.setObjectName("muted")
        left.addWidget(active_title)
        left.addWidget(self.empty)
        left.addWidget(self.active)
        hist_title = QLabel("History")
        hist_title.setObjectName("muted")
        left.addWidget(hist_title)
        left.addWidget(self.history, 1)
        left_wrap = QWidget()
        left_wrap.setLayout(left)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(6)
        detail_title = QLabel("Details")
        detail_title.setObjectName("muted")
        right.addWidget(detail_title)
        right.addWidget(self.detail, 1)
        right_wrap = QWidget()
        right_wrap.setLayout(right)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_wrap)
        splitter.addWidget(right_wrap)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.addLayout(head)
        root.addLayout(cards)
        root.addWidget(splitter, 1)

        self.auto_refresh.toggled.connect(self._auto_toggled)
        self.refresh_btn.clicked.connect(self._refresh_clicked)
        self.clear_btn.clicked.connect(self.clear_requested.emit)
        self.bitmap.bit_clicked.connect(self._select_bit)
        self.active.itemSelectionChanged.connect(self._active_selection_changed)
        self.can_section.chip.clicked.connect(self._show_can_detail)

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self.clear_btn.setEnabled(connected)

    def set_command_status(self, text: str, ok: bool = True) -> None:
        self.command_status.setText(text)
        set_tone(self.command_status, "ok" if ok else "fault")

    def update_from(self, snapshot: StoreSnapshot) -> None:
        self._snapshot = snapshot
        if self.auto_refresh.isChecked():
            self._render(snapshot)

    def _auto_toggled(self, checked: bool) -> None:
        self.refresh_btn.setVisible(not checked)
        self.live_label.setText("Live" if checked else "Paused")
        set_tone(self.live_label, "ok" if checked else "warn")
        if checked and self._snapshot is not None:
            self._render(self._snapshot)

    def _refresh_clicked(self) -> None:
        if self._snapshot is not None:
            self._render(self._snapshot)

    def _render(self, snapshot: StoreSnapshot) -> None:
        faults = snapshot.active_faults
        post_n = sum(1 for bit in faults if bit.bit < 32)
        run_n = len(faults) - post_n
        has_feed = any(get_signal(snapshot, key) for key in _FAULT_FEED_KEYS)
        can = evaluate_can_health(snapshot, self._catalog)
        self._can_health = can

        fault_text: str
        fault_tone: str
        if not has_feed and not faults:
            fault_text, fault_tone = "NO DATA", "dim"
        elif not faults:
            fault_text, fault_tone = "ALL CLEAR", "ok"
        else:
            fault_text = "1 FAULT" if len(faults) == 1 else f"{len(faults)} FAULTS"
            fault_tone = "fault"

        # With no inverter faults, a degraded CAN leads the headline rather than
        # hiding behind "ALL CLEAR". With faults, the fault count leads and the
        # CAN story stays in the sub-line.
        if can.degraded and not faults:
            self.headline.setText(can.label)
            set_tone(self.headline, can.tone)
        else:
            self.headline.setText(fault_text)
            set_tone(self.headline, fault_tone)

        parts = []
        if not has_feed and not faults:
            parts.append("No CAN notes, no fault words — nothing to report.")
        elif not faults:
            parts.append("No inverter faults (POST/RUN all clear)")
        else:
            if post_n:
                parts.append(f"{post_n} POST")
            if run_n:
                parts.append(f"{run_n} RUN")
            latching = sum(1 for bit in faults if bit.latching)
            if latching:
                parts.append(f"{latching} latching — needs power cycle")
        if can.degraded:
            parts.append(f"CAN: {can.note}")
        self.counts.setText(" · ".join(parts))

        active_ids = tuple(bit.bit for bit in faults)
        self.bitmap.set_state(set(active_ids), self._selected_bit)
        if active_ids != self._active_ids:
            self._active_ids = active_ids
            self._fill_active(faults)
        self.empty.setVisible(not faults)
        self.active.setVisible(bool(faults))

        history_key = tuple((event.timestamp, event.bit, event.active) for event in snapshot.fault_history)
        if history_key != self._history_key:
            self._history_key = history_key
            self._fill_history(snapshot)

        if self._selected_bit is not None:
            self._show_detail(self._selected_bit, set(active_ids))
        elif faults:
            self._show_detail(faults[0].bit, set(active_ids))
        # Detail stays untouched when nothing is selected — the user may have
        # clicked a bit and we must not blank it on every refresh.

        self._render_can_section(can)

    def _render_can_section(self, can) -> None:
        """Fill the labeled CAN module block: chip, short summary, raw words.

        Kept terse — long explanations live in the detail pane via the chip's
        click, not in this always-on band."""
        section = self.can_section
        section.chip.setText(can.label)
        set_tone(section.chip, can.tone)
        # Tint the block only when there is something to say — healthy CAN
        # keeps the default quiet border so it does not draw the eye.
        set_tone(section, can.tone if can.degraded else None)
        section.note.setText(can.note)

        values = _can_value_text(can)
        section.values.setText(values)
        section.values.setVisible(bool(values))
    def _show_can_detail(self) -> None:  # kept for any external callers/tests
        health = self._can_health
        if health is None:
            return
        lines = [health.label, health.note, ""]
        values = _can_value_text(health)
        if values:
            lines.extend([values, ""])
        if health.reasons:
            lines.extend(f"• {reason}" for reason in health.reasons)
        elif health.known:
            lines.append("No CAN errors on the bus right now.")
        lines.extend(
            [
                "",
                f"CAN_Status 0x00C8 and CAN_Faults 0x00C9 are shadow registers of the CAN module",
                f"(CAN Protocol {self._catalog.can_status.source}).",
            ]
        )
        applies_to = self._catalog.can_status.applies_to
        if applies_to:
            lines.append(f"{applies_to} map — Gen 5/CM reports the same things as separate watch items.")
        lines.append("Latched CAN fault bits clear with Clear Faults, like POST/RUN faults.")
        self.detail.setPlainText("\n".join(lines))

    def _fill_active(self, faults: tuple[FaultBit, ...]) -> None:
        selected = self._selected_bit
        self.active.blockSignals(True)
        self.active.setRowCount(len(faults))
        restore: int | None = None
        for row, bit in enumerate(faults):
            color = QColor(_severity_color(bit.severity))
            values = [_bank(bit), bit.name, str(bit.bit)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setData(_BIT_ROLE, bit.bit)
                item.setForeground(QBrush(color))
                if column == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.active.setItem(row, column, item)
            if bit.bit == selected:
                restore = row
        if restore is not None:
            self.active.selectRow(restore)
        else:
            self.active.clearSelection()
        self.active.blockSignals(False)
        self._fit_active_height()

    def _fit_active_height(self) -> None:
        """Size the active list to its rows (scrolls past _ACTIVE_ROWS_VISIBLE)."""
        rows = max(1, min(self.active.rowCount(), _ACTIVE_ROWS_VISIBLE))
        row_h = self.active.verticalHeader().defaultSectionSize()
        frame = 2 * self.active.frameWidth()
        self.active.setFixedHeight(self.active.horizontalHeader().height() + rows * row_h + frame + 2)

    def _fill_history(self, snapshot: StoreSnapshot) -> None:
        events = list(reversed(snapshot.fault_history))
        self.history.setRowCount(len(events))
        if not events:
            self.history.setRowCount(1)
            empty = QTableWidgetItem("No edges yet.")
            empty.setFlags(empty.flags() & ~Qt.ItemFlag.ItemIsEditable)
            empty.setForeground(QBrush(QColor(DIM)))
            self.history.setItem(0, 0, empty)
            self.history.setItem(0, 1, QTableWidgetItem(""))
            self.history.setItem(0, 2, QTableWidgetItem(""))
            return
        for row, event in enumerate(events):
            stamp = datetime.fromtimestamp(event.timestamp)
            verb = "SET" if event.active else "CLR"
            color = QColor(_severity_color(event.severity) if event.active else OK)
            values = [f"{stamp:%H:%M:%S}", verb, event.name]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setForeground(QBrush(color))
                self.history.setItem(row, column, item)

    def _active_selection_changed(self) -> None:
        items = self.active.selectedItems()
        if not items:
            return
        bit = items[0].data(_BIT_ROLE)
        if bit is None:
            return
        self._select_bit(int(bit))

    def _select_bit(self, bit: int) -> None:
        self._selected_bit = bit
        active_ids = set(self._active_ids)
        self.bitmap.set_state(active_ids, bit)
        self.active.blockSignals(True)
        for row in range(self.active.rowCount()):
            item = self.active.item(row, 0)
            if item and item.data(_BIT_ROLE) == bit:
                self.active.selectRow(row)
                break
        else:
            self.active.clearSelection()
        self.active.blockSignals(False)
        self._show_detail(bit, active_ids)

    def _show_detail(self, bit: int, active_ids: set[int]) -> None:
        spec = self._catalog.fault_bits.get(bit)
        if spec is None:
            self.detail.setPlainText(f"Bit {bit} is not in the catalog.")
            return
        state = "ACTIVE" if bit in active_ids else "clear"
        lines = [
            f"{spec.name}",
            f"{_bank(spec)} bit {spec.bit}  ·  {state}  ·  {spec.severity}",
        ]
        if spec.latching:
            lines.append("Latching — Clear Faults will not drop this; recycle power.")
        if spec.notes:
            lines.append(spec.notes)
        if spec.description:
            lines.append("")
            lines.append(spec.description)
        self.detail.setPlainText("\n".join(lines))
