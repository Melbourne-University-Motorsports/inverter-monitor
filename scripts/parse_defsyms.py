#!/usr/bin/env python3
"""Parse an RMS GUI defsyms_*.txt file into data/defsyms.yaml."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

COLUMNS = ("name", "address", "type", "display", "width_bits", "gui_group")


def parse_defsyms(path: Path) -> dict:
    sections: list[dict] = []
    current: dict | None = None
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("#") and "########" not in line and line != "#":
            if ", 0x" in line:
                continue
            title = line.lstrip("# ").strip()
            if title:
                current = {"section": title, "symbols": []}
                sections.append(current)
            continue
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 6 or not parts[1].startswith("0x"):
            continue
        if current is None:
            current = {"section": "Ungrouped", "symbols": []}
            sections.append(current)
        current["symbols"].append(
            {
                "name": parts[0],
                "address": parts[1],
                "type": parts[2],
                "display": parts[3],
                "width_bits": int(parts[4]),
                "gui_group": int(parts[5]) if parts[5].isdigit() else parts[5],
                "writable": (
                    current["section"].startswith("EEPROM")
                    or (
                        current["section"].startswith("GUI Command")
                        and "Command" in parts[0]
                    )
                ),
            }
        )
    return {
        "source_file": path.name,
        "note": (
            "RMS GUI parameter map. Addresses are for the proprietary RS232 Memory View "
            "protocol, not the SCI 20-word broadcast and not CAN payloads. "
            "The 6th column is a GUI group/page id, not an EEPROM default."
        ),
        "columns": list(COLUMNS),
        "sections": sections,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    doc = parse_defsyms(args.input)
    args.output.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
    count = sum(len(section["symbols"]) for section in doc["sections"])
    print(f"Wrote {count} symbols -> {args.output}")


if __name__ == "__main__":
    main()
