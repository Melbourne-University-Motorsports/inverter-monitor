from inverter_monitor.catalog import load_catalog
from inverter_monitor.decode import Decoder
from inverter_monitor.simulate import DemoSource
from inverter_monitor.store import InverterStore


def test_demo_source_emits_decodable_frames():
    catalog = load_catalog()
    decoder = Decoder(catalog)
    store = InverterStore(catalog)
    source = DemoSource(catalog)
    seen = set()
    for _ in range(80):
        frame = source.recv(0.2)
        assert frame is not None
        updates = decoder.decode_frame(frame.arbitration_id, frame.data)
        message = catalog.messages.get(frame.arbitration_id)
        store.apply_frame(
            frame.arbitration_id,
            frame.data,
            updates,
            name=message.name if message else "",
        )
        seen.add(frame.arbitration_id)
        if 0x0AA in seen and 0x0A5 in seen:
            break
    snapshot = store.snapshot()
    assert "M165_Motor_Position_Info.D2_Motor_Speed" in snapshot.signals
    assert snapshot.frame_count > 0
    source.close()
