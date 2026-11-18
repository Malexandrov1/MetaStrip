"""Build an onedir Windows application without downloading external executables."""

import importlib.metadata
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if sys.platform != "win32":
        raise SystemExit("Build on Windows with Python 3.12+; cross-compilation is unsupported.")
    root = Path(__file__).resolve().parents[1]
    required = (
        "PyInstaller",
        "PySide6",
        "PySide6_Essentials",
        "PySide6_Addons",
        "shiboken6",
        "PyMuPDF",
        "Pillow",
    )
    missing = []
    for name in required:
        try:
            importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    if missing:
        raise SystemExit(
            "Missing build dependencies: "
            + ", ".join(missing)
            + '. Install with: python -m pip install -e ".[windows-build]"'
        )
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        "MetaStrip",
        "--paths",
        str(root),
        "--distpath",
        str(root / "dist"),
        "--workpath",
        str(root / "build"),
        "--specpath",
        str(root / "build"),
        "--collect-data",
        "pymupdf",
        "--hidden-import",
        "pymupdf",
        str(root / "app" / "main.py"),
    ]
    subprocess.run(command, cwd=root, check=True, shell=False)
    bundle = root / "dist" / "MetaStrip"
    notices = bundle / "licenses"
    notices.mkdir(exist_ok=True)
    for filename in ("LICENSE", "THIRD_PARTY_NOTICES.md", "README.md"):
        shutil.copy2(root / filename, bundle / filename)
    for name in (
        "PySide6",
        "PySide6_Essentials",
        "PySide6_Addons",
        "shiboken6",
        "PyMuPDF",
        "Pillow",
        "pyinstaller",
    ):
        distribution = importlib.metadata.distribution(name)
        for relative in distribution.files or ():
            if any(
                part.lower() in {"licenses", "license", "copying"} for part in relative.parts
            ) or relative.name.lower().startswith(("license", "copying", "notice")):
                source = Path(distribution.locate_file(relative))
                if source.is_file():
                    target = notices / name / Path(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    print(f"Built {bundle / 'MetaStrip.exe'}")
    print("External tools were not bundled. Complete docs/RELEASE_CHECKLIST.md before release.")
    print("Bundling PyMuPDF requires AGPL compliance or an appropriate commercial license.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
