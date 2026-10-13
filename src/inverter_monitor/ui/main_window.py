from __future__ import annotations

import queue

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from inverter_monitor.calibration import (
    EEPROM_COMMIT_COMMAND,
    EEPROM_COMMIT_UNLOCK,
    EEPROM_STATE_ADDRESS,
    EEPROM_WRITE_ADDRESSES,
    RAM_WRITE_ADDRESSES,
    eeprom_persist_writes,
    read_calibration,
    write_blocked_reason,
)
from inverter_monitor.catalog import Catalog
from inverter_monitor.decode import M193_PARAM_COMMAND_ID, PARAM_CLEAR_FAULTS, Decoder, pack_param_write
from inverter_monitor.feed import feed_state
from inverter_monitor.memory_map import (
    CAN_STATUS_WATCH_ADDRESSES,
    CLEAR_FAULTS_ADDRESS,
    DEFAULT_CAN_ID_OFFSET,
    DEFAULT_WATCH_ADDRESSES,
    OVERVIEW_WATCH_ADDRESSES,
    STATUS_WATCH_ADDRESSES,
    MemoryPoller,
    WatchList,
    snapshot_addresses,
)
from inverter_monitor.serial_memory import SerialMemoryViewSource
from inverter_monitor.serial_sci import SCI_BAUD, list_serial_ports
from inverter_monitor.store import InverterStore, first_signal, get_signal
from inverter_monitor.transport import FramePump, LiveCanSource
from inverter_monitor.ui.calibration import CalibrationPage
from inverter_monitor.ui.eeprom import (
    EepromPage,
    EepromPushDialog,
    EepromPushStep,
    describe_word,
)
from inverter_monitor.ui.faults import FaultsPage
from inverter_monitor.ui.graphs import GraphsPage
from inverter_monitor.ui.overview import OverviewPage
from inverter_monitor.ui.raw import RawPage
from inverter_monitor.ui.states import StatesPage
from inverter_monitor.ui.symbols import SymbolsPage
from inverter_monitor.ui.widgets import HexSpinBox, StatusStrip


def _looks_like_serial(text: str) -> bool:
    return text.upper().startswith("COM") or text.startswith("/dev/")


class MainWindow(QMainWindow):
    def __init__(self, catalog: Catalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PM100 Inverter Monitor")
        self.resize(1280, 800)
        self.catalog = catalog
        self.store = InverterStore(catalog)
        self.decoder = Decoder(catalog)
        self.bitrate = 500000
        self.serial_baud = SCI_BAUD
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._pump: FramePump | None = None
        self._source_label = "disconnected"
        self._lost_reason: str | None = None
        self.watch_list = WatchList(DEFAULT_WATCH_ADDRESSES)
        self.poller = MemoryPoller(self.watch_list)
        self._offset_from_memory: int | None = None
        self._offset_from_user = False
        self._setting_offset = False

        self.source_label = QLabel("Source")
        self.source = QComboBox()
        self.source.addItems(["RS232"])
        self.source.hide()
        self.source_label.hide()
        self.channel = QComboBox()
        self.channel.setEditable(True)
        self.channel.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.channel.setMinimumWidth(180)
        self.baud = QSpinBox()
        self.baud.setRange(1200, 921600)
        self.baud.setValue(SCI_BAUD)
        self.can_bitrate = QSpinBox()
        self.can_bitrate.setRange(10000, 1000000)
        self.can_bitrate.setValue(500000)
        self.can_bitrate.setSingleStep(10000)
        self.offset = HexSpinBox(digits=3)
        self.offset.setRange(0, 2047)
        self.offset.setValue(DEFAULT_CAN_ID_OFFSET)
        self.offset.valueChanged.connect(self._offset_edited)
        self.connect_btn = QPushButton("Start")
        self.connect_btn.setObjectName("primary")
        self.connect_btn.clicked.connect(self._toggle)
        self.refresh_ports_btn = QPushButton("Refresh")
        self.refresh_ports_btn.setToolTip("Rescan serial ports")
        self.refresh_ports_btn.clicked.connect(self._refresh_ports)

        self.port_label = QLabel("Port")
        self.baud_label = QLabel("Baud")
        self.bitrate_label = QLabel("Bitrate")
        self.offset_label = QLabel("CAN ID offset")

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.source_label)
        toolbar.addWidget(self.source)
        toolbar.addSpacing(14)
        toolbar.addWidget(self.port_label)
        toolbar.addWidget(self.channel, 1)
        toolbar.addWidget(self.refresh_ports_btn)
        toolbar.addWidget(self.baud_label)
        toolbar.addWidget(self.baud)
        toolbar.addWidget(self.bitrate_label)
        toolbar.addWidget(self.can_bitrate)
        toolbar.addSpacing(14)
        toolbar.addWidget(self.offset_label)
        toolbar.addWidget(self.offset)
        toolbar.addSpacing(14)
        toolbar.addWidget(self.connect_btn)

        self.strip = StatusStrip(catalog)
        self.tabs = QTabWidget()
        self.overview = OverviewPage(catalog)
        self.faults = FaultsPage(catalog)
        self.faults.clear_requested.connect(self._clear_faults)
        self._clear_pending = False
        self.graphs = GraphsPage(catalog)
        self.graphs.selection_changed.connect(self._sync_poll_set)
        self.raw = RawPage()
        self.states = StatesPage(catalog)
        self.symbols = SymbolsPage(catalog, self.watch_list)
        self.symbols.watches_changed.connect(self._sync_poll_set)
        self.eeprom = EepromPage(catalog)
        self.eeprom.pull_requested.connect(self._pull_eeprom)
        self.eeprom.push_requested.connect(self._push_eeprom)
        self.eeprom.single_read_requested.connect(self._single_read_eeprom)
        self._push_active = False
        self._push_cancelled = False
        self._push_remaining: list[tuple[int, int]] = []
        self._push_head: tuple[int, int] | None = None
        self._push_head_count: int | None = None
        self._push_results: dict[int, bool] = {}
        self._push_errors: dict[int, str] = {}
        self._push_dialog: EepromPushDialog | None = None
        self.calibration = CalibrationPage()
        self.calibration.ram_write_requested.connect(self._calibration_ram_write)
        self.calibration.eeprom_commit_requested.connect(self._calibration_eeprom_commit)
        self.tabs.addTab(self.overview, "Overview")
        self.tabs.addTab(self.faults, "Faults")
        self.tabs.addTab(self.graphs, "Graphs")
        self.tabs.addTab(self.symbols, "Symbols")
        self.tabs.addTab(self.eeprom, "EEPROM")
        self.tabs.addTab(self.calibration, "Calibration")
        self.tabs.addTab(self.raw, "Raw")
        self.tabs.addTab(self.states, "States")
        self.tabs.currentChanged.connect(self._sync_poll_set)
        self._sync_poll_set()

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(toolbar)
        layout.addWidget(self.strip)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

        about = QAction("About", self)
        about.triggered.connect(self._about)
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        file_menu.addAction("Quit", self.close, QKeySequence.StandardKey.Quit)
        help_menu = menu.addMenu("&Help")
        help_menu.addAction(about)

        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._drain)
        self._timer.start()

        self.source.currentTextChanged.connect(self._source_changed)
        self._source_changed(self.source.currentText())
        self.offset_label.hide()
        self.offset.hide()
        self.bitrate_label.hide()
        self.can_bitrate.hide()

    def start_rs232(self, port: str, baud: int = SCI_BAUD) -> None:
        self.source.setCurrentText("RS232")
        self.baud.setValue(baud)
        self._set_channel(port)
        if self._pump is None:
            self._toggle()

    def start_memory_view(self, port: str, baud: int = SCI_BAUD) -> None:
        self.start_rs232(port, baud=baud)

    def start_can(self, channel: str, bitrate: int = 500000) -> None:
        if self.source.findText("CAN") < 0:
            self.source.addItem("CAN")
        self.source.setCurrentText("CAN")
        self.can_bitrate.setValue(bitrate)
        self._set_channel(channel)
        if self._pump is None:
            self._toggle()

    def _channel_text(self) -> str:
        return self.channel.currentText().strip()

    def _set_channel(self, value: str) -> None:
        if self.channel.findText(value) < 0:
            self.channel.addItem(value)
        self.channel.setCurrentText(value)

    def _refresh_ports(self) -> None:
        current = self._channel_text()
        self.channel.clear()
        ports = list_serial_ports()
        if ports:
            self.channel.addItems(ports)
        if current:
            self._set_channel(current)
        elif ports:
            self.channel.setCurrentIndex(0)

    def _source_changed(self, name: str) -> None:
        rs232 = name == "RS232"
        for widget in (self.baud, self.baud_label, self.refresh_ports_btn):
            widget.setVisible(rs232)
        for widget in (self.can_bitrate, self.bitrate_label):
            widget.setVisible(not rs232)
        snapshot = self.store.snapshot()
        feed = feed_state(snapshot, self._pump is not None, self._lost_reason)
        if rs232:
            self.port_label.setText("Port")
            self._refresh_ports()
            self._sync_eeprom_tab()
            self.overview.update_from(snapshot, "RS232", feed=feed)
            return
        self.port_label.setText("Channel")
        if not self._channel_text() or _looks_like_serial(self._channel_text()):
            self._set_channel("can0")
        self._sync_eeprom_tab()
        self.overview.update_from(snapshot, "CAN", feed=feed)

    def _sync_poll_set(self, _index: int = 0) -> None:
        current = self.tabs.currentWidget()
        if current is self.symbols:
            extra = self.watch_list.addresses()
        elif current is self.graphs:
            extra = self.graphs.poll_addresses()
        elif current is self.calibration:
            extra = self.calibration.poll_addresses()
        elif current is self.faults:
            # Faults also reads the CAN module's status/fault words and error
            # counters (Gen 3 memory view) so the CAN flag has something to show.
            extra = CAN_STATUS_WATCH_ADDRESSES
        elif current is self.eeprom:
            extra = (EEPROM_STATE_ADDRESS,)
        elif current is self.overview or current is self.raw:
            extra = OVERVIEW_WATCH_ADDRESSES
        else:
            extra = ()
        self.poller.set_active_addresses((*STATUS_WATCH_ADDRESSES, *extra))

    def _sync_eeprom_tab(self) -> None:
        index = self.tabs.indexOf(self.eeprom)
        if index < 0:
            return
        show = self.source.currentText() == "RS232" or self.eeprom.has_snapshot
        self.tabs.setTabVisible(index, show)

    def _make_source(self):
        kind = self.source.currentText()
        if kind == "RS232":
            port = self._channel_text()
            if not port:
                raise FileNotFoundError(
                    "Select an RS232 port. Close RMS GUI first. RS232 polls with rm only."
                )
            return SerialMemoryViewSource(port, self.poller, baud=self.baud.value())
        if kind != "CAN":
            raise ValueError(f"Unknown source: {kind}")
        channel = self._channel_text()
        if not channel:
            raise FileNotFoundError("Set a CAN channel.")
        self.bitrate = self.can_bitrate.value()
        return LiveCanSource(channel=channel, bitrate=self.bitrate)

    def _toggle(self) -> None:
        if self._pump is not None:
            self._lost_reason = None
            self._stop()
            return
        try:
            source = self._make_source()
        except Exception as exc:
            QMessageBox.critical(self, "Cannot start source", str(exc))
            return
        self._lost_reason = None
        kind = self.source.currentText()
        self.decoder = Decoder(
            self.catalog,
            id_offset=self.offset.value() if kind == "CAN" else 0,
        )
        self.store = InverterStore(self.catalog)
        self._queue = queue.SimpleQueue()
        if kind == "RS232":
            self.poller.start_dump(snapshot_addresses(self.catalog.memory_symbols))
        self._pump = FramePump(source, self.decoder, self.catalog, self._queue)
        self._pump.start()
        self._source_label = source.label
        self.connect_btn.setText("Stop")
        self.eeprom.set_rs232_active(kind == "RS232")

    def _stop(self) -> None:
        if self._pump is not None:
            self._pump.stop()
            self._pump = None
        self.connect_btn.setText("Start")
        self._source_label = "disconnected"
        self.eeprom.set_rs232_active(False)

    def _source_lost(self, reason: str) -> None:
        self._stop()
        self._lost_reason = reason
        if self.source.currentText() == "RS232":
            self._refresh_ports()

    def _drain(self) -> None:
        drained = 0
        while drained < 32:
            try:
                batch = self._queue.get_nowait()
            except queue.Empty:
                break
            for frame, updates, name in batch.frames:
                self.store.apply_frame(frame.arbitration_id, frame.data, updates, name=name)
            drained += 1
        if self._pump is not None and self._pump.lost_reason:
            self._source_lost(self._pump.lost_reason)
        snapshot = self.store.snapshot()
        offset_signal = get_signal(snapshot, "MemoryView.CAN_ID_Offset_EEPROM")
        if offset_signal and offset_signal.raw is not None and not self._offset_from_user:
            raw = int(offset_signal.raw) & 0xFFFF
            if raw != self._offset_from_memory:
                self._offset_from_memory = raw
                self._setting_offset = True
                self.offset.setValue(raw)
                self._setting_offset = False
        running = self._pump is not None
        rs232 = running and self.source.currentText() == "RS232"
        feed = feed_state(snapshot, running, self._lost_reason)
        self.strip.update_from(snapshot, self._source_label, running, self._lost_reason, feed=feed)
        self.overview.update_from(snapshot, self.source.currentText(), feed=feed)
        self.faults.update_from(snapshot, feed)
        self._update_clear_status()
        self.graphs.update_from(snapshot)
        self.symbols.update_from(snapshot, feed)
        self.eeprom.set_rs232_active(rs232)
        self.eeprom.update_from(snapshot, self.poller.dump_progress())
        self._sync_eeprom_tab()
        self.calibration.update_from(snapshot, self.source.currentText(), rs232)
        self.raw.update_from(snapshot)
        self.states.update_from(snapshot, feed)

    def _offset_edited(self, _value: int) -> None:
        if not self._setting_offset:
            self._offset_from_user = True

    def _update_clear_status(self) -> None:
        if self._pump is None:
            if self._push_active:
                self._abort_push("Connection lost.")
            return
        source = self._pump.source
        error = getattr(source, "last_write_error", None)
        accepted = getattr(source, "last_write_ok", False)
        address = getattr(source, "last_write_address", None)
        if self._push_active:
            self._account_push_write(source, error, accepted, address)
            return
        if address in RAM_WRITE_ADDRESSES:
            self.calibration.set_write_status(error, accepted)
            return
        if address in EEPROM_WRITE_ADDRESSES:
            self.calibration.set_write_status(error, accepted, kind="eeprom")
            return
        if error:
            self.faults.set_command_status(error, False)
            self._clear_pending = False
        elif accepted and self._clear_pending:
            self.faults.set_command_status("Clear command accepted", True)
            self._clear_pending = False

    def _clear_faults(self) -> None:
        if self._pump is None:
            QMessageBox.information(self, "Not connected", "Start RS232 or CAN first.")
            return
        snapshot = self.store.snapshot()
        enable = first_signal(
            snapshot,
            "M170_Internal_States.D6_Inverter_Enable_State",
            "MemoryView.Inverter_Enable",
        )
        enabled = bool(enable.value) if enable else False
        if self.source.currentText() == "CAN" and enabled:
            QMessageBox.warning(
                self,
                "Inverter still enabled",
                "In CAN mode the inverter must be disabled before Clear Faults.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Clear faults",
            "Send Clear Faults Command (value 0)?\n\n"
            "Clears active POST and RUN faults except EEPROM Update Required.\n"
            "Hardware Gate/Desaturation is latching and needs a power cycle.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        source = self._pump.source
        if hasattr(source, "enqueue_write"):
            source.enqueue_write(CLEAR_FAULTS_ADDRESS, 0)
        elif hasattr(source, "enqueue_send"):
            source.enqueue_send(
                M193_PARAM_COMMAND_ID + self.offset.value(),
                pack_param_write(PARAM_CLEAR_FAULTS, 0),
            )
        else:
            QMessageBox.information(self, "Cannot clear", "This source cannot send a clear command.")
            return
        self._clear_pending = True
        self.faults.set_command_status("Sending clear command…", True)

    def _calibration_ram_write(self, address: int, value: int) -> None:
        if address not in RAM_WRITE_ADDRESSES:
            QMessageBox.warning(
                self,
                "Write blocked",
                f"0x{address:04X} is not on the RAM allow-list (Delay Command, Gamma Adjust).",
            )
            return
        if self._pump is None or self.source.currentText() != "RS232":
            QMessageBox.information(
                self,
                "RS232 not running",
                "Start RS232 first. Delay and Gamma RAM writes use Memory View wm.",
            )
            return
        source = self._pump.source
        if not hasattr(source, "enqueue_write"):
            QMessageBox.information(self, "Cannot write", "This source cannot send Memory View writes.")
            return
        snapshot = self.store.snapshot()
        reading = read_calibration(snapshot)
        blocked = write_blocked_reason(reading.vsm, reading.enable, reading.inverter_mode)
        if blocked:
            QMessageBox.warning(self, "Write blocked", blocked)
            return
        source.enqueue_write(address, value)
        self.calibration.note_write(address, value)

    def _calibration_eeprom_commit(self) -> None:
        if self._pump is None or self.source.currentText() != "RS232":
            QMessageBox.information(
                self,
                "RS232 not running",
                "Start RS232 first.",
            )
            return
        source = self._pump.source
        if not hasattr(source, "enqueue_write"):
            QMessageBox.information(self, "Cannot write", "This source cannot send Memory View writes.")
            return
        snapshot = self.store.snapshot()
        reading = read_calibration(snapshot)
        blocked = write_blocked_reason(
            reading.vsm, reading.enable, reading.inverter_mode, kind="eeprom"
        )
        if blocked:
            QMessageBox.warning(self, "Write blocked", blocked)
            return
        if reading.delay_command is None or reading.gamma_adjust_x10 is None:
            QMessageBox.information(
                self,
                "Still reading",
                "Need Delay and Gamma first.",
            )
            return
        delay = reading.delay_command
        gamma = reading.gamma_adjust_x10
        answer = QMessageBox.question(
            self,
            "Program EEPROM?",
            f"Save Delay {delay} and Gamma {gamma} ({gamma / 10:.1f}°) to EEPROM?\n\n"
            "After: Recycle Power → off 20–30 s → on.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for address, value in eeprom_persist_writes(delay, gamma):
            source.enqueue_write(address, value)
            self.calibration.note_write(address, value)

    def _pull_eeprom(self) -> None:
        if self._pump is None or self.source.currentText() != "RS232":
            QMessageBox.information(
                self,
                "RS232 not running",
                "Start RS232 first. EEPROM words are Memory View reads, not CAN.",
            )
            return
        self.poller.start_dump(snapshot_addresses(self.catalog.memory_symbols))

    def _single_read_eeprom(self, address: int) -> None:
        if self._pump is None or self.source.currentText() != "RS232":
            return
        self.poller.request_read(int(address))

    # -- EEPROM push ----------------------------------------------------

    _PUSH_COMMIT_LABELS = {
        EEPROM_COMMIT_UNLOCK[0]: ("Program EEPROM — unlock", "wm0000=5a0f"),
        EEPROM_COMMIT_COMMAND[0]: ("Program EEPROM — commit", "wm0001=0059"),
    }

    def _push_eeprom(self) -> None:
        if self._push_dialog is not None:
            QMessageBox.information(self, "Push running", "A push is already open.")
            return
        if self._pump is None or self.source.currentText() != "RS232":
            QMessageBox.information(
                self,
                "RS232 not running",
                "Start RS232 first. EEPROM words are Memory View writes, not CAN.",
            )
            return
        pending = self.eeprom.pending_writes()
        if not pending:
            QMessageBox.information(
                self,
                "Nothing to flash",
                "No edited values. Double-click an EEPROM value to edit it first.",
            )
            return
        snapshot = self.store.snapshot()
        reading = read_calibration(snapshot)
        blocked = write_blocked_reason(
            reading.vsm, reading.enable, reading.inverter_mode, kind="eeprom"
        )
        if blocked:
            QMessageBox.warning(self, "Cannot push yet", blocked)
            return
        lines: list[str] = []
        for address, raw in pending:
            symbol = self.catalog.memory_by_address.get(address)
            if symbol is None:
                continue
            old = describe_word(symbol, self.eeprom.baseline_raw(address))
            lines.append(f"{symbol.name} ({symbol.address_text}): {old} → {describe_word(symbol, raw)}")
        box = QMessageBox(self)
        box.setWindowTitle(f"Push {len(lines)} edits to inverter?")
        box.setText(
            f"Write {len(lines)} edited words with Memory View (wm), "
            "then program EEPROM (wm0000/wm0001)?"
        )
        box.setInformativeText(
            "After programming: Recycle Power → off 20–30 s → on. "
            "Expect POST 26 (EEPROM Update Required), then VSM 15 (Recycle Power)."
        )
        box.setDetailedText("\n".join(lines))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        steps = [
            EepromPushStep(
                address,
                f"{self.catalog.memory_by_address[address].name} "
                f"({self.catalog.memory_by_address[address].address_text})",
                f"{describe_word(symbol, self.eeprom.baseline_raw(address))} → "
                f"{describe_word(symbol, raw)}",
            )
            for address, raw in pending
            if (symbol := self.catalog.memory_by_address.get(address)) is not None
        ]
        for address, (label, detail) in self._PUSH_COMMIT_LABELS.items():
            steps.append(EepromPushStep(address, f"{label} ({address:#06x})", detail))
        self._push_dialog = EepromPushDialog(self, steps)
        self._push_dialog.cancel_requested.connect(self._cancel_push)
        self._push_dialog.done_requested.connect(self._finish_push)
        self._push_active = True
        self._push_cancelled = False
        self._push_remaining = [(address, raw) for address, raw in pending]
        self._push_remaining.extend([EEPROM_COMMIT_UNLOCK, EEPROM_COMMIT_COMMAND])
        self._push_head = None
        self._push_results = {}
        self._push_errors = {}
        self._push_dialog.set_status("Sending edited words…")
        self._push_dialog.show()
        self._send_next_push()

    def _send_next_push(self) -> None:
        dialog = self._push_dialog
        if dialog is None:
            return
        if self._pump is None:
            self._abort_push("Connection lost.")
            return
        source = self._pump.source
        if not hasattr(source, "enqueue_write"):
            self._abort_push("This source cannot send Memory View writes.")
            return
        if not self._push_remaining:
            self._complete_push()
            return
        address, value = self._push_remaining.pop(0)
        self._push_head = (address, value)
        # Watch a monotonic count, not the sticky ok/error pair: two successful
        # writes look identical there, which stalled the loop after one word and
        # left the commit pair unsent.
        self._push_head_count = int(getattr(source, "write_count", 0))
        source.enqueue_write(address, value)
        if address in (EEPROM_COMMIT_UNLOCK[0], EEPROM_COMMIT_COMMAND[0]):
            dialog.cancel_btn.setEnabled(False)
            dialog.set_status("Programming EEPROM — do not unplug or power off…")

    def _account_push_write(
        self, source: object, error: str | None, accepted: bool, address: int | None
    ) -> None:
        dialog = self._push_dialog
        if dialog is None or self._push_head is None:
            return
        head_address, _value = self._push_head
        if address != head_address:
            return
        if self._push_head_count is not None:
            if int(getattr(source, "write_count", 0)) == self._push_head_count:
                return
            self._push_head_count = None
        ok = bool(accepted) and not error
        self._push_results[head_address] = ok
        if not ok:
            self._push_errors[head_address] = error or "No acknowledgement from the inverter."
        dialog.set_step_status(head_address, "Sent ✓" if ok else "Failed", ok)
        dialog.set_status(f"Sent {len(self._push_results)}/{dialog.progress.maximum()} words…")
        self._push_head = None
        commit = {EEPROM_COMMIT_UNLOCK[0], EEPROM_COMMIT_COMMAND[0]}
        if not ok and head_address in commit:
            self._abort_push(
                f"Program EEPROM failed ({self._push_errors[head_address]}). "
                "Nothing was programmed — your edits are still unsaved."
            )
            return
        if self._push_cancelled:
            for rest, _ in self._push_remaining:
                dialog.set_step_status(rest, "Skipped", None)
            self._push_remaining = []
            self._complete_push(cancelled=True)
            return
        self._send_next_push()

    def eeprom_progress_done(self) -> int:
        return len(self._push_results)

    def eeprom_progress_total(self) -> int:
        dialog = self._push_dialog
        if dialog is None:
            return 0
        return dialog.progress.maximum()

    def _complete_push(self, cancelled: bool = False) -> None:
        dialog = self._push_dialog
        if dialog is None:
            return
        self._push_active = False
        commit = {EEPROM_COMMIT_UNLOCK[0], EEPROM_COMMIT_COMMAND[0]}
        failed = sorted(
            address for address, ok in self._push_results.items() if not ok and address not in commit
        )
        programmed = self._push_results.get(EEPROM_COMMIT_COMMAND[0], False)
        recycle = (
            "Recycle Power → off 20–30 s → on. Expect POST 26 "
            "(EEPROM Update Required), then VSM 15 (Recycle Power). "
            "While EEprom_State reads 7, EEPROM reads may show 0 — "
            "that is the busy window, not a wipe."
        )
        if cancelled and not programmed:
            dialog.finish(
                "Stopped before programming — nothing was flashed. "
                "Your edits are still unsaved."
            )
            return
        if not programmed:
            dialog.finish("Nothing was flashed. Your edits are still unsaved.")
            return
        if failed:
            names = ", ".join(
                self.catalog.memory_by_address[address].name
                for address in failed
                if address in self.catalog.memory_by_address
            )
            dialog.finish(
                f"Programmed, but {len(failed)} words failed and kept their old "
                f"values ({names}). They are still marked unsaved. {recycle}"
            )
            return
        dialog.finish(f"Programmed {len(self._push_results) - len(commit)} words. {recycle}")

    def _cancel_push(self) -> None:
        if not self._push_active:
            return
        self._push_cancelled = True
        if self._push_dialog is not None:
            self._push_dialog.set_status("Stopping after the current word…")

    def _abort_push(self, reason: str) -> None:
        dialog = self._push_dialog
        if dialog is None:
            return
        self._push_active = False
        if self._push_head is not None:
            head_address, _value = self._push_head
            self._push_results.setdefault(head_address, False)
            dialog.set_step_status(head_address, "Failed", False)
            self._push_head = None
        for rest, _ in self._push_remaining:
            dialog.set_step_status(rest, "Skipped", None)
        self._push_remaining = []
        dialog.finish(f"{reason} Nothing was programmed.")

    def _finish_push(self) -> None:
        dialog = self._push_dialog
        if dialog is None:
            return
        commit = {EEPROM_COMMIT_UNLOCK[0], EEPROM_COMMIT_COMMAND[0]}
        flashed = [address for address, ok in self._push_results.items() if ok and address not in commit]
        self.eeprom.mark_flashed(flashed)
        if self._pump is not None:
            source = self._pump.source
            for attr, value in (
                ("last_write_ok", False),
                ("last_write_error", None),
                ("last_write_address", None),
            ):
                if hasattr(source, attr):
                    try:
                        setattr(source, attr, value)
                    except AttributeError:
                        pass
            if self.source.currentText() == "RS232":
                self.poller.start_dump(snapshot_addresses(self.catalog.memory_symbols))
        self._push_dialog = None
        self._push_active = False
        self._push_cancelled = False
        dialog.close()

    def _about(self) -> None:
        QMessageBox.information(
            self,
            "About",
            "Live monitor and configuration tool for Cascadia / Rinehart PM100 inverters over RS232.\n\n"
            "RS232 polls watched symbols with rm; EEPROM dumps once on connect.\n\n"
            "Symbols is a personal Memory View watch list; other tabs poll on their own.\n"
            "EEPROM loads once on RS232 connect (Pull from inverter to reload).\n"
            "Calibration iterates Delay Command and Gamma Adjust in RAM. "
            "Program EEPROM is optional, last, and only from that tab.\n"
            "VSM state is on RS232 address 0x0093.",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop()
        super().closeEvent(event)
