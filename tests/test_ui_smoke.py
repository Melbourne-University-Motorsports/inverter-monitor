import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from inverter_monitor.catalog import load_catalog
from inverter_monitor.calibration import EEPROM_STATE_ADDRESS
from inverter_monitor.cli import build_parser
from inverter_monitor.decode import Decoder
from inverter_monitor.memory_map import (
    CAN_ID_OFFSET_ADDRESS,
    DEFAULT_CAN_ID_OFFSET,
    DEFAULT_WATCH_ADDRESSES,
    FEEDBACK_SPEED_ADDRESS,
    MEMORY_FRAME_ID,
    STATUS_WATCH_ADDRESSES,
    VSM_STATE_ADDRESS,
    pack_memory_frame,
)
from inverter_monitor.ui.main_window import MainWindow
from inverter_monitor.ui.theme import apply_theme


def _visible_tree_names(tree) -> list[str]:
    names: list[str] = []
    for index in range(tree.topLevelItemCount()):
        heading = tree.topLevelItem(index)
        if heading is None or heading.isHidden():
            continue
        for child_index in range(heading.childCount()):
            child = heading.child(child_index)
            if child is not None and not child.isHidden():
                names.append(child.text(0))
    return names


def _tree_groups(tree) -> list[str]:
    return [
        tree.topLevelItem(index).text(0)
        for index in range(tree.topLevelItemCount())
        if tree.topLevelItem(index) is not None
    ]


def _select_tree_name(tree, name: str) -> None:
    for index in range(tree.topLevelItemCount()):
        heading = tree.topLevelItem(index)
        if heading is None:
            continue
        for child_index in range(heading.childCount()):
            child = heading.child(child_index)
            if child is not None and child.text(0) == name:
                tree.setCurrentItem(child)
                child.setSelected(True)
                return
    raise AssertionError(f"{name} not in tree")


def test_main_window_starts_and_paints():
    catalog = load_catalog()
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    window = MainWindow(catalog)
    window.show()
    app.processEvents()
    tabs = [window.tabs.tabText(index) for index in range(window.tabs.count())]
    assert tabs == ["Overview", "Faults", "Graphs", "Symbols", "EEPROM", "Calibration", "Raw", "States"]
    assert window.strip.vsm_name.text()
    assert window.strip.enable.text() == "ENABLE —"
    assert window.strip.faults.text() == "FAULTS —"
    assert window.strip.source.text() == "DISCONNECTED"
    labels = [window.source.itemText(i) for i in range(window.source.count())]
    assert labels == ["RS232"]
    assert window.source.isHidden()
    assert window.offset.value() == DEFAULT_CAN_ID_OFFSET
    assert window.offset.text() == "0x0A0"
    assert CAN_ID_OFFSET_ADDRESS not in window.watch_list.addresses()
    assert VSM_STATE_ADDRESS in window.watch_list.addresses()
    watch_headers = [
        window.symbols.watch_table.horizontalHeaderItem(index).text()
        for index in range(window.symbols.watch_table.columnCount())
    ]
    assert watch_headers == ["Address", "Name", "Value", "Raw"]
    watch_names = [
        window.symbols.watch_table.item(row, 1).text()
        for row in range(window.symbols.watch_table.rowCount())
    ]
    assert "CAN_ID_Offset_EEPROM" not in watch_names
    assert "VSM_State" in watch_names
    assert "Inverter_Enable" in watch_names
    assert "Inverter_Mode" in watch_names
    assert "Feedback_Speed_(RPM)" in watch_names
    assert "Mod_A_Temp_(C)_x_10" in watch_names
    assert "DIN1_Forward_Switch" in watch_names
    assert window.overview.flags["lockout"].isHidden()
    assert not window.overview.flags["discharge"].isHidden()
    assert "Accel analog 1" not in [card._title.text() for card in window.overview.cards]
    assert "Post_Fault_Lo" in watch_names
    assert "Run_Fault_Hi" in watch_names
    assert window.faults.auto_refresh.isChecked()
    assert window.faults.active.horizontalHeaderItem(0).text() != "Sev"
    headers = [
        window.faults.active.horizontalHeaderItem(index).text()
        for index in range(window.faults.active.columnCount())
    ]
    assert "Sev" not in headers
    assert window.faults.clear_btn.text() == "Clear faults"
    assert not window.faults.clear_btn.isEnabled()
    assert window.calibration.program_btn.text() == "Program EEPROM"
    assert not window.calibration.program_btn.isEnabled()
    assert window.calibration.steps.count() == 5
    assert "EEPROM" in window.calibration.steps.item(4).text()
    assert "Memory Values" in window.calibration.session.summary.text()
    assert "CAN" in _tree_groups(window.eeprom.tree)
    assert "Motor / Resolver" in _tree_groups(window.eeprom.tree)
    assert "Resolver" in _tree_groups(window.symbols.catalog_tree)
    assert "CAN_ID_Offset_EEPROM" in _visible_tree_names(window.eeprom.tree)
    assert "Serial_Number_EEPROM" in _visible_tree_names(window.eeprom.tree)
    assert "CAN_ID_Offset_EEPROM" not in _visible_tree_names(window.symbols.catalog_tree)
    assert window.source.currentText() == "RS232"
    assert not window.refresh_ports_btn.isHidden()
    assert not window.baud.isHidden()
    assert window.can_bitrate.isHidden()
    window.refresh_ports_btn.click()
    app.processEvents()
    assert window.tabs.isTabVisible(window.tabs.indexOf(window.eeprom))
    assert window.overview.flags["lockout"].isHidden()
    assert not window.refresh_ports_btn.isHidden()
    window.symbols.search.setText("vsm")
    app.processEvents()
    names = _visible_tree_names(window.symbols.catalog_tree)
    assert "VSM_State" in names
    _select_tree_name(window.symbols.catalog_tree, "VSM_State")
    window.symbols.add_btn.click()
    app.processEvents()
    assert 0x0093 in window.watch_list.addresses()
    assert not window.symbols.reload_btn.isEnabled()
    parser = build_parser()
    assert parser.parse_args([]).id_offset == DEFAULT_CAN_ID_OFFSET
    assert parser.parse_args(["--id-offset", "0"]).id_offset == 0
    assert parser.parse_args(["--id-offset", "0xB0"]).id_offset == 0xB0
    assert parser.parse_args(["--serial", "COM3"]).serial == "COM3"
    assert parser.parse_args(["--memory-view", "COM3"]).memory_view == "COM3"
    window.close()
    app.processEvents()


def test_memory_view_vsm_fills_status_and_overview():
    catalog = load_catalog()
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    window = MainWindow(catalog)
    decoder = Decoder(catalog)
    payload = pack_memory_frame(VSM_STATE_ADDRESS, 4)
    updates = decoder.decode_frame(MEMORY_FRAME_ID, payload)
    window.store.apply_frame(MEMORY_FRAME_ID, payload, updates, now=1.0, name="Memory_View")
    snapshot = window.store.snapshot(now=1.0)
    window.strip.update_from(snapshot, "rs232:/dev/cu.test", True)
    window.overview.update_from(snapshot, "RS232")
    window.states.update_from(snapshot)
    assert window.strip.vsm_id.text() == "4"
    assert "Wait" in window.strip.vsm_name.text()
    assert "Waiting for M170" not in window.strip.vsm_desc.text()
    assert "Waiting for M170" not in window.overview.detail.toPlainText()
    assert "VSM_Wait" in window.overview.detail.toPlainText() or "Wait" in window.overview.detail.toPlainText()
    assert window.overview.flags["lockout"].isHidden()
    speed = pack_memory_frame(FEEDBACK_SPEED_ADDRESS, 1500)
    speed_updates = decoder.decode_frame(MEMORY_FRAME_ID, speed)
    window.store.apply_frame(MEMORY_FRAME_ID, speed, speed_updates, now=1.0, name="Memory_View")
    window.overview.update_from(window.store.snapshot(now=1.0), "RS232")
    assert window.overview.cards[0]._value.text() == "1500"
    window.close()
    app.processEvents()


def _tree_value(tree, name: str) -> str:
    for index in range(tree.topLevelItemCount()):
        heading = tree.topLevelItem(index)
        if heading is None:
            continue
        for child_index in range(heading.childCount()):
            child = heading.child(child_index)
            if child is not None and child.text(0) == name:
                return child.text(3) if tree.columnCount() == 5 else child.text(2)
    raise AssertionError(f"{name} not in tree")


def test_eeprom_snapshot_and_manual_offset():
    catalog = load_catalog()
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    window = MainWindow(catalog)
    decoder = Decoder(catalog)
    payload = pack_memory_frame(CAN_ID_OFFSET_ADDRESS, 0x00B0)
    updates = decoder.decode_frame(MEMORY_FRAME_ID, payload)
    window.store.apply_frame(MEMORY_FRAME_ID, payload, updates, now=1.0, name="Memory_View")
    window._drain()
    assert window.offset.value() == 0x0B0
    assert _tree_value(window.eeprom.tree, "CAN_ID_Offset_EEPROM") == "0x00B0"
    window.offset.setValue(0x0C0)
    later = pack_memory_frame(CAN_ID_OFFSET_ADDRESS, 0x00A0)
    later_updates = decoder.decode_frame(MEMORY_FRAME_ID, later)
    window.store.apply_frame(MEMORY_FRAME_ID, later, later_updates, now=2.0, name="Memory_View")
    window._drain()
    assert window.offset.value() == 0x0C0
    assert window.eeprom.pull_btn.text() == "Pull from inverter"
    assert window.tabs.isTabVisible(window.tabs.indexOf(window.eeprom))
    assert _tree_value(window.eeprom.tree, "CAN_ID_Offset_EEPROM") == "0x00A0"
    window.close()
    app.processEvents()


def test_tab_poll_set_preserves_symbols_watch_list():
    catalog = load_catalog()
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    window = MainWindow(catalog)
    window.show()
    app.processEvents()

    extra_name = "Commanded_Speed_(RPM)"
    extra_address = 0x0096
    assert window.tabs.currentWidget() is window.overview
    assert window.poller.poll_addresses() == DEFAULT_WATCH_ADDRESSES
    assert extra_address not in window.watch_list.addresses()
    assert not window.symbols.reload_btn.isEnabled()

    window.tabs.setCurrentWidget(window.symbols)
    app.processEvents()
    assert window.poller.poll_addresses() == window.watch_list.addresses()
    window.symbols.search.setText("commanded_speed")
    app.processEvents()
    _select_tree_name(window.symbols.catalog_tree, extra_name)
    window.symbols.add_btn.click()
    app.processEvents()
    assert extra_address in window.watch_list.addresses()
    assert extra_address in window.poller.poll_addresses()
    assert window.symbols.reload_btn.isEnabled()

    window.tabs.setCurrentWidget(window.overview)
    app.processEvents()
    assert extra_address in window.watch_list.addresses()
    assert extra_address not in window.poller.poll_addresses()
    assert window.poller.poll_addresses() == DEFAULT_WATCH_ADDRESSES

    window.tabs.setCurrentWidget(window.graphs)
    app.processEvents()
    graph_poll = window.poller.poll_addresses()
    assert extra_address in window.watch_list.addresses()
    assert extra_address not in graph_poll
    assert FEEDBACK_SPEED_ADDRESS in graph_poll
    assert VSM_STATE_ADDRESS in graph_poll
    assert 0x00A4 not in graph_poll
    window.graphs.picker.chip("M160_Temperature_Set_1.D2_Module_B").setChecked(True)
    app.processEvents()
    assert 0x00A4 in window.poller.poll_addresses()
    assert extra_address in window.watch_list.addresses()
    assert extra_address not in window.poller.poll_addresses()

    window.tabs.setCurrentWidget(window.faults)
    app.processEvents()
    assert extra_address in window.watch_list.addresses()
    assert window.poller.poll_addresses() == STATUS_WATCH_ADDRESSES

    window.tabs.setCurrentWidget(window.eeprom)
    app.processEvents()
    assert window.poller.poll_addresses() == (*STATUS_WATCH_ADDRESSES, EEPROM_STATE_ADDRESS)

    window.tabs.setCurrentWidget(window.calibration)
    app.processEvents()
    cal_poll = window.poller.poll_addresses()
    assert extra_address in window.watch_list.addresses()
    assert extra_address not in cal_poll
    assert VSM_STATE_ADDRESS in cal_poll
    assert 0x0005 in cal_poll
    assert 0x0010 in cal_poll
    assert 0x0074 in cal_poll
    assert 0x0089 in cal_poll
    window.calibration.skip_delay.setChecked(True)
    app.processEvents()
    assert "skip" in window.calibration.steps.item(1).text().lower()
    assert not window.calibration.delay_page.isEnabled()

    window.tabs.setCurrentWidget(window.symbols)
    app.processEvents()
    watch_names = [
        window.symbols.watch_table.item(row, 1).text()
        for row in range(window.symbols.watch_table.rowCount())
    ]
    assert extra_name in watch_names
    assert extra_address in window.poller.poll_addresses()

    window.symbols.reload_btn.click()
    app.processEvents()
    assert extra_address not in window.watch_list.addresses()
    assert extra_name not in [
        window.symbols.watch_table.item(row, 1).text()
        for row in range(window.symbols.watch_table.rowCount())
    ]
    assert window.watch_list.addresses() == DEFAULT_WATCH_ADDRESSES
    assert window.poller.poll_addresses() == DEFAULT_WATCH_ADDRESSES
    assert not window.symbols.reload_btn.isEnabled()
    window.close()
    app.processEvents()


def test_calibration_proposes_next_gamma_from_ram_reads():
    catalog = load_catalog()
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    window = MainWindow(catalog)
    decoder = Decoder(catalog)
    now = 1.0
    for address, raw in ((0x0010, 100), (0x0089, 800), (0x0097, 1200)):
        payload = pack_memory_frame(address, raw)
        updates = decoder.decode_frame(MEMORY_FRAME_ID, payload)
        window.store.apply_frame(MEMORY_FRAME_ID, payload, updates, now=now, name="Memory_View")
    window.calibration.update_from(window.store.snapshot(now=now), "RS232", True)
    assert window.calibration.next_gamma == 0
    assert window.calibration.apply_gamma_btn.isEnabled()
    assert "0" in window.calibration.apply_gamma_btn.text()
    assert "CONVERGED ON" not in window.calibration.gamma_converged_chip.text()
    window.calibration._delta_at_gamma_write = 800
    window.calibration.update_from(window.store.snapshot(now=now), "RS232", True)
    assert not window.calibration.apply_gamma_btn.isEnabled()
    assert "Keep spinning" in window.calibration.gamma_status.text()
    assert not window.calibration.program_btn.isEnabled()
    window.close()
    app.processEvents()


def test_calibration_eeprom_program_enabled_in_wait():
    catalog = load_catalog()
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    window = MainWindow(catalog)
    decoder = Decoder(catalog)
    now = 1.0
    for address, raw in (
        (0x0005, 50),
        (0x0010, 0xFFF8),
        (0x0118, 50),
        (0x011A, 0xFFF8),
        (0x0056, 5),
        (0x0092, 1),
        (VSM_STATE_ADDRESS, 4),
        (0x0094, 0),
    ):
        payload = pack_memory_frame(address, raw)
        updates = decoder.decode_frame(MEMORY_FRAME_ID, payload)
        window.store.apply_frame(MEMORY_FRAME_ID, payload, updates, now=now, name="Memory_View")
    window.calibration.update_from(window.store.snapshot(now=now), "RS232", True)
    assert window.calibration.program_btn.isEnabled()
    busy = pack_memory_frame(0x0056, 7)
    updates = decoder.decode_frame(MEMORY_FRAME_ID, busy)
    window.store.apply_frame(MEMORY_FRAME_ID, busy, updates, now=now, name="Memory_View")
    window.calibration.update_from(window.store.snapshot(now=now), "RS232", True)
    assert not window.calibration.program_btn.isEnabled()
    assert "programming" in window.calibration.ram_vs_eeprom.text().lower()
    window.close()
    app.processEvents()
