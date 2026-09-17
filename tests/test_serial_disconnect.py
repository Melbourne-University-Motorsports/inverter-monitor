import os
import queue
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from serial import SerialException, SerialTimeoutException
from PySide6.QtWidgets import QApplication

from inverter_monitor.catalog import load_catalog
from inverter_monitor.decode import Decoder
from inverter_monitor.memory_map import MemoryPoller, VSM_STATE_ADDRESS, WatchList
from inverter_monitor.serial_memory import SerialMemoryViewSource
from inverter_monitor.serial_sci import (
    close_serial,
    serial_lost_reason,
    SerialSciSource,
)
from inverter_monitor.transport import FramePump, SourceLost
from inverter_monitor.ui.main_window import MainWindow
from inverter_monitor.ui.theme import apply_theme


UNPLUG = SerialException(
    "device reports readiness to read but returned no data "
    "(device disconnected or multiple access on port?)"
)


class _FakeSerial:
    def __init__(self, **kwargs):
        self.is_open = True
        self.closed = False
        self.cancelled = False

    def write(self, data):
        raise UNPLUG

    @property
    def in_waiting(self):
        raise UNPLUG

    def read(self, size):
        raise UNPLUG

    def cancel_read(self):
        self.cancelled = True

    def cancel_write(self):
        self.cancelled = True

    def close(self):
        self.is_open = False
        self.closed = True


def test_timeout_is_not_a_lost_port():
    assert serial_lost_reason(SerialTimeoutException("write timeout")) is None
    assert serial_lost_reason(ValueError("bad hex")) is None


def test_unplug_errors_become_plain_language():
    reason = serial_lost_reason(UNPLUG, port="/dev/cu.test")
    assert reason is not None
    assert "unplugged" in reason.lower()
    assert "/dev/cu.test" in reason
    mac = OSError(6, "Device not configured")
    mac.errno = 6
    assert serial_lost_reason(mac) is not None


def test_close_serial_swallows_dead_port():
    class Boom:
        is_open = True

        def cancel_read(self):
            raise OSError("gone")

        def close(self):
            raise OSError("gone")

    close_serial(Boom())
    close_serial(None)


def test_memory_view_unplug_raises_source_lost(monkeypatch):
    import serial as serial_mod

    monkeypatch.setattr(serial_mod, "Serial", _FakeSerial)
    poller = MemoryPoller(WatchList((VSM_STATE_ADDRESS,)))
    source = SerialMemoryViewSource("/dev/cu.test", poller)
    with pytest.raises(SourceLost, match="unplugged"):
        source.recv(0.2)
    source.close()
    assert source._serial.closed


def test_sci_source_unplug_raises_source_lost(monkeypatch):
    import serial as serial_mod

    monkeypatch.setattr(serial_mod, "Serial", _FakeSerial)
    source = SerialSciSource("/dev/cu.test")
    with pytest.raises(SourceLost, match="unplugged"):
        source.recv(0.2)
    source.close()


def test_frame_pump_stops_on_source_lost():
    catalog = load_catalog()
    decoder = Decoder(catalog)
    closed = {"done": False}

    class LostSource:
        label = "rs232:/dev/cu.test"

        def recv(self, timeout):
            raise SourceLost("Serial port /dev/cu.test unplugged. Plug it back in and press Start.")

        def close(self):
            closed["done"] = True

    out = queue.SimpleQueue()
    pump = FramePump(LostSource(), decoder, catalog, out)
    pump.start()
    pump._thread.join(timeout=2.0)
    assert not pump._thread.is_alive()
    assert pump.lost_reason is not None
    assert "unplugged" in pump.lost_reason
    assert closed["done"]


def test_frame_pump_stop_does_not_wait_out_hung_close():
    catalog = load_catalog()
    decoder = Decoder(catalog)

    class HungSource:
        label = "rs232:hung"

        def recv(self, timeout):
            time.sleep(min(timeout, 0.02))
            return None

        def interrupt(self):
            return None

        def close(self):
            time.sleep(5)

    pump = FramePump(HungSource(), decoder, catalog, queue.SimpleQueue())
    pump.start()
    time.sleep(0.05)
    started = time.monotonic()
    pump.stop()
    assert time.monotonic() - started < 2.0


def test_status_strip_unplug_is_not_idle():
    catalog = load_catalog()
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    window = MainWindow(catalog)
    snapshot = window.store.snapshot()
    window.strip.update_from(snapshot, "disconnected", False)
    assert window.strip.enable.text() == "ENABLE —"
    assert window.strip.faults.text() == "FAULTS —"
    assert window.strip.source.text() == "DISCONNECTED"
    assert window.strip.rate.text() == "0 fps"
    reason = "Serial port /dev/cu.test unplugged. Plug it back in and press Start."
    window.strip.update_from(snapshot, "disconnected", False, reason)
    assert "unplugged" in window.strip.vsm_desc.text().lower()
    assert window.strip.enable.text() == "ENABLE —"
    window.close()
    app.processEvents()


def test_main_window_returns_to_start_when_pump_loses_source():
    catalog = load_catalog()
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    window = MainWindow(catalog)

    class LostPump:
        def __init__(self):
            self.source = type(
                "Src",
                (),
                {
                    "last_write_error": None,
                    "last_write_ok": False,
                    "last_write_address": None,
                },
            )()
            self.lost_reason = "Serial port /dev/cu.test unplugged. Plug it back in and press Start."
            self.stopped = False

        def stop(self):
            self.stopped = True

    pump = LostPump()
    window._pump = pump
    window._source_label = "rs232:/dev/cu.test@57600"
    window.connect_btn.setText("Stop")
    window._drain()
    assert pump.stopped
    assert window._pump is None
    assert window.connect_btn.text() == "Start"
    assert window.strip.source.text() == "DISCONNECTED"
    assert "unplugged" in window.strip.vsm_desc.text().lower()
    assert window.strip.enable.text() == "ENABLE —"
    window.close()
    app.processEvents()
