"""Discover trusted local tools and probe versions without downloads or a shell."""

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from app.core.models import CancelledError, MetaStripError

_APP_ROOT = Path(__file__).resolve().parents[2]
_TOOLS = ("exiftool", "ffmpeg", "ffprobe")
_GUIDANCE = {
    "exiftool": (
        "Independent metadata inspection and TIFF cleanup",
        "TIFF cleaning requires ExifTool; image inspection otherwise has limited coverage.",
        "https://exiftool.org/install.html",
    ),
    "ffmpeg": (
        "Lossless video remuxing and stream integrity checks",
        "MP4 and MOV cleaning requires FFmpeg and ffprobe.",
        "https://ffmpeg.org/download.html",
    ),
    "ffprobe": (
        "Container and stream metadata inspection",
        "MP4 and MOV inspection and cleaning requires ffprobe.",
        "https://ffmpeg.org/ffprobe.html",
    ),
}


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    path: str | None
    version: str | None
    status: str
    purpose: str
    features: str
    guidance_url: str
    error: str | None = None


def _resolve_tool(name: str) -> str | None:
    """Use absolute candidates so Windows never implicitly searches the CWD."""
    override = os.environ.get(f"METASTRIP_{name.upper()}")
    filename = name + (".exe" if os.name == "nt" else "")
    candidates: list[Path] = []
    if override:
        override_path = Path(override).expanduser()
        if override_path.is_absolute():
            candidates.append(override_path)
        elif override_path.name != override:
            return None
        else:
            filename = override
    else:
        candidates.extend(
            (
                _APP_ROOT / "tools" / filename,
                _APP_ROOT / "tools" / name / filename,
                _APP_ROOT / "tools" / name / "bin" / filename,
                _APP_ROOT / "tools" / "bin" / filename,
            )
        )
    if not (override and Path(override).expanduser().is_absolute()):
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            location = Path(directory.strip('"'))
            if directory and location.is_absolute():
                candidates.append(location / filename)
    for candidate in candidates:
        try:
            found = shutil.which(str(candidate))
            if found and (os.name != "nt" or Path(found).suffix.lower() == ".exe"):
                return str(Path(found).resolve())
        except (OSError, ValueError):
            continue
    return None


def check_dependencies() -> dict[str, str | None]:
    """Resolve tools without executing them; suitable for lightweight capability checks."""
    return {name: _resolve_tool(name) for name in _TOOLS}


def dependency_diagnostics(cancel: Event | None = None) -> tuple[DependencyStatus, ...]:
    """Probe versions locally; call from a background worker, never the GUI thread."""
    from app.core.tools import check_cancel, run_tool

    statuses = []
    for name, path in check_dependencies().items():
        check_cancel(cancel)
        purpose, features, url = _GUIDANCE[name]
        if path is None:
            statuses.append(DependencyStatus(name, None, None, "Missing", purpose, features, url))
            continue
        arguments = [path, "-config", "", "-ver"] if name == "exiftool" else [path, "-version"]
        try:
            output = run_tool(arguments, cancel, timeout=5).decode("utf-8", errors="replace")
            first_line = output.splitlines()[0].strip()[:256] if output.strip() else ""
            expected = (
                re.fullmatch(r"\d+\.\d+(?:_\d+)?", first_line)
                if name == "exiftool"
                else re.match(rf"{name} version \S+", first_line)
            )
            if not expected or any(ord(char) < 32 for char in first_line):
                raise MetaStripError("The local tool did not return a readable version.")
            statuses.append(
                DependencyStatus(
                    name,
                    path,
                    first_line,
                    "Installed",
                    purpose,
                    features,
                    url,
                )
            )
        except CancelledError:
            raise
        except (MetaStripError, OSError):
            statuses.append(
                DependencyStatus(
                    name,
                    path,
                    None,
                    "Unavailable",
                    purpose,
                    features,
                    url,
                    "The executable was found but its version probe failed or timed out.",
                )
            )
    return tuple(statuses)
