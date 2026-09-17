import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel

from inverter_monitor.ui.theme import TONES, apply_theme, set_tone, vsm_color, vsm_tone
from inverter_monitor.ui.widgets import FlagChip


def _app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


def _rendered_colors(widget) -> set[str]:
    widget.resize(160, 48)
    widget.show()
    QApplication.processEvents()
    img = widget.grab().toImage()
    return {
        QColor(img.pixel(x, y)).name()
        for x in range(0, img.width(), 2)
        for y in range(0, img.height(), 2)
    }


def test_vsm_tone_mapping():
    assert vsm_tone(None) == "dim"
    assert vsm_tone(6) == "ok"
    assert vsm_tone(7) == "fault"
    assert vsm_tone(1) == "warn"
    assert vsm_tone(4) == "blue"
    assert vsm_tone(99) == "dim"
    # QPainter call sites derive colors from the same mapping
    assert vsm_color(6) == TONES["ok"]


def test_set_tone_sets_and_clears_property():
    _app()
    label = QLabel("x")
    set_tone(label, "fault")
    assert label.property("tone") == "fault"
    set_tone(label, None)
    assert label.property("tone") is None
    with pytest.raises(ValueError):
        set_tone(label, "chartreuse")


def test_tone_drives_rendered_colors():
    _app()
    label = QLabel("Sample text")
    set_tone(label, "fault")
    assert QColor(TONES["fault"]).name() in _rendered_colors(label)
    set_tone(label, "ok")
    colors = _rendered_colors(label)
    assert QColor(TONES["ok"]).name() in colors
    assert QColor(TONES["fault"]).name() not in colors
    label.close()


def test_flag_chip_border_follows_tone():
    _app()
    chip = FlagChip("LOCKOUT")
    chip.set_state(True)
    assert QColor(TONES["warn"]).name() in _rendered_colors(chip)
    chip.set_state(False)
    colors = _rendered_colors(chip)
    assert QColor(TONES["dim"]).name() in colors
    assert QColor(TONES["warn"]).name() not in colors
    chip.close()
