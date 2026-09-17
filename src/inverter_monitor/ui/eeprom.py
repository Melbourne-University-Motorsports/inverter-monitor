from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from inverter_monitor.catalog import Catalog
from inverter_monitor.memory_map import EEPROM_GROUP_ORDER, DumpProgress, snapshot_symbols
from inverter_monitor.store import StoreSnapshot
from inverter_monitor.ui.symbol_widgets import GroupedSymbolTree
from inverter_monitor.ui.theme import PAGE_MARGINS


class EepromPage(QWidget):
    """Motor/inverter programming words. Loaded once on RS232 connect, not live-polled."""

    pull_requested = Signal()

    def __init__(self, catalog: Catalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self._symbols = snapshot_symbols(catalog.memory_symbols)
        self._rs232 = False
        self._loaded = 0

        self.pull_btn = QPushButton("Pull from inverter")
        self.pull_btn.clicked.connect(self.pull_requested.emit)
        self.status = QLabel("Start RS232.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)

        self.tree = GroupedSymbolTree(show_kind=True)
        self.tree.set_symbols(self._symbols, EEPROM_GROUP_ORDER)

        self.readonly = QLabel("Read Only")
        self.readonly.setObjectName("muted")
        self.match_count = QLabel("")
        self.match_count.setObjectName("muted")

        tools = QHBoxLayout()
        tools.addWidget(self.pull_btn)
        tools.addWidget(self.status, 1)
        tools.addWidget(self.readonly)
        tools.addWidget(self.match_count)

        find = QHBoxLayout()
        find.addWidget(QLabel("Find"))
        find.addWidget(self.search, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.addLayout(tools)
        root.addLayout(find)
        root.addWidget(self.tree, 1)

        self.search.textChanged.connect(self._refresh_filter)
        self._refresh_filter()
        self.set_rs232_active(False)

    @property
    def has_snapshot(self) -> bool:
        return self._loaded > 0

    def set_rs232_active(self, active: bool) -> None:
        self._rs232 = active
        self.pull_btn.setEnabled(active)
        if not active and self.status.text().startswith("Reading"):
            self.status.setText("Start RS232.")

    def _refresh_filter(self) -> None:
        shown = self.tree.apply_filter(self.search.text())
        self.match_count.setText(f"{shown} shown")

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
            self.status.setText(f"Loaded {shown}/{len(self._symbols)} words.")
            return
        if progress.total:
            self.status.setText("Waiting for EEPROM replies…")
            return
        self.status.setText("Pull to reload.")
