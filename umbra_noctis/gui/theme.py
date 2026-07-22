"""Dark theme for night-time processing, with an optional red-light mode."""

DARK_QSS = """
* { font-size: 13px; }
QMainWindow, QWidget { background: #14161c; color: #d8dae2; }
QLabel#pageTitle { font-size: 20px; font-weight: 600; color: #eceef5; }
QLabel#pageHint { color: #9aa0b4; }
QLabel#stepDone { color: #7ee0a3; }
QPushButton {
    background: #232735; border: 1px solid #3a4056; border-radius: 6px;
    padding: 7px 14px; color: #e6e8f0;
}
QPushButton:hover { background: #2c3145; }
QPushButton:pressed { background: #1b1e2b; }
QPushButton:disabled { color: #666c80; background: #1a1d27; }
QPushButton#primary {
    background: #3b5bd9; border-color: #4a6ae8; font-weight: 600;
}
QPushButton#primary:hover { background: #4a6ae8; }
QPushButton#navButton {
    text-align: left; padding: 12px 16px; border: none; border-radius: 0;
    background: transparent; color: #9aa0b4; font-size: 14px;
}
QPushButton#navButton:checked {
    background: #232735; color: #ffffff; border-left: 3px solid #3b5bd9;
}
QTableWidget, QTreeWidget, QListWidget, QTextEdit, QPlainTextEdit {
    background: #191c26; border: 1px solid #2a2f40; border-radius: 6px;
    alternate-background-color: #1e2230; selection-background-color: #3b5bd9;
}
QHeaderView::section {
    background: #20242f; color: #aab; border: none; padding: 5px;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #1e2230; border: 1px solid #343b52; border-radius: 5px;
    padding: 4px 8px; color: #e6e8f0;
}
QComboBox::drop-down { border: none; }
QProgressBar {
    background: #1e2230; border: 1px solid #343b52; border-radius: 5px;
    text-align: center; color: #d8dae2;
}
QProgressBar::chunk { background: #3b5bd9; border-radius: 4px; }
QGroupBox {
    border: 1px solid #2a2f40; border-radius: 8px; margin-top: 12px;
    padding-top: 10px; font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
QCheckBox::indicator, QRadioButton::indicator { width: 15px; height: 15px; }
QSlider::groove:horizontal { height: 5px; background: #2a2f40; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 14px; margin: -6px 0; border-radius: 7px; background: #4a6ae8;
}
QToolTip { background: #232735; color: #e6e8f0; border: 1px solid #3a4056; }
QSplitter::handle { background: #2a2f40; }
QStatusBar { color: #9aa0b4; }
QGraphicsView { border: 1px solid #2a2f40; border-radius: 4px; background: #0c0d12; }
"""

RED_NIGHT_QSS = DARK_QSS + """
* { color: #c46a5a; }
QLabel#pageTitle { color: #e08a76; }
QPushButton#primary { background: #7a2e1f; border-color: #a0402c; }
QProgressBar::chunk { background: #a0402c; }
QPushButton#navButton:checked { border-left: 3px solid #a0402c; color: #e08a76; }
"""
