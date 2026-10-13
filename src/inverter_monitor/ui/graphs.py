from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from html import escape

import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
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
from inverter_monitor.store import StoreSnapshot, fresh_signal
from inverter_monitor.ui.theme import BG, DIM, PAGE_MARGINS, TEXT


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


def nearest_sample(
    points: Sequence[tuple[float, float]],
    t: float,
) -> tuple[float, float] | None:
    if not points:
        return None
    return min(points, key=lambda point: abs(point[0] - t))


def format_graph_number(value: float) -> str:
    digits = 1 if abs(value) >= 10 else 2
    return f"{value:.{digits}f}"


def hover_rows(
    series: Iterable[tuple[str, Sequence[tuple[float, float]], str]],
    t: float,
) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for name, points, color in series:
        sample = nearest_sample(points, t)
        if sample is None:
            continue
        rows.append((name, format_graph_number(sample[1]), color))
    return rows


def format_hover_html(t: float, rows: Sequence[tuple[str, str, str]]) -> str:
    parts = [
        f'<div style="color:{TEXT}">',
        f'<div style="color:{DIM};margin-bottom:4px">{t:.2f} s</div>',
    ]
    for name, value, color in rows:
        parts.append(
            "<div>"
            f'<span style="color:{color}">●</span> {escape(name)}'
            f'&nbsp;&nbsp;<b>{escape(value)}</b>'
            "</div>"
        )
    parts.append("</div>")
    return "".join(parts)


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
        self._minimum_height = -1

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self.flow.heightForWidth(width)

    def sync_minimum_height(self) -> None:
        """Match the host height to the chips currently in the flow.

        Chips are hidden and re-parented on every rebuild, which changes the
        wrapping height. Without this the host keeps the height it had before
        the filter, so the scroll area keeps a stale range and the list looks
        half empty (or scrolled past the matches) after a search.
        """
        height = self.heightForWidth(max(1, self.width()))
        if height != self._minimum_height:
            self._minimum_height = height
            self.setMinimumHeight(height)
            self.updateGeometry()

    def event(self, event) -> bool:  # noqa: N802
        # A pending layout request means the chips changed: recompute the height.
        if event.type() == QEvent.Type.LayoutRequest:
            self.sync_minimum_height()
        return super().event(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.sync_minimum_height()


class _ChipScroll(QScrollArea):
    def __init__(self, host: _FlowHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidget(host)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._pin_top = False
        bar = self.verticalScrollBar()
        # The range is only recalculated once the flow host has been laid out,
        # so a one-shot reset would be undone: hold the top until the user scrolls.
        bar.rangeChanged.connect(lambda *_: self._apply_pin())
        bar.actionTriggered.connect(lambda *_: self._release_pin())
        bar.sliderPressed.connect(self._release_pin)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(280, 140)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(160, 72)

    def pin_to_top(self) -> None:
        """Scroll back to the first row and keep it there until the user scrolls."""
        self._pin_top = True
        self._apply_pin()

    def _apply_pin(self) -> None:
        if not self._pin_top:
            return
        bar = self.verticalScrollBar()
        bar.setValue(bar.minimum())

    def _release_pin(self, *_args) -> None:
        self._pin_top = False


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
        self._enabled_scroll = _ChipScroll(self._enabled_host)
        self._available_scroll = _ChipScroll(self._available_host)
        self._park = QWidget()
        self._park.hide()
        self._last_query = self.search.text()

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
        enabled_box.addWidget(self._enabled_scroll, 1)
        enabled_wrap = QWidget()
        enabled_wrap.setLayout(enabled_box)

        available_box = QVBoxLayout()
        available_box.setContentsMargins(0, 0, 0, 0)
        available_box.setSpacing(4)
        available_box.addWidget(self.available_heading)
        available_box.addWidget(self._available_scroll, 1)
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
            new_query = query != self._last_query
            self._last_query = query
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
            # A new search starts at the top of both lists: the old scroll offset
            # would otherwise hide the few matching chips above the viewport.
            if new_query:
                for scroll in (self._enabled_scroll, self._available_scroll):
                    scroll.pin_to_top()
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
        self._hover_t: float | None = None

        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot.addLegend()
        self.plot.setLabel("bottom", "time", units="s")
        self.plot.setCursor(Qt.CursorShape.CrossCursor)
        self._cursor = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen(DIM, width=1, style=Qt.PenStyle.DashLine),
        )
        self._cursor.setVisible(False)
        self._cursor.setZValue(10)
        self.plot.addItem(self._cursor, ignoreBounds=True)
        self._hover_dots = pg.ScatterPlotItem(
            size=9,
            pxMode=True,
            pen=pg.mkPen(TEXT, width=1),
        )
        self._hover_dots.setZValue(11)
        self.plot.addItem(self._hover_dots, ignoreBounds=True)

        self.hover_label = QLabel(self.plot.viewport())
        self.hover_label.setObjectName("graphHover")
        self.hover_label.setTextFormat(Qt.TextFormat.RichText)
        self.hover_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hover_label.hide()

        self._mouse_proxy = pg.SignalProxy(
            self.plot.scene().sigMouseMoved,
            rateLimit=40,
            slot=self._on_mouse_moved,
        )
        self.plot.installEventFilter(self)
        self.plot.viewport().installEventFilter(self)

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
        root.setContentsMargins(*PAGE_MARGINS)
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
            # Only fresh samples extend a trace: a stale signal must not draw a
            # flat line at its last value while the inverter is quiet.
            signal = fresh_signal(snapshot, *graph_lookup_keys(key))
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
        if self._hover_t is not None:
            self.hover_at(self._hover_t)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched in (self.plot, self.plot.viewport()) and event.type() == QEvent.Type.Leave:
            self.hover_at(None)
        return super().eventFilter(watched, event)

    def _on_mouse_moved(self, event) -> None:
        pos = event[0]
        view_box = self.plot.getViewBox()
        if not view_box.sceneBoundingRect().contains(pos):
            self.hover_at(None)
            return
        self.hover_at(float(view_box.mapSceneToView(pos).x()))

    def hover_at(self, t: float | None) -> None:
        self._hover_t = t
        if t is None:
            self._cursor.setVisible(False)
            self._hover_dots.clear()
            self.hover_label.hide()
            return
        selected = self.selected_keys()
        series: list[tuple[str, Sequence[tuple[float, float]], str]] = []
        spots: list[dict] = []
        for index, key in enumerate(selected):
            buf = self._buffers.get(key)
            if not buf:
                continue
            color = COLORS[index % len(COLORS)]
            series.append((graph_signal_label(key), buf, color))
            sample = nearest_sample(buf, t)
            if sample is not None:
                spots.append({"pos": (t, sample[1]), "brush": color})
        rows = hover_rows(series, t)
        self._cursor.setPos(t)
        self._cursor.setVisible(True)
        if spots:
            self._hover_dots.setData(spots)
        else:
            self._hover_dots.clear()
        self.hover_label.setText(format_hover_html(t, rows))
        self.hover_label.adjustSize()
        self._place_hover_label()
        self.hover_label.show()
        self.hover_label.raise_()

    def _place_hover_label(self) -> None:
        view_box = self.plot.getViewBox()
        plot_rect = self.plot.mapFromScene(view_box.sceneBoundingRect()).boundingRect()
        top_left = self.plot.viewport().mapFrom(self.plot, plot_rect.topLeft())
        bottom_right = self.plot.viewport().mapFrom(self.plot, plot_rect.bottomRight())
        rect = QRect(top_left, bottom_right)
        hint = self.hover_label.sizeHint()
        x = rect.right() - hint.width() - 8
        y = rect.top() + 8
        self.hover_label.move(max(rect.left() + 8, x), max(rect.top() + 8, y))
