from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from inverter_monitor.catalog import Catalog
from inverter_monitor.feed import FeedState
from inverter_monitor.memory_map import (
    LIVE_GROUP_ORDER,
    RELOAD_WATCH_ADDRESSES,
    WatchList,
    live_symbols,
)
from inverter_monitor.store import StoreSnapshot
from inverter_monitor.ui.symbol_widgets import GroupedSymbolTree, symbol_value_texts
from inverter_monitor.ui.theme import PAGE_MARGINS, mono_font

_ADDR_ROLE = Qt.ItemDataRole.UserRole


class SymbolsPage(QWidget):
    """Live Memory View symbols, grouped the way RMS GUI pages them."""

    watches_changed = Signal()

    def __init__(
        self,
        catalog: Catalog,
        watch_list: WatchList,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self._watch = watch_list
        self._live = live_symbols(catalog.memory_symbols)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.add_btn = QPushButton("Add to watch")
        self.remove_btn = QPushButton("Remove")
        self.reload_btn = QPushButton("Reload default list")

        self.catalog_tree = GroupedSymbolTree()
        self.catalog_tree.set_symbols(self._live, LIVE_GROUP_ORDER)
        self.catalog_tree.itemDoubleClicked.connect(lambda *_args: self._add_selected())

        self.watch_table = QTableWidget(0, 4)
        self.watch_table.setHorizontalHeaderLabels(["Address", "Name", "Value", "Raw"])
        self.watch_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.watch_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.watch_table.verticalHeader().setVisible(False)
        self.watch_table.setFont(mono_font(12))
        self.watch_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.watch_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.watch_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self.match_count = QLabel("")
        self.match_count.setObjectName("muted")

        tools = QHBoxLayout()
        tools.addWidget(QLabel("Find"))
        tools.addWidget(self.search, 1)
        tools.addWidget(self.match_count)

        catalog_box = QVBoxLayout()
        catalog_box.setContentsMargins(0, 0, 0, 0)
        catalog_heading = QLabel("Catalog")
        catalog_heading.setObjectName("muted")
        catalog_box.addWidget(catalog_heading)
        catalog_box.addLayout(tools)
        catalog_box.addWidget(self.catalog_tree, 1)
        catalog_box.addWidget(self.add_btn)
        catalog_wrap = QWidget()
        catalog_wrap.setLayout(catalog_box)

        watch_box = QVBoxLayout()
        watch_box.setContentsMargins(0, 0, 0, 0)
        watch_heading = QLabel("Watch list")
        watch_heading.setObjectName("muted")
        watch_box.addWidget(watch_heading)
        watch_box.addWidget(self.watch_table, 1)
        watch_buttons = QHBoxLayout()
        watch_buttons.addWidget(self.remove_btn)
        watch_buttons.addWidget(self.reload_btn)
        watch_box.addLayout(watch_buttons)
        watch_wrap = QWidget()
        watch_wrap.setLayout(watch_box)

        splitter = QSplitter()
        splitter.addWidget(catalog_wrap)
        splitter.addWidget(watch_wrap)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.addWidget(splitter, 1)

        self.search.textChanged.connect(self._refresh_catalog)
        self.add_btn.clicked.connect(self._add_selected)
        self.remove_btn.clicked.connect(self._remove_selected)
        self.reload_btn.clicked.connect(self._reload_default)
        self._refresh_catalog()
        self._refresh_watch_rows()
        self._sync_reload_enabled()

    def _refresh_catalog(self) -> None:
        shown = self.catalog_tree.apply_filter(self.search.text())
        self.match_count.setText(f"{shown} shown")

    def _add_selected(self) -> None:
        changed = False
        for address in self.catalog_tree.selected_addresses():
            if not self._watch.contains(address):
                self._watch.add(address)
                changed = True
        if changed:
            self._refresh_watch_rows()
            self._sync_reload_enabled()
            self.watches_changed.emit()

    def _remove_selected(self) -> None:
        rows = {index.row() for index in self.watch_table.selectedIndexes()}
        changed = False
        for row in sorted(rows, reverse=True):
            item = self.watch_table.item(row, 0)
            if item is None:
                continue
            address = item.data(_ADDR_ROLE)
            if address is None:
                continue
            self._watch.remove(int(address))
            changed = True
        if changed:
            self._refresh_watch_rows()
            self._sync_reload_enabled()
            self.watches_changed.emit()

    def _reload_default(self) -> None:
        if self._watch.addresses() == RELOAD_WATCH_ADDRESSES:
            return
        self._watch.replace(RELOAD_WATCH_ADDRESSES)
        self._refresh_watch_rows()
        self._sync_reload_enabled()
        self.watches_changed.emit()

    def _sync_reload_enabled(self) -> None:
        self.reload_btn.setEnabled(self._watch.addresses() != RELOAD_WATCH_ADDRESSES)

    def _refresh_watch_rows(self) -> None:
        symbols = [
            self._catalog.memory_by_address[address]
            for address in self._watch.addresses()
            if address in self._catalog.memory_by_address
        ]
        self.watch_table.setRowCount(len(symbols))
        for row, symbol in enumerate(symbols):
            values = [symbol.address_text, symbol.name, "—", "—"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(_ADDR_ROLE, symbol.address)
                self.watch_table.setItem(row, column, item)

    def update_from(self, snapshot: StoreSnapshot, feed: FeedState | None = None) -> None:
        live = feed.live if feed is not None else True
        self.catalog_tree.update_from(snapshot, self._catalog.memory_by_address, live=live)
        for row in range(self.watch_table.rowCount()):
            addr_item = self.watch_table.item(row, 0)
            if addr_item is None:
                continue
            address = addr_item.data(_ADDR_ROLE)
            symbol = self._catalog.memory_by_address.get(int(address)) if address is not None else None
            if symbol is None:
                continue
            if live:
                value, raw = symbol_value_texts(symbol, snapshot)
            else:
                value, raw = "—", "—"
            self._set_watch_cell(row, 2, value, address)
            self._set_watch_cell(row, 3, raw, address)

    def _set_watch_cell(self, row: int, column: int, text: str, address: object) -> None:
        item = self.watch_table.item(row, column)
        if item is None:
            item = QTableWidgetItem(text)
            item.setData(_ADDR_ROLE, address)
            self.watch_table.setItem(row, column, item)
        else:
            item.setText(text)
