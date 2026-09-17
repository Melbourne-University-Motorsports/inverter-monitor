#!/usr/bin/env python3
"""Parse a USBPcap .pcapng and dump serial-relevant USB traffic."""

from __future__ import annotations

import argparse
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

SHB = 0x0A0D0D0A
IDB = 0x00000001
EPB = 0x00000006
SPB = 0x00000003
NRB = 0x00000004
ISB = 0x00000005
DSB = 0x0000000A

TRANSFER = {
    0: "ISO",
    1: "INT",
    2: "CTL",
    3: "BLK",
    0xFE: "IRP",
    0xFF: "UNK",
}

# USBPcap info bit 0: 1 = PDO->FDO (complete / from device side of IRP)
INFO_PDO_TO_FDO = 0x01

# CDC SET_LINE_CODING
SET_LINE_CODING = 0x20
GET_LINE_CODING = 0x21
SET_CONTROL_LINE_STATE = 0x22


def u32(b: bytes, off: int = 0) -> int:
    return struct.unpack_from("<I", b, off)[0]


def iter_blocks(data: bytes):
    off = 0
    n = len(data)
    while off + 8 <= n:
        btype = u32(data, off)
        blen = u32(data, off + 4)
        if blen < 12 or off + blen > n:
            raise SystemExit(f"bad block at {off:#x}: type={btype:#x} len={blen}")
        body = data[off + 8 : off + blen - 4]
        yield btype, body
        off += blen


def parse_options(blob: bytes):
    opts = {}
    off = 0
    while off + 4 <= len(blob):
        code, length = struct.unpack_from("<HH", blob, off)
        off += 4
        val = blob[off : off + length]
        pad = (4 - (length % 4)) % 4
        off += length + pad
        if code == 0:
            break
        opts[code] = val
    return opts


def parse_idb(body: bytes):
    link_type, reserved, snaplen = struct.unpack_from("<HHI", body, 0)
    opts = parse_options(body[8:])
    name = opts.get(2, b"").split(b"\x00", 1)[0].decode("utf-8", "replace")
    desc = opts.get(3, b"").split(b"\x00", 1)[0].decode("utf-8", "replace")
    return {"link_type": link_type, "snaplen": snaplen, "name": name, "desc": desc}


def parse_epb(body: bytes):
    ifc, ts_hi, ts_lo, caplen, origlen = struct.unpack_from("<IIIII", body, 0)
    pkt = body[20 : 20 + caplen]
    ts = (ts_hi << 32) | ts_lo
    return ifc, ts, pkt


def parse_usbpcap(pkt: bytes):
    if len(pkt) < 27:
        return None
    header_len = struct.unpack_from("<H", pkt, 0)[0]
    if header_len < 27 or header_len > len(pkt):
        return None
    irp_id = struct.unpack_from("<Q", pkt, 2)[0]
    status = struct.unpack_from("<I", pkt, 10)[0]
    function = struct.unpack_from("<H", pkt, 14)[0]
    info = pkt[16]
    bus, device = struct.unpack_from("<HH", pkt, 17)
    endpoint = pkt[21]
    transfer = pkt[22]
    data_length = struct.unpack_from("<I", pkt, 23)[0]
    rest = pkt[header_len:]
    # control header may sit inside header_len after 27 bytes
    extra = pkt[27:header_len]
    payload = rest[:data_length] if data_length else rest
    return {
        "header_len": header_len,
        "irp_id": irp_id,
        "status": status,
        "function": function,
        "info": info,
        "bus": bus,
        "device": device,
        "endpoint": endpoint,
        "ep_num": endpoint & 0x7F,
        "ep_dir": "IN" if endpoint & 0x80 else "OUT",
        "transfer": transfer,
        "xfer": TRANSFER.get(transfer, f"?{transfer}"),
        "data_length": data_length,
        "extra": extra,
        "payload": payload,
        "complete": bool(info & INFO_PDO_TO_FDO),
    }


def hexdump(b: bytes, n: int = 64) -> str:
    h = b[:n].hex(" ")
    a = "".join(chr(x) if 32 <= x < 127 else "." for x in b[:n])
    extra = f" …(+{len(b)-n})" if len(b) > n else ""
    return f"{h}{extra}  |{a}|"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pcap")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    data = Path(args.pcap).read_bytes()

    ifaces = {}
    packets = []
    other = Counter()
    for btype, body in iter_blocks(data):
        if btype == SHB:
            continue
        if btype == IDB:
            ifaces[len(ifaces)] = parse_idb(body)
            continue
        if btype == EPB:
            ifc, ts, pkt = parse_epb(body)
            rec = parse_usbpcap(pkt)
            if rec is None:
                other["unparsed"] += 1
                continue
            rec["ifc"] = ifc
            rec["ts"] = ts
            packets.append(rec)
            if args.limit and len(packets) >= args.limit:
                break
            continue
        other[f"block_{btype:#x}"] += 1

    print("=== interfaces ===")
    for i, inf in ifaces.items():
        print(f"  [{i}] link={inf['link_type']} name={inf['name']!r} desc={inf['desc']!r}")
    print(f"packets={len(packets)} other={dict(other)}")

    devices = Counter((p["bus"], p["device"]) for p in packets)
    print("=== devices (bus, addr) ===")
    for k, n in devices.most_common():
        print(f"  bus={k[0]} addr={k[1]}  n={n}")

    xfer = Counter((p["xfer"], p["ep_dir"], p["ep_num"], p["complete"]) for p in packets)
    print("=== transfer mix (type, dir, ep, complete) ===")
    for k, n in xfer.most_common():
        print(f"  {k}  n={n}")

    # Control setup packets: first 8 bytes of payload are setup if OUT/setup stage
    print("\n=== control payloads (first 80) ===")
    nctl = 0
    for i, p in enumerate(packets):
        if p["xfer"] != "CTL" or not p["payload"]:
            continue
        nctl += 1
        if nctl <= 80:
            print(
                f"{i:5d} bus={p['bus']} dev={p['device']} ep={p['ep_dir']}{p['ep_num']} "
                f"fn={p['function']:#06x} st={p['status']:#010x} cmp={int(p['complete'])} "
                f"extra={p['extra'].hex()} {hexdump(p['payload'], 32)}"
            )
    print(f"  (control with payload: {nctl})")

    # Bulk with data
    print("\n=== bulk/int with payload (first 120) ===")
    nblk = 0
    streams = defaultdict(bytearray)
    ascii_chunks = []
    for i, p in enumerate(packets):
        if p["xfer"] not in {"BLK", "INT"}:
            continue
        if not p["payload"]:
            continue
        # For IN, data usually arrives on complete. For OUT, on submit.
        key = (p["bus"], p["device"], p["ep_dir"], p["ep_num"])
        # Dedup: USBPcap often logs submit+complete; keep data-bearing side
        streams[key] += p["payload"]
        nblk += 1
        if nblk <= 120:
            print(
                f"{i:5d} {p['xfer']} {p['ep_dir']}{p['ep_num']} "
                f"cmp={int(p['complete'])} {hexdump(p['payload'], 48)}"
            )
        text = "".join(chr(x) if 32 <= x < 127 else "." for x in p["payload"])
        if any(32 <= x < 127 for x in p["payload"]):
            ascii_chunks.append((i, p["ep_dir"], p["ep_num"], text, p["payload"]))

    print("\n=== reconstructed stream sizes ===")
    for k, buf in streams.items():
        print(f"  bus={k[0]} dev={k[1]} {k[2]}{k[3]}  {len(buf)} bytes")

    print("\n=== reconstructed streams (hex, up to 4k each) ===")
    for k, buf in streams.items():
        print(f"\n-- bus={k[0]} dev={k[1]} {k[2]}{k[3]} --")
        show = bytes(buf[:4096])
        for off in range(0, len(show), 32):
            chunk = show[off : off + 32]
            print(f"{off:04x}  {hexdump(chunk, 32)}")
        if len(buf) > 4096:
            print(f"  … {len(buf)-4096} more bytes")

    print("\n=== ascii-ish bulk chunks containing letters/digits (first 80) ===")
    shown = 0
    for i, d, ep, text, raw in ascii_chunks:
        if any(c.isalnum() for c in text):
            print(f"{i:5d} {d}{ep} {text!r}")
            shown += 1
            if shown >= 80:
                break

    # Look for SCI-like 20-word lines: space-separated ints ending CR/LF
    print("\n=== SCI-like line scan on IN streams ===")
    for k, buf in streams.items():
        if k[2] != "IN":
            continue
        text = bytes(buf).decode("latin1", "replace")
        lines = [ln for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln.strip()]
        print(f"  {k}: {len(lines)} lines, sample:")
        for ln in lines[:15]:
            print(f"    {ln[:200]!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
