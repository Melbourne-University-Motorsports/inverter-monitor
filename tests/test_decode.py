from inverter_monitor.catalog import load_catalog
from inverter_monitor.decode import Decoder, encode_physical, extract_raw, pack_param_write
from inverter_monitor.memory_map import MEMORY_FRAME_ID, RUN_FAULT_LO_ADDRESS, pack_memory_frame
from inverter_monitor.store import InverterStore


def test_catalog_loads_vsm_and_faults():
    catalog = load_catalog()
    assert 6 in catalog.vsm_states
    assert catalog.vsm_states[6].name
    assert 0 in catalog.fault_bits
    assert 63 in catalog.fault_bits
    assert catalog.fault_bits[44].name.startswith("Motor Over-temperature")
    assert 0x0AA in catalog.messages
    assert 0x0AB in catalog.messages


def test_signed_torque_roundtrip():
    catalog = load_catalog()
    message = catalog.messages_by_name["M172_Torque_And_Timer_Info"]
    payload = encode_physical(message, {"D2_Torque_Feedback": -12.5})
    signal = next(item for item in message.signals if item.name == "D2_Torque_Feedback")
    raw = extract_raw(payload, signal)
    assert raw == -125
    decoder = Decoder(catalog)
    updates = {item.signal: item for item in decoder.decode_frame(message.can_id, payload)}
    assert updates["D2_Torque_Feedback"].value == -12.5


def test_vsm_state_in_byte0():
    catalog = load_catalog()
    message = catalog.messages_by_name["M170_Internal_States"]
    payload = encode_physical(message, {"D1_VSM_State": 7, "D6_Inverter_Enable_Lockout": True})
    decoder = Decoder(catalog)
    updates = {item.signal: item for item in decoder.decode_frame(0x0AA, payload)}
    assert updates["D1_VSM_State"].raw == 7
    assert updates["D1_VSM_State"].enum_name == "Blink_Fault_Code"
    assert updates["D6_Inverter_Enable_Lockout"].value is True


def test_fault_bit_expansion():
    catalog = load_catalog()
    decoder = Decoder(catalog)
    store = InverterStore(catalog)
    message = catalog.messages_by_name["M171_Fault_Codes"]
    payload = encode_physical(message, {"D3_Run_Fault_Lo": 0x1000})
    updates = decoder.decode_frame(0x0AB, payload)
    store.apply_frame(0x0AB, payload, updates, now=1.0, name=message.name)
    snapshot = store.snapshot(now=1.0)
    assert snapshot.run_word == 0x1000
    assert [bit.bit for bit in snapshot.active_faults] == [44]
    assert snapshot.fault_history[-1].active is True


def test_memory_view_fault_words_expand():
    catalog = load_catalog()
    decoder = Decoder(catalog)
    store = InverterStore(catalog)
    payload = pack_memory_frame(RUN_FAULT_LO_ADDRESS, 0x1000)
    updates = decoder.decode_frame(MEMORY_FRAME_ID, payload)
    store.apply_frame(MEMORY_FRAME_ID, payload, updates, now=1.0, name="Memory_View")
    snapshot = store.snapshot(now=1.0)
    assert snapshot.run_word == 0x1000
    assert [bit.bit for bit in snapshot.active_faults] == [44]


def test_param_write_packs_clear_faults():
    payload = pack_param_write(20, 0)
    assert payload == bytes([0x14, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])
