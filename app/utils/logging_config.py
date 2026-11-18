"""Privacy-conscious diagnostics: log operational events, never metadata values."""

import logging


def configure_logging() -> None:
    """Configure console-only warnings without persisting users' filenames or metadata."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
