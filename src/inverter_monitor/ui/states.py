from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from inverter_monitor.catalog import CAN_COMMAND_MODE, Catalog, mode_label
from inverter_monitor.store import StoreSnapshot, command_mode, first_signal
from inverter_monitor.ui.theme import vsm_color


class StatesPage(QWidget):
    def __init__(self, catalog: Catalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self._mode: int | None = CAN_COMMAND_MODE
        self.vsm_table = self._make_table(["ID", "Name", "Description"], catalog.vsm_states)
        self.inv_table = self._make_table(["ID", "Name", "Description"], catalog.inverter_states)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)

        vsm_box = QVBoxLayout()
        vsm_box.addWidget(QLabel("Vehicle State Machine"))
        vsm_box.addWidget(self.vsm_table)
        vsm_wrap = QWidget()
        vsm_wrap.setLayout(vsm_box)

        inv_box = QVBoxLayout()
        inv_box.addWidget(QLabel("Inverter mode"))
        inv_box.addWidget(self.inv_table)
        inv_wrap = QWidget()
        inv_wrap.setLayout(inv_box)

        tables = QSplitter(Qt.Orientation.Vertical)
        tables.addWidget(vsm_wrap)
        tables.addWidget(inv_wrap)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(tables)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.addWidget(splitter)

        self.vsm_table.itemSelectionChanged.connect(self._show_selected)

    def _make_table(self, headers: list[str], states: dict) -> QTableWidget:
        table = QTableWidget(len(states), 3)
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for row, state_id in enumerate(sorted(states)):
            state = states[state_id]
            description, _, _ = state.text(self._mode)
            for column, value in enumerate([str(state.id), state.name, description]):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, state.id)
                table.setItem(row, column, item)
        return table

    def _refill_descriptions(self, table: QTableWidget, states: dict) -> None:
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            state = states.get(int(item.text()))
            if state is None:
                continue
            description, _, _ = state.text(self._mode)
            cell = table.item(row, 2)
            if cell is not None:
                cell.setText(description)

    def _show_selected(self) -> None:
        items = self.vsm_table.selectedItems()
        if not items:
            return
        state_id = int(self.vsm_table.item(items[0].row(), 0).text())
        state = self._catalog.vsm_states.get(state_id)
        if not state:
            return
        description, entry, exit = state.text(self._mode)
        lines = [
            f"{state.id}  {state.name}  ({mode_label(self._mode)} wording)",
            description,
            "",
        ]
        if entry:
            lines.append(f"Entry: {entry}")
        if exit:
            lines.append(f"Exit: {exit}")
        if state.conditions:
            lines.append("Conditions:")
            lines.extend(f"  • {item}" for item in state.conditions)
        if state.lockouts:
            lines.append("Lockouts / notes:")
            lines.extend(f"  • {item}" for item in state.lockouts)
        self.detail.setPlainText("\n".join(lines))

    def update_from(self, snapshot: StoreSnapshot) -> None:
        mode = command_mode(snapshot)
        effective = CAN_COMMAND_MODE if mode is None else mode
        if effective != self._mode:
            self._mode = effective
            self._refill_descriptions(self.vsm_table, self._catalog.vsm_states)
            self._refill_descriptions(self.inv_table, self._catalog.inverter_states)
            self._show_selected()
        vsm = first_signal(
            snapshot,
            "M170_Internal_States.D1_VSM_State",
            "MemoryView.VSM_State",
        )
        inv = first_signal(
            snapshot,
            "M170_Internal_States.D2_Inverter_State",
            "MemoryView.Inverter_Mode",
        )
        self._highlight(self.vsm_table, int(vsm.raw) if vsm and vsm.raw is not None else None)
        self._highlight(self.inv_table, int(inv.raw) if inv and inv.raw is not None else None)

    def _highlight(self, table: QTableWidget, current_id: int | None) -> None:
        color = QColor(vsm_color(current_id))
        color.setAlpha(50)
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            active = current_id is not None and item and int(item.text()) == current_id
            for column in range(table.columnCount()):
                cell = table.item(row, column)
                if cell:
                    cell.setBackground(QBrush(color if active else QColor("#00000000")))
