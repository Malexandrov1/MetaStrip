"""Consistent application palette, spacing and visual states."""


def stylesheet(theme: str = "Dark") -> str:
    light = theme == "Light"
    bg = "#f2f4f7" if light else "#111318"
    surface = "#ffffff" if light else "#191c23"
    raised = "#e9eef4" if light else "#222630"
    border = "#cdd5df" if light else "#303642"
    fg = "#192536" if light else "#edf1f7"
    muted = "#536476" if light else "#9aa6b8"
    return f"""
    QWidget {{ background: {bg}; color: {fg}; font-family: 'Segoe UI', 'Inter', sans-serif;
        font-size: 13px; }}
    QMainWindow {{ background: {bg}; }}
    QFrame#Sidebar {{ background: {surface}; border-right: 1px solid {border}; }}
    QFrame#Card {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
    QFrame#Card QLabel, QFrame#Sidebar QLabel {{ background: transparent; }}
    QLabel#Brand {{ font-size: 24px; font-weight: 700; letter-spacing: -1px; }}
    QLabel#Title {{ font-size: 28px; font-weight: 650; }}
    QLabel#Subtitle, QLabel#Muted {{ color: {muted}; }}
    QLabel#Section {{ font-size: 15px; font-weight: 600; }}
    QLabel#Privacy {{ color: #68cbb0; font-size: 11px; }}
    QPushButton {{ background: {raised}; border: 1px solid {border}; border-radius: 7px;
        padding: 10px 16px; font-weight: 600; }}
    QPushButton:hover {{ border-color: #6d8fac; background: {surface}; }}
    QPushButton:pressed {{ background: {border}; }}
    QPushButton:disabled {{ color: {muted}; background: {surface}; }}
    QPushButton#Primary {{ color: #10241f; background: #76d8b7; border-color: #76d8b7; }}
    QPushButton#Primary:hover {{ background: #98e5cb; }}
    QPushButton#Primary:disabled {{ background: {raised}; color: {muted}; border-color: {border}; }}
    QPushButton#Nav {{ text-align: left; background: transparent; border: none;
        border-radius: 8px; padding: 13px 14px; font-weight: 500; }}
    QPushButton#Nav:checked {{ background: {raised}; color: #68cbb0; }}
    QPushButton#Nav:hover {{ background: {raised}; }}
    QFrame#DropZone {{ background: {surface}; border: 1px dashed #63788a; border-radius: 12px; }}
    QFrame#DropZone QLabel {{ background: transparent; }}
    QLabel#DropTitle {{ font-size: 19px; font-weight: 600; }}
    QLineEdit, QSpinBox, QComboBox {{ background: {surface}; border: 1px solid {border};
        border-radius: 6px; padding: 9px; selection-background-color: #387867; }}
    QLineEdit:focus, QComboBox:focus {{ border-color: #76d8b7; }}
    QTableWidget, QTreeWidget {{ background: {surface}; border: 1px solid {border};
        border-radius: 8px; gridline-color: {border}; alternate-background-color: {raised}; }}
    QTableWidget::item, QTreeWidget::item {{ padding: 7px; border: none; }}
    QTableWidget::item:selected, QTreeWidget::item:selected {{
        background: #315d55; color: #ffffff; }}
    QHeaderView::section {{ background: {raised}; color: {muted}; border: none;
        border-bottom: 1px solid {border}; padding: 10px; font-weight: 600; }}
    QProgressBar {{ background: {raised}; border: none; border-radius: 4px; height: 7px;
        color: {muted}; }}
    QProgressBar::chunk {{ background: #76d8b7; border-radius: 4px; }}
    QCheckBox {{ spacing: 9px; padding: 6px 0; }}
    QCheckBox::indicator {{ width: 17px; height: 17px; border: 1px solid {muted};
        border-radius: 4px; background: {surface}; }}
    QCheckBox::indicator:checked {{ background: #76d8b7; border-color: #76d8b7; }}
    QScrollArea {{ border: none; }}
    QToolTip {{ background: {raised}; color: {fg}; border: 1px solid {border}; padding: 7px; }}
    QStatusBar {{ color: {muted}; border-top: 1px solid {border}; }}
    QScrollBar:vertical {{ width: 9px; background: {surface}; }}
    QScrollBar::handle:vertical {{ background: {border}; border-radius: 4px; min-height: 24px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    """
