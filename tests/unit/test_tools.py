"""Subprocesses enforce argument isolation, failure handling and time bounds."""

import sys
from threading import Event, Timer

import pytest

from app.core.models import CancelledError, MetaStripError
from app.core.tools import run_tool


def test_arguments_are_literal_not_shell_expressions() -> None:
    literal = "$(echo unsafe); & echo unsafe"
    result = run_tool([sys.executable, "-c", "import sys; print(sys.argv[1])", literal])
    assert result.decode().strip() == literal


def test_nonzero_tool_exit_raises_safe_error() -> None:
    with pytest.raises(MetaStripError):
        run_tool([sys.executable, "-c", "raise SystemExit(2)"])


def test_tool_timeout() -> None:
    with pytest.raises(MetaStripError, match="timeout"):
        run_tool([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.1)


def test_running_tool_can_be_cancelled() -> None:
    cancel = Event()
    timer = Timer(0.15, cancel.set)
    timer.start()
    try:
        with pytest.raises(CancelledError):
            run_tool([sys.executable, "-c", "import time; time.sleep(10)"], cancel, timeout=5)
    finally:
        timer.cancel()
