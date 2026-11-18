"""Native painted controls retain semantics, contrast and interruptible motion."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QFontMetrics

from app.ui.components.controls import AnimatedButton, AnimatedCheckBox, AnimatedProgressBar
from app.ui.components.icons import line_icon
from app.ui.motion import reduced_motion, set_reduced_motion
from app.ui.styles.tokens import palette


@pytest.fixture(autouse=True)
def motion_policy(qapp):
    original = reduced_motion()
    set_reduced_motion(True)
    if not QFontDatabase.families():
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
    yield
    set_reduced_motion(original)


@pytest.mark.gui
@pytest.mark.parametrize("theme", ["Dark", "Light"])
def test_checked_checkbox_renders_a_contrasting_painted_checkmark(qtbot, theme: str) -> None:
    widget = AnimatedCheckBox("Preserve color profiles")
    widget.setProperty("metastripTheme", theme)
    widget.resize(280, 36)
    qtbot.addWidget(widget)
    widget.show()
    widget.setChecked(True)
    widget.clearFocus()
    qtbot.wait(20)
    checked = widget.grab().toImage()
    colors = palette(theme)
    from PySide6.QtGui import QColor

    stroke = QColor(colors.accent_text)
    fill = QColor(colors.accent)

    def distance(first, second) -> int:
        return sum(abs(first.getRgb()[i] - second.getRgb()[i]) for i in range(3))

    # Interior of the indicator excludes borders, focus rings and all text.
    scale = checked.devicePixelRatio()
    pixels = [
        checked.pixelColor(x, y)
        for x in range(round(6 * scale), round(17 * scale))
        for y in range(round(12 * scale), round(24 * scale))
    ]
    assert sum(distance(pixel, stroke) < 60 for pixel in pixels) >= 8
    assert sum(distance(pixel, fill) < 60 for pixel in pixels) >= 20
    widget.setChecked(False)
    unchecked = widget.grab().toImage()
    assert checked != unchecked


@pytest.mark.gui
def test_checkbox_rapid_changes_and_reduced_motion_finish_in_correct_state(qtbot) -> None:
    widget = AnimatedCheckBox("History")
    qtbot.addWidget(widget)
    widget.show()
    set_reduced_motion(False)
    for state in (True, False, True, False, True):
        widget.setChecked(state)
        qtbot.wait(8)
    set_reduced_motion(True)
    assert widget.isChecked()
    assert widget.property("checkedProgress") == pytest.approx(1)
    widget.setChecked(False)
    assert widget.property("checkedProgress") == pytest.approx(0)


@pytest.mark.gui
def test_button_loading_confirmation_and_disabled_states_do_not_resize_or_activate(qtbot) -> None:
    widget = AnimatedButton("Clean files", feedback=True)
    widget.setObjectName("Primary")
    widget.setIcon(line_icon("copy"))
    qtbot.addWidget(widget)
    widget.resize(widget.sizeHint())
    widget.show()
    size = widget.size()
    # Paint reserves space on both edges, and for the icon and status mark.
    available = size.width() - 32 - 18 - 10 - 18
    assert QFontMetrics(widget._text_font(), widget).horizontalAdvance(widget.text()) <= available
    clicks = []
    widget.clicked.connect(lambda: clicks.append(True))
    widget.set_busy(True)
    widget.grab()
    assert widget.size() == size
    widget.set_busy(False)
    widget.confirm("Complete")
    widget.grab()
    assert widget.size() == size
    widget.set_busy(True)
    assert not widget.property("confirmed")
    widget.setEnabled(False)
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton)
    assert not clicks
    assert widget.property("pressProgress") == pytest.approx(0)


@pytest.mark.gui
def test_progress_keeps_the_true_completed_count_during_display_animation(qtbot) -> None:
    widget = AnimatedProgressBar()
    qtbot.addWidget(widget)
    widget.setRange(0, 10)
    widget.show()
    set_reduced_motion(False)
    widget.setValue(7)
    assert widget.value() == 7
    widget.setValue(2)
    assert widget.value() == 2
    set_reduced_motion(True)
    assert widget.property("displayedValue") == pytest.approx(2)
