#!/usr/bin/env python3
"""Version and archive approved AI Resume Expert delivery artifacts locally."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from _json_cli import CliFailure, JsonArgumentParser, emit, emit_failure, load_json


DEFAULT_OUTPUT_DIR = Path("reports") / "ai-resume-expert"
ALLOWED_KINDS = {
    "markdown_draft",
    "diagnosis",
    "change_comparison",
    "evidence_trace",
    "project_selection",
    "jd_coverage",
    "interview_questions",
    "materials_inventory",
}
ALLOWED_SUFFIXES = {".md", ".json"}
FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _output_root(path: Path) -> Path:
    if path.is_symlink():
        raise CliFailure("SYMLINK_OUTPUT_REFUSED", "Output directory cannot be a symbolic link.", 2)
    skill_dir = Path(__file__).resolve().parents[1]
    if path.exists() and not path.is_dir():
        raise CliFailure("OUTPUT_DIRECTORY_NOT_FOUND", "Output path must be a directory: {0}".format(path), 2)
    resolved = path.resolve()
    try:
        resolved.relative_to(skill_dir.resolve())
    except ValueError:
        pass
    else:
        raise CliFailure("SKILL_PACKAGE_OUTPUT_REFUSED", "Artifacts must not be written into the Skill package.", 2)
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise CliFailure("OUTPUT_DIRECTORY_CREATE_FAILED", "Could not create output directory: {0}".format(exc), 2)
    if path.is_symlink():
        raise CliFailure("SYMLINK_OUTPUT_REFUSED", "Output directory cannot be a symbolic link.", 2)
    return path


def _version_directory(root: Path) -> Path:
    for number in range(1, 1000):
        candidate = root / "draft-{0:03d}".format(number)
        try:
            candidate.mkdir(mode=0o700)
            return candidate
        except FileExistsError:
            continue
        except OSError as exc:
            raise CliFailure("OUTPUT_DIRECTORY_CREATE_FAILED", "Could not create version directory: {0}".format(exc), 2)
    raise CliFailure("OUTPUT_VERSION_LIMIT", "Could not allocate a unique draft version directory.", 2)


def _validated_artifacts(document: Any) -> List[Dict[str, Any]]:
    if not isinstance(document, dict) or not isinstance(document.get("artifacts"), list):
        raise CliFailure("INVALID_MANIFEST", "Manifest must contain an artifacts array.", 2)
    entries: List[Dict[str, Any]] = []
    filenames = set()
    for index, raw in enumerate(document["artifacts"]):
        if not isinstance(raw, dict):
            raise CliFailure("INVALID_MANIFEST", "Artifact {0} must be an object.".format(index), 2)
        kind = raw.get("kind")
        filename = raw.get("filename")
        source_value = raw.get("source")
        if kind not in ALLOWED_KINDS:
            raise CliFailure("UNSUPPORTED_ARTIFACT_KIND", "Artifact {0} has an unsupported kind.".format(index), 2)
        if not isinstance(filename, str) or not FILENAME.fullmatch(filename) or Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
            raise CliFailure("UNSAFE_ARTIFACT_FILENAME", "Artifact {0} must use a safe .md or .json filename.".format(index), 2)
        if filename in filenames:
            raise CliFailure("DUPLICATE_ARTIFACT_FILENAME", "Manifest contains duplicate filename: {0}".format(filename), 2)
        if not isinstance(source_value, str) or not source_value:
            raise CliFailure("INVALID_MANIFEST", "Artifact {0} must provide a source file.".format(index), 2)
        source = Path(source_value)
        if source.is_symlink():
            raise CliFailure("SYMLINK_INPUT_REFUSED", "Artifact source cannot be a symbolic link: {0}".format(source), 2)
        if not source.is_file():
            raise CliFailure("ARTIFACT_SOURCE_NOT_FOUND", "Artifact source is not a readable file: {0}".format(source), 2)
        filenames.add(filename)
        entries.append({"kind": kind, "filename": filename, "source": source})
    if not entries:
        raise CliFailure("EMPTY_ARTIFACT_MANIFEST", "At least one formal delivery artifact is required.", 2)
    return entries


def _copy_artifacts(entries: List[Dict[str, Any]], destination: Path) -> Dict[str, Any]:
    artifacts: List[Dict[str, Any]] = []
    for entry in entries:
        target = destination / entry["filename"]
        try:
            shutil.copyfile(str(entry["source"]), str(target), follow_symlinks=False)
            os.chmod(target, 0o600)
        except OSError as exc:
            raise CliFailure("OUTPUT_WRITE_FAILED", "Could not archive artifact {0}: {1}".format(entry["filename"], exc), 2)
        artifacts.append(
            {
                "kind": entry["kind"],
                "path": str(target.resolve()),
                "sha256": sha256_file(target),
                "size_bytes": target.stat().st_size,
            }
        )
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
    }


def _write_manifest(destination: Path, payload: Dict[str, Any]) -> Path:
    target = destination / "artifact-manifest.json"
    temporary = destination / ".artifact-manifest.json.tmp"
    try:
        import json

        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(target))
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise CliFailure("OUTPUT_WRITE_FAILED", "Could not write artifact manifest: {0}".format(exc), 2)
    return target


def build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(description="Archive approved AI Resume Expert delivery artifacts in a versioned local directory.")
    parser.add_argument("--manifest", required=True, help="JSON manifest listing formal artifact source files, kinds, and filenames.")
    parser.add_argument("--authorized", action="store_true", help="Confirm the user authorized persistence of these formal delivery artifacts.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Artifact root; defaults to reports/ai-resume-expert in the current working directory.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if not args.authorized:
            raise CliFailure("PERSISTENCE_NOT_AUTHORIZED", "Explicit user authorization is required before archiving delivery artifacts.", 2)
        entries = _validated_artifacts(load_json(Path(args.manifest)))
        root = _output_root(Path(args.output_dir))
        destination = _version_directory(root)
        try:
            report = _copy_artifacts(entries, destination)
            manifest_path = _write_manifest(destination, report)
        except BaseException:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        emit({"ok": True, "command": "archive_resume_artifacts", "version_directory": str(destination.resolve()), "manifest": str(manifest_path.resolve()), "artifacts": report["artifacts"]})
        return 0
    except CliFailure as failure:
        return emit_failure(failure, "archive_resume_artifacts")


if __name__ == "__main__":
    raise SystemExit(main())
