from inverter_monitor.decode import decode_sci_words, signed16
from inverter_monitor.serial_sci import parse_sci_line, sci_updates
from inverter_monitor.store import InverterStore
from inverter_monitor.catalog import load_catalog
from inverter_monitor.decode import Decoder, pack_sci_words
from inverter_monitor.decode import SCI_FRAME_ID


def test_parse_sci_line_signed_torque_and_speed():
    # 20 SCI records; torque feedback FFF6 = -10 -> -1.0 Nm; speed 07D0 = 2000 rpm
    fields = ["0000", "00C8", "FFF6", "012C", "0E74", "0064", "07D0", "0000", "0000", "0000"]
    fields += ["0000", "0000", "0000", "0000", "01F4", "0258", "1000", "0000", "0000", "0028"]
    words = parse_sci_line(" ".join(fields))
    assert words is not None
    assert len(words) == 20
    assert signed16(words[2]) == -10
    updates = {item.key: item for item in sci_updates(words)}
    assert updates["M172_Torque_And_Timer_Info.D2_Torque_Feedback"].value == -1.0
    assert updates["M165_Motor_Position_Info.D2_Motor_Speed"].value == 2000
    assert updates["M163_Analog_Input_Voltages.D1_Analog_Input_1"].value == 2.0
    assert updates["M171_Fault_Codes.D3_Run_Fault_Lo"].raw == 0x1000


def test_sci_frame_roundtrip_into_store():
    catalog = load_catalog()
    decoder = Decoder(catalog)
    store = InverterStore(catalog)
    fields = ["0000"] * 16 + ["1000", "0000", "0000", "0000"]
    words = parse_sci_line(" ".join(fields))
    assert words is not None
    payload = pack_sci_words(words)
    updates = decoder.decode_frame(SCI_FRAME_ID, payload)
    store.apply_frame(SCI_FRAME_ID, payload, updates, name="SCI_Broadcast")
    snapshot = store.snapshot()
    assert [bit.bit for bit in snapshot.active_faults] == [44]
