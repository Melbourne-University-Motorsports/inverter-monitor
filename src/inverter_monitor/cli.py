from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication

from inverter_monitor.catalog import load_catalog
from inverter_monitor.memory_map import DEFAULT_CAN_ID_OFFSET
from inverter_monitor.serial_sci import SCI_BAUD
from inverter_monitor.ui.main_window import MainWindow
from inverter_monitor.ui.theme import apply_theme


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only PM100DX inverter monitor")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--serial",
        metavar="PORT",
        help="Live RS232 Memory View (COM3, /dev/cu.*, …). Polls watched symbols with rm",
    )
    source.add_argument("--memory-view", metavar="PORT", help=argparse.SUPPRESS)
    source.add_argument(
        "--can",
        metavar="INTERFACE",
        help="Live CAN (socketcan, pcan, slcan, kvaser, virtual)",
    )
    source.add_argument("--bus", metavar="INTERFACE", help=argparse.SUPPRESS)
    parser.add_argument("--channel", default="can0", help="CAN channel if --can is used")
    parser.add_argument("--bitrate", type=int, default=500000, help="CAN bitrate")
    parser.add_argument("--baud", type=int, default=SCI_BAUD, help="RS232 baud (default 57600)")
    parser.add_argument(
        "--id-offset",
        type=lambda value: int(value, 0),
        default=DEFAULT_CAN_ID_OFFSET,
        help="Subtract from on-wire CAN IDs before decode (default 0x0A0)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    catalog = load_catalog()
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    window = MainWindow(catalog)
    window.offset.setValue(args.id_offset)
    window.can_bitrate.setValue(args.bitrate)
    window.baud.setValue(args.baud)
    window.show()
    serial_port = args.serial or args.memory_view
    can_iface = args.can or args.bus
    if serial_port:
        window.start_rs232(serial_port, baud=args.baud)
    elif can_iface:
        window.start_can(can_iface, args.channel, bitrate=args.bitrate)
    return app.exec()
