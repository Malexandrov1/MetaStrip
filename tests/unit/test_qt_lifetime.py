"""Regression checks for native paint crashes and deferred QObject destruction."""

import gc
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from weakref import ref

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from app.ui.components.controls import AnimatedCheckBox
from app.ui.motion import set_reduced_motion


@pytest.mark.gui
def test_motion_change_does_not_resurrect_a_deferred_deleted_python_receiver(qapp) -> None:
    parent = QWidget()
    checkbox = AnimatedCheckBox("History", parent)
    checkbox.setChecked(True)
    original_wrapper = ref(checkbox)
    checkbox.deleteLater()
    del checkbox
    gc.collect()
    set_reduced_motion(True)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    set_reduced_motion(False)
    assert original_wrapper() is None or not isValid(original_wrapper())
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.gui
def test_motion_change_skips_deleted_cpp_receiver_with_live_python_reference(qapp) -> None:
    checkbox = AnimatedCheckBox("Privacy")
    checkbox.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(checkbox)
    set_reduced_motion(True)
    set_reduced_motion(False)


@pytest.mark.gui
def test_motion_policy_rejects_worker_thread_widget_access(qapp) -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(set_reduced_motion, True)
        with pytest.raises(RuntimeError, match="GUI thread"):
            future.result(timeout=5)


def test_controls_paint_and_teardown_survive_in_a_separate_python_process() -> None:
    # Before the fix this sequence raised QFont TypeError and could terminate the
    # entire interpreter with 0xC0000005 / 0xC0000409. A child keeps pytest alive.
    program = r"""
import gc
import os
import faulthandler
faulthandler.enable()
if os.name == 'nt':
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0003 | 0x8000)
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget
from app.ui.components.controls import AnimatedButton, AnimatedCheckBox, AnimatedProgressBar
from app.ui.motion import AnimatedStackedWidget, set_reduced_motion
app = QApplication([])
for iteration in range(60):
    parent = QWidget()
    checkbox = AnimatedCheckBox('Privacy', parent)
    button = AnimatedButton('Clean files', parent)
    progress = AnimatedProgressBar(parent)
    button.move(0, 45)
    progress.move(0, 90)
    parent.resize(320, 120)
    parent.show()
    set_reduced_motion(False)
    checkbox.setChecked(True)
    progress.setRange(0, 10)
    progress.setValue(7)
    button.set_busy(True)
    app.processEvents()
    button.grab()
    button.set_busy(False)
    button.confirm('Complete')
    parent.grab()
    checkbox.deleteLater()
    del checkbox
    gc.collect()
    set_reduced_motion(True)
    parent.close()
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    del parent, button, progress
    gc.collect()
    set_reduced_motion(False)
    app.processEvents()
print('60 paint/deletion cycles passed')
"""
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", program],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "60 paint/deletion cycles passed" in result.stdout
    assert not result.stderr, result.stderr
