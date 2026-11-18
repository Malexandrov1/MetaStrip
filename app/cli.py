"""Offline command-line access for reproducible inspection and cleanup."""

import argparse
import json
import sys
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from threading import Event
from typing import Any

from app.core.models import MetaStripError, ProcessingOptions, VerificationState


def _json_default(value: Any) -> str:
    if isinstance(value, (Path, Enum)):
        return str(value)
    raise TypeError(f"Unsupported JSON type: {type(value).__name__}")


def main(argv: list[str] | None = None) -> int:
    """Run a command; nonzero status means a failed, unsupported or cancelled file."""
    parser = argparse.ArgumentParser(description="MetaStrip local metadata tools")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("diagnostics", help="Show local dependency availability")
    inspect = commands.add_parser("inspect", help="Print metadata locally as JSON")
    inspect.add_argument("files", type=Path, nargs="+")
    clean = commands.add_parser("clean", help="Create verified sanitized copies")
    clean.add_argument("files", type=Path, nargs="+")
    clean.add_argument("--output", type=Path, required=True)
    clean.add_argument("--suffix", default="_clean")
    clean.add_argument("--remove-color-profile", action="store_true")
    clean.add_argument("--remove-pdf-annotations", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "diagnostics":
        from app.utils.dependency_checker import check_dependencies

        print(json.dumps(check_dependencies(), indent=2, default=_json_default))
        return 0

    failed = False
    cancel = Event()
    try:
        if args.command == "inspect":
            from app.core.inspector import MetadataInspector

            inspector = MetadataInspector()
            for path in args.files:
                try:
                    print(json.dumps(asdict(inspector.inspect(path)), default=_json_default))
                except (MetaStripError, OSError) as exc:
                    print(json.dumps({"source": str(path), "error": str(exc)}))
                    failed = True
        else:
            from app.core.sanitizer import Sanitizer

            sanitizer = Sanitizer()
            options = ProcessingOptions(
                output_dir=args.output,
                suffix=args.suffix,
                preserve_color_profile=not args.remove_color_profile,
                remove_pdf_annotations=args.remove_pdf_annotations,
            )
            for path in args.files:
                result = sanitizer.process(path, options, cancel)
                print(json.dumps(asdict(result), default=_json_default))
                failed |= bool(result.error or result.cancelled) or result.verification.state in (
                    VerificationState.FAILED,
                    VerificationState.UNSUPPORTED,
                    VerificationState.NOT_VERIFIED,
                )
    except KeyboardInterrupt:
        cancel.set()
        print("Cancelled.", file=sys.stderr)
        return 130
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
