#!/usr/bin/env python3
"""Persist an explicit user visual signoff for an automatic resume-PDF report."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Sequence

from _json_cli import CliFailure, JsonArgumentParser, atomic_create_json, emit, emit_failure, parse_json_cli
from pdf_pipeline import build_pdf_visual_signoff


SKILL_ROOT = Path(__file__).resolve().parents[1]


def _output_path(value: str) -> Path:
    path = Path(value)
    if path.suffix.lower() != ".json":
        raise CliFailure("INVALID_SIGNOFF_OUTPUT", "--output must name a .json signoff file.", 2)
    if path.exists() or path.is_symlink():
        raise CliFailure("SIGNOFF_OUTPUT_EXISTS", "Visual signoff output must be a new path and cannot overwrite an existing audit record: {0}".format(path), 2)
    parent = path.parent
    if parent.is_symlink():
        raise CliFailure("SYMLINK_OUTPUT_REFUSED", "Visual signoff output directory cannot be a symbolic link.", 2)
    if not parent.exists() or not parent.is_dir():
        raise CliFailure("OUTPUT_DIRECTORY_NOT_FOUND", "Create the visual signoff output directory first: {0}".format(parent), 2)
    resolved = path.resolve()
    try:
        resolved.relative_to(SKILL_ROOT.resolve())
        raise CliFailure("SKILL_PACKAGE_OUTPUT_REFUSED", "Visual signoff records must be written outside the Skill package.", 2)
    except ValueError:
        pass
    return resolved


def build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(
        description="Record explicit user visual review of a hash-bound automatic resume PDF validation report."
    )
    parser.add_argument("--validation-report", required=True, help="Automatic visual_signoff_pending validation JSON to sign.")
    parser.add_argument("--output", required=True, help="New user-output .json path for the hash-bound visual signoff record.")
    parser.add_argument(
        "--confirmed-by-user",
        action="store_true",
        help="Required acknowledgement that the user explicitly reviewed every retained color and grayscale preview.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    command = "record_pdf_visual_signoff"
    try:
        args = parse_json_cli(build_parser(), argv)
        if not args.confirmed_by_user:
            raise CliFailure(
                "USER_VISUAL_CONFIRMATION_REQUIRED",
                "Refusing to create a visual signoff without explicit --confirmed-by-user acknowledgement.",
                2,
            )
        output = _output_path(args.output)
        confirmed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        signoff, errors = build_pdf_visual_signoff(Path(args.validation_report), confirmed_at)
        if not signoff:
            raise CliFailure(
                "AUTOMATIC_VALIDATION_REPORT_NOT_SIGNABLE",
                "The automatic validation report is missing, malformed, stale, or not eligible for visual signoff.",
                1,
                {"errors": errors},
            )
        atomic_create_json(output, signoff)
        emit(
            {
                "ok": True,
                "command": command,
                "status": "recorded",
                "signoff_path": str(output),
                "signoff": signoff,
            }
        )
        return 0
    except CliFailure as failure:
        return emit_failure(failure, command)


if __name__ == "__main__":
    sys.exit(main())
