import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from inverter_monitor.catalog import load_catalog
from inverter_monitor.decode import Decoder
from inverter_monitor.memory_map import MEMORY_FRAME_ID, pack_memory_frame
from inverter_monitor.ui.main_window import MainWindow


class FakeSource:
    """Stands in for SerialMemoryViewSource: records writes, mimics the public ack state."""

    def __init__(self) -> None:
        self.label = "fake"
        self.queued: list[tuple[int, int]] = []
        self.sent: list[tuple[int, int]] = []
        self.last_write_ok = False
        self.last_write_error: str | None = None
        self.last_write_address: int | None = None
        self.write_count = 0

    def enqueue_write(self, address: int, value: int) -> None:
        self.queued.append((int(address), int(value)))

    def flush_one(self, *, fail: bool = False, error: str = "boom") -> tuple[int, int]:
        address, value = self.queued.pop(0)
        self.sent.append((address, value))
        self.last_write_address = address
        self.write_count += 1
        if fail:
            self.last_write_ok = False
            self.last_write_error = error
        else:
            self.last_write_ok = True
            self.last_write_error = None
        return address, value


class FakePump:
    def __init__(self, source: FakeSource) -> None:
        self.source = source

    def stop(self) -> None: ...


class _AutoYes:
    """QMessageBox stand-in whose exec() confirms."""

    StandardButton = QMessageBox.StandardButton

    def __init__(self, *args, **kwargs) -> None:
        self._text = ""

    def setWindowTitle(self, *_a) -> None: ...
    def setText(self, text) -> None: self._text = text
    def setInformativeText(self, *_a) -> None: ...
    def setDetailedText(self, *_a) -> None: ...
    def setStandardButtons(self, *_a) -> None: ...
    def setDefaultButton(self, *_a) -> None: ...
    def exec(self):
        return QMessageBox.StandardButton.Yes


def _window_with_edits(edits: list[tuple[int, int]]):
    import inverter_monitor.ui.main_window as mw

    app = QApplication.instance() or QApplication([])
    catalog = load_catalog()
    window = MainWindow(catalog)
    decoder = Decoder(catalog)
    for address, raw in ((0x0093, 4), (0x0094, 0), (0x0092, 0), *edits):
        payload = pack_memory_frame(address, raw)
        window.store.apply_frame(
            MEMORY_FRAME_ID, payload, decoder.decode_frame(MEMORY_FRAME_ID, payload), now=1.0
        )
    for address, raw in edits:
        window.eeprom._baseline[address] = raw
        window.eeprom._pending[address] = raw
    source = FakeSource()
    window._pump = FakePump(source)
    return app, window, source


def _drive(window, source, *, max_steps=20):
    """Flush queued words one at a time, exactly as FramePump would."""
    steps = 0
    while source.queued and steps < max_steps:
        source.flush_one()
        window._update_clear_status()
        steps += 1
    return steps


def test_push_sends_every_word_and_the_commit_pair(monkeypatch):
    import inverter_monitor.ui.main_window as mw

    monkeypatch.setattr(mw, "QMessageBox", _AutoYes)
    app, window, source = _window_with_edits([(0x0117, 5)])
    window._push_eeprom()
    app.processEvents()
    assert source.queued, "push should enqueue the edited word"
    _drive(window, source)
    assert source.sent == [(0x0117, 5), (0x0000, 0x5A0F), (0x0001, 0x0059)]
    assert window._push_dialog is not None
    assert window._push_dialog.done_btn.isEnabled()
    window.close()


def test_push_does_not_stall_after_a_successful_word(monkeypatch):
    import inverter_monitor.ui.main_window as mw

    monkeypatch.setattr(mw, "QMessageBox", _AutoYes)
    app, window, source = _window_with_edits([(0x0117, 5), (0x011A, 0xFFF6)])
    window._push_eeprom()
    app.processEvents()
    steps = _drive(window, source)
    assert steps < 20, "push loop did not finish; it stalled"
    assert len(source.sent) == 4
    assert source.queued == []
    window.close()


def test_push_reports_failure_instead_of_hanging(monkeypatch):
    import inverter_monitor.ui.main_window as mw

    monkeypatch.setattr(mw, "QMessageBox", _AutoYes)
    app, window, source = _window_with_edits([(0x0117, 5)])
    window._push_eeprom()
    app.processEvents()
    # The edited word fails; the loop must still try to program the EEPROM.
    source.flush_one(fail=True, error="No RAE")
    window._update_clear_status()
    assert source.queued, "loop stalled after a failed edit"
    _drive(window, source)
    assert source.sent == [(0x0117, 5), (0x0000, 0x5A0F), (0x0001, 0x0059)]
    assert source.queued == []
    assert window._push_dialog is not None
    assert window._push_dialog.done_btn.isEnabled()
    text = window._push_dialog.status.text()
    assert "failed" in text.lower()
    window.close()

