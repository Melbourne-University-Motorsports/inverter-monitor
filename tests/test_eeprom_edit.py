import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from inverter_monitor.catalog import load_catalog
from inverter_monitor.memory_map import (
    MemoryPoller,
    WatchList,
    edit_unit,
    format_engineering,
    parse_engineering,
    parse_raw_word,
)


def _by_address():
    return {item.address: item for item in load_catalog().memory_symbols}


def test_edit_units_only_where_obvious():
    symbols = _by_address()
    assert edit_unit(symbols[0x0117]) == "V"  # DC_UnderVolt_Thresh_EEPROM_(V)_x_10
    assert edit_unit(symbols[0x011A]) == "deg"  # Gamma_Adjust_EEPROM_(Deg)_x_10
    assert edit_unit(symbols[0x0101]) == "A"
    assert edit_unit(symbols[0x0106]) == "°C"
    assert edit_unit(symbols[0x0120]) == "kbps"
    assert edit_unit(symbols[0x011B]) == ""  # Inv_Cmd_Mode_EEPROM(CAN=0_VSM=1)
    assert edit_unit(symbols[0x0116]) == ""  # Run_Mode_EEPROM(Trq=0_Spd=1)
    assert edit_unit(symbols[0x0129]) == ""  # hex Lo word
    assert edit_unit(symbols[0x0113]) == ""  # serial number has no unit


def test_engineering_round_trip():
    symbols = _by_address()
    undervolt = symbols[0x0117]
    assert format_engineering(undervolt, 5) == "0.5"
    assert parse_engineering(undervolt, "0.5 V") == 5
    assert parse_engineering(undervolt, "0.5") == 5
    gamma = symbols[0x011A]
    assert format_engineering(gamma, 0xFFF8) == "-0.8"
    assert parse_engineering(gamma, "-0.8") == 0xFFF8
    delay = symbols[0x0118]
    assert format_engineering(delay, 1100) == "1100"
    assert parse_engineering(delay, "1100") == 1100


def test_engineering_rejects_out_of_range_with_plain_message():
    symbols = _by_address()
    with pytest.raises(ValueError, match="between"):
        parse_engineering(symbols[0x0117], "99999")
    with pytest.raises(ValueError, match="not a number"):
        parse_engineering(symbols[0x0117], "abc")


def test_raw_word_accepts_dec_and_hex():
    symbols = _by_address()
    assert parse_raw_word(symbols[0x011D], "160") == 160
    assert parse_raw_word(symbols[0x011D], "0x00A0") == 160
    assert parse_raw_word(symbols[0x011A], "-8") == 0xFFF8
    with pytest.raises(ValueError, match="between"):
        parse_raw_word(symbols[0x011D], "70000")


def test_poller_single_read_joins_active_dump():
    poller = MemoryPoller(WatchList([0x0093]))
    poller.start_dump([0x0113, 0x0119])
    poller.request_read(0x0117)
    assert poller.next_address() == 0x0117
    assert poller.next_address() == 0x0093
    assert poller.next_address() == 0x0113
    assert poller.dump_progress().active


def _eeprom_item(page, address: int):
    item = page.tree.item_for_address(address)
    assert item is not None
    return item


def _feed_eeprom(page, raws: dict[int, int]):
    from inverter_monitor.decode import Decoder
    from inverter_monitor.memory_map import MEMORY_FRAME_ID, DumpProgress, pack_memory_frame
    from inverter_monitor.store import InverterStore

    catalog = page._catalog
    decoder = Decoder(catalog)
    store = InverterStore(catalog)
    for address, raw in raws.items():
        payload = pack_memory_frame(address, raw)
        updates = decoder.decode_frame(MEMORY_FRAME_ID, payload)
        store.apply_frame(MEMORY_FRAME_ID, payload, updates, now=1.0, name="Memory_View")
    snapshot = store.snapshot(now=1.0)
    progress = DumpProgress(done=len(raws), total=len(raws), active=False)
    page.update_from(snapshot, progress)
    return snapshot, progress


def test_eeprom_page_apply_marks_row_dirty_until_flashed():
    from PySide6.QtWidgets import QApplication

    from inverter_monitor.ui.eeprom import DIRTY_BG, EepromPage

    catalog = load_catalog()
    app = QApplication.instance() or QApplication([])
    page = EepromPage(catalog)
    page.show()
    app.processEvents()
    page.set_rs232_active(True)
    assert not page.push_btn.isEnabled()
    snapshot, progress = _feed_eeprom(page, {0x0117: 0, 0x011A: 0xFFF8})

    item = _eeprom_item(page, 0x0117)
    page.tree.setCurrentItem(item)
    item.setSelected(True)
    app.processEvents()
    assert page.units_field.isVisible()
    assert page.units_field.text() == "0.0"

    page.units_field.setText("0.5")
    app.processEvents()
    assert page.pending_writes() == ((0x0117, 5),)
    assert page.dirty.text() == "1 unsaved"
    assert page.push_btn.isEnabled()

    page.update_from(snapshot, progress)
    assert item.text(page.tree.value_column) == "0.50"
    assert item.background(page.tree.value_column).color() == DIRTY_BG

    page.mark_flashed([0x0117])
    assert page.pending_count == 0
    assert page.dirty.text() == ""
    assert item.background(page.tree.value_column).color() != DIRTY_BG


def test_eeprom_typing_stages_and_invalid_unstages():
    from PySide6.QtWidgets import QApplication

    from inverter_monitor.ui.eeprom import EepromPage

    catalog = load_catalog()
    app = QApplication.instance() or QApplication([])
    page = EepromPage(catalog)
    page.show()
    app.processEvents()
    page.set_rs232_active(True)
    _feed_eeprom(page, {0x0117: 0})

    item = _eeprom_item(page, 0x0117)
    page.tree.setCurrentItem(item)
    item.setSelected(True)
    app.processEvents()

    page.units_field.setText("abc")
    app.processEvents()
    assert page.pending_count == 0
    assert "not a number" in page.validation.text()

    page.units_field.setText("1.0")
    app.processEvents()
    assert page.pending_writes() == ((0x0117, 10),)
    assert page.validation.text() == ""

    # Typing back the inverter value unstages the row.
    page.units_field.setText("0.0")
    app.processEvents()
    assert page.pending_count == 0
    assert item.text(page.tree.value_column) == "0.00"


def test_eeprom_card_height_stable_and_no_reset_on_readonly():
    from PySide6.QtWidgets import QApplication

    from inverter_monitor.ui.eeprom import EepromPage

    catalog = load_catalog()
    app = QApplication.instance() or QApplication([])
    page = EepromPage(catalog)
    page.show()
    app.processEvents()
    page.set_rs232_active(True)
    _feed_eeprom(page, {0x0117: 0, 0x0050: 0x2022})
    rereads: list[int] = []
    page.single_read_requested.connect(rereads.append)

    fixed = page.edit_card.height()
    item = _eeprom_item(page, 0x0117)
    page.tree.setCurrentItem(item)
    item.setSelected(True)
    app.processEvents()
    assert page.edit_card.height() == fixed
    assert page.reset_btn.isVisible()

    page.units_field.setText("0.5")
    app.processEvents()
    assert page.pending_count == 1
    page.reset_btn.click()
    app.processEvents()
    assert page.pending_count == 0
    assert rereads == [0x0117]
    assert not page.push_btn.isEnabled()

    info = _eeprom_item(page, 0x0050)
    page.tree.setCurrentItem(info)
    info.setSelected(True)
    app.processEvents()
    assert page.edit_card.height() == fixed
    assert page.reset_btn.isHidden()
    assert "Read-only" in page.baseline_label.text()
