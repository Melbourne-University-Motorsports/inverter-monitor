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
from inverter_monitor.store import StoreSnapshot, get_signal
from inverter_monitor.ui.theme import (
    ACCENT,
    BORDER,
    DIM,
    FAULT,
    OK,
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


def _severity_color(severity: str) -> str:
    if severity == "warning":
        return WARN
    if severity == "info":
        return DIM
    return FAULT


def _bank(bit: int | FaultBit) -> str:
    number = bit.bit if isinstance(bit, FaultBit) else bit
    return "POST" if number < 32 else "RUN"


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
        self.setToolTip("POST bits 0–31, RUN bits 32–63. Click a cell for the name.")

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
            self.setToolTip("POST bits 0–31, RUN bits 32–63. Click a cell for the name.")
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        self._hover = None
        self.update()
        super().leaveEvent(event)


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

        self.headline = QLabel("NO DATA")
        self.headline.setObjectName("faultHeadline")
        set_tone(self.headline, "dim")
        self.counts = QLabel("Connect a source — fault words update live.")
        self.counts.setObjectName("muted")
        self.counts.setWordWrap(True)

        self.live_label = QLabel("Live")
        self.live_label.setObjectName("liveBadge")
        set_tone(self.live_label, "ok")
        self.auto_refresh = QCheckBox("Auto-refresh")
        self.auto_refresh.setChecked(True)
        self.auto_refresh.setToolTip("On: follow the inverter. Off: freeze this page.")
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setVisible(False)
        self.clear_btn = QPushButton("Clear faults")
        self.clear_btn.setObjectName("danger")
        self.clear_btn.setEnabled(False)
        self.clear_btn.setToolTip("Send Clear Faults Command (value 0). Confirm in the dialog.")
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
        map_card = Card()
        map_layout = QVBoxLayout(map_card)
        map_layout.setContentsMargins(14, 10, 14, 10)
        map_hint = QLabel("POST 0–31  RUN 32–63")
        map_hint.setObjectName("muted")
        map_layout.addWidget(map_hint)
        map_layout.addWidget(self.bitmap)
        map_layout.addWidget(self.command_status)

        self.active = QTableWidget(0, 3)
        self.active.setHorizontalHeaderLabels(["", "Name", "Bit"])
        self.active.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.active.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.active.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.active.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.active.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.active.verticalHeader().setVisible(False)
        self.active.setShowGrid(False)
        self.active.setMinimumHeight(120)

        self.empty = QLabel("No active faults.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setObjectName("emptyState")
        set_tone(self.empty, "ok")

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Select a bit or an active fault.")
        self.detail.setMaximumHeight(120)

        self.history = QTableWidget(0, 3)
        self.history.setHorizontalHeaderLabels(["Time", "", "Name"])
        self.history.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.history.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.history.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.history.verticalHeader().setVisible(False)
        self.history.setShowGrid(False)
        self.history.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.history.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        left = QVBoxLayout()
        active_title = QLabel("Active")
        active_title.setObjectName("muted")
        left.addWidget(active_title)
        left.addWidget(self.empty)
        left.addWidget(self.active, 1)
        left.addWidget(self.detail)
        left_wrap = QWidget()
        left_wrap.setLayout(left)

        right = QVBoxLayout()
        hist_title = QLabel("History")
        hist_title.setObjectName("muted")
        right.addWidget(hist_title)
        right.addWidget(self.history, 1)
        right_wrap = QWidget()
        right_wrap.setLayout(right)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_wrap)
        splitter.addWidget(right_wrap)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.addLayout(head)
        root.addWidget(map_card)
        root.addWidget(splitter, 1)

        self.auto_refresh.toggled.connect(self._auto_toggled)
        self.refresh_btn.clicked.connect(self._refresh_clicked)
        self.clear_btn.clicked.connect(self.clear_requested.emit)
        self.bitmap.bit_clicked.connect(self._select_bit)
        self.active.itemSelectionChanged.connect(self._active_selection_changed)

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self.clear_btn.setEnabled(connected)
        if not connected and not self.command_status.text():
            self.command_status.setText("Start a source to clear faults.")

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
        if not has_feed and not faults:
            self.headline.setText("NO DATA")
            set_tone(self.headline, "dim")
            self.counts.setText("Waiting for M171 or RS232 fault words.")
        elif not faults:
            self.headline.setText("ALL CLEAR")
            set_tone(self.headline, "ok")
            self.counts.setText("POST and RUN words are zero.")
        else:
            label = "1 FAULT" if len(faults) == 1 else f"{len(faults)} FAULTS"
            self.headline.setText(label)
            set_tone(self.headline, "fault")
            parts = []
            if post_n:
                parts.append(f"{post_n} POST")
            if run_n:
                parts.append(f"{run_n} RUN")
            latching = sum(1 for bit in faults if bit.latching)
            if latching:
                parts.append(f"{latching} latching — needs power cycle")
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
