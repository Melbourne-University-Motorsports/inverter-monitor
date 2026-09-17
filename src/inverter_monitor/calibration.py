"""Resolver calibration helpers.

Iterate in RAM (Memory View `wm`) until Cos corr / Delta resolver converge.
EEPROM is last: copy those Memory Values into the EEPROM words, then the
captured Program EEPROM pair.

Addresses match G3 defsyms. Gamma Adjust RAM (0x0010) is marked non-writable
in that file because the parser only flags GUI Command names containing
"Command"; the RMS Memory Values tab still writes it.
"""

from __future__ import annotations

from dataclasses import dataclass

from inverter_monitor.memory_map import FEEDBACK_SPEED_ADDRESS
from inverter_monitor.store import SignalSnapshot, StoreSnapshot, first_signal

RESOLVER_DELAY_COMMAND_ADDRESS = 0x0005
GAMMA_ADJUST_ADDRESS = 0x0010
DELTA_AT_1000_ADDRESS = 0x0063
SIN_CORR_ADDRESS = 0x0073
COS_CORR_ADDRESS = 0x0074
GAMMA_RESOLVER_ADDRESS = 0x0075
DELTA_RESOLVER_ADDRESS = 0x0089
VOLTAGE_FEEDBACK_SPEED_ADDRESS = 0x00BA
EEPROM_STATE_ADDRESS = 0x0056
RESOLVER_DELAY_EEPROM_ADDRESS = 0x0118
GAMMA_ADJUST_EEPROM_ADDRESS = 0x011A
DC_UNDERVOLT_EEPROM_ADDRESS = 0x0117

VSM_WAIT = 4
VSM_READY = 5
VSM_RUNNING = 6
VSM_FAULT = 7
VSM_RECYCLE = 15
# Software User Manual Inverter_Mode: 4–7 plus 8/10/11 are start/run, not Stop.
INVERTER_MODE_LIVE = frozenset({4, 5, 6, 7, 8, 10, 11})
# yuh3: idle 5, then 7 while EEPROM reads go to zero during program.
EEPROM_STATE_IDLE = 5
EEPROM_STATE_BUSY = 7

DEFAULT_RESOLVER_DELAY = 1100
MAX_RESOLVER_DELAY = 6250
GAMMA_GOAL_X10 = 900
GAMMA_TOLERANCE_X10 = 7
DEFAULT_TARGET_RPM = 1000
DIRECTION_MIN_RPM = 300
HAND_TURN_RPM = 20

# yuh3 Program EEPROM pair. yuh4 (1) confirmed signed Gamma RAM writes with RAE.
EEPROM_COMMIT_UNLOCK = (0x0000, 0x5A0F)
EEPROM_COMMIT_COMMAND = (0x0001, 0x0059)

RAM_WRITE_ADDRESSES = frozenset(
    {
        RESOLVER_DELAY_COMMAND_ADDRESS,
        GAMMA_ADJUST_ADDRESS,
    }
)
EEPROM_SHADOW_ADDRESSES = frozenset(
    {
        RESOLVER_DELAY_EEPROM_ADDRESS,
        GAMMA_ADJUST_EEPROM_ADDRESS,
    }
)
EEPROM_COMMIT_ADDRESSES = frozenset(
    {
        EEPROM_COMMIT_UNLOCK[0],
        EEPROM_COMMIT_COMMAND[0],
    }
)
EEPROM_WRITE_ADDRESSES = EEPROM_SHADOW_ADDRESSES | EEPROM_COMMIT_ADDRESSES

CALIBRATION_WATCH_ADDRESSES = (
    RESOLVER_DELAY_COMMAND_ADDRESS,
    GAMMA_ADJUST_ADDRESS,
    SIN_CORR_ADDRESS,
    COS_CORR_ADDRESS,
    GAMMA_RESOLVER_ADDRESS,
    DELTA_RESOLVER_ADDRESS,
    DELTA_AT_1000_ADDRESS,
    FEEDBACK_SPEED_ADDRESS,
    VOLTAGE_FEEDBACK_SPEED_ADDRESS,
    GAMMA_ADJUST_EEPROM_ADDRESS,
    RESOLVER_DELAY_EEPROM_ADDRESS,
    EEPROM_STATE_ADDRESS,
)

SPEED_KEYS = (
    "MemoryView.Feedback_Speed_(RPM)",
    "M165_Motor_Position_Info.D2_Motor_Speed",
)
VOLTAGE_SPEED_KEYS = ("MemoryView.Voltage_Feedback_Speed_(RPM)",)
GAMMA_RESOLVER_KEYS = ("MemoryView.Gamma_Resolver_(DEG)_x_10",)
DELTA_KEYS = (
    "MemoryView.Delta_Resolver_In_Fil_(DEG)_x_10",
    "M165_Motor_Position_Info.D4_Delta_Resolver_Filtered",
)
DELTA_AT_1000_KEYS = ("MemoryView.Delta_Resolver_In_Fil_at_1000RPM",)
GAMMA_ADJUST_KEYS = ("MemoryView.Gamma_Adjust_(Deg)_x_10",)
GAMMA_EEPROM_KEYS = ("MemoryView.Gamma_Adjust_EEPROM_(Deg)_x_10",)
DELAY_COMMAND_KEYS = ("MemoryView.Resolver_Delay_Command",)
DELAY_EEPROM_KEYS = ("MemoryView.Resolver_PWM_Delay_EEPROM_(Counts)",)
SIN_KEYS = ("MemoryView.Sin_corr_(V)_x_100",)
COS_KEYS = ("MemoryView.Cos_corr(V)_x_100",)
EEPROM_STATE_KEYS = ("MemoryView.EEprom_State",)
VSM_KEYS = ("MemoryView.VSM_State", "M170_Internal_States.D1_VSM_State")
ENABLE_KEYS = (
    "MemoryView.Inverter_Enable",
    "M170_Internal_States.D6_Inverter_Enable_State",
)
INVERTER_MODE_KEYS = (
    "MemoryView.Inverter_Mode",
    "M170_Internal_States.D2_Inverter_State",
)


def encode_u16(value: int) -> int:
    return int(value) & 0xFFFF


def clamp_delay(value: int) -> int:
    return max(0, min(MAX_RESOLVER_DELAY, int(value)))


def wrap_error_x10(error: int) -> int:
    """Fold a Deg×10 error into (-1800, 1800]. 2700 and −900 are the same angle."""
    wrapped = int(error) % 3600
    if wrapped > 1800:
        wrapped -= 3600
    return wrapped


def next_gamma_adjust(old_gamma_x10: int, delta_x10: int, goal_x10: int) -> int:
    """New Gamma Adjust (Deg)×10. Same as RMS: old + delta − goal, with wrap."""
    return int(old_gamma_x10) + wrap_error_x10(int(delta_x10) - int(goal_x10))


def gamma_goal_x10(forward: bool) -> int:
    return GAMMA_GOAL_X10 if forward else -GAMMA_GOAL_X10


def gamma_converged(delta_x10: int, goal_x10: int, tolerance: int = GAMMA_TOLERANCE_X10) -> bool:
    return abs(wrap_error_x10(int(delta_x10) - int(goal_x10))) <= int(tolerance)


def angle_delta_x10(previous: int, current: int) -> int:
    return wrap_error_x10(int(current) - int(previous))


def gui_counts(signal: SignalSnapshot | None) -> int | None:
    """Signed GUI integer (900 = 90.0°). Memory View `raw` is already signed."""
    if signal is None or signal.raw is None:
        return None
    return int(signal.raw)


@dataclass(frozen=True)
class CalibrationReading:
    speed_rpm: int | None = None
    voltage_speed_rpm: int | None = None
    gamma_resolver_x10: int | None = None
    delta_x10: int | None = None
    delta_at_1000_x10: int | None = None
    gamma_adjust_x10: int | None = None
    gamma_eeprom_x10: int | None = None
    delay_command: int | None = None
    delay_eeprom: int | None = None
    sin_corr_x100: int | None = None
    cos_corr_x100: int | None = None
    eeprom_state: int | None = None
    vsm: int | None = None
    enable: int | None = None
    inverter_mode: int | None = None

    def delta_for_gamma(self, target_rpm: int = DEFAULT_TARGET_RPM) -> tuple[int | None, str]:
        spinning = self.speed_rpm is not None and abs(self.speed_rpm) >= target_rpm
        if spinning and self.delta_at_1000_x10 is not None:
            return self.delta_at_1000_x10, "at 1000 RPM"
        return self.delta_x10, "live"

    def delay_matches_eeprom(self) -> bool | None:
        if self.delay_command is None or self.delay_eeprom is None:
            return None
        return self.delay_command == self.delay_eeprom

    def gamma_matches_eeprom(self) -> bool | None:
        if self.gamma_adjust_x10 is None or self.gamma_eeprom_x10 is None:
            return None
        return self.gamma_adjust_x10 == self.gamma_eeprom_x10


def read_calibration(snapshot: StoreSnapshot) -> CalibrationReading:
    def counts(*keys: str) -> int | None:
        return gui_counts(first_signal(snapshot, *keys))

    return CalibrationReading(
        speed_rpm=counts(*SPEED_KEYS),
        voltage_speed_rpm=counts(*VOLTAGE_SPEED_KEYS),
        gamma_resolver_x10=counts(*GAMMA_RESOLVER_KEYS),
        delta_x10=counts(*DELTA_KEYS),
        delta_at_1000_x10=counts(*DELTA_AT_1000_KEYS),
        gamma_adjust_x10=counts(*GAMMA_ADJUST_KEYS),
        gamma_eeprom_x10=counts(*GAMMA_EEPROM_KEYS),
        delay_command=counts(*DELAY_COMMAND_KEYS),
        delay_eeprom=counts(*DELAY_EEPROM_KEYS),
        sin_corr_x100=counts(*SIN_KEYS),
        cos_corr_x100=counts(*COS_KEYS),
        eeprom_state=counts(*EEPROM_STATE_KEYS),
        vsm=counts(*VSM_KEYS),
        enable=counts(*ENABLE_KEYS),
        inverter_mode=counts(*INVERTER_MODE_KEYS),
    )


def inferred_forward(speed_rpm: int | None, min_rpm: int = HAND_TURN_RPM) -> bool | None:
    if speed_rpm is None or abs(speed_rpm) < min_rpm:
        return None
    return speed_rpm > 0


def gamma_follows_forward(samples: list[tuple[int, int]]) -> bool | None:
    """True when Gamma Resolver increases while Feedback Speed is positive."""
    votes = 0
    n = 0
    for (speed0, gamma0), (speed1, gamma1) in zip(samples, samples[1:]):
        if abs(speed1) < HAND_TURN_RPM:
            continue
        step = angle_delta_x10(gamma0, gamma1)
        if step == 0:
            continue
        n += 1
        if (speed1 > 0 and step > 0) or (speed1 < 0 and step < 0):
            votes += 1
        else:
            votes -= 1
    if n < 3:
        return None
    if votes > 0:
        return True
    if votes < 0:
        return False
    return None


def speeds_agree(
    feedback_rpm: int | None,
    voltage_rpm: int | None,
    min_rpm: int = DIRECTION_MIN_RPM,
) -> str:
    if feedback_rpm is None:
        return "Waiting for Feedback Speed."
    if voltage_rpm is None:
        return "not available over CAN — use RS232"
    if abs(feedback_rpm) < min_rpm:
        return f"Spin faster (need ~{min_rpm} RPM)."
    if abs(voltage_rpm) < min_rpm / 2:
        return "Voltage speed is too low — spin faster, or the phases are wrong."
    if (feedback_rpm > 0) != (voltage_rpm > 0):
        return "Signs disagree — swap two motor phase leads."
    if abs(abs(feedback_rpm) - abs(voltage_rpm)) > max(200, 0.4 * abs(feedback_rpm)):
        return "Magnitudes disagree — resolver type or motor-type EEPROM may be wrong."
    return "Feedback Speed and Voltage Feedback Speed agree."


def write_blocked_reason(
    vsm: int | None,
    enable: int | bool | None,
    inverter_mode: int | None,
    *,
    kind: str = "ram",
) -> str | None:
    """Why a Memory View write must not go out.

    CAN EEPROM params are writable only while the motor is not enabled.
    Wait (VSM 4) is this bench's idle — do not treat 4 as forbidden.
    Ready/Running (5/6), enable on, and Inverter_Mode start/run states are.
    """
    if enable not in (None, 0, False):
        return "Inverter is enabled. Disable it and sit in Wait (VSM 4)."
    if vsm == VSM_RECYCLE:
        return "VSM is Recycle Power (15). Power-cycle before writing again."
    if vsm in {VSM_READY, VSM_RUNNING}:
        return f"VSM is {vsm} (Ready/Running). Writes wait until Wait (4)."
    if inverter_mode in INVERTER_MODE_LIVE:
        return (
            f"Inverter mode {inverter_mode} looks like a start/run state. "
            "Stop first (Wait / Stop), then write."
        )
    if kind == "eeprom" and vsm is None:
        return "VSM unknown — will not program EEPROM until Wait (4) is confirmed."
    if kind == "eeprom" and vsm == VSM_FAULT:
        return "VSM is Fault (7). Clear faults before programming EEPROM."
    if kind == "eeprom" and vsm != VSM_WAIT:
        return f"VSM is {vsm}. Program EEPROM only in Wait (4) with enable off."
    return None


def eeprom_commit_frames() -> tuple[tuple[int, int], tuple[int, int]]:
    """yuh3 Program EEPROM pair: unlock then command, each waiting for RAE."""
    return EEPROM_COMMIT_UNLOCK, EEPROM_COMMIT_COMMAND


def eeprom_persist_writes(
    delay_command: int, gamma_adjust_x10: int
) -> tuple[tuple[int, int], ...]:
    """Copy Memory Values into EEPROM shadows, then the Program EEPROM pair.

    yuh3 wrote the EEPROM-named word (`wm0117`) then `wm0000=5a0f` / `wm0001=0059`.
    yuh4 (1) confirmed signed Gamma RAM (`wm0010=fff8` / `fff6`) with RAE.
    """
    return (
        (RESOLVER_DELAY_EEPROM_ADDRESS, encode_u16(delay_command)),
        (GAMMA_ADJUST_EEPROM_ADDRESS, encode_u16(gamma_adjust_x10)),
        EEPROM_COMMIT_UNLOCK,
        EEPROM_COMMIT_COMMAND,
    )
