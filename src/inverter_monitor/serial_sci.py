from __future__ import annotations

import errno
import time
from pathlib import Path

from inverter_monitor.decode import SCI_FRAME_ID, SignalUpdate, decode_sci_words, pack_sci_words
from inverter_monitor.transport import CanFrame, SourceLost

SCI_BAUD = 57600
SCI_RECORD_COUNT = 20
SERIAL_UNPLUGGED = "Serial port unplugged. Plug it back in and press Start."

_LOST_ERRNOS = {
    errno.EIO,
    errno.ENXIO,
    errno.ENODEV,
    errno.EBADF,
    errno.ENOENT,
    errno.ENOTTY,
}
_LOST_HINTS = (
    "device disconnected",
    "device not configured",
    "device not found",
    "device not functioning",
    "clearcommerror",
    "the device does not recognize",
    "returned no data",
    "multiple access on port",
    "port is closed",
    "port not open",
    "input/output error",
    "i/o error",
    "no such file",
    "access is denied",
    "the handle is invalid",
    "a device attached to the system is not functioning",
)


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


def serial_unplugged_message(port: str | None = None) -> str:
    if port:
        return f"Serial port {port} unplugged. Plug it back in and press Start."
    return SERIAL_UNPLUGGED


def serial_lost_reason(exc: BaseException, port: str | None = None) -> str | None:
    """Return a user-facing reason when `exc` means the serial adapter is gone."""
    try:
        from serial import SerialException, SerialTimeoutException
    except ImportError:
        SerialException = OSError
        SerialTimeoutException = tuple()  # type: ignore[assignment]
    if isinstance(exc, SerialTimeoutException):
        return None
    lost = False
    if isinstance(exc, SerialException):
        lost = True
    elif isinstance(exc, OSError) and getattr(exc, "errno", None) in _LOST_ERRNOS:
        lost = True
    else:
        text = str(exc).lower()
        lost = any(hint in text for hint in _LOST_HINTS)
    if not lost:
        return None
    return serial_unplugged_message(port)


def raise_if_serial_lost(exc: BaseException, port: str | None = None) -> None:
    reason = serial_lost_reason(exc, port)
    if reason:
        raise SourceLost(reason) from exc


def interrupt_serial(port) -> None:
    for name in ("cancel_read", "cancel_write"):
        cancel = getattr(port, name, None)
        if not callable(cancel):
            continue
        try:
            cancel()
        except Exception:
            continue


def close_serial(port) -> None:
    if port is None:
        return
    interrupt_serial(port)
    try:
        if getattr(port, "is_open", True):
            port.close()
    except Exception:
        return


def read_waiting(port, *, name: str | None = None) -> bytes:
    """Read queued bytes without blocking. Raises SourceLost if the port is gone."""
    try:
        waiting = port.in_waiting
        if not waiting:
            return b""
        return port.read(waiting)
    except Exception as exc:
        raise_if_serial_lost(exc, name)
        raise


def write_serial(port, data: bytes, *, name: str | None = None) -> None:
    try:
        port.write(data)
    except Exception as exc:
        raise_if_serial_lost(exc, name)
        raise


class SerialSciSource:
    """Read-only listener for inverter RS232 SCI ASCII broadcast (57600 8N1)."""

    def __init__(self, port: str, baud: int = SCI_BAUD) -> None:
        import serial

        self.label = f"rs232:{port}@{baud}"
        self._port = port
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
            chunk = read_waiting(self._serial, name=self._port)
            if chunk:
                self._buf += chunk
            newline = self._buf.find(b"\n")
            if newline < 0:
                time.sleep(0.005)
                continue
            raw_line, self._buf = self._buf[:newline], self._buf[newline + 1 :]
            line = raw_line.decode("ascii", errors="ignore").strip("\r")
            words = parse_sci_line(line)
            if words:
                return sci_frame(words)
        return None

    def interrupt(self) -> None:
        interrupt_serial(self._serial)

    def close(self) -> None:
        close_serial(self._serial)


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
