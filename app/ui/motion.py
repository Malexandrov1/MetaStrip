"""Interruptible native Qt transitions and an explicit reduced-motion policy."""

import os
from collections.abc import Callable
from functools import lru_cache
from weakref import WeakMethod

from PySide6.QtCore import (
    QCoreApplication,
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QThread,
    Slot,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget, QWidget
from shiboken6 import isValid

from app.ui.styles.tokens import DURATION

_listeners: set[WeakMethod] = set()
_override: bool | None = None


def require_gui_thread() -> None:
    app = QCoreApplication.instance()
    if app is not None and QThread.currentThread() != app.thread():
        raise RuntimeError("Motion and widget state must be changed on the GUI thread.")


def register_motion_callback(callback: Callable[[], None]) -> None:
    """Observe live Python wrappers without retaining or resurrecting Qt receivers.

    A native receiver can survive its Python wrapper until DeferredDelete runs.
    A process-global Qt signal may then dispatch to a re-created wrapper missing
    its Python initialization state. WeakMethod requires the original wrapper.
    """
    require_gui_thread()
    _listeners.add(WeakMethod(callback, _listeners.discard))


@lru_cache(maxsize=1)
def _system_reduced_motion() -> bool:
    if os.environ.get("METASTRIP_REDUCED_MOTION", "").lower() in {"1", "true", "yes"}:
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        enabled = wintypes.BOOL(True)
        try:
            api = ctypes.WinDLL("user32", use_last_error=True).SystemParametersInfoW
            api.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
            api.restype = wintypes.BOOL
            if api(0x1042, 0, ctypes.byref(enabled), 0):  # SPI_GETCLIENTAREAANIMATION
                return not bool(enabled.value)
        except OSError:
            pass
    return False


def reduced_motion() -> bool:
    return _system_reduced_motion() if _override is None else _override


def set_reduced_motion(value: bool) -> None:
    """Apply an explicit preference; running components finish their current state."""
    global _override
    require_gui_thread()
    _override = bool(value)
    for listener in tuple(_listeners):
        callback = listener()
        if callback is None or not isValid(callback.__self__):
            _listeners.discard(listener)
            continue
        callback()


def animation(target: QObject, property_name: bytes, duration: int) -> QPropertyAnimation:
    require_gui_thread()
    result = QPropertyAnimation(target, property_name, target)
    result.setDuration(duration)
    result.setEasingCurve(QEasingCurve.Type.OutCubic)
    return result


def animate_to(tween: QPropertyAnimation, value: float, *, immediate: bool = False) -> None:
    """Replace an obsolete transition from its current interpolated value."""
    require_gui_thread()
    tween.stop()
    target = tween.targetObject()
    if target is None or not isValid(target):
        return
    name = bytes(tween.propertyName()).decode()
    if immediate or reduced_motion():
        target.setProperty(name, value)
        return
    tween.setStartValue(target.property(name))
    tween.setEndValue(value)
    tween.start()


class AnimatedStackedWidget(QStackedWidget):
    """A brief incoming-page fade, with no snapshots or stale overlay widgets."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._effect: QGraphicsOpacityEffect | None = None
        self._page: QWidget | None = None
        self._transition = QPropertyAnimation(self)
        self._transition.setPropertyName(b"opacity")
        self._transition.setDuration(DURATION.page)
        self._transition.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._transition.finished.connect(self._finish_transition)
        register_motion_callback(self._motion_changed)

    @Slot()
    def _finish_transition(self) -> None:
        self._transition.stop()
        self._transition.setTargetObject(None)
        if self._page is not None and isValid(self._page):
            self._page.setGraphicsEffect(None)
        self._page = None
        self._effect = None

    @Slot()
    def _motion_changed(self) -> None:
        if reduced_motion():
            self._finish_transition()

    def setCurrentIndex(self, index: int) -> None:
        if index == self.currentIndex() or not 0 <= index < self.count():
            return
        self._finish_transition()
        super().setCurrentIndex(index)
        page = self.currentWidget()
        if page is None or not self.isVisible() or reduced_motion():
            return
        self._page = page
        self._effect = QGraphicsOpacityEffect(page)
        self._effect.setOpacity(0.72)
        page.setGraphicsEffect(self._effect)
        self._transition.setTargetObject(self._effect)
        self._transition.setStartValue(0.72)
        self._transition.setEndValue(1.0)
        self._transition.start()

    def setCurrentWidget(self, widget: QWidget) -> None:
        self.setCurrentIndex(self.indexOf(widget))
