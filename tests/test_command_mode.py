from inverter_monitor.catalog import (
    CAN_COMMAND_MODE,
    VSM_COMMAND_MODE,
    load_catalog,
    mode_label,
)
from inverter_monitor.decode import Decoder, encode_physical
from inverter_monitor.store import InverterStore, command_mode


def _snapshot_with_command_mode(raw: int):
    catalog = load_catalog()
    decoder = Decoder(catalog)
    store = InverterStore(catalog)
    message = catalog.messages_by_name["M170_Internal_States"]
    payload = encode_physical(message, {"D5_Inverter_Command_Mode": raw})
    store.apply_frame(
        message.can_id, payload, decoder.decode_frame(message.can_id, payload),
        now=1.0, name=message.name,
    )
    return store.snapshot(now=1.0)


def test_vsm_state_prefers_can_wording_by_default():
    catalog = load_catalog()
    wait = catalog.vsm_states[4]
    assert "CAN" in wait.text(None)[0]
    assert "forward or reverse" in wait.text(VSM_COMMAND_MODE)[0]
    assert wait.text(CAN_COMMAND_MODE)[0] == wait.text(None)[0]


def test_vsm_state_falls_back_without_can_override():
    catalog = load_catalog()
    start = catalog.vsm_states[0]
    assert start.text(VSM_COMMAND_MODE)[0] == "Default state at vehicle power-up."
    assert start.text(None)[0]  # CAN wording present


def test_command_mode_reads_m170_with_can_fallback():
    assert command_mode(_snapshot_with_command_mode(0)) == CAN_COMMAND_MODE
    assert command_mode(_snapshot_with_command_mode(1)) == VSM_COMMAND_MODE


def test_mode_label_defaults_to_can():
    assert mode_label(None) == "CAN mode"
    assert mode_label(CAN_COMMAND_MODE) == "CAN mode"
    assert mode_label(VSM_COMMAND_MODE) == "VSM mode"
