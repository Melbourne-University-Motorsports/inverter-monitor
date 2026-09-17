import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
from inverter_monitor.ui.graphs import GraphsPage, graph_signal_matches
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
