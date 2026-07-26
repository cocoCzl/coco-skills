#!/usr/bin/env python3
"""Small shared helpers for deterministic AI Resume Expert CLIs.

The scripts intentionally depend only on the Python standard library.  Every
machine-readable command prints exactly one JSON document to stdout; human
diagnostics go in that document instead of being mixed into the stream.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


class CliFailure(Exception):
    """An expected CLI failure with a stable error code and exit status."""

    def __init__(self, code: str, message: str, exit_code: int = 2, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.details = details or {}


class JsonArgumentParser(argparse.ArgumentParser):
    """Argument parser that turns usage failures into JSON-safe exceptions."""

    def error(self, message: str) -> None:
        raise CliFailure("INVALID_ARGUMENTS", message, 2)


def emit(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))


def emit_failure(failure: CliFailure, command: str) -> int:
    payload: Dict[str, Any] = {
        "ok": False,
        "command": command,
        "error": {
            "code": failure.code,
            "message": failure.message,
        },
    }
    if failure.details:
        payload["error"]["details"] = failure.details
    emit(payload)
    return failure.exit_code


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise CliFailure("INPUT_NOT_FOUND", "Input file does not exist: {0}".format(path), 2)
    except PermissionError:
        raise CliFailure("INPUT_NOT_READABLE", "Input file is not readable: {0}".format(path), 2)
    except json.JSONDecodeError as exc:
        raise CliFailure(
            "INVALID_JSON",
            "Input is not valid JSON at line {0}, column {1}.".format(exc.lineno, exc.colno),
            2,
        )
    except OSError as exc:
        raise CliFailure("INPUT_READ_FAILED", "Could not read input: {0}".format(exc), 2)


def inside_path(path: Path, directory: Path) -> bool:
    """Return whether ``path`` resolves inside ``directory`` on Python 3.9+."""

    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write a JSON file atomically without following a final-path symlink."""

    parent = path.parent
    if not parent.is_dir():
        raise CliFailure(
            "OUTPUT_DIRECTORY_NOT_FOUND",
            "Output directory does not exist; create it explicitly first: {0}".format(parent),
            2,
        )
    if path.is_symlink():
        raise CliFailure("SYMLINK_OUTPUT_REFUSED", "Refusing to write through a symbolic link: {0}".format(path), 2)
    temporary = parent / (".{0}.{1}.tmp".format(path.name, os.getpid()))
    if temporary.exists():
        raise CliFailure("TEMPORARY_PATH_EXISTS", "Temporary output path already exists: {0}".format(temporary), 2)
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    except CliFailure:
        raise
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise CliFailure("OUTPUT_WRITE_FAILED", "Could not write output: {0}".format(exc), 2)


def atomic_create_json(path: Path, payload: Dict[str, Any]) -> None:
    """Publish a new JSON record without replacing an existing destination.

    `os.replace` is intentionally unsuitable for audit acknowledgements: a
    second process can create the destination after a caller checks it and
    before replacement.  Write a private temporary file, then publish it with
    a hard link, whose destination creation is atomic and fails if occupied.
    """

    parent = path.parent
    if not parent.is_dir():
        raise CliFailure(
            "OUTPUT_DIRECTORY_NOT_FOUND",
            "Output directory does not exist; create it explicitly first: {0}".format(parent),
            2,
        )
    if path.exists() or path.is_symlink():
        raise CliFailure("SIGNOFF_OUTPUT_EXISTS", "Refusing to overwrite an existing audit record: {0}".format(path), 2)
    temporary = parent / (".{0}.{1}.{2}.tmp".format(path.name, os.getpid(), secrets.token_hex(8)))
    try:
        descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(str(temporary), str(path))
        except FileExistsError:
            raise CliFailure("SIGNOFF_OUTPUT_EXISTS", "Refusing to overwrite an existing audit record: {0}".format(path), 2)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    except CliFailure:
        raise
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise CliFailure("OUTPUT_WRITE_FAILED", "Could not create output: {0}".format(exc), 2)


def parse_json_cli(parser: JsonArgumentParser, argv: Optional[Sequence[str]]) -> argparse.Namespace:
    """Keep parsing as a named helper so every command has the same behavior."""

    return parser.parse_args(argv)
