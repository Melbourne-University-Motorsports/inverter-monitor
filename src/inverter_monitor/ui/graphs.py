from __future__ import annotations

from collections import deque
from collections.abc import Iterable

import pyqtgraph as pg
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from inverter_monitor.catalog import (
    DEFAULT_GRAPH_KEYS,
    Catalog,
    graph_lookup_keys,
    graph_poll_addresses,
    graphable_keys,
)
from inverter_monitor.store import StoreSnapshot, first_signal
from inverter_monitor.ui.theme import BG, TEXT


COLORS = [
    "#4c8dff",
    "#3ecf8e",
    "#f5a524",
    "#e5484d",
    "#c084fc",
    "#67e8f9",
    "#f9a8d4",
    "#fde047",
]


def graph_signal_label(key: str) -> str:
    return key.split(".", 1)[-1]


def graph_signal_matches(key: str, query: str) -> bool:
    tokens = [token.lower() for token in query.split() if token.strip()]
    if not tokens:
        return True
    message, _, name = key.partition(".")
    haystack = f"{key} {message} {name}".replace("_", " ").lower()
    return all(token in haystack for token in tokens)


class _FlowLayout(QLayout):
    """Wrap child widgets onto the next line when the row is full."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:  # noqa: N802
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        x = rect.x()
        y = rect.y()
        line_height = 0
        space = self.spacing()
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + space
            if next_x - space > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + space
                next_x = x + hint.width() + space
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


class _FlowHost(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.flow = _FlowLayout(self)
        self.setLayout(self.flow)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self.flow.heightForWidth(width)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.setMinimumHeight(self.heightForWidth(max(1, self.width())))


class _ChipScroll(QScrollArea):
    def __init__(self, host: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidget(host)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(280, 140)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(160, 72)


class SignalPicker(QWidget):
    """Searchable wrapping chips, split into traces on the graph and the rest."""

    selection_changed = Signal()

    def __init__(
        self,
        keys: Iterable[str],
        enabled: Iterable[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._keys = tuple(keys)
        self._enabled = {key for key in enabled if key in self._keys}
        self._chips: dict[str, QCheckBox] = {}
        self._rebuilding = False

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search signals…")
        self.search.setClearButtonEnabled(True)
        self.match_count = QLabel("")
        self.match_count.setObjectName("muted")

        self.enabled_heading = QLabel("On graph")
        self.enabled_heading.setObjectName("muted")
        self.available_heading = QLabel("Available")
        self.available_heading.setObjectName("muted")

        self._enabled_host = _FlowHost()
        self._available_host = _FlowHost()
        self._park = QWidget()
        self._park.hide()

        for key in self._keys:
            chip = QCheckBox(graph_signal_label(key))
            chip.setObjectName("signalChip")
            chip.setToolTip(key)
            chip.setChecked(key in self._enabled)
            chip.toggled.connect(lambda checked, signal_key=key: self._on_chip_toggled(signal_key, checked))
            self._chips[key] = chip

        tools = QHBoxLayout()
        tools.addWidget(self.search, 1)
        tools.addWidget(self.match_count)

        enabled_box = QVBoxLayout()
        enabled_box.setContentsMargins(0, 0, 0, 0)
        enabled_box.setSpacing(4)
        enabled_box.addWidget(self.enabled_heading)
        enabled_box.addWidget(_ChipScroll(self._enabled_host), 1)
        enabled_wrap = QWidget()
        enabled_wrap.setLayout(enabled_box)

        available_box = QVBoxLayout()
        available_box.setContentsMargins(0, 0, 0, 0)
        available_box.setSpacing(4)
        available_box.addWidget(self.available_heading)
        available_box.addWidget(_ChipScroll(self._available_host), 1)
        available_wrap = QWidget()
        available_wrap.setLayout(available_box)

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(12)
        columns.addWidget(enabled_wrap, 2)
        columns.addWidget(available_wrap, 3)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addLayout(tools)
        layout.addLayout(columns, 1)

        self.search.textChanged.connect(self._rebuild_lists)
        self._rebuild_lists()

    def selected_keys(self) -> list[str]:
        return [key for key in self._keys if key in self._enabled]

    def chip(self, key: str) -> QCheckBox:
        return self._chips[key]

    def visible_keys(self, enabled: bool) -> list[str]:
        query = self.search.text()
        return [
            key
            for key in self._keys
            if (key in self._enabled) == enabled and graph_signal_matches(key, query)
        ]

    def _on_chip_toggled(self, key: str, checked: bool) -> None:
        if checked:
            self._enabled.add(key)
        else:
            self._enabled.discard(key)
        if self._rebuilding:
            return
        self._rebuild_lists()
        self.selection_changed.emit()

    def _clear_flow(self, host: _FlowHost) -> None:
        while host.flow.count():
            item = host.flow.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(self._park)

    def _rebuild_lists(self) -> None:
        self._rebuilding = True
        try:
            self._clear_flow(self._enabled_host)
            self._clear_flow(self._available_host)
            query = self.search.text()
            shown_enabled = 0
            shown_available = 0
            for key in self._keys:
                chip = self._chips[key]
                if not graph_signal_matches(key, query):
                    chip.hide()
                    chip.setParent(self._park)
                    continue
                chip.blockSignals(True)
                chip.setChecked(key in self._enabled)
                chip.blockSignals(False)
                chip.show()
                if key in self._enabled:
                    self._enabled_host.flow.addWidget(chip)
                    shown_enabled += 1
                else:
                    self._available_host.flow.addWidget(chip)
                    shown_available += 1
            self.enabled_heading.setText(f"On graph ({shown_enabled})")
            self.available_heading.setText(f"Available ({shown_available})")
            total = shown_enabled + shown_available
            self.match_count.setText(f"{total} shown" if query.strip() else "")
            self._enabled_host.updateGeometry()
            self._available_host.updateGeometry()
        finally:
            self._rebuilding = False


class GraphsPage(QWidget):
    selection_changed = Signal()

    def __init__(self, catalog: Catalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        pg.setConfigOptions(antialias=True, background=BG, foreground=TEXT)

        self._catalog = catalog
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._t0: float | None = None

        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot.addLegend()
        self.plot.setLabel("bottom", "time", units="s")

        self.window = QComboBox()
        self.window.addItems(["10 s", "30 s", "60 s"])
        self.window.setCurrentIndex(1)
        self.paused = QCheckBox("Pause")

        self.picker = SignalPicker(graphable_keys(catalog), DEFAULT_GRAPH_KEYS)
        self.picker.selection_changed.connect(self.selection_changed.emit)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Window"))
        controls.addWidget(self.window)
        controls.addWidget(self.paused)
        controls.addStretch()

        plot_wrap = QWidget()
        plot_layout = QVBoxLayout(plot_wrap)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.addLayout(controls)
        plot_layout.addWidget(self.plot, 1)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(plot_wrap)
        splitter.addWidget(self.picker)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([480, 240])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.addWidget(splitter)

    def selected_keys(self) -> list[str]:
        return self.picker.selected_keys()

    def poll_addresses(self) -> tuple[int, ...]:
        return graph_poll_addresses(self._catalog, self.selected_keys())

    def _window_s(self) -> float:
        return float(self.window.currentText().split()[0])

    def update_from(self, snapshot: StoreSnapshot) -> None:
        if self.paused.isChecked():
            return
        if self._t0 is None:
            self._t0 = snapshot.now
        t = snapshot.now - self._t0
        window = self._window_s()
        selected = self.selected_keys()
        for key in selected:
            signal = first_signal(snapshot, *graph_lookup_keys(key))
            if signal is None or not isinstance(signal.value, (int, float)) or isinstance(signal.value, bool):
                continue
            buf = self._buffers.setdefault(key, deque())
            buf.append((t, float(signal.value)))
            while buf and t - buf[0][0] > window:
                buf.popleft()
        for key in list(self._curves):
            if key not in selected:
                self.plot.removeItem(self._curves.pop(key))
                self._buffers.pop(key, None)
        for index, key in enumerate(selected):
            buf = self._buffers.get(key)
            if not buf:
                continue
            xs = [point[0] for point in buf]
            ys = [point[1] for point in buf]
            color = COLORS[index % len(COLORS)]
            name = key.split(".", 1)[-1]
            if key not in self._curves:
                self._curves[key] = self.plot.plot(pen=pg.mkPen(color, width=2), name=name)
            self._curves[key].setData(xs, ys)
        self.plot.setXRange(max(0.0, t - window), max(window, t), padding=0)
