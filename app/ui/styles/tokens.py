"""MetaStrip's visual and motion primitives, shared by styles and native painters."""

from dataclasses import dataclass

from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class Colors:
    bg: str
    surface: str
    raised: str
    hover: str
    border: str
    text: str
    muted: str
    accent: str
    accent_text: str
    selection: str
    warning: str
    error: str
    disabled: str


DARK = Colors(
    bg="#151817",
    surface="#1b1f1d",
    raised="#232925",
    hover="#2a322d",
    border="#343c36",
    text="#e8ede9",
    muted="#a0aca4",
    accent="#94c9ad",
    accent_text="#14271d",
    selection="#293e32",
    warning="#d6ba88",
    error="#d79a93",
    disabled="#738078",
)
LIGHT = Colors(
    bg="#f5f6f3",
    surface="#ffffff",
    raised="#edf0ea",
    hover="#e5eae2",
    border="#cdd4ca",
    text="#25322a",
    muted="#5c6b60",
    accent="#3b7556",
    accent_text="#ffffff",
    selection="#dce9dc",
    warning="#84642c",
    error="#aa4f49",
    disabled="#7c897f",
)

FONT_FAMILY = "Segoe UI"
BODY_SIZE = 13
CAPTION_SIZE = 12
TITLE_SIZE = 27
SPACING = (4, 8, 12, 16, 20, 24, 32, 40, 48)
CONTROL_HEIGHT = 36
NAV_HEIGHT = 42
CHECKBOX_SIZE = 18
ICON_SIZE = 18
RADIUS = 6
PANEL_RADIUS = 8
FOCUS_WIDTH = 2
ELEVATION = (0, 1)  # Elevation is communicated by surface tone and a one-pixel border.


@dataclass(frozen=True)
class Durations:
    hover: int = 110
    press: int = 90
    checkbox: int = 170
    navigation: int = 190
    page: int = 210
    progress: int = 180
    success: int = 320


DURATION = Durations()


def palette(theme: str = "Dark") -> Colors:
    return LIGHT if theme == "Light" else DARK


def widget_colors(widget: QWidget) -> Colors:
    """Resolve the explicit root preference without global stylesheet side effects."""
    current: QWidget | None = widget
    while current is not None:
        theme = current.property("metastripTheme")
        if theme in {"Dark", "Light"}:
            return palette(theme)
        current = current.parentWidget()
    return LIGHT if widget.palette().window().color().lightness() > 160 else DARK
