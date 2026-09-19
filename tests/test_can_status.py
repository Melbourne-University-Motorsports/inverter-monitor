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
    POST_FAULT_LO_ADDRESS,
    RUN_FAULT_LO_ADDRESS,
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
    # The Faults page treats a clean POST word as the fault feed being present;
    # otherwise it shows NO DATA even while the CAN registers are reading fine.
    for address, value in ((POST_FAULT_LO_ADDRESS, 0), (RUN_FAULT_LO_ADDRESS, 0)):
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


def test_faults_page_headline_carries_the_can_flag():
    catalog = load_catalog()
    app = _app()
    page = FaultsPage(catalog)
    page.show()
    app.processEvents()

    _, _, clean = _snapshot(catalog, status=0x0000, faults=0x0000, tx=0, rx=0)
    page.update_from(clean)
    assert page.headline.text() == "ALL CLEAR"
    assert page.headline.property("tone") == "ok"

    # With no inverter faults and a degraded CAN, the CAN problem leads the
    # headline rather than be a footnote on "ALL CLEAR".
    _, _, degraded = _snapshot(catalog, status=0x0020, faults=0x000B, tx=97, rx=2)
    page.update_from(degraded)
    assert page.headline.text() == "CAN degraded"
    assert page.headline.property("tone") == "warn"
    assert "No inverter faults (POST/RUN all clear)" in page.counts.text()

    # Bus off is red and leads the headline too.
    _, _, bus_off = _snapshot(catalog, status=0x0080, faults=0x0000, tx=255, rx=0)
    page.update_from(bus_off)
    assert page.headline.text() == "CAN bus off"
    assert page.headline.property("tone") == "fault"

    page.close()
    app.processEvents()


def test_faults_page_can_section_is_terse_until_you_click_the_chip():
    catalog = load_catalog()
    app = _app()
    page = FaultsPage(catalog)
    page.show()
    app.processEvents()

    _, _, clean = _snapshot(catalog, status=0x0000, faults=0x0000, tx=0, rx=0)
    page.update_from(clean)
    section = page.can_section
    assert section.title.text().startswith("CAN MODULE")
    assert section.hint.text() == "click chip for details"
    assert section.chip.text() == "CAN OK"
    assert section.chip.property("tone") == "ok"
    assert section.values.text() == "Status 0000h   Faults (sticky) 0000h   Tx 0   Rx 0"
    assert "No CAN errors" in section.note.text()
    assert section.property("tone") is None  # quiet frame when healthy
    # The detail pane stays empty until the user clicks the chip.
    assert page.detail.toPlainText() == ""

    # Error Warning in the status word, ACKE + Stuff Error + Stuck At Dominant latched.
    _, _, degraded = _snapshot(catalog, status=0x0020, faults=0x000B, tx=97, rx=2)
    page.update_from(degraded)
    assert section.chip.text() == "CAN degraded"
    assert section.chip.property("tone") == "warn"
    assert section.property("tone") == "warn"  # orange-framed block when degraded
    # The always-on note stays short — bit names only, no full explanations.
    assert "Error Warning" in section.note.text()
    assert "Acknowledge Error" in section.note.text()
    assert page.detail.toPlainText() == ""

    # Clicking the chip routes the annotated reasons into the detail pane.
    section.chip.clicked.emit()
    detail = page.detail.toPlainText()
    assert "Error Warning —" in detail
    assert "Acknowledge Error —" in detail
    assert "Stuck At Dominant" in detail  # explained, not a trigger itself
    assert "clear with Clear Faults" in detail

    page.close()
    app.processEvents()



def test_faults_page_can_section_no_feed():
    catalog = load_catalog()
    app = _app()
    page = FaultsPage(catalog)
    page.show()
    app.processEvents()
    page.update_from(_memory_view_only_snapshot(catalog))
    section = page.can_section
    assert section.chip.text() == "CAN —"
    assert section.chip.property("tone") == "dim"
    assert "No fresh CAN status reading yet." in section.note.text()
    assert not section.values.isVisible()
    page.close()
    app.processEvents()



def test_status_strip_reflects_the_can_flag():
    catalog = load_catalog()
    app = _app()
    strip = StatusStrip(catalog)
    _, _, clean = _snapshot(catalog, status=0x0000, faults=0x0000, tx=0, rx=0)
    strip.update_from(clean, "RS232", True)
    assert strip.faults.text() == "FAULTS 0"
    assert strip.faults.property("tone") == "ok"

    _, _, degraded = _snapshot(catalog, status=0x0020, faults=0x000B, tx=97, rx=2)
    strip.update_from(degraded, "RS232", True)
    assert strip.faults.text() == "FAULTS 0 · CAN DEGRADED"
    assert strip.faults.property("tone") == "warn"

    _, _, bus_off = _snapshot(catalog, status=0x0080, faults=0x0000, tx=255, rx=0)
    strip.update_from(bus_off, "RS232", True)
    assert strip.faults.text() == "FAULTS 0 · CAN BUS OFF"
    assert strip.faults.property("tone") == "fault"

    # Memory View up but CAN registers not polled yet: no false alarm.
    strip.update_from(_memory_view_only_snapshot(catalog), "RS232", True)
    assert strip.faults.text() == "FAULTS 0"
    assert strip.faults.property("tone") == "ok"
    app.processEvents()


def _memory_view_only_snapshot(catalog):
    """Memory View is up (VSM_State read) but the CAN registers are not polled yet."""
    store = InverterStore(catalog)
    decoder = Decoder(catalog)
    payload = pack_memory_frame(0x0093, 4)
    updates = decoder.decode_frame(MEMORY_FRAME_ID, payload)
    store.apply_frame(MEMORY_FRAME_ID, payload, updates, now=1.0, name="Memory_View")
    return store.snapshot(now=1.0)