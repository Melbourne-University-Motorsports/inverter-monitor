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

from inverter_monitor.catalog import Catalog
from inverter_monitor.decode import M193_PARAM_COMMAND_ID, PARAM_CLEAR_FAULTS, Decoder, pack_param_write
from inverter_monitor.memory_map import (
    CLEAR_FAULTS_ADDRESS,
    DEFAULT_CAN_ID_OFFSET,
    DEFAULT_WATCH_ADDRESSES,
    STATUS_WATCH_ADDRESSES,
    MemoryPoller,
    WatchList,
    snapshot_addresses,
)
from inverter_monitor.serial_memory import SerialMemoryViewSource
from inverter_monitor.serial_sci import SCI_BAUD, list_serial_ports
from inverter_monitor.store import InverterStore, first_signal, get_signal
from inverter_monitor.transport import FramePump, LiveCanSource
from inverter_monitor.ui.eeprom import EepromPage
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
        self.setWindowTitle("PM100DX Inverter Monitor")
        self.resize(1280, 800)
        self.catalog = catalog
        self.store = InverterStore(catalog)
        self.decoder = Decoder(catalog)
        self.bus_interface = "socketcan"
        self.bitrate = 500000
        self.serial_baud = SCI_BAUD
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._pump: FramePump | None = None
        self._source_label = "disconnected"
        self.watch_list = WatchList(DEFAULT_WATCH_ADDRESSES)
        self.poller = MemoryPoller(self.watch_list)
        self._offset_from_memory: int | None = None
        self._offset_from_user = False
        self._setting_offset = False

        self.source = QComboBox()
        self.source.addItems(["RS232", "CAN"])
        self.can_iface = QComboBox()
        self.can_iface.addItems(["socketcan", "pcan", "slcan", "kvaser", "virtual"])
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
        self.iface_label = QLabel("CAN iface")
        self.bitrate_label = QLabel("Bitrate")
        self.offset_label = QLabel("CAN ID offset")

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Source"))
        toolbar.addWidget(self.source)
        toolbar.addWidget(self.iface_label)
        toolbar.addWidget(self.can_iface)
        toolbar.addWidget(self.port_label)
        toolbar.addWidget(self.channel, 1)
        toolbar.addWidget(self.refresh_ports_btn)
        toolbar.addWidget(self.baud_label)
        toolbar.addWidget(self.baud)
        toolbar.addWidget(self.bitrate_label)
        toolbar.addWidget(self.can_bitrate)
        toolbar.addWidget(self.offset_label)
        toolbar.addWidget(self.offset)
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
        self.eeprom = EepromPage(catalog)
        self.eeprom.pull_requested.connect(self._pull_eeprom)
        self.tabs.addTab(self.overview, "Overview")
        self.tabs.addTab(self.faults, "Faults")
        self.tabs.addTab(self.graphs, "Graphs")
        self.tabs.addTab(self.symbols, "Symbols")
        self.tabs.addTab(self.eeprom, "EEPROM")
        self.tabs.addTab(self.raw, "Raw")
        self.tabs.addTab(self.states, "States")
        self.tabs.currentChanged.connect(self._sync_poll_set)
        self._sync_poll_set()

        root = QWidget()
        layout = QVBoxLayout(root)
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
        self.can_iface.currentTextChanged.connect(lambda _text: self._source_changed(self.source.currentText()))
        self._source_changed(self.source.currentText())

    def start_rs232(self, port: str, baud: int = SCI_BAUD) -> None:
        self.source.setCurrentText("RS232")
        self.baud.setValue(baud)
        self._set_channel(port)
        if self._pump is None:
            self._toggle()

    def start_memory_view(self, port: str, baud: int = SCI_BAUD) -> None:
        self.start_rs232(port, baud=baud)

    def start_can(self, interface: str, channel: str, bitrate: int = 500000) -> None:
        self.source.setCurrentText("CAN")
        if self.can_iface.findText(interface) < 0:
            self.can_iface.addItem(interface)
        self.can_iface.setCurrentText(interface)
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
        for widget in (self.can_iface, self.iface_label, self.can_bitrate, self.bitrate_label):
            widget.setVisible(not rs232)
        if rs232:
            self.port_label.setText("Port")
            self._refresh_ports()
            self._sync_eeprom_tab()
            self.overview.update_from(self.store.snapshot(), "RS232")
            return
        self.port_label.setText("Channel")
        iface = self.can_iface.currentText()
        defaults = {
            "socketcan": "can0",
            "pcan": "PCAN_USBBUS1",
            "slcan": "",
            "kvaser": "0",
            "virtual": "vcan0",
        }
        if not self._channel_text() or _looks_like_serial(self._channel_text()):
            self._set_channel(defaults.get(iface, "can0"))
        self._sync_eeprom_tab()
        self.overview.update_from(self.store.snapshot(), "CAN")

    def _sync_poll_set(self, _index: int = 0) -> None:
        current = self.tabs.currentWidget()
        if current is self.symbols:
            self.poller.set_active_addresses(None)
            return
        if current is self.graphs:
            addresses = (*STATUS_WATCH_ADDRESSES, *self.graphs.poll_addresses())
        elif current is self.faults or current is self.states or current is self.eeprom:
            addresses = STATUS_WATCH_ADDRESSES
        else:
            addresses = DEFAULT_WATCH_ADDRESSES
        self.poller.set_active_addresses(addresses)

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
        interface = self.can_iface.currentText().strip() or self.bus_interface
        channel = self._channel_text()
        if not channel:
            raise FileNotFoundError("Set a CAN channel (can0, PCAN_USBBUS1, …).")
        self.bitrate = self.can_bitrate.value()
        return LiveCanSource(interface=interface, channel=channel, bitrate=self.bitrate)

    def _toggle(self) -> None:
        if self._pump is not None:
            self._stop()
            return
        try:
            source = self._make_source()
        except Exception as exc:
            QMessageBox.critical(self, "Cannot start source", str(exc))
            return
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
        self.strip.update_from(snapshot, self._source_label, running)
        self.overview.update_from(snapshot, self.source.currentText())
        self.faults.set_connected(running)
        self.faults.update_from(snapshot)
        self._update_clear_status()
        self.graphs.update_from(snapshot)
        self.symbols.update_from(snapshot)
        self.eeprom.set_rs232_active(rs232)
        self.eeprom.update_from(snapshot, self.poller.dump_progress())
        self._sync_eeprom_tab()
        self.raw.update_from(snapshot)
        self.states.update_from(snapshot)

    def _offset_edited(self, _value: int) -> None:
        if not self._setting_offset:
            self._offset_from_user = True

    def _update_clear_status(self) -> None:
        if self._pump is None:
            return
        source = self._pump.source
        error = getattr(source, "last_write_error", None)
        accepted = getattr(source, "last_write_ok", False)
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

    def _pull_eeprom(self) -> None:
        if self._pump is None or self.source.currentText() != "RS232":
            QMessageBox.information(
                self,
                "RS232 not running",
                "Start RS232 first. EEPROM words are Memory View reads, not CAN.",
            )
            return
        self.poller.start_dump(snapshot_addresses(self.catalog.memory_symbols))

    def _about(self) -> None:
        QMessageBox.information(
            self,
            "About",
            "Read-only monitor for Cascadia / Rinehart PM100DX inverters.\n\n"
            "Pick one live source:\n"
            "• RS232 — poll watched symbols with rm; EEPROM dumps once on connect\n"
            "• CAN — subscribe-only python-can (socketcan, PCAN, slcan, …)\n\n"
            "Symbols is a personal Memory View watch list; other tabs poll on their own.\n"
            "EEPROM loads once on RS232 connect (Pull from inverter to reload).\n"
            "VSM state is on CAN M170 or RS232 address 0x0093.",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop()
        super().closeEvent(event)
