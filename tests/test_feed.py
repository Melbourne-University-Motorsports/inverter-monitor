"""Liveness/feed-state tests: the UI must not present last-known values as current.

Covers the two failures the status strip and pages have to tell apart:
a dead transport (USB serial unplugged / stopped) and a live transport with a
quiet inverter (powered off).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from inverter_monitor.catalog import load_catalog
from inverter_monitor.decode import Decoder, encode_physical
from inverter_monitor.feed import (
    DISCONNECTED,
    LIVE,
    NO_DATA,
    feed_state,
)
from inverter_monitor.memory_map import (
    FEEDBACK_SPEED_ADDRESS,
    MEMORY_FRAME_ID,
    VSM_STATE_ADDRESS,
    WatchList,
    pack_memory_frame,
)
from inverter_monitor.store import InverterStore
from inverter_monitor.ui.faults import FaultsPage
from inverter_monitor.ui.overview import OverviewPage
from inverter_monitor.ui.states import StatesPage
from inverter_monitor.ui.symbols import SymbolsPage
from inverter_monitor.ui.theme import apply_theme
from inverter_monitor.ui.widgets import StatusStrip


def _app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


def _memory_snapshot(catalog, address, raw, now):
    store = InverterStore(catalog)
    decoder = Decoder(catalog)
    payload = pack_memory_frame(address, raw)
    updates = decoder.decode_frame(MEMORY_FRAME_ID, payload)
    store.apply_frame(MEMORY_FRAME_ID, payload, updates, now=now, name="Memory_View")
    return store


def test_feed_state_separates_disconnected_from_inverter_off():
    catalog = load_catalog()
    empty = InverterStore(catalog).snapshot(now=5.0)

    idle = feed_state(empty, running=False)
    assert idle.stage == DISCONNECTED
    assert not idle.live and idle.tone == "dim"
    assert "Start" in idle.reason

    lost = feed_state(empty, running=False, lost_reason="Serial port /dev/cu.test unplugged.")
    assert lost.stage == DISCONNECTED
    assert lost.alert and lost.tone == "warn"
    assert "unplugged" in lost.reason

    quiet = feed_state(empty, running=True)
    assert quiet.stage == NO_DATA
    assert quiet.connected and not quiet.live and quiet.tone == "warn"
    assert "powered on" in quiet.reason


def test_frame_rate_decays_when_the_inverter_goes_quiet():
    """Regression: the rate used to freeze at its last value after the last frame."""
    catalog = load_catalog()
    store = _memory_snapshot(catalog, VSM_STATE_ADDRESS, 4, now=1.0)
    assert store.snapshot(now=1.5).frames_per_sec == 1
    assert store.snapshot(now=3.0).frames_per_sec == 0


def test_status_strip_drops_last_values_when_inverter_goes_quiet():
    catalog = load_catalog()
    app = _app()
    store = _memory_snapshot(catalog, VSM_STATE_ADDRESS, 4, now=1.0)
    strip = StatusStrip(catalog)

    live = store.snapshot(now=1.0)
    strip.update_from(live, "rs232:/dev/cu.test@57600", True, feed=feed_state(live, True))
    assert strip.vsm_id.text() == "4"
    assert strip.source.text() == "RS232:/DEV/CU.TEST@57600"

    quiet = store.snapshot(now=10.0)
    quiet_feed = feed_state(quiet, True)
    assert not quiet_feed.live
    strip.update_from(quiet, "rs232:/dev/cu.test@57600", True, feed=quiet_feed)
    assert strip.vsm_id.text() == "—"
    assert strip.vsm_name.text() == "No data"
    assert "powered on" in strip.vsm_desc.text()
    assert strip.enable.text() == "ENABLE —"
    assert strip.source.text() == "NO DATA"
    assert strip.rate.text() == "0 fps"
    app.processEvents()


def test_overview_blanks_last_values_when_inverter_goes_quiet():
    catalog = load_catalog()
    app = _app()
    store = _memory_snapshot(catalog, FEEDBACK_SPEED_ADDRESS, 1500, now=1.0)
    page = OverviewPage(catalog)

    live = store.snapshot(now=1.0)
    page.update_from(live, "RS232", feed=feed_state(live, True))
    assert page.cards[0]._value.text() == "1500"

    quiet = store.snapshot(now=10.0)
    quiet_feed = feed_state(quiet, True)
    page.update_from(quiet, "RS232", feed=quiet_feed)
    assert page.cards[0]._value.text() == "—"
    assert page.cards[0]._unit.text() == ""
    assert "powered on" in page.detail.toPlainText()
    assert page.relays.text() == "Relays —"
    app.processEvents()


def test_faults_page_does_not_keep_last_faults_when_feed_dies():
    catalog = load_catalog()
    app = _app()
    store = InverterStore(catalog)
    decoder = Decoder(catalog)
    message = catalog.messages_by_name["M171_Fault_Codes"]
    payload = encode_physical(message, {"D3_Run_Fault_Lo": 0x1000})
    updates = decoder.decode_frame(0x0AB, payload)
    store.apply_frame(0x0AB, payload, updates, now=1.0, name=message.name)

    page = FaultsPage(catalog)
    live = store.snapshot(now=1.0)
    page.update_from(live, feed=feed_state(live, True))
    assert page.headline.text() == "1 FAULT"
    assert page.active.rowCount() == 1

    quiet = store.snapshot(now=10.0)
    quiet_feed = feed_state(quiet, True)
    assert not quiet_feed.live
    page.update_from(quiet, feed=quiet_feed)
    assert page.headline.text() == "NO DATA"
    assert "powered on" in page.counts.text()
    assert page.active.isHidden()
    assert page.empty.isHidden()
    assert page.live_label.text() == "No data"
    assert page.can_section.chip.text() == "CAN —"
    app.processEvents()


def test_states_page_clears_the_last_highlight_when_feed_dies():
    catalog = load_catalog()
    app = _app()
    store = _memory_snapshot(catalog, VSM_STATE_ADDRESS, 4, now=1.0)
    page = StatesPage(catalog)

    live = store.snapshot(now=1.0)
    page.update_from(live, feed=feed_state(live, True))
    active_row = next(
        row
        for row in range(page.vsm_table.rowCount())
        if page.vsm_table.item(row, 0).text() == "4"
    )
    assert page.vsm_table.item(active_row, 0).background().color().alpha() == 50

    quiet = store.snapshot(now=10.0)
    page.update_from(quiet, feed=feed_state(quiet, True))
    assert page.vsm_table.item(active_row, 0).background().color().alpha() == 0
    app.processEvents()


def test_symbols_page_blanks_watch_values_when_feed_dies():
    catalog = load_catalog()
    app = _app()
    watch = WatchList((VSM_STATE_ADDRESS,))
    page = SymbolsPage(catalog, watch)
    store = _memory_snapshot(catalog, VSM_STATE_ADDRESS, 4, now=1.0)

    live = store.snapshot(now=1.0)
    page.update_from(live, feed=feed_state(live, True))
    assert page.watch_table.item(0, 2).text() != "—"

    quiet = store.snapshot(now=10.0)
    page.update_from(quiet, feed=feed_state(quiet, True))
    assert page.watch_table.item(0, 2).text() == "—"
    assert page.watch_table.item(0, 3).text() == "—"
    app.processEvents()


def test_live_feed_still_reports_live():
    catalog = load_catalog()
    store = _memory_snapshot(catalog, VSM_STATE_ADDRESS, 4, now=1.0)
    state = feed_state(store.snapshot(now=1.0), True)
    assert state.stage == LIVE and state.live and state.tone == "ok"
