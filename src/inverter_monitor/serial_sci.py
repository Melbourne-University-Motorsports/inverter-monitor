from __future__ import annotations

import time
from pathlib import Path

from inverter_monitor.decode import SCI_FRAME_ID, SignalUpdate, decode_sci_words, pack_sci_words
from inverter_monitor.transport import CanFrame

SCI_BAUD = 57600
SCI_RECORD_COUNT = 20


def parse_sci_line(line: str) -> list[int] | None:
    """Parse one SCI ASCII row: 20 hex words separated by whitespace."""
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    tokens = text.replace(",", " ").split()
    words: list[int] = []
    for token in tokens:
        if token.lower() in {"lim", "="}:
            return None
        try:
            value = int(token, 16)
        except ValueError:
            if not words:
                return None
            continue
        if value > 0xFFFF:
            return None
        words.append(value)
        if len(words) == SCI_RECORD_COUNT:
            return words
    return words if len(words) == SCI_RECORD_COUNT else None


def sci_updates(words: list[int]) -> list[SignalUpdate]:
    return decode_sci_words(words)


def sci_frame(words: list[int], timestamp: float | None = None) -> CanFrame:
    return CanFrame(
        timestamp=timestamp if timestamp is not None else time.time(),
        arbitration_id=SCI_FRAME_ID,
        data=pack_sci_words(words),
    )


def list_serial_ports() -> list[str]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [port.device for port in list_ports.comports()]


class SerialSciSource:
    """Read-only listener for inverter RS232 SCI ASCII broadcast (57600 8N1)."""

    def __init__(self, port: str, baud: int = SCI_BAUD) -> None:
        import serial

        self.label = f"rs232:{port}@{baud}"
        self._serial = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
            write_timeout=0,
        )
        self._buf = b""

    def recv(self, timeout: float) -> CanFrame | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            waiting = self._serial.in_waiting
            chunk = self._serial.read(waiting or 1)
            if chunk:
                self._buf += chunk
            newline = self._buf.find(b"\n")
            if newline < 0:
                continue
            raw_line, self._buf = self._buf[:newline], self._buf[newline + 1 :]
            line = raw_line.decode("ascii", errors="ignore").strip("\r")
            words = parse_sci_line(line)
            if words:
                return sci_frame(words)
        return None

    def close(self) -> None:
        self._serial.close()


class SciLogSource:
    """Replay a RealTerm / capture.txt SCI log."""

    def __init__(self, path: Path, period_s: float = 0.05) -> None:
        self.label = f"sci-log:{path.name}"
        self._lines = path.read_text(errors="ignore").splitlines()
        self._index = 0
        self._period = period_s
        self._last = 0.0

    def recv(self, timeout: float) -> CanFrame | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._index >= len(self._lines):
                time.sleep(min(timeout, 0.05))
                return None
            if self._last and time.monotonic() - self._last < self._period:
                time.sleep(0.001)
                continue
            line = self._lines[self._index]
            self._index += 1
            words = parse_sci_line(line)
            if not words:
                continue
            self._last = time.monotonic()
            return sci_frame(words)
        return None

    def close(self) -> None:
        return None
