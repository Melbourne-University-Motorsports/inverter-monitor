from __future__ import annotations

import queue
import time

from inverter_monitor.memory_map import (
    MEMORY_FRAME_ID,
    MemoryPoller,
    pack_memory_frame,
    parse_read_reply,
    read_command,
    write_command,
)
from inverter_monitor.serial_sci import (
    SCI_BAUD,
    close_serial,
    interrupt_serial,
    read_waiting,
    write_serial,
)
from inverter_monitor.transport import CanFrame, SourceLost


class SerialMemoryViewSource:
    """Poll Memory View with `rm`. `wm` is queued: Clear Faults, Calibration RAM, EEPROM persist."""

    def __init__(self, port: str, poller: MemoryPoller, baud: int = SCI_BAUD) -> None:
        import serial

        self.label = f"rs232:{port}@{baud}"
        self._port = port
        self._poller = poller
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
            write_timeout=0.2,
        )
        self._buf = b""
        self._writes: queue.SimpleQueue[tuple[int, int]] = queue.SimpleQueue()
        self.last_write_error: str | None = None
        self.last_write_ok = False
        self.last_write_address: int | None = None

    def enqueue_write(self, address: int, value: int) -> None:
        self._writes.put((int(address), int(value) & 0xFFFF))

    def recv(self, timeout: float) -> CanFrame | None:
        self._flush_write()
        address = self._poller.next_address()
        if address is None:
            time.sleep(min(timeout, 0.05))
            return None
        try:
            write_serial(self._serial, read_command(address), name=self._port)
        except SourceLost:
            raise
        except Exception:
            time.sleep(min(timeout, 0.05))
            return None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            chunk = read_waiting(self._serial, name=self._port)
            if chunk:
                self._buf += chunk
            while b"\n" in self._buf:
                raw_line, self._buf = self._buf.split(b"\n", 1)
                line = raw_line.decode("ascii", errors="ignore").strip("\r")
                parsed = parse_read_reply(line)
                if parsed is None:
                    continue
                reply_addr, raw = parsed
                return CanFrame(
                    timestamp=time.time(),
                    arbitration_id=MEMORY_FRAME_ID,
                    data=pack_memory_frame(reply_addr, raw),
                )
            time.sleep(0.005)
        return None

    def _flush_write(self) -> None:
        try:
            address, value = self._writes.get_nowait()
        except queue.Empty:
            return
        self.last_write_address = address
        try:
            write_serial(self._serial, write_command(address, value), name=self._port)
        except SourceLost:
            raise
        except Exception as exc:
            self.last_write_ok = False
            self.last_write_error = str(exc)
            return
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            chunk = read_waiting(self._serial, name=self._port)
            if chunk:
                self._buf += chunk
            if self._consume_rae():
                self.last_write_ok = True
                self.last_write_error = None
                return
            time.sleep(0.005)
        self.last_write_ok = False
        self.last_write_error = f"No RAE from inverter after write to 0x{address:04X}."

    def _consume_rae(self) -> bool:
        index = self._buf.find(b"RAE")
        if index < 0:
            return False
        self._buf = self._buf[index + 3 :].lstrip(b"\r\n")
        return True

    def interrupt(self) -> None:
        interrupt_serial(self._serial)

    def close(self) -> None:
        close_serial(self._serial)
