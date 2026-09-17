from inverter_monitor.calibration import (
    CalibrationReading,
    EEPROM_COMMIT_COMMAND,
    EEPROM_COMMIT_UNLOCK,
    EEPROM_WRITE_ADDRESSES,
    GAMMA_ADJUST_ADDRESS,
    GAMMA_ADJUST_EEPROM_ADDRESS,
    RAM_WRITE_ADDRESSES,
    RESOLVER_DELAY_COMMAND_ADDRESS,
    RESOLVER_DELAY_EEPROM_ADDRESS,
    VSM_FAULT,
    VSM_READY,
    VSM_RECYCLE,
    VSM_RUNNING,
    VSM_WAIT,
    clamp_delay,
    encode_u16,
    eeprom_commit_frames,
    eeprom_persist_writes,
    gamma_converged,
    gamma_follows_forward,
    next_gamma_adjust,
    wrap_error_x10,
    write_blocked_reason,
)
from inverter_monitor.memory_map import checksum_prefix, write_command


def test_gamma_formula_matches_rms_and_wraps_full_turns():
    assert next_gamma_adjust(100, 800, 900) == 0
    assert next_gamma_adjust(0, 900, 900) == 0
    assert next_gamma_adjust(50, 920, 900) == 70
    # 2700°×10 is the same angle as −900, so reverse already at goal.
    assert wrap_error_x10(2700 - (-900)) == 0
    assert next_gamma_adjust(120, 2700, -900) == 120
    assert gamma_converged(893, 900)
    assert not gamma_converged(880, 900)


def test_gamma_ram_write_frame_is_signed():
    assert encode_u16(-900) == 0xFC7C
    assert write_command(GAMMA_ADJUST_ADDRESS, encode_u16(-900)) == (
        f"wm0010=fc7c{checksum_prefix('wm0010=fc7c')}\r".encode("ascii")
    )
    assert write_command(RESOLVER_DELAY_COMMAND_ADDRESS, 1100) == (
        f"wm0005=044c{checksum_prefix('wm0005=044c')}\r".encode("ascii")
    )
    # yuh4 (1): Memory Values Gamma −8 then −10, each RAE.
    assert write_command(GAMMA_ADJUST_ADDRESS, encode_u16(-8)) == (
        f"wm0010=fff8{checksum_prefix('wm0010=fff8')}\r".encode("ascii")
    )
    assert write_command(GAMMA_ADJUST_ADDRESS, encode_u16(-10)) == (
        f"wm0010=fff6{checksum_prefix('wm0010=fff6')}\r".encode("ascii")
    )


def test_ram_versus_eeprom_match_helpers():
    both = CalibrationReading(delay_command=1100, delay_eeprom=1100, gamma_adjust_x10=-8, gamma_eeprom_x10=-8)
    assert both.delay_matches_eeprom() is True
    assert both.gamma_matches_eeprom() is True
    differ = CalibrationReading(delay_command=1200, delay_eeprom=1100, gamma_adjust_x10=-10, gamma_eeprom_x10=-8)
    assert differ.delay_matches_eeprom() is False
    assert differ.gamma_matches_eeprom() is False
    unknown = CalibrationReading(delay_command=1100)
    assert unknown.delay_matches_eeprom() is None


def test_ram_allow_list_excludes_eeprom_commit():
    assert RESOLVER_DELAY_COMMAND_ADDRESS in RAM_WRITE_ADDRESSES
    assert GAMMA_ADJUST_ADDRESS in RAM_WRITE_ADDRESSES
    assert EEPROM_COMMIT_UNLOCK[0] not in RAM_WRITE_ADDRESSES
    assert EEPROM_COMMIT_COMMAND[0] not in RAM_WRITE_ADDRESSES
    assert EEPROM_COMMIT_UNLOCK[0] in EEPROM_WRITE_ADDRESSES
    assert EEPROM_COMMIT_COMMAND[0] in EEPROM_WRITE_ADDRESSES
    assert RESOLVER_DELAY_EEPROM_ADDRESS in EEPROM_WRITE_ADDRESSES
    assert GAMMA_ADJUST_EEPROM_ADDRESS in EEPROM_WRITE_ADDRESSES
    assert clamp_delay(-10) == 0
    assert clamp_delay(9000) == 6250


def test_eeprom_persist_copies_ram_then_commit_pair():
    frames = eeprom_persist_writes(50, -8)
    assert frames[0] == (RESOLVER_DELAY_EEPROM_ADDRESS, 50)
    assert frames[1] == (GAMMA_ADJUST_EEPROM_ADDRESS, encode_u16(-8))
    assert frames[2:] == eeprom_commit_frames()
    assert write_command(*EEPROM_COMMIT_UNLOCK).startswith(b"wm0000=5a0f")
    assert write_command(*EEPROM_COMMIT_COMMAND).startswith(b"wm0001=0059")


def test_gamma_resolver_follows_forward_samples():
    increasing = [(40, 100), (50, 180), (60, 240), (55, 300), (50, 390)]
    assert gamma_follows_forward(increasing) is True
    decreasing = [(40, 390), (50, 300), (60, 240), (55, 180), (50, 100)]
    assert gamma_follows_forward(decreasing) is False
    assert gamma_follows_forward([(0, 0), (0, 10)]) is None


def test_writes_allowed_in_wait_blocked_when_enabled_or_running():
    assert write_blocked_reason(VSM_WAIT, 0, 1) is None
    assert write_blocked_reason(None, None, None) is None
    assert write_blocked_reason(None, None, None, kind="eeprom") is not None
    assert write_blocked_reason(VSM_WAIT, 0, 1, kind="eeprom") is None
    assert "enabled" in write_blocked_reason(VSM_WAIT, 1, 1).lower()
    assert "Ready/Running" in write_blocked_reason(VSM_READY, 0, 1)
    assert "Ready/Running" in write_blocked_reason(VSM_RUNNING, 0, 1)
    assert "start/run" in write_blocked_reason(VSM_WAIT, 0, 6).lower()
    assert "Fault" in write_blocked_reason(VSM_FAULT, 0, 1, kind="eeprom")
    assert write_blocked_reason(VSM_FAULT, 0, 1, kind="ram") is None
    assert "Recycle" in write_blocked_reason(VSM_RECYCLE, 0, 1)
    assert "Wait" in write_blocked_reason(0, 0, 1, kind="eeprom")
