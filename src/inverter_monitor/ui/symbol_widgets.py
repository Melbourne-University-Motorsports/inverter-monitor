from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
)

from inverter_monitor.memory_map import MemorySymbol
from inverter_monitor.store import StoreSnapshot, format_value, get_signal
from inverter_monitor.ui.theme import mono_font

_ADDR_ROLE = Qt.ItemDataRole.UserRole
_KIND_ROLE = Qt.ItemDataRole.UserRole + 1


def ordered_groups(symbols: Iterable[MemorySymbol], preferred: tuple[str, ...]) -> list[str]:
    present = {symbol.group for symbol in symbols}
    ordered = [name for name in preferred if name in present]
    ordered.extend(sorted(present.difference(ordered)))
    return ordered


def group_symbols(
    symbols: Iterable[MemorySymbol],
    preferred: tuple[str, ...],
) -> list[tuple[str, list[MemorySymbol]]]:
    buckets: dict[str, list[MemorySymbol]] = {}
    for symbol in symbols:
        buckets.setdefault(symbol.group, []).append(symbol)
    return [(name, buckets[name]) for name in ordered_groups(symbols, preferred)]


def symbol_value_texts(symbol: MemorySymbol, snapshot: StoreSnapshot) -> tuple[str, str]:
    signal = get_signal(snapshot, symbol.key)
    if signal is None or signal.raw is None:
        return "—", "—"
    return format_value(signal, snapshot.now), f"0x{signal.raw & 0xFFFF:04X}"


class GroupedSymbolTree(QTreeWidget):
    """RMS-style parameter pages: a group heading with the symbols under it."""

    def __init__(self, parent=None, *, show_kind: bool = False) -> None:
        super().__init__(parent)
        self._show_kind = show_kind
        self._items: dict[int, QTreeWidgetItem] = {}
        labels = ["Group / name", "Address", "Value", "Raw"]
        if show_kind:
            labels = ["Group / name", "Kind", "Address", "Value", "Raw"]
        self.setColumnCount(len(labels))
        self.setHeaderLabels(labels)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setFont(mono_font(12))
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, self.columnCount()):
            self.header().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setStretchLastSection(False)

    @property
    def value_column(self) -> int:
        return 3 if self._show_kind else 2

    @property
    def raw_column(self) -> int:
        return 4 if self._show_kind else 3

    def item_for_address(self, address: int) -> QTreeWidgetItem | None:
        return self._items.get(int(address))

    def set_symbols(
        self,
        symbols: Iterable[MemorySymbol],
        preferred_groups: tuple[str, ...] = (),
    ) -> None:
        self.clear()
        self._items = {}
        for group, items in group_symbols(symbols, preferred_groups):
            heading = QTreeWidgetItem([group, "", "", "", ""][: self.columnCount()])
            heading.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.addTopLevelItem(heading)
            heading.setFirstColumnSpanned(True)
            for symbol in items:
                row = [symbol.name, symbol.address_text, "—", "—"]
                if self._show_kind:
                    row = [symbol.name, symbol.kind, symbol.address_text, "—", "—"]
                child = QTreeWidgetItem(row)
                child.setData(0, _ADDR_ROLE, symbol.address)
                child.setData(0, _KIND_ROLE, symbol.kind)
                heading.addChild(child)
                self._items[symbol.address] = child
        self.expandAll()

    def apply_filter(self, query: str) -> int:
        tokens = [token.lower() for token in query.split() if token.strip()]
        visible = 0
        for index in range(self.topLevelItemCount()):
            heading = self.topLevelItem(index)
            if heading is None:
                continue
            group_hit = bool(tokens) and all(token in heading.text(0).lower() for token in tokens)
            any_visible = group_hit
            for child_index in range(heading.childCount()):
                child = heading.child(child_index)
                haystack = " ".join(
                    (
                        heading.text(0),
                        child.text(0),
                        child.text(1),
                        child.text(2) if self._show_kind else "",
                        f"{child.data(0, _ADDR_ROLE):04x}" if child.data(0, _ADDR_ROLE) is not None else "",
                    )
                ).lower()
                match = group_hit or not tokens or all(token in haystack for token in tokens)
                child.setHidden(not match)
                if match:
                    any_visible = True
                    visible += 1
            heading.setHidden(not any_visible)
        return visible

    def selected_addresses(self) -> list[int]:
        addresses: list[int] = []
        seen: set[int] = set()
        for item in self.selectedItems():
            address = item.data(0, _ADDR_ROLE)
            if address is None:
                for child_index in range(item.childCount()):
                    child = item.child(child_index)
                    if child.isHidden():
                        continue
                    child_addr = child.data(0, _ADDR_ROLE)
                    if child_addr is not None and int(child_addr) not in seen:
                        seen.add(int(child_addr))
                        addresses.append(int(child_addr))
                continue
            if int(address) not in seen:
                seen.add(int(address))
                addresses.append(int(address))
        return addresses

    def update_from(self, snapshot: StoreSnapshot, catalog_by_address: dict[int, MemorySymbol]) -> None:
        for address, item in self._items.items():
            symbol = catalog_by_address.get(address)
            if symbol is None:
                continue
            value, raw = symbol_value_texts(symbol, snapshot)
            item.setText(self.value_column, value)
            item.setText(self.raw_column, raw)
