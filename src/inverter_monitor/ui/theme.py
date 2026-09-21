from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget


# Surface order, darkest to lightest: window BG < cards PANEL < inputs PANEL_ALT.
# Labels and containers stay transparent so text sits directly on its surface.
BG = "#14161a"
PANEL = "#1e2127"
PANEL_ALT = "#262b33"
BORDER = "#333a45"
TEXT = "#e8eaed"
DIM = "#99a1ab"
ACCENT = "#4c8dff"
OK = "#3ecf8e"
WARN = "#f5a524"
FAULT = "#e5484d"
BLUE = "#6cb6ff"
SELECTION = "#2d3e55"
CHIP_ON = "#1f3049"

# Layout rhythm. Pages keep zero side margins so their content aligns with the
# status strip and toolbar; the main window's own margins frame everything.
PAGE_MARGINS = (0, 8, 0, 0)
CARD_MARGINS = (14, 12, 14, 12)

# Semantic color roles for state-driven widgets. A widget sets the `tone`
# dynamic property (via set_tone) and the QSS selectors in apply_theme do
# the rest — no inline setStyleSheet fragments.
TONES = {
    "dim": DIM,
    "ok": OK,
    "warn": WARN,
    "fault": FAULT,
    "blue": BLUE,
}


def vsm_tone(state_id: int | None) -> str:
    if state_id is None:
        return "dim"
    if state_id == 6:
        return "ok"
    if state_id == 7:
        return "fault"
    if state_id in {1, 2, 3, 15}:
        return "warn"
    if state_id in {4, 5}:
        return "blue"
    return "dim"


def vsm_color(state_id: int | None) -> str:
    """Hex color for QPainter/QBrush call sites. QSS-styled widgets use vsm_tone."""
    return TONES[vsm_tone(state_id)]


def set_tone(widget: QWidget, tone: str | None) -> None:
    """Point the widget's `tone` QSS selector at a semantic color and repolish.

    Passing None clears the tone, returning to the default text color.
    """
    if tone is not None and tone not in TONES:
        raise ValueError(f"unknown tone {tone!r}; expected one of {sorted(TONES)}")
    if widget.property("tone") == tone:
        return
    widget.setProperty("tone", tone)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def apply_theme(app: QApplication) -> None:
    palette = QPalette()
    bg = QColor(BG)
    panel = QColor(PANEL)
    text = QColor(TEXT)
    dim = QColor(DIM)
    accent = QColor(ACCENT)
    palette.setColor(QPalette.ColorRole.Window, bg)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, QColor(PANEL_ALT))
    palette.setColor(QPalette.ColorRole.AlternateBase, panel)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, panel)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, panel)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, dim)
    app.setPalette(palette)
    app.setStyle("Fusion")
    tone_rules = "\n".join(
        f'        QLabel[tone="{name}"] {{ color: {hexcode}; }}'
        for name, hexcode in TONES.items()
    )
    app.setStyleSheet(
        f"""
        QWidget {{ color: {TEXT}; font-size: 13px; }}
        QMainWindow, QDialog {{ background: {BG}; }}

        QFrame#card, QFrame#strip {{
            background: {PANEL};
            border: 1px solid {BORDER};
            border-radius: 8px;
        }}
        /* A card only gains a tone when its own subsystem is in trouble; the
           inverter card and a healthy CAN card keep the quiet border. */
        QFrame#card[tone="warn"] {{ border-color: {WARN}; }}
        QFrame#card[tone="fault"] {{ border-color: {FAULT}; }}
        QFrame#card[tone="ok"] {{ border-color: {OK}; }}

        /* Labeled section inside a card (e.g. the CAN module block). The base
           style keeps it quiet; a tone adds a soft left-accent background. */
        QFrame#subCard {{
            background: transparent;
            border: 1px solid {BORDER};
            border-radius: 8px;
        }}
        QFrame#subCard[tone="warn"] {{
            background: rgba(245, 165, 36, 0.08);
            border-color: {WARN};
        }}
        QFrame#subCard[tone="fault"] {{
            background: rgba(229, 72, 77, 0.08);
            border-color: {FAULT};
        }}
        QFrame#subCard[tone="ok"] {{
            border-color: {OK};
        }}
        QFrame#subCard > QLabel {{
            background: transparent;
        }}

        QPushButton#textBtn {{
            background: transparent;
            border: none;
            color: {ACCENT};
            padding: 0 4px;
        }}
        QPushButton#textBtn:hover {{
            text-decoration: underline;
        }}
        QPushButton#textBtn:checked {{
            color: {TEXT};
        }}

        QLabel#muted {{ color: {DIM}; }}
        QLabel#metric {{ font-size: 28px; font-weight: 600; }}
        QLabel#unit {{ color: {DIM}; font-size: 13px; }}
        QLabel#vsmId {{ font-size: 42px; font-weight: 700; }}
        QLabel#vsmName {{ font-size: 20px; font-weight: 600; }}
        QLabel#faultHeadline {{ font-size: 28px; font-weight: 700; }}
        QLabel#faultCount {{ font-size: 18px; font-weight: 700; }}
        QLabel#liveBadge, QLabel#enableState {{ font-weight: 600; }}
        QLabel#emptyState {{ font-size: 16px; font-weight: 600; padding: 24px; }}
        QLabel#flagChip {{
            border: 1px solid {DIM};
            border-radius: 8px;
            padding: 4px 8px;
        }}
        QLabel#flagChip[tone="ok"] {{ border-color: {OK}; }}
        QLabel#flagChip[tone="warn"] {{ border-color: {WARN}; }}
        QLabel#flagChip[tone="fault"] {{ border-color: {FAULT}; }}
        /* tone rules lose to object-name rules that set color, so a toned
           label must not also use #muted or #unit. */
{tone_rules}

        QTabWidget::pane {{ border: none; }}
        QTabBar::tab {{
            color: {DIM};
            padding: 7px 14px;
            margin-right: 2px;
            border-radius: 6px;
        }}
        QTabBar::tab:hover {{ color: {TEXT}; }}
        QTabBar::tab:selected {{
            background: {PANEL_ALT};
            color: {TEXT};
        }}

        QTableWidget, QTreeWidget, QTextEdit, QListWidget {{
            background: {PANEL};
            border: 1px solid {BORDER};
            selection-background-color: {SELECTION};
            selection-color: {TEXT};
        }}
        QTableWidget {{ gridline-color: {BORDER}; }}
        QTreeWidget::item {{ padding: 2px 0; }}
        QListWidget::item {{ padding: 6px 10px; }}
        QHeaderView::section {{
            background: {PANEL_ALT};
            color: {DIM};
            padding: 6px;
            border: none;
            border-bottom: 1px solid {BORDER};
        }}

        QLineEdit, QComboBox, QSpinBox {{
            background: {PANEL_ALT};
            border: 1px solid {BORDER};
            border-radius: 6px;
            padding: 4px 8px;
            selection-background-color: {SELECTION};
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
        QComboBox QAbstractItemView {{
            background: {PANEL_ALT};
            border: 1px solid {BORDER};
            selection-background-color: {SELECTION};
        }}

        QPushButton {{
            background: {PANEL_ALT};
            border: 1px solid {BORDER};
            border-radius: 6px;
            padding: 6px 14px;
        }}
        QPushButton:hover {{ border-color: {ACCENT}; }}
        QPushButton:pressed {{ background: {BG}; }}
        QPushButton#primary {{
            background: {ACCENT};
            color: white;
            border: none;
        }}
        QPushButton#danger {{
            background: {FAULT};
            color: white;
            border: none;
        }}
        QPushButton#danger:disabled {{
            background: {PANEL_ALT};
            color: {DIM};
        }}

        QScrollArea {{
            background: {PANEL};
            border: none;
        }}
        QCheckBox#signalChip {{
            background: {PANEL_ALT};
            border: 1px solid {BORDER};
            border-radius: 6px;
            padding: 4px 10px;
            spacing: 6px;
        }}
        QCheckBox#signalChip:hover {{ border-color: {ACCENT}; }}
        QCheckBox#signalChip:checked {{
            border-color: {ACCENT};
            background: {CHIP_ON};
        }}

        QMenuBar {{ background: {BG}; }}
        QMenuBar::item {{
            padding: 4px 8px;
            background: transparent;
        }}
        QMenuBar::item:selected {{ background: {PANEL_ALT}; border-radius: 4px; }}
        QMenu {{
            background: {PANEL};
            border: 1px solid {BORDER};
        }}
        QMenu::item:selected {{ background: {SELECTION}; }}

        QToolTip {{
            background: {PANEL_ALT};
            color: {TEXT};
            border: 1px solid {BORDER};
            padding: 4px 6px;
        }}

        QLabel#graphHover {{
            background: {PANEL};
            border: 1px solid {BORDER};
            border-radius: 6px;
            padding: 6px 8px;
        }}

        QScrollBar:vertical {{
            background: transparent;
            width: 10px;
        }}
        QScrollBar::handle:vertical {{
            background: {BORDER};
            border-radius: 5px;
            min-height: 24px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{
            background: transparent;
            height: 10px;
        }}
        QScrollBar::handle:horizontal {{
            background: {BORDER};
            border-radius: 5px;
            min-width: 24px;
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        """
    )


def mono_font(size: int = 12) -> QFont:
    font = QFont("Menlo")
    if font.family() != "Menlo":
        font = QFont("JetBrains Mono")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(size)
    return font
