import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from inverter_monitor.catalog import (
    DEFAULT_GRAPH_KEYS,
    graph_lookup_keys,
    graph_poll_addresses,
    graphable_keys,
    load_catalog,
)
from inverter_monitor.decode import Decoder
from inverter_monitor.memory_map import (
    FEEDBACK_SPEED_ADDRESS,
    MEMORY_FRAME_ID,
    MOD_A_TEMP_ADDRESS,
    pack_memory_frame,
)
from inverter_monitor.store import InverterStore
from inverter_monitor.ui.graphs import (
    GraphsPage,
    format_graph_number,
    format_hover_html,
    graph_signal_matches,
    hover_rows,
    nearest_sample,
)
from inverter_monitor.ui.theme import apply_theme


SPEED = "M165_Motor_Position_Info.D2_Motor_Speed"
MODULE_B = "M160_Temperature_Set_1.D2_Module_B"
COMMANDED_SPEED = "MemoryView.Commanded_Speed_(RPM)"
MODULE_B_ADDRESS = 0x00A4


def _page() -> GraphsPage:
    catalog = load_catalog()
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    page = GraphsPage(catalog)
    page.show()
    app.processEvents()
    return page


def test_graph_signal_matches_name_and_message():
    assert graph_signal_matches(SPEED, "")
    assert graph_signal_matches(SPEED, "motor speed")
    assert graph_signal_matches(SPEED, "M165")
    assert not graph_signal_matches(SPEED, "torque")
    assert not graph_signal_matches(SPEED, "motor voltage")


def test_graphs_split_enabled_and_searchable():
    page = _page()
    app = QApplication.instance()
    assert set(page.selected_keys()) == set(DEFAULT_GRAPH_KEYS)
    assert SPEED in page.picker.visible_keys(enabled=True)
    assert MODULE_B in page.picker.visible_keys(enabled=False)

    page.picker.search.setText("module b")
    app.processEvents()
    assert page.picker.visible_keys(enabled=True) == []
    assert page.picker.visible_keys(enabled=False) == [MODULE_B]

    page.picker.chip(MODULE_B).setChecked(True)
    app.processEvents()
    assert MODULE_B in page.selected_keys()
    assert MODULE_B in page.picker.visible_keys(enabled=True)

    page.picker.search.clear()
    page.picker.chip(SPEED).setChecked(False)
    app.processEvents()
    assert SPEED not in page.selected_keys()
    assert SPEED in page.picker.visible_keys(enabled=False)
    page.close()
    app.processEvents()


def test_search_resets_the_chip_lists_to_the_top():
    """A search must not keep the old scroll offset, which hides the few matches."""
    page = _page()
    app = QApplication.instance()
    picker = page.picker
    available = picker._available_scroll
    bar = available.verticalScrollBar()
    assert bar.maximum() > 0  # the unfiltered list is taller than the viewport

    bar.setValue(bar.maximum())
    app.processEvents()
    picker.search.setText("module b")
    for _ in range(5):
        app.processEvents()

    chip = picker.chip(MODULE_B)
    assert chip.isVisible()
    offset = chip.mapTo(available.viewport(), chip.rect().topLeft()).y()
    assert offset >= 0, "match sits above the viewport after scrolling down"
    assert bar.value() == 0
    assert bar.maximum() == 0, "stale scroll range left over from the unfiltered list"

    picker.search.clear()
    for _ in range(5):
        app.processEvents()
    assert picker.chip(MODULE_B).mapTo(available.viewport(), picker.chip(MODULE_B).rect().topLeft()).y() >= 0
    page.close()
    app.processEvents()


def test_user_scroll_survives_a_chip_toggle():
    """Pin-to-top is released by a real scroll, so browsing stays where the user left it."""
    page = _page()
    app = QApplication.instance()
    available = page.picker._available_scroll
    bar = available.verticalScrollBar()
    page.picker.search.setText("module")
    app.processEvents()
    page.picker.search.clear()
    app.processEvents()
    assert available._pin_top

    for _ in range(6):
        app.sendEvent(
            available.viewport(),
            QWheelEvent(
                QPointF(10, 10),
                QPointF(10, 10),
                QPoint(0, 0),
                QPoint(0, -120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            ),
        )
        app.processEvents()
    assert not available._pin_top
    assert bar.value() > 0

    page.picker.chip(MODULE_B).setChecked(True)
    app.processEvents()
    assert bar.value() > 0, "the user's scroll position was thrown away by a rebuild"
    page.close()
    app.processEvents()


def test_graph_aliases_map_to_memory_view_addresses():
    catalog = load_catalog()
    assert graph_lookup_keys(SPEED) == (SPEED, "MemoryView.Feedback_Speed_(RPM)")
    addresses = graph_poll_addresses(catalog, DEFAULT_GRAPH_KEYS)
    assert FEEDBACK_SPEED_ADDRESS in addresses
    assert MOD_A_TEMP_ADDRESS in addresses
    assert MODULE_B_ADDRESS not in addresses
    assert MODULE_B_ADDRESS in graph_poll_addresses(catalog, [MODULE_B])
    keys = graphable_keys(catalog)
    assert SPEED in keys
    assert COMMANDED_SPEED in keys
    assert "MemoryView.Feedback_Speed_(RPM)" not in keys


def test_nearest_sample_picks_closest_time():
    points = [(0.0, 10.0), (1.0, 20.0), (2.0, 30.0)]
    assert nearest_sample(points, 1.1) == (1.0, 20.0)
    assert nearest_sample(points, 0.4) == (0.0, 10.0)
    assert nearest_sample([], 1.0) is None


def test_hover_rows_format_each_series_at_that_time():
    rows = hover_rows(
        [
            ("Motor_Speed", [(0.0, 1500.0), (1.0, 1600.0)], "#4c8dff"),
            ("Torque_Feedback", [(0.0, 10.0), (1.0, 12.5)], "#3ecf8e"),
            ("Empty", [], "#f5a524"),
        ],
        1.0,
    )
    assert rows == [
        ("Motor_Speed", "1600.0", "#4c8dff"),
        ("Torque_Feedback", "12.5", "#3ecf8e"),
    ]
    assert format_graph_number(9.25) == "9.25"
    html = format_hover_html(1.0, rows)
    assert "1.00 s" in html
    assert "Motor_Speed" in html
    assert "1600.0" in html
    assert "Torque_Feedback" in html


def test_graphs_plot_memory_view_speed():
    page = _page()
    catalog = load_catalog()
    store = InverterStore(catalog)
    decoder = Decoder(catalog)
    payload = pack_memory_frame(FEEDBACK_SPEED_ADDRESS, 1500)
    updates = decoder.decode_frame(MEMORY_FRAME_ID, payload)
    store.apply_frame(MEMORY_FRAME_ID, payload, updates, now=1.0, name="Memory_View")
    page.update_from(store.snapshot(now=1.0))
    assert SPEED in page._buffers
    assert page._buffers[SPEED][-1][1] == 1500.0
    page.close()
    QApplication.instance().processEvents()


def test_graphs_hover_lists_values_at_that_time():
    page = _page()
    catalog = load_catalog()
    store = InverterStore(catalog)
    decoder = Decoder(catalog)
    payload = pack_memory_frame(FEEDBACK_SPEED_ADDRESS, 1500)
    updates = decoder.decode_frame(MEMORY_FRAME_ID, payload)
    store.apply_frame(MEMORY_FRAME_ID, payload, updates, now=1.0, name="Memory_View")
    page.update_from(store.snapshot(now=1.0))
    page.hover_at(0.0)
    app = QApplication.instance()
    app.processEvents()
    assert page.hover_label.isVisible()
    text = page.hover_label.text()
    assert "0.00 s" in text
    assert "D2_Motor_Speed" in text
    assert "1500.0" in text
    page.hover_at(None)
    app.processEvents()
    assert page.hover_label.isHidden()
    page.close()
    app.processEvents()
