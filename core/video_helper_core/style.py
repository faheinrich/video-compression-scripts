"""Look shared by all tools (cards, captions, the accent run button, progress bar)."""
from PySide6.QtWidgets import QLabel

STYLE = """
QFrame#summary, QFrame#detailBar { background: palette(alternate-base); border: 1px solid palette(mid); border-radius: 8px; }
QFrame#drawer { border-left: 1px solid palette(mid); }
QLabel[role="caption"] { color: palette(placeholder-text); font-size: 11px; font-weight: 600; letter-spacing: 0.5px; }
QLabel[role="value"] { font-size: 15px; font-weight: 600; }
QLabel[role="value"][tone="good"] { color: #23875a; }
QLabel[role="value"][tone="warn"] { color: #b7701a; }
QLabel[role="hint"] { color: palette(placeholder-text); font-size: 12px; }
QPushButton#runButton { background: palette(highlight); color: palette(highlighted-text); border: none; border-radius: 6px; padding: 6px 18px; font-weight: 600; }
QPushButton#runButton[mode="stop"] { background: #c63f35; color: white; }
QPushButton#runButton:disabled { background: palette(midlight); color: palette(placeholder-text); }
QPushButton[role="chip"] { border: 1px solid palette(mid); border-radius: 12px; padding: 3px 12px; background: transparent; }
QPushButton[role="chip"]:checked { background: palette(text); color: palette(base); border-color: palette(text); }
QPushButton[role="segment"] { border: 1px solid palette(mid); padding: 5px 8px; background: palette(base); }
QPushButton[role="segment"]:checked { background: palette(highlight); color: palette(highlighted-text); border-color: palette(highlight); font-weight: 600; }
QProgressBar { border: none; background: palette(midlight); border-radius: 3px; max-height: 6px; }
QProgressBar::chunk { background: palette(highlight); border-radius: 3px; }
"""


def caption(text):
    label = QLabel(text.upper())
    label.setProperty("role", "caption")
    return label
