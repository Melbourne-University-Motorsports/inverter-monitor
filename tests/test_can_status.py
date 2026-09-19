import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from inverter_monitor.can_health import (
    FAULT,
    NO_FEED_NOTE,
    OK,
    UNKNOWN,
    WARNING,
    WAITING_NOTE,
    evaluate_can_health,
)
from inverter_monitor.catalog import load_catalog
from inverter_monitor.decode import Decoder, encode_physical
from inverter_monitor.memory_map import (
    CAN_FAULTS_ADDRESS,
    CAN_RX_ERROR_ADDRESS,
    CAN_STATUS_ADDRESS,
    CAN_STATUS_WATCH_ADDRESSES,
    CAN_TX_ERROR_ADDRESS,
    CAN_TX_ERROR_MAX_ADDRESS,
    MEMORY_FRAME_ID,
    pack_memory_frame,
)
from inverter_monitor.store import InverterStore
from inverter_monitor.ui.faults import FaultsPage
from inverter_monitor.ui.theme import apply_theme
from inverter_monitor.ui.widgets import StatusStrip


def _app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


def _snapshot(catalog, *, status=None, faults=None, tx=None, rx=None, now=1.0):
    store = InverterStore(catalog)
    decoder = Decoder(catalog)
    for address, value in (
        (CAN_STATUS_ADDRESS, status),
        (CAN_FAULTS_ADDRESS, faults),
        (CAN_TX_ERROR_ADDRESS, tx),
        (CAN_RX_ERROR_ADDRESS, rx),
    ):
        if value is None:
            continue
        payload = pack_memory_frame(address, value)
        updates = decoder.decode_frame(MEMORY_FRAME_ID, payload)
        store.apply_frame(MEMORY_FRAME_ID, payload, updates, now=now, name="Memory_View")
    return store, decoder, store.snapshot(now=now)


def test_can_status_catalog_matches_the_gen3_register_map():
    catalog = load_catalog()
    can = catalog.can_status
    assert can.applies_to.startswith("Gen 3")
    assert "Gen 3 only" in can.source

    status = can.register("CAN_Status")
    faults = can.register("CAN_Faults")
    assert status is not None and faults is not None
    assert (status.address, faults.address) == (0x00C8, 0x00C9)
    assert faults.sticky and not status.sticky

    masks = {bit.mask: bit for bit in status.bits}
    assert masks[0x0080].severity == "fault" and masks[0x0080].name == "Bus Off"
    assert masks[0x0040].severity == "warning"  # Error Passive
    assert masks[0x0020].severity == "warning"  # Error Warning
    assert {masks[mask].severity for mask in (0x0001, 0x0002, 0x0004, 0x0008, 0x0010)} == {"info"}

    fault_masks = {bit.mask for bit in faults.bits}
    assert fault_masks == {0x01, 0x02, 0x04, 0x08, 0x10, 0x20}
    assert {bit.mask: bit.severity for bit in faults.bits}[0x08] == "info"  # Stuck At Dominant 1

    counters = {counter.name: counter for counter in can.counters}
    assert counters["CAN_Tx_Error_Counter"].address == CAN_TX_ERROR_ADDRESS
    assert counters["CAN_Rx_Error_Counter"].address == CAN_RX_ERROR_ADDRESS
    assert counters["CAN_Tx_Error_Counter_(Max)"].address == CAN_TX_ERROR_MAX_ADDRESS
    assert counters["CAN_Rx_Error_Counter"].maximum == 127
    assert all(counter.warn_at == 96 for counter in counters.values())

    # Gen 5/CM watch items are filed separately and are not the Gen 3 map.
    assert "CAN_Status_Bus_Off" in can.gen5_only
    assert "CAN_Status" not in can.gen5_only
    assert {note.name for note in can.undocumented} == {"CANES_Low", "CANES_High"}


def test_can_status_symbols_exist_in_the_defsyms_catalog():
    catalog = load_catalog()
    by_key = {symbol.key: symbol for symbol in catalog.memory_symbols}
    for register in catalog.can_status.registers:
        symbol = by_key[register.symbol]
        assert symbol.address == register.address
    for counter in catalog.can_status.counters:
        symbol = by_key[counter.symbol]
        assert symbol.address == counter.address


def test_faults_tab_polls_the_can_registers():
    assert CAN_STATUS_WATCH_ADDRESSES == (
        CAN_STATUS_ADDRESS,
        CAN_FAULTS_ADDRESS,
        CAN_TX_ERROR_ADDRESS,
        CAN_RX_ERROR_ADDRESS,
    )
    catalog = load_catalog()
    for address in CAN_STATUS_WATCH_ADDRESSES:
        assert address in catalog.memory_by_address


def test_clean_words_read_ok():
    catalog = load_catalog()
    _, _, snapshot = _snapshot(catalog, status=0x0000, faults=0x0000, tx=0, rx=0)
    health = evaluate_can_health(snapshot, catalog)
    assert health.level == OK
    assert health.label == "CAN OK"
    assert health.reasons == ()
    assert health.counters == (("CAN_Tx_Error_Counter", 0), ("CAN_Rx_Error_Counter", 0))


def test_error_warning_bit_is_a_degraded_warning_with_an_explanation():
    catalog = load_catalog()
    _, _, snapshot = _snapshot(catalog, status=0x0020, faults=0x0000, tx=99, rx=3)
    health = evaluate_can_health(snapshot, catalog)
    assert health.level == WARNING
    assert health.label == "CAN degraded"
    assert health.tone == "warn"
    assert any("Error Warning" in reason and "96" in reason for reason in health.reasons)


def test_error_passive_and_latched_fault_bits_are_warnings():
    catalog = load_catalog()
    _, _, snapshot = _snapshot(catalog, status=0x0040, faults=0x0010, tx=140, rx=0)
    health = evaluate_can_health(snapshot, catalog)
    assert health.level == WARNING
    assert any("Error Passive" in reason for reason in health.reasons)
    assert any("Bit Error" in reason for reason in health.reasons)
    assert "Error Passive" in health.note and "Bit Error" in health.note


def test_bus_off_is_a_fault():
    catalog = load_catalog()
    _, _, snapshot = _snapshot(catalog, status=0x0080, faults=0x0004, tx=255, rx=0)
    health = evaluate_can_health(snapshot, catalog)
    assert health.level == FAULT
    assert health.label == "CAN bus off"
    assert health.tone == "fault"
    assert any("Bus Off" in reason for reason in health.reasons)
    assert "no messages can be sent or received" in health.note


def test_stuck_dominant_alone_does_not_raise_the_flag():
    """The bit sets on every power-up, so it must not cry wolf on its own."""
    catalog = load_catalog()
    _, _, snapshot = _snapshot(catalog, status=0x0000, faults=0x0008, tx=0, rx=0)
    health = evaluate_can_health(snapshot, catalog)
    assert health.level == OK
    assert health.reasons == ()
    assert health.note.startswith("No CAN errors")


def test_tx_counter_at_the_warning_level_is_a_warning():
    catalog = load_catalog()
    _, _, snapshot = _snapshot(catalog, status=0x0000, faults=0x0000, tx=96, rx=0)
    health = evaluate_can_health(snapshot, catalog)
    assert health.level == WARNING
    assert any("CAN Tx Error Counter at 96" in reason for reason in health.reasons)


def test_no_can_diagnostics_on_this_feed_reads_as_unavailable():
    catalog = load_catalog()
    store = InverterStore(catalog)
    decoder = Decoder(catalog)
    message = catalog.messages_by_name["M170_Internal_States"]
    payload = encode_physical(message, {"D1_VSM_State": 4})
    store.apply_frame(message.can_id, payload, decoder.decode_frame(message.can_id, payload), now=1.0)
    snapshot = store.snapshot(now=1.0)
    health = evaluate_can_health(snapshot, catalog)
    assert health.level == UNKNOWN
    assert health.label == "CAN —"
    assert health.note == NO_FEED_NOTE

    # Memory View is running but the CAN poll has not landed yet.
    waiting = _memory_view_only_snapshot(catalog)
    assert evaluate_can_health(waiting, catalog).note == WAITING_NOTE


def test_stale_can_words_are_not_reported_as_ok():
    catalog = load_catalog()
    store, _, _ = _snapshot(catalog, status=0x0020, faults=0x0000, tx=0, rx=0, now=1.0)
    health = evaluate_can_health(store.snapshot(now=60.0), catalog)
    assert health.level == UNKNOWN
    assert health.note == WAITING_NOTE


def test_faults_page_shows_the_can_band_and_the_strip_reflects_it():
    catalog = load_catalog()
    app = _app()
    page = FaultsPage(catalog)
    page.show()
    app.processEvents()

    _, _, clean = _snapshot(catalog, status=0x0000, faults=0x0000, tx=0, rx=0)
    page.update_from(clean)
    assert page.can_chip.text() == "CAN OK"
    assert page.can_chip.property("tone") == "ok"
    assert page.can_values.text() == "0x00C8 0000   0x00C9 0000   Tx 0   Rx 0"

    # Error Warning in the status word, ACKE + Stuff Error + Stuck At Dominant latched.
    _, _, degraded = _snapshot(catalog, status=0x0020, faults=0x000B, tx=97, rx=2)
    page.update_from(degraded)
    assert page.can_chip.text() == "CAN degraded"
    assert page.can_chip.property("tone") == "warn"
    assert "Error Warning" in page.can_note.text()
    assert "Stuck At Dominant" in page.can_chip.toolTip()  # explained, not a trigger

    page.can_chip.clicked.emit()
    app.processEvents()
    detail = page.detail.toPlainText()
    assert "CAN degraded" in detail
    assert "Error Warning" in detail and "Acknowledge Error" in detail
    assert "Gen 3" in detail

    strip = StatusStrip(catalog)
    strip.update_from(clean, "RS232", True)
    assert strip.faults.text() == "FAULTS 0"
    assert strip.faults.property("tone") == "ok"

    strip.update_from(degraded, "RS232", True)
    assert strip.faults.text() == "FAULTS 0 · CAN DEGRADED"
    assert strip.faults.property("tone") == "warn"

    _, _, bus_off = _snapshot(catalog, status=0x0080, faults=0x0000, tx=255, rx=0)
    strip.update_from(bus_off, "RS232", True)
    assert strip.faults.text() == "FAULTS 0 · CAN BUS OFF"
    assert strip.faults.property("tone") == "fault"

    # Nothing read yet: the strip stays quiet rather than crying wolf.
    strip.update_from(_memory_view_only_snapshot(catalog), "RS232", True)
    assert strip.faults.text() == "FAULTS 0"
    assert strip.faults.property("tone") == "ok"

    page.close()
    app.processEvents()


def _memory_view_only_snapshot(catalog):
    """Memory View is up (VSM_State read) but the CAN registers are not polled yet."""
    store = InverterStore(catalog)
    decoder = Decoder(catalog)
    payload = pack_memory_frame(0x0093, 4)
    updates = decoder.decode_frame(MEMORY_FRAME_ID, payload)
    store.apply_frame(MEMORY_FRAME_ID, payload, updates, now=1.0, name="Memory_View")
    return store.snapshot(now=1.0)
