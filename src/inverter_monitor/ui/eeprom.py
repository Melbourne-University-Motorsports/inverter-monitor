from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from inverter_monitor.catalog import Catalog
from inverter_monitor.memory_map import (
    EEPROM_GROUP_ORDER,
    DumpProgress,
    MemorySymbol,
    decode_raw,
    edit_unit,
    format_engineering,
    parse_engineering,
    parse_raw_word,
    snapshot_symbols,
)
from inverter_monitor.store import SignalSnapshot, StoreSnapshot
from inverter_monitor.ui.symbol_widgets import GroupedSymbolTree
from inverter_monitor.ui.theme import FAULT, OK, PAGE_MARGINS, set_tone
from inverter_monitor.ui.widgets import Card

DIRTY_BG = QColor("#5a2228")
DIRTY_TIP = "Edited — not yet on the inverter. Push to flash it."


def describe_word(symbol: MemorySymbol, raw_u16: int | None) -> str:
    """Plain-language word value, e.g. "0.5 V (0x0005)" or "not read yet". """
    if raw_u16 is None:
        return "not read yet"
    value, raw = _edited_texts(symbol, int(raw_u16) & 0xFFFF, 0.0)
    if symbol.display == "hex":
        return raw
    unit = edit_unit(symbol)
    return f"{value} {unit} ({raw})" if unit else f"{value} ({raw})"


@dataclass(frozen=True)
class EepromPushStep:
    address: int
    label: str
    detail: str


class EepromPushDialog(QDialog):
    """Per-word progress for a Push, then the power-recycle prompt."""

    cancel_requested = Signal()
    done_requested = Signal()

    def __init__(self, parent: QWidget | None, steps: list[EepromPushStep]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pushing to inverter")
        self.setMinimumWidth(560)
        self._rows: dict[int, int] = {}

        intro = QLabel(
            f"Flashing {max(len(steps) - 2, 0)} edited words, then programming EEPROM."
        )
        intro.setWordWrap(True)

        self.table = QTableWidget(len(steps), 3)
        self.table.setHorizontalHeaderLabels(["Word", "Change", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for row, step in enumerate(steps):
            self.table.setItem(row, 0, QTableWidgetItem(step.label))
            self.table.setItem(row, 1, QTableWidgetItem(step.detail))
            self.table.setItem(row, 2, QTableWidgetItem("Queued"))
            self._rows[step.address] = row

        self.progress = QProgressBar()
        self.progress.setRange(0, len(steps))
        self.progress.setValue(0)

        self.status = QLabel("Starting…")
        self.status.setWordWrap(True)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        self.done_btn = QPushButton("Done")
        self.done_btn.setObjectName("primary")
        self.done_btn.setEnabled(False)
        self.done_btn.clicked.connect(self.done_requested.emit)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.done_btn)

        root = QVBoxLayout(self)
        root.addWidget(intro)
        root.addWidget(self.table, 1)
        root.addWidget(self.progress)
        root.addWidget(self.status)
        root.addLayout(buttons)

    def set_step_status(self, address: int, text: str, ok: bool | None) -> None:
        row = self._rows.get(int(address))
        if row is None:
            return
        item = QTableWidgetItem(text)
        if ok is True:
            item.setForeground(QBrush(QColor(OK)))
        elif ok is False:
            item.setForeground(QBrush(QColor(FAULT)))
        self.table.setItem(row, 2, item)
        self.progress.setValue(self.progress.value() + 1)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def finish(self, text: str) -> None:
        self.status.setText(text)
        self.done_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)


def _edited_texts(symbol: MemorySymbol, raw_u16: int, now: float) -> tuple[str, str]:
    """Value/raw strings for a pending edit, formatted like a live signal."""
    from inverter_monitor.store import format_value

    decoded = decode_raw(symbol, raw_u16)
    signal = SignalSnapshot(
        key=symbol.key,
        message="MemoryView",
        signal=symbol.name,
        value=decoded,  # type: ignore[arg-type]
        raw=int(raw_u16) & 0xFFFF,
        unit=symbol.unit,
        kind="hex" if symbol.display == "hex" else "number",
        last_seen=now,
    )
    return format_value(signal, now), f"0x{int(raw_u16) & 0xFFFF:04X}"


class EepromPage(QWidget):
    """EEPROM words. Pulled once on RS232 connect; edits flash via Push."""

    pull_requested = Signal()
    push_requested = Signal()
    single_read_requested = Signal(int)

    def __init__(self, catalog: Catalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self._symbols = snapshot_symbols(catalog.memory_symbols)
        self._by_address = {symbol.address: symbol for symbol in self._symbols}
        self._rs232 = False
        self._loaded = 0
        self._pending: dict[int, int] = {}
        self._baseline: dict[int, int] = {}
        self._highlighted: set[int] = set()
        self._selected: int | None = None
        self._syncing = False

        self.pull_btn = QPushButton("Pull from inverter")
        self.pull_btn.setToolTip("Re-read all EEPROM words. Keeps your unflashed edits.")
        self.pull_btn.clicked.connect(self.pull_requested.emit)
        self.push_btn = QPushButton("Push to inverter")
        self.push_btn.setObjectName("danger")
        self.push_btn.setToolTip("Write your edits, then program EEPROM (needs Wait, enable off).")
        self.push_btn.clicked.connect(self.push_requested.emit)
        self.status = QLabel("Start RS232.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)

        self.tree = GroupedSymbolTree(show_kind=True)
        self.tree.set_symbols(self._symbols, EEPROM_GROUP_ORDER)

        self.hint = QLabel("Double-click a value to edit it")
        self.hint.setObjectName("muted")
        self.dirty = QLabel("")
        self.match_count = QLabel("")
        self.match_count.setObjectName("muted")

        tools = QHBoxLayout()
        tools.addWidget(self.pull_btn)
        tools.addWidget(self.push_btn)
        tools.addWidget(self.status, 1)
        tools.addWidget(self.dirty)
        tools.addWidget(self.hint)
        tools.addWidget(self.match_count)

        find = QHBoxLayout()
        find.addWidget(QLabel("Find"))
        find.addWidget(self.search, 1)

        self.edit_card = self._build_edit_card()

        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.addLayout(tools)
        root.addLayout(find)
        root.addWidget(self.tree, 1)
        root.addWidget(self.edit_card)

        self.search.textChanged.connect(self._refresh_filter)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(self._begin_edit)
        self._refresh_filter()
        self._refresh_edit_bar()
        self.set_rs232_active(False)

    # -- edit card ------------------------------------------------------

    def _build_edit_card(self) -> Card:
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)
        self.edit_title = QLabel("Select a value above to edit it.")
        self.edit_title.setObjectName("muted")
        self.edit_title.setWordWrap(False)
        layout.addWidget(self.edit_title)

        editor = QHBoxLayout()
        self.units_label = QLabel("Value")
        self.units_field = QLineEdit()
        self.units_field.setMinimumWidth(120)
        self.units_field.setPlaceholderText("e.g. 0.5")
        self.unit_suffix = QLabel("")
        self.unit_suffix.setObjectName("muted")
        self.raw_label = QLabel("Raw")
        self.raw_field = QLineEdit()
        self.raw_field.setMinimumWidth(100)
        self.raw_field.setPlaceholderText("e.g. 5")
        self.raw_hex = QLabel("")
        self.raw_hex.setObjectName("muted")
        editor.addWidget(self.units_label)
        editor.addWidget(self.units_field)
        editor.addWidget(self.unit_suffix)
        editor.addSpacing(12)
        editor.addWidget(self.raw_label)
        editor.addWidget(self.raw_field)
        editor.addWidget(self.raw_hex)
        editor.addStretch()
        layout.addLayout(editor)

        actions = QHBoxLayout()
        self.baseline_label = QLabel("")
        self.baseline_label.setObjectName("muted")
        self.baseline_label.setWordWrap(False)
        self.validation = QLabel("")
        self.validation.setWordWrap(False)
        self.validation.setMinimumWidth(300)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setToolTip("Drop this edit and re-read the word from the inverter.")
        self.reset_btn.clicked.connect(self._reset_selected)
        actions.addWidget(self.baseline_label, 1)
        actions.addWidget(self.validation, 1)
        actions.addWidget(self.reset_btn)
        layout.addLayout(actions)

        self.units_field.textChanged.connect(self._units_changed)
        self.raw_field.textChanged.connect(self._raw_changed)
        # Freeze the height so selecting different rows never moves the table.
        card.setFixedHeight(card.sizeHint().height())
        return card

    # -- public state ---------------------------------------------------

    @property
    def has_snapshot(self) -> bool:
        return self._loaded > 0

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def pending_writes(self) -> tuple[tuple[int, int], ...]:
        return tuple(sorted(self._pending.items()))

    def baseline_raw(self, address: int) -> int | None:
        return self._baseline.get(int(address))

    def mark_flashed(self, addresses: tuple[int, ...] | list[int]) -> None:
        for address in addresses:
            self._pending.pop(int(address), None)
        self._refresh_dirty_rows()
        self._refresh_edit_bar()
        self._refresh_buttons()

    def set_rs232_active(self, active: bool) -> None:
        self._rs232 = active
        self.pull_btn.setEnabled(active)
        if not active and self.status.text().startswith("Reading"):
            self.status.setText("Start RS232.")
        self._refresh_buttons()

    # -- selection + editing --------------------------------------------

    def _selected_symbol(self) -> MemorySymbol | None:
        if self._selected is None:
            return None
        return self._by_address.get(self._selected)

    @staticmethod
    def _editable(symbol: MemorySymbol) -> bool:
        return symbol.kind == "eeprom"

    def _selection_changed(self) -> None:
        address: int | None = None
        for item in self.tree.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data is not None:
                address = int(data)
                break
        self._selected = address
        self._refresh_edit_bar()

    def _begin_edit(self, *_args: object) -> None:
        self._selection_changed()
        symbol = self._selected_symbol()
        if symbol is None or not self._editable(symbol):
            return
        target = self.units_field if edit_unit(symbol) else self.raw_field
        if target.isVisible():
            target.setFocus()
            target.selectAll()

    def _current_edit_raw(self, symbol: MemorySymbol) -> int | None:
        if symbol.address in self._pending:
            return self._pending[symbol.address]
        return self._baseline.get(symbol.address)

    def _refresh_edit_bar(self) -> None:
        symbol = self._selected_symbol()
        if symbol is None:
            self.edit_title.setText("Select a value above to edit it.")
            self._set_editor_visible(False)
            self.baseline_label.setText("")
            self.validation.setText("")
            self.validation.setVisible(False)
            self.reset_btn.setVisible(False)
            return
        self.edit_title.setText(f"{symbol.name}  ({symbol.address_text})")
        if not self._editable(symbol):
            self._set_editor_visible(False)
            self.baseline_label.setText("Read-only — factory info, never flashed.")
            self.validation.setText("")
            self.validation.setVisible(False)
            self.reset_btn.setVisible(False)
            return
        self._set_editor_visible(True)
        self.validation.setVisible(True)
        self.reset_btn.setVisible(True)
        unit = edit_unit(symbol)
        self.units_label.setVisible(bool(unit))
        self.units_field.setVisible(bool(unit))
        self.unit_suffix.setVisible(bool(unit))
        self.unit_suffix.setText(unit)
        current = self._current_edit_raw(symbol)
        self._syncing = True
        try:
            if unit:
                self.units_field.setText(
                    "" if current is None else format_engineering(symbol, current)
                )
            self.raw_field.setText("" if current is None else str(self._to_signed(symbol, current)))
            self.raw_hex.setText(
                "" if current is None else f"0x{int(current) & 0xFFFF:04X}"
            )
        finally:
            self._syncing = False
        self.validation.setText("")
        set_tone(self.validation, None)
        self._refresh_baseline_label(symbol)
        self.reset_btn.setEnabled(True)

    def _set_editor_visible(self, visible: bool) -> None:
        for widget in (
            self.units_label,
            self.units_field,
            self.unit_suffix,
            self.raw_label,
            self.raw_field,
            self.raw_hex,
        ):
            widget.setVisible(visible)

    @staticmethod
    def _to_signed(symbol: MemorySymbol, raw_u16: int) -> int:
        raw = int(raw_u16) & 0xFFFF
        if symbol.signed and raw >= 0x8000:
            raw -= 0x10000
        return raw

    def _refresh_baseline_label(self, symbol: MemorySymbol) -> None:
        baseline = self._baseline.get(symbol.address)
        pending = self._pending.get(symbol.address)
        if baseline is None:
            self.baseline_label.setText("On inverter: not read yet — Pull first.")
            return
        value, raw = _edited_texts(symbol, baseline, 0.0)
        if pending is None:
            self.baseline_label.setText(f"On inverter: {value} ({raw}).")
            return
        new_value, new_raw = _edited_texts(symbol, pending, 0.0)
        self.baseline_label.setText(f"On inverter: {value} ({raw}) → edit: {new_value} ({new_raw}).")

    # -- synced fields: typing a valid value stages the edit; nothing flashes
    # until Push. Invalid input explains why and leaves the row unstaged. ---

    def _units_changed(self, _text: str) -> None:
        if self._syncing:
            return
        symbol = self._selected_symbol()
        if symbol is None or not self._editable(symbol) or not edit_unit(symbol):
            return
        try:
            raw = parse_engineering(symbol, self.units_field.text())
        except ValueError as exc:
            self._edit_invalid(symbol, str(exc))
            return
        self._syncing = True
        try:
            self.raw_field.setText(str(self._to_signed(symbol, raw)))
            self.raw_hex.setText(f"0x{raw & 0xFFFF:04X}")
        finally:
            self._syncing = False
        self._stage(symbol, raw)

    def _raw_changed(self, _text: str) -> None:
        if self._syncing:
            return
        symbol = self._selected_symbol()
        if symbol is None or not self._editable(symbol):
            return
        try:
            raw = parse_raw_word(symbol, self.raw_field.text())
        except ValueError as exc:
            self._edit_invalid(symbol, str(exc))
            return
        self._syncing = True
        try:
            self.raw_hex.setText(f"0x{raw & 0xFFFF:04X}")
            if edit_unit(symbol):
                self.units_field.setText(format_engineering(symbol, raw))
        finally:
            self._syncing = False
        self._stage(symbol, raw)

    def _stage(self, symbol: MemorySymbol, raw: int) -> None:
        self.validation.setText("")
        set_tone(self.validation, None)
        if self._baseline.get(symbol.address) == raw:
            self._pending.pop(symbol.address, None)
        else:
            self._pending[symbol.address] = raw
        self._refresh_dirty_rows()
        self._refresh_baseline_label(symbol)
        self._refresh_buttons()

    def _edit_invalid(self, symbol: MemorySymbol, message: str) -> None:
        self.validation.setText(message)
        set_tone(self.validation, "fault")
        self._pending.pop(symbol.address, None)
        self._refresh_dirty_rows()
        self._refresh_baseline_label(symbol)
        self._refresh_buttons()

    def _reset_selected(self) -> None:
        symbol = self._selected_symbol()
        if symbol is None:
            return
        self._pending.pop(symbol.address, None)
        self.single_read_requested.emit(symbol.address)
        self.status.setText(f"Re-reading {symbol.address_text} from the inverter…")
        self._refresh_dirty_rows()
        self._refresh_edit_bar()
        self._refresh_buttons()

    # -- table filter + dirty rows --------------------------------------

    def _refresh_filter(self) -> None:
        shown = self.tree.apply_filter(self.search.text())
        self.match_count.setText(f"{shown} shown")

    def _refresh_dirty_rows(self) -> None:
        now = 0.0
        for address in sorted(self._highlighted - set(self._pending)):
            item = self.tree.item_for_address(address)
            symbol = self._by_address.get(address)
            if item is not None and symbol is not None:
                baseline = self._baseline.get(address)
                if baseline is None:
                    item.setText(self.tree.value_column, "—")
                    item.setText(self.tree.raw_column, "—")
                else:
                    value, raw_text = _edited_texts(symbol, baseline, now)
                    item.setText(self.tree.value_column, value)
                    item.setText(self.tree.raw_column, raw_text)
                item.setBackground(self.tree.value_column, QBrush())
                item.setBackground(self.tree.raw_column, QBrush())
                item.setToolTip(self.tree.value_column, "")
                item.setToolTip(self.tree.raw_column, "")
        self._highlighted = set(self._pending)
        brush = QBrush(DIRTY_BG)
        for address, raw in self._pending.items():
            item = self.tree.item_for_address(address)
            symbol = self._by_address.get(address)
            if item is None or symbol is None:
                continue
            value, raw_text = _edited_texts(symbol, raw, now)
            item.setText(self.tree.value_column, value)
            item.setText(self.tree.raw_column, raw_text)
            item.setBackground(self.tree.value_column, brush)
            item.setBackground(self.tree.raw_column, brush)
            item.setToolTip(self.tree.value_column, DIRTY_TIP)
            item.setToolTip(self.tree.raw_column, DIRTY_TIP)

    def _refresh_buttons(self) -> None:
        count = len(self._pending)
        self.dirty.setText(f"{count} unsaved" if count else "")
        set_tone(self.dirty, "fault" if count else None)
        self.push_btn.setEnabled(self._rs232 and count > 0)

    # -- live updates ----------------------------------------------------

    def update_from(self, snapshot: StoreSnapshot, progress: DumpProgress) -> None:
        loaded = sum(
            1
            for symbol in self._symbols
            if (signal := snapshot.signals.get(symbol.key)) is not None and signal.raw is not None
        )
        if loaded:
            self.tree.update_from(snapshot, self._catalog.memory_by_address)
            self._loaded = loaded
        elif self._rs232 and progress.active:
            self.tree.update_from(snapshot, self._catalog.memory_by_address)
        for symbol in self._symbols:
            signal = snapshot.signals.get(symbol.key)
            if signal is not None and signal.raw is not None:
                self._baseline[symbol.address] = int(signal.raw) & 0xFFFF
        self._refresh_dirty_rows()
        symbol = self._selected_symbol()
        if symbol is not None:
            self._refresh_baseline_label(symbol)
        self._refresh_buttons()
        shown = self._loaded
        if progress.active and progress.total:
            self.status.setText(f"Reading EEPROM {progress.done}/{progress.total}…")
            return
        if not self._rs232:
            if shown:
                self.status.setText(f"Last snapshot: {shown}/{len(self._symbols)} words.")
            else:
                self.status.setText("Start RS232.")
            return
        if progress.total and shown:
            if self._pending:
                self.status.setText(
                    f"Loaded {shown}/{len(self._symbols)} words. "
                    f"{len(self._pending)} edited — Push to flash."
                )
            else:
                self.status.setText(f"Loaded {shown}/{len(self._symbols)} words.")
            return
        if progress.total:
            self.status.setText("Waiting for EEPROM replies…")
            return
        self.status.setText("Pull to reload.")
