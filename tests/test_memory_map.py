from inverter_monitor.catalog import load_catalog
from inverter_monitor.decode import Decoder
from inverter_monitor.memory_map import (
    MEMORY_FRAME_ID,
    MemoryPoller,
    WatchList,
    checksum_prefix,
    pack_memory_frame,
    parse_read_reply,
    read_command,
    search_symbols,
    snapshot_addresses,
    write_command,
)


def test_checksum_matches_captured_gui_frames():
    assert checksum_prefix("rm0093") == "55"
    assert read_command(0x0093) == b"rm009355\r"
    assert checksum_prefix("*0093=0004") == "09"
    assert parse_read_reply("*0093=000409") == (0x0093, 0x0004)
    assert parse_read_reply("*0117=00050B") == (0x0117, 0x0005)
    assert parse_read_reply("*0117=00050C") is None
    assert write_command(0x0117, 5) == b"wm0117=000551\r"
    assert write_command(0x0002, 0) == f"wm0002=0000{checksum_prefix('wm0002=0000')}\r".encode("ascii")


def test_search_covers_memory_and_eeprom():
    catalog = load_catalog()
    vsm = search_symbols(catalog.memory_symbols, "vsm state", "memory")
    assert any(item.name == "VSM_State" and item.address == 0x0093 for item in vsm)
    eeprom = search_symbols(catalog.memory_symbols, "serial 0113", "eeprom")
    assert any(item.name == "Serial_Number_EEPROM" for item in eeprom)
    hidden = search_symbols(catalog.memory_symbols, "vsm", "eeprom")
    assert all(item.kind == "eeprom" for item in hidden)
    assert not any(item.name == "VSM_State" for item in hidden)
    year = search_symbols(catalog.memory_symbols, "code version yyyy")
    assert any(item.address == 0x0050 for item in year)
    offset = search_symbols(catalog.memory_symbols, "can id offset", "eeprom")
    assert any(item.name == "CAN_ID_Offset_EEPROM" and item.address == 0x011D for item in offset)
    faults = search_symbols(catalog.memory_symbols, "post fault lo")
    assert any(item.name == "Post_Fault_Lo" and item.address == 0x0057 for item in faults)


def test_symbols_group_by_rms_function():
    catalog = load_catalog()
    by_name = {item.name: item for item in catalog.memory_symbols}
    assert by_name["CAN_ID_Offset_EEPROM"].group == "CAN"
    assert by_name["CAN_Bit_Rate_EEPROM_(kbps)"].group == "CAN"
    assert by_name["Resolver_PWM_Delay_EEPROM_(Counts)"].group == "Motor / Resolver"
    assert by_name["Sin_Offset_EEPROM_(ADC_Counts)"].group == "Motor / Resolver"
    assert by_name["Sin_corr_(V)_x_100"].group == "Resolver"
    assert by_name["Motor_Temp_(C)_x_10"].group == "Thermal"
    assert by_name["VSM_State"].group == "VSM / IO"
    assert by_name["Post_Fault_Lo"].group == "VSM / IO"
    assert by_name["Code_Version_YYYY"].group == "Firmware"
    assert by_name["CAN_ID_Offset_EEPROM"].snapshot
    assert not by_name["VSM_State"].snapshot
    assert not by_name["Post_Fault_Lo"].snapshot
    dump = snapshot_addresses(catalog.memory_symbols)
    assert 0x011D in dump
    assert 0x0113 in dump
    assert 0x0050 in dump
    assert 0x0093 not in dump
    assert 0x0057 not in dump


def test_poller_interleaves_dump_with_watch():
    watch = WatchList([0x0093])
    poller = MemoryPoller(watch)
    poller.start_dump([0x0113, 0x011D])
    assert poller.next_address() == 0x0113
    assert poller.dump_progress().active
    assert poller.next_address() == 0x0093
    assert poller.next_address() == 0x011D
    progress = poller.dump_progress()
    assert not progress.active
    assert progress.done == 2
    assert poller.next_address() == 0x0093


def test_poller_dumps_without_watch():
    poller = MemoryPoller(WatchList())
    poller.start_dump([0x0113, 0x011D])
    assert poller.next_address() == 0x0113
    assert poller.next_address() == 0x011D
    assert poller.next_address() is None
    assert not poller.dump_progress().active


def test_poller_active_overrides_watch():
    watch = WatchList([0x0093])
    poller = MemoryPoller(watch)
    poller.set_active_addresses([0x0057, 0x0058, 0x0057])
    assert poller.poll_addresses() == (0x0057, 0x0058)
    assert poller.next_address() == 0x0057
    assert watch.addresses() == (0x0093,)
    poller.set_active_addresses(None)
    assert poller.poll_addresses() == (0x0093,)
    assert poller.next_address() == 0x0093


def test_watch_list_replace():
    watches = WatchList([0x0093])
    watches.replace([0x0057, 0x0058, 0x0057])
    assert watches.addresses() == (0x0057, 0x0058)
    watches.replace(())
    assert watches.addresses() == ()


def test_watch_list_add_remove():
    watches = WatchList()
    watches.add(0x0093)
    watches.add(0x0113)
    watches.add(0x0093)
    assert watches.addresses() == (0x0093, 0x0113)
    watches.remove(0x0093)
    assert watches.addresses() == (0x0113,)
    assert not watches.contains(0x0093)


def test_memory_view_frame_decodes_vsm():
    catalog = load_catalog()
    decoder = Decoder(catalog)
    updates = decoder.decode_frame(MEMORY_FRAME_ID, pack_memory_frame(0x0093, 4))
    assert len(updates) == 1
    update = updates[0]
    assert update.key == "MemoryView.VSM_State"
    assert update.raw == 4
    assert update.enum_name == "VSM_Wait"


def test_memory_view_decodes_inverter_mode_and_command_mode():
    catalog = load_catalog()
    decoder = Decoder(catalog)
    mode = decoder.decode_frame(MEMORY_FRAME_ID, pack_memory_frame(0x0092, 1))[0]
    assert mode.key == "MemoryView.Inverter_Mode"
    assert mode.enum_name == "Stop"
    cmd = decoder.decode_frame(MEMORY_FRAME_ID, pack_memory_frame(0x011B, 1))[0]
    assert cmd.key == "MemoryView.Inv_Cmd_Mode_EEPROM(CAN=0_VSM=1)"
    assert cmd.enum_name == "VSM_mode"
