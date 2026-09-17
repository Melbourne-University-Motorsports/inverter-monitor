import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from inverter_monitor.catalog import load_catalog
from inverter_monitor.decode import Decoder, encode_physical
from inverter_monitor.store import InverterStore
from inverter_monitor.ui.faults import FaultsPage
from inverter_monitor.ui.theme import apply_theme


def test_faults_page_leads_with_active_name_not_severity():
    catalog = load_catalog()
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    page = FaultsPage(catalog)
    assert page.auto_refresh.isChecked()
    headers = [page.active.horizontalHeaderItem(index).text() for index in range(page.active.columnCount())]
    assert headers == ["", "Name", "Bit"]
    assert page.headline.text() == "NO DATA"

    decoder = Decoder(catalog)
    store = InverterStore(catalog)
    message = catalog.messages_by_name["M171_Fault_Codes"]
    payload = encode_physical(message, {"D3_Run_Fault_Lo": 0x1000})
    updates = decoder.decode_frame(0x0AB, payload)
    store.apply_frame(0x0AB, payload, updates, now=1.0, name=message.name)
    page.update_from(store.snapshot(now=1.0))

    assert page.headline.text() == "1 FAULT"
    assert page.active.rowCount() == 1
    assert page.active.item(0, 0).text() == "RUN"
    assert "Motor Over-temperature" in page.active.item(0, 1).text()
    assert page.active.item(0, 2).text() == "44"
    assert page.empty.isHidden()
    assert "Motor Over-temperature" in page.detail.toPlainText()

    page.auto_refresh.setChecked(False)
    cleared = encode_physical(message, {"D3_Run_Fault_Lo": 0})
    store.apply_frame(0x0AB, cleared, decoder.decode_frame(0x0AB, cleared), now=2.0, name=message.name)
    page.update_from(store.snapshot(now=2.0))
    assert page.headline.text() == "1 FAULT"
    page.refresh_btn.click()
    assert page.headline.text() == "ALL CLEAR"
    page.close()
