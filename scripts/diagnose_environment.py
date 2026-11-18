"""Print dependency availability without network requests or secret-bearing settings."""

import importlib.metadata
import json
import os
import platform
import shutil
from urllib.parse import urlsplit


def main() -> int:
    packages: dict[str, str | None] = {}
    for name in ("PySide6", "PyMuPDF", "Pillow", "pytest", "pytest-qt", "ruff", "PyInstaller"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    proxies: dict[str, str] = {}
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        value = os.environ.get(name)
        if value:
            try:
                parsed = urlsplit(value)
                proxies[name] = f"{parsed.hostname}:{parsed.port}"
            except ValueError:
                proxies[name] = "Configured; invalid proxy URL"
    report = {
        "python": platform.python_version(),
        "platform": platform.system(),
        "packages": packages,
        "tools": {
            name: shutil.which(os.environ.get(f"METASTRIP_{name.upper()}") or name)
            for name in ("exiftool", "ffmpeg", "ffprobe")
        },
        "package_index_disabled": os.environ.get("PIP_NO_INDEX", "").lower()
        in {"1", "true", "yes", "on"},
        "proxy_hosts": proxies,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
