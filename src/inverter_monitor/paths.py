from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2],  # src/inverter_monitor -> repo
        here.parents[1],
        Path.cwd(),
    ]
    for candidate in candidates:
        if (candidate / "data" / "reference_decode.yaml").is_file():
            return candidate
    raise FileNotFoundError(
        "Could not find data/reference_decode.yaml. Run from the inverter-monitor repo."
    )


def data_dir() -> Path:
    return project_root() / "data"
