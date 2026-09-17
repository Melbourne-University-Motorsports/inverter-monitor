from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from inverter_monitor.catalog import Catalog
from inverter_monitor.decode import MEMORY_FRAME_ID, SCI_FRAME_ID, Decoder, SignalUpdate


@dataclass(frozen=True)
class CanFrame:
    timestamp: float
    arbitration_id: int
    data: bytes
    is_extended: bool = False


class SourceLost(Exception):
    """The live source is gone (unplugged serial adapter, bus disappeared)."""


class FrameSource(Protocol):
    label: str

    def recv(self, timeout: float) -> CanFrame | None: ...

    def close(self) -> None: ...


def can_interface_for(channel: str) -> str:
    text = channel.strip()
    upper = text.upper()
    if upper.startswith("PCAN"):
        return "pcan"
    if upper.startswith("COM") or text.startswith("/dev/"):
        return "slcan"
    if text.startswith("vcan"):
        return "virtual"
    if text.isdigit():
        return "kvaser"
    return "socketcan"


class LiveCanSource:
    """python-can bus. Receives continuously; TX is only queued Clear Faults / param writes."""

    def __init__(self, channel: str, bitrate: int = 500000, interface: str | None = None) -> None:
        import can

        interface = interface or can_interface_for(channel)
        self.label = f"can:{channel}"
        self._bus = can.Bus(
            interface=interface,
            channel=channel,
            bitrate=bitrate,
            receive_own_messages=False,
        )
        self._tx: queue.SimpleQueue[tuple[int, bytes]] = queue.SimpleQueue()
        self.last_write_error: str | None = None
        self.last_write_ok = False

    def enqueue_send(self, arbitration_id: int, data: bytes) -> None:
        self._tx.put((int(arbitration_id), bytes(data)))

    def recv(self, timeout: float) -> CanFrame | None:
        self._flush_tx()
        message = self._bus.recv(timeout=timeout)
        if message is None:
            return None
        return CanFrame(
            timestamp=message.timestamp or time.time(),
            arbitration_id=message.arbitration_id,
            data=bytes(message.data),
            is_extended=bool(message.is_extended_id),
        )

    def _flush_tx(self) -> None:
        try:
            arbitration_id, data = self._tx.get_nowait()
        except queue.Empty:
            return
        try:
            import can

            self._bus.send(
                can.Message(
                    arbitration_id=arbitration_id,
                    data=data,
                    is_extended_id=False,
                )
            )
        except Exception as exc:
            self.last_write_ok = False
            self.last_write_error = str(exc)
            return
        self.last_write_ok = True
        self.last_write_error = None

    def close(self) -> None:
        self._bus.shutdown()


class ReplaySource:
    def __init__(self, path: Path, speed: float = 1.0) -> None:
        import can

        self.label = f"replay:{path.name}"
        self._reader = can.LogReader(str(path))
        self._speed = max(speed, 0.01)
        self._started_wall: float | None = None
        self._started_log: float | None = None
        self._pending: CanFrame | None = None
        self._done = False

    def recv(self, timeout: float) -> CanFrame | None:
        if self._done:
            time.sleep(min(timeout, 0.05))
            return None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._pending is None:
                try:
                    message = next(self._reader)
                except StopIteration:
                    self._done = True
                    return None
                self._pending = CanFrame(
                    timestamp=message.timestamp or time.time(),
                    arbitration_id=message.arbitration_id,
                    data=bytes(message.data),
                    is_extended=bool(message.is_extended_id),
                )
            frame = self._pending
            if self._started_log is None:
                self._started_log = frame.timestamp
                self._started_wall = time.monotonic()
                self._pending = None
                return frame
            due = (frame.timestamp - self._started_log) / self._speed
            wait = due - (time.monotonic() - (self._started_wall or 0.0))
            if wait <= 0:
                self._pending = None
                return frame
            time.sleep(min(wait, deadline - time.monotonic(), 0.05))
        return None

    def close(self) -> None:
        close = getattr(self._reader, "stop", None) or getattr(self._reader, "close", None)
        if callable(close):
            close()


class PumpBatch:
    def __init__(self) -> None:
        self.frames: list[tuple[CanFrame, list[SignalUpdate], str]] = []


class FramePump:
    def __init__(
        self,
        source: FrameSource,
        decoder: Decoder,
        catalog: Catalog,
        out_queue: queue.SimpleQueue[PumpBatch],
    ) -> None:
        self._source = source
        self._decoder = decoder
        self._catalog = catalog
        self._queue = out_queue
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="can-pump", daemon=True)
        self.lost_reason: str | None = None

    @property
    def source(self) -> FrameSource:
        return self._source

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._interrupt_source()
        self._thread.join(timeout=1.0)
        if self._thread.is_alive():
            # close() can block on a yanked USB serial port; don't freeze the UI.
            threading.Thread(target=self._close_source, name="source-close", daemon=True).start()

    def _interrupt_source(self) -> None:
        interrupt = getattr(self._source, "interrupt", None)
        if callable(interrupt):
            try:
                interrupt()
            except Exception:
                return

    def _close_source(self) -> None:
        try:
            self._source.close()
        except Exception:
            return

    def _run(self) -> None:
        batch = PumpBatch()
        last_flush = time.monotonic()
        try:
            while not self._stop.is_set():
                try:
                    frame = self._source.recv(0.05)
                except SourceLost as exc:
                    self.lost_reason = str(exc) or "Connection lost."
                    break
                except Exception:
                    time.sleep(0.05)
                    continue
                if frame is not None:
                    updates = self._decoder.decode_frame(frame.arbitration_id, frame.data)
                    message = self._catalog.message_for(frame.arbitration_id, self._decoder.id_offset)
                    if frame.arbitration_id == SCI_FRAME_ID:
                        name = "SCI_Broadcast"
                    elif frame.arbitration_id == MEMORY_FRAME_ID:
                        name = "Memory_View"
                    else:
                        name = message.name if message else ""
                    batch.frames.append((frame, updates, name))
                now = time.monotonic()
                if batch.frames and (len(batch.frames) >= 64 or now - last_flush >= 0.02):
                    self._queue.put(batch)
                    batch = PumpBatch()
                    last_flush = now
            if batch.frames:
                self._queue.put(batch)
        finally:
            self._close_source()
