"""One value that says whether the monitor is actually reading the inverter.

Two failures look different to the operator but mean the same thing to every
widget on screen:

* the transport is gone — USB serial unplugged, source stopped, CAN bus lost;
* the transport is fine but the inverter has gone quiet — powered off,
  resetting, or the link to it dropped.

In both cases the last decoded values are history, not current state. Pages
used to keep showing them, which read as "the inverter is still in VSM 4".
:class:`FeedState` collapses both failures into one value the status strip and
the pages render as "no live data" plus a plain-language reason.

Liveness comes from ``StoreSnapshot.frames_per_sec``, which counts frames in
the trailing second. It is > 0 for a live CAN broadcast or RS232 poll and falls
to 0 within a second of either failure, so the UI has a single witness instead
of trusting a per-signal age that can lag by the signal's own cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

from inverter_monitor.store import StoreSnapshot

#: The transport is up and frames are arriving.
LIVE = "live"
#: The transport is up but nothing has arrived for a second.
NO_DATA = "no-data"
#: No source is running (stopped, or the port was unplugged).
DISCONNECTED = "disconnected"

#: Shown when the port is open but the inverter has gone quiet.
NO_DATA_REASON = (
    "Connected, but the inverter is not sending data. "
    "Check that it is powered on and talking."
)
#: Shown when no source is running for an ordinary reason (never started/stopped).
IDLE_REASON = "Not connected. Choose a port and press Start."


@dataclass(frozen=True)
class FeedState:
    stage: str
    connected: bool
    live: bool
    reason: str = ""
    #: True when the reason is a failure worth an orange cue, as opposed to the
    #: neutral "nothing started yet" text.
    alert: bool = False

    @property
    def tone(self) -> str:
        if self.live:
            return "ok"
        return "warn" if self.alert else "dim"

    @property
    def strip_text(self) -> str:
        if self.stage == LIVE:
            return "LIVE"
        return "NO DATA" if self.stage == NO_DATA else "DISCONNECTED"


def feed_state(
    snapshot: StoreSnapshot,
    running: bool,
    lost_reason: str | None = None,
) -> FeedState:
    """Classify the current feed from the pump state and recent frame rate."""
    if not running:
        reason = (lost_reason or "").strip()
        if reason:
            return FeedState(DISCONNECTED, False, False, reason, alert=True)
        return FeedState(DISCONNECTED, False, False, IDLE_REASON)
    if snapshot.frames_per_sec <= 0:
        return FeedState(NO_DATA, True, False, NO_DATA_REASON, alert=True)
    return FeedState(LIVE, True, True)
