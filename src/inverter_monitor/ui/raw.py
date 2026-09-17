from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from inverter_monitor.store import StoreSnapshot
from inverter_monitor.ui.theme import PAGE_MARGINS, mono_font


class RawPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "Name", "DLC", "Data", "Hz", "Age"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setFont(mono_font(12))
        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.addWidget(self.table)

    def update_from(self, snapshot: StoreSnapshot) -> None:
        frames = sorted(snapshot.frames.values(), key=lambda item: item.arbitration_id)
        self.table.setRowCount(len(frames))
        for row, frame in enumerate(frames):
            hz = 0.0 if not frame.period_s else 1.0 / max(frame.period_s, 1e-6)
            age_ms = (snapshot.now - frame.last_seen) * 1000.0
            payload = " ".join(f"{byte:02X}" for byte in frame.data)
            values = [
                f"0x{frame.arbitration_id:03X}",
                frame.name,
                str(len(frame.data)),
                payload,
                f"{hz:.1f}",
                f"{age_ms:.0f} ms",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
