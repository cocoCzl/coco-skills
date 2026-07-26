#!/usr/bin/env python3
"""Validate a locally generated resume PDF and emit machine-readable results."""

from __future__ import annotations

import re
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from _json_cli import CliFailure, JsonArgumentParser, atomic_write_json, emit, emit_failure, parse_json_cli
from pdf_pipeline import MAX_PDF_BYTES, apply_pdf_visual_signoff, sha256_file, validate_pdf_artifact


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("reports") / "ai-resume-expert"


def _input_pdf(path: Path) -> Path:
    if not path.exists():
        raise CliFailure("INPUT_NOT_FOUND", "PDF input does not exist: {0}".format(path), 2)
    if path.is_symlink():
        raise CliFailure("SYMLINK_INPUT_REFUSED", "PDF input cannot be a symbolic link.", 2)
    if not path.is_file():
        raise CliFailure("INPUT_NOT_FILE", "PDF input must be a regular file.", 2)
    try:
        size = path.stat().st_size
        if size > MAX_PDF_BYTES:
            raise CliFailure("INPUT_TOO_LARGE", "PDF input exceeds the 50 MiB validation limit.", 2)
        with path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise CliFailure("INVALID_PDF", "Input does not have a PDF file signature.", 2)
    except PermissionError:
        raise CliFailure("INPUT_NOT_READABLE", "PDF input is not readable.", 2)
    except OSError as exc:
        raise CliFailure("INPUT_READ_FAILED", "Could not inspect PDF input: {0}".format(exc), 2)
    return path


def _output_dir(path: Path) -> Path:
    if path.is_symlink():
        raise CliFailure("SYMLINK_OUTPUT_REFUSED", "Output directory cannot be a symbolic link.", 2)
    resolved = path.resolve()
    try:
        resolved.relative_to(SKILL_ROOT.resolve())
        raise CliFailure("SKILL_PACKAGE_OUTPUT_REFUSED", "PDF validation artifacts must not be written into the Skill package.", 2)
    except ValueError:
        pass
    if path.exists() and not path.is_dir():
        raise CliFailure("OUTPUT_DIRECTORY_NOT_FOUND", "Output path must be a directory: {0}".format(path), 2)
    if not path.exists():
        try:
            path.mkdir(mode=0o700, parents=True)
        except OSError as exc:
            raise CliFailure("OUTPUT_DIRECTORY_CREATE_FAILED", "Could not create output directory: {0}".format(exc), 2)
    if path.is_symlink():
        raise CliFailure("SYMLINK_OUTPUT_REFUSED", "Output directory cannot be a symbolic link.", 2)
    return path.resolve()


def _stem(requested: Optional[str], pdf_path: Path) -> str:
    value = requested or pdf_path.stem
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value):
        raise CliFailure("INVALID_ARTIFACT_NAME", "Artifact name must use 1-80 ASCII letters, digits, dot, underscore, or hyphen.", 2)
    return value


def _validate_executable_override(value: Optional[str], allowed: Sequence[str], option: str) -> None:
    if value and (value not in set(allowed) or os.path.sep in value or (os.path.altsep and os.path.altsep in value)):
        raise CliFailure(
            "UNSAFE_EXECUTABLE_OVERRIDE",
            "{0} only accepts a PATH-resolved command name (no directory) from: {1}.".format(option, ", ".join(allowed)),
            2,
        )


def _create_validation_directory(output_root: Path, stem: str, pdf_hash: str) -> Path:
    prefix = "{0}-{1}-validation".format(stem, pdf_hash[:12])
    for number in range(1, 1000):
        candidate = output_root / (prefix + "-{0:03d}".format(number))
        try:
            candidate.mkdir(mode=0o700)
            return candidate
        except FileExistsError:
            continue
        except OSError as exc:
            raise CliFailure("OUTPUT_DIRECTORY_CREATE_FAILED", "Could not create a versioned validation directory: {0}".format(exc), 2)
    raise CliFailure("OUTPUT_VERSION_LIMIT", "Could not allocate a unique validation directory.", 2)


def build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(description="Validate an A4, one-to-two-page, ATS-readable local resume PDF.")
    parser.add_argument("input", help="Path to a local resume PDF.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Validation artifact root; defaults to reports/ai-resume-expert in the current working directory.",
    )
    parser.add_argument(
        "--source-markdown",
        help="UTF-8 Markdown file snapshot required for automatic source-to-PDF qualification; visual signoff remains required before delivery qualification.",
    )
    parser.add_argument("--name", help="Stable artifact basename; defaults to the PDF filename.")
    parser.add_argument("--pdftotext", help="Optional PATH-resolved pdftotext command name.")
    parser.add_argument("--pdfinfo", help="Optional PATH-resolved pdfinfo command name.")
    parser.add_argument("--pdftoppm", help="Optional PATH-resolved pdftoppm command name.")
    parser.add_argument("--pdffonts", help="Optional PATH-resolved pdffonts command name.")
    parser.add_argument(
        "--visual-signoff",
        help="Optional hash-bound JSON produced by record_pdf_visual_signoff.py; only a valid current signoff can release the PDF.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    command = "validate_pdf"
    try:
        args = parse_json_cli(build_parser(), argv)
        _validate_executable_override(args.pdftotext, ("pdftotext",), "--pdftotext")
        _validate_executable_override(args.pdfinfo, ("pdfinfo",), "--pdfinfo")
        _validate_executable_override(args.pdftoppm, ("pdftoppm",), "--pdftoppm")
        _validate_executable_override(args.pdffonts, ("pdffonts",), "--pdffonts")
        pdf_path = _input_pdf(Path(args.input))
        output_root = _output_dir(Path(args.output_dir))
        stem = _stem(args.name, pdf_path)
        markdown: Optional[str] = None
        source_path: Optional[Path] = None
        if args.source_markdown:
            source = Path(args.source_markdown)
            if not source.exists() or not source.is_file() or source.is_symlink():
                raise CliFailure("MARKDOWN_SOURCE_NOT_READABLE", "Source Markdown must be a readable regular file.", 2)
            try:
                markdown = source.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise CliFailure("MARKDOWN_SOURCE_NOT_READABLE", "Could not read UTF-8 source Markdown: {0}".format(exc), 2)
            source_path = source.resolve()
        output_dir = _create_validation_directory(output_root, stem, sha256_file(pdf_path))
        report = validate_pdf_artifact(
            pdf_path,
            output_dir,
            stem,
            source_markdown=markdown,
            pdftotext_request=args.pdftotext,
            pdfinfo_request=args.pdfinfo,
            pdftoppm_request=args.pdftoppm,
            pdffonts_request=args.pdffonts,
            source_markdown_path=source_path,
        )
        if args.visual_signoff:
            report = apply_pdf_visual_signoff(report, Path(args.visual_signoff))
        report_path = output_dir / (stem + ".validation.json")
        report["output_root"] = str(output_root)
        report["version_directory"] = str(output_dir)
        atomic_write_json(report_path, report)
        report["report_path"] = str(report_path.resolve())
        emit(report)
        if report["qualified"] or report["status"] == "visual_signoff_pending":
            return 0
        if report["status"] == "capability_unavailable":
            return 3
        return 1
    except CliFailure as failure:
        return emit_failure(failure, command)


if __name__ == "__main__":
    sys.exit(main())
