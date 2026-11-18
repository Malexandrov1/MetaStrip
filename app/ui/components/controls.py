"""Native, accessible controls with restrained, interruptible painted feedback."""

from PySide6.QtCore import Property, QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QCheckBox, QProgressBar, QPushButton, QWidget

from app.ui.motion import animate_to, animation, reduced_motion, register_motion_callback
from app.ui.styles.tokens import (
    CHECKBOX_SIZE,
    CONTROL_HEIGHT,
    DURATION,
    FOCUS_WIDTH,
    ICON_SIZE,
    NAV_HEIGHT,
    RADIUS,
    widget_colors,
)

_BUTTON_INSET = 15
_BUTTON_ICON_GAP = 10
_BUTTON_FEEDBACK_WIDTH = 18


def mix(first: str | QColor, second: str | QColor, amount: float) -> QColor:
    a, b = QColor(first), QColor(second)
    amount = max(0.0, min(1.0, amount))
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * amount,
        a.greenF() + (b.greenF() - a.greenF()) * amount,
        a.blueF() + (b.blueF() - a.blueF()) * amount,
        a.alphaF() + (b.alphaF() - a.alphaF()) * amount,
    )


class AnimatedButton(QPushButton):
    """QPushButton semantics with a predictable shape and smooth surface feedback."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        feedback: bool = False,
    ) -> None:
        super().__init__(text, parent)
        self._reserve_feedback = feedback
        self._hover = 0.0
        self._press = 0.0
        self._selected = 0.0
        self._busy = False
        self._confirmation_text: str | None = None
        self._hover_animation = animation(self, b"hoverProgress", DURATION.hover)
        self._press_animation = animation(self, b"pressProgress", DURATION.press)
        self._selected_animation = animation(self, b"selectedProgress", DURATION.navigation)
        self._confirmation_timer = QTimer(self)
        self._confirmation_timer.setSingleShot(True)
        self._confirmation_timer.timeout.connect(self._restore_text)
        self.setMinimumHeight(CONTROL_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.pressed.connect(lambda: animate_to(self._press_animation, 1.0))
        self.released.connect(lambda: animate_to(self._press_animation, 0.0))
        self.toggled.connect(self._checked_changed)
        self.objectNameChanged.connect(lambda: self.updateGeometry())
        register_motion_callback(self._finish_motion)

    def _set_hover(self, value: float) -> None:
        self._hover = value
        self.update()

    def _set_press(self, value: float) -> None:
        self._press = value
        self.update()

    def _set_selected(self, value: float) -> None:
        self._selected = value
        self.update()

    hoverProgress = Property(float, lambda self: self._hover, _set_hover)
    pressProgress = Property(float, lambda self: self._press, _set_press)
    selectedProgress = Property(float, lambda self: self._selected, _set_selected)

    @Slot(bool)
    def _checked_changed(self, checked: bool) -> None:
        animate_to(self._selected_animation, float(checked), immediate=not self.isVisible())

    @Slot()
    def _finish_motion(self) -> None:
        if reduced_motion():
            animate_to(self._hover_animation, float(self.underMouse() and self.isEnabled()))
            animate_to(self._press_animation, float(self.isDown() and self.isEnabled()))
            animate_to(self._selected_animation, float(self.isChecked()))

    def enterEvent(self, event: QEvent) -> None:
        if self.isEnabled():
            animate_to(self._hover_animation, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        animate_to(self._hover_animation, 0.0)
        super().leaveEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            animate_to(self._hover_animation, 0.0, immediate=True)
            animate_to(self._press_animation, 0.0, immediate=True)
        super().changeEvent(event)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        height = NAV_HEIGHT if self.objectName() == "Nav" else CONTROL_HEIGHT
        width = QFontMetrics(self._text_font(), self).horizontalAdvance(self.text())
        width += 2 * (_BUTTON_INSET + 1)
        if not self.icon().isNull():
            width += ICON_SIZE + _BUTTON_ICON_GAP
        if self._reserve_feedback:
            width += _BUTTON_FEEDBACK_WIDTH + 4
        return QSize(max(hint.width(), width), height)

    def _text_font(self) -> QFont:
        font = self.font()
        font.setWeight(QFont.Weight.Medium if self.objectName() == "Nav" else QFont.Weight.DemiBold)
        return font

    def set_busy(self, busy: bool) -> None:
        """Expose a loading state while preserving text, geometry and enabled policy."""
        self._busy = bool(busy)
        if self._busy and self.property("confirmed"):
            self._confirmation_timer.stop()
            self._restore_text()
        self.setProperty("busy", self._busy)
        self.update()

    def confirm(self, text: str = "Saved") -> None:
        self._confirmation_timer.stop()
        if self._confirmation_text is None:
            self._confirmation_text = self.text()
        self.setProperty("confirmed", True)
        self.setAccessibleDescription(text)
        self.update()
        self._confirmation_timer.start(1100)

    @Slot()
    def _restore_text(self) -> None:
        self._confirmation_text = None
        self.setProperty("confirmed", False)
        self.setAccessibleDescription("")
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        colors = widget_colors(self)
        nav = self.objectName() == "Nav"
        primary = self.objectName() == "Primary"
        enabled = self.isEnabled()
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        base = colors.surface if nav else colors.raised
        if nav:
            background = mix(base, colors.selection, self._selected)
            background = mix(background, colors.hover, self._hover * (1 - self._selected) * 0.8)
        elif primary and enabled:
            background = mix(colors.accent, colors.accent_text, self._press * 0.12)
            background = mix(background, colors.text, self._hover * 0.08)
        else:
            background = mix(base, colors.hover, self._hover)
            background = mix(background, colors.border, self._press * 0.5)
        foreground = colors.accent_text if primary and enabled else colors.text
        if nav:
            foreground = mix(colors.muted, colors.text, self._selected)
        if not enabled:
            background = QColor(colors.surface)
            foreground = colors.disabled
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            border = background if nav or (primary and enabled) else QColor(colors.border)
            painter.setPen(QPen(border, 1))
            painter.setBrush(background)
            painter.drawRoundedRect(rect, RADIUS, RADIUS)
            if nav and self._selected > 0.001:
                indicator = QColor(colors.accent)
                indicator.setAlphaF(self._selected)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(indicator)
                painter.drawRoundedRect(QRectF(1, rect.center().y() - 7, 2, 14), 1, 1)
            if self.hasFocus() and enabled:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(colors.accent), FOCUS_WIDTH))
                painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), RADIUS - 1, RADIUS - 1)
            painter.setPen(QColor(foreground))
            font = self._text_font()
            painter.setFont(font)
            text_rect = rect.adjusted(_BUTTON_INSET, 0, -_BUTTON_INSET, 0)
            if not self.icon().isNull():
                icon_rect = QRectF(
                    text_rect.left(), rect.center().y() - ICON_SIZE / 2, ICON_SIZE, ICON_SIZE
                )
                mode = self.icon().Mode.Normal if enabled else self.icon().Mode.Disabled
                self.icon().paint(painter, icon_rect.toRect(), Qt.AlignmentFlag.AlignCenter, mode)
                text_rect.setLeft(text_rect.left() + ICON_SIZE + _BUTTON_ICON_GAP)
            if self._busy or self.property("confirmed"):
                mark = QRectF(text_rect.right() - 12, rect.center().y() - 5, 11, 10)
                painter.setPen(
                    QPen(
                        QColor(foreground),
                        1.7,
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin,
                    )
                )
                if self._busy:
                    for offset in (0, 5, 10):
                        painter.drawPoint(QPointF(mark.left() + offset, mark.center().y()))
                else:
                    painter.drawLine(
                        QPointF(mark.left(), mark.center().y()),
                        QPointF(mark.center().x(), mark.bottom()),
                    )
                    painter.drawLine(
                        QPointF(mark.center().x(), mark.bottom()), QPointF(mark.right(), mark.top())
                    )
                text_rect.adjust(0, 0, -_BUTTON_FEEDBACK_WIDTH, 0)
            alignment = Qt.AlignmentFlag.AlignVCenter | (
                Qt.AlignmentFlag.AlignLeft
                if nav or not self.icon().isNull()
                else Qt.AlignmentFlag.AlignHCenter
            )
            text = QFontMetrics(font, self).elidedText(
                self.text(), Qt.TextElideMode.ElideRight, int(text_rect.width())
            )
            painter.drawText(text_rect, alignment, text)


class AnimatedCheckBox(QCheckBox):
    """A real QCheckBox, with a drawn checkmark instead of stylesheet glyphs."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._checked = 0.0
        self._hover = 0.0
        self._check_animation = animation(self, b"checkedProgress", DURATION.checkbox)
        self._hover_animation = animation(self, b"hoverProgress", DURATION.hover)
        self.setMinimumHeight(CONTROL_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.checkStateChanged.connect(self._state_changed)
        register_motion_callback(self._finish_motion)

    def _set_checked(self, value: float) -> None:
        self._checked = value
        self.update()

    def _set_hover(self, value: float) -> None:
        self._hover = value
        self.update()

    checkedProgress = Property(float, lambda self: self._checked, _set_checked)
    hoverProgress = Property(float, lambda self: self._hover, _set_hover)

    @Slot(Qt.CheckState)
    def _state_changed(self, state: Qt.CheckState) -> None:
        animate_to(
            self._check_animation,
            float(state != Qt.CheckState.Unchecked),
            immediate=not self.isVisible(),
        )

    @Slot()
    def _finish_motion(self) -> None:
        if reduced_motion():
            self._check_animation.stop()
            self._hover_animation.stop()
            self._set_checked(float(self.checkState() != Qt.CheckState.Unchecked))
            self._set_hover(float(self.underMouse() and self.isEnabled()))

    def enterEvent(self, event: QEvent) -> None:
        if self.isEnabled():
            animate_to(self._hover_animation, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        animate_to(self._hover_animation, 0.0)
        super().leaveEvent(event)

    def hitButton(self, position: QPoint) -> bool:
        return self.rect().contains(position)

    def sizeHint(self) -> QSize:
        return QSize(
            self.fontMetrics().horizontalAdvance(self.text()) + CHECKBOX_SIZE + 16, CONTROL_HEIGHT
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        colors = widget_colors(self)
        enabled = self.isEnabled()
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            box = QRectF(2, (self.height() - CHECKBOX_SIZE) / 2, CHECKBOX_SIZE, CHECKBOX_SIZE)
            checked = self._checked
            background = mix(colors.surface, colors.accent, checked * (1.0 if enabled else 0.3))
            border = mix(colors.muted, colors.accent, max(checked, self._hover * 0.7))
            if not enabled:
                border = QColor(colors.border)
            painter.setPen(QPen(border, 1))
            painter.setBrush(background)
            painter.drawRoundedRect(box, 4, 4)
            if checked > 0.001:
                stroke = QColor(colors.accent_text if enabled else colors.muted)
                stroke.setAlphaF(checked)
                painter.setPen(
                    QPen(
                        stroke,
                        2,
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin,
                    )
                )
                path = QPainterPath()
                if self.checkState() == Qt.CheckState.PartiallyChecked:
                    path.moveTo(box.left() + 4, box.center().y())
                    path.lineTo(box.right() - 4, box.center().y())
                else:
                    path.moveTo(box.left() + 4, box.top() + 9)
                    path.lineTo(box.left() + 7.5, box.top() + 12.5)
                    path.lineTo(box.left() + 14, box.top() + 5.5)
                painter.drawPath(path)
            if self.hasFocus() and enabled:
                painter.setPen(QPen(QColor(colors.accent), FOCUS_WIDTH))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(box.adjusted(-2, -2, 2, 2), 5, 5)
            painter.setPen(QColor(colors.text if enabled else colors.disabled))
            painter.setFont(self.font())
            text_rect = QRectF(box.right() + 11, 0, self.width() - box.right() - 13, self.height())
            text = self.fontMetrics().elidedText(
                self.text(), Qt.TextElideMode.ElideRight, int(text_rect.width())
            )
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, text)


class AnimatedProgressBar(QProgressBar):
    """Smooth display interpolation; the native value remains the actual completed count."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._displayed = 0.0
        self._value_animation = animation(self, b"displayedValue", DURATION.progress)
        self.setFixedHeight(6)
        self.valueChanged.connect(self._value_changed)
        register_motion_callback(self._finish_motion)

    def _set_displayed(self, value: float) -> None:
        self._displayed = value
        self.update()

    displayedValue = Property(float, lambda self: self._displayed, _set_displayed)

    @Slot(int)
    def _value_changed(self, value: int) -> None:
        animate_to(self._value_animation, float(value), immediate=not self.isVisible())

    @Slot()
    def _finish_motion(self) -> None:
        if reduced_motion():
            animate_to(self._value_animation, float(self.value()))

    def setRange(self, minimum: int, maximum: int) -> None:
        self._value_animation.stop()
        super().setRange(minimum, maximum)
        self._displayed = float(max(minimum, self.value()))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        if self.minimum() == self.maximum():
            super().paintEvent(event)
            return
        colors = widget_colors(self)
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(self.rect())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors.raised))
            painter.drawRoundedRect(rect, 3, 3)
            width = self.maximum() - self.minimum()
            fraction = (self._displayed - self.minimum()) / width if width else 0
            filled = QRectF(rect)
            filled.setWidth(rect.width() * max(0.0, min(1.0, fraction)))
            painter.setBrush(QColor(colors.accent))
            painter.drawRoundedRect(filled, 3, 3)
