#!/usr/bin/env python3
"""Shared, stdlib-only helpers for local PDF rendering and quality checks."""

from __future__ import annotations

import hashlib
import json
import os
import select
import re
import shutil
import struct
import subprocess
import tempfile
import time
import unicodedata
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from xml.etree import ElementTree


COMMAND_TIMEOUT_SECONDS = 90
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_SIGNOFF_JSON_BYTES = 2 * 1024 * 1024
URL_PATTERN = re.compile(r"(?:https?://|mailto:|tel:)[^\s<>()\]\"'|｜,，;；。]+", re.IGNORECASE)
CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$", re.IGNORECASE)
PDF_VISUAL_SIGNOFF_KIND = "pdf_visual_signoff"
PDF_VISUAL_SIGNOFF_SCHEMA_VERSION = "1.0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def resolve_command(requested: Optional[str], candidates: Sequence[str]) -> Optional[str]:
    """Resolve an explicit executable or the first available local candidate."""

    if requested:
        if Path(requested).name not in set(candidates):
            raise ValueError("executable override basename is not allowed")
        if os.path.sep in requested or (os.path.altsep and os.path.altsep in requested):
            raise ValueError("executable override paths are not allowed")
        return shutil.which(requested)
    for name in candidates:
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def run_local(command: Sequence[str], timeout: int = COMMAND_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
    """Run a resolved local command without invoking a shell."""

    return subprocess.run(
        list(command),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )


def run_local_pty(command: Sequence[str], timeout: int = COMMAND_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
    """Run a local command on a pseudo-terminal when the platform provides one.

    LibreOffice on macOS can abort during headless startup when both output
    streams are anonymous pipes.  A private PTY preserves a non-interactive,
    shell-free invocation while avoiding that platform-specific failure.
    Other platforms fall back to ordinary captured pipes.
    """

    try:
        import pty
    except ImportError:
        return run_local(command, timeout=timeout)
    pid, master = pty.fork()
    if pid == 0:
        try:
            os.execv(str(command[0]), list(command))
        except OSError:
            os._exit(127)
    output = bytearray()
    started = time.monotonic()
    status: Optional[int] = None
    try:
        while True:
            if time.monotonic() - started > timeout:
                os.kill(pid, 9)
                os.waitpid(pid, 0)
                raise subprocess.TimeoutExpired(list(command), timeout, output=bytes(output))
            readable, _writable, _exceptional = select.select([master], [], [], 0.15)
            if readable:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    chunk = b""
                if chunk:
                    output.extend(chunk)
            waited_pid, waited_status = os.waitpid(pid, os.WNOHANG)
            if waited_pid == pid:
                status = waited_status
                try:
                    while True:
                        chunk = os.read(master, 65536)
                        if not chunk:
                            break
                        output.extend(chunk)
                except OSError:
                    pass
                break
        if status is None:
            _waited_pid, status = os.waitpid(pid, 0)
        return subprocess.CompletedProcess(
            list(command),
            os.waitstatus_to_exitcode(status),
            stdout=output.decode("utf-8", errors="replace"),
            stderr="",
        )
    finally:
        os.close(master)


def normalize_url(value: str) -> str:
    return value.strip().rstrip(".,;:，。；：").replace("&amp;", "&")


def markdown_expectations(markdown: str) -> Dict[str, Any]:
    headings: List[str] = []
    for raw in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", raw)
        if not match:
            continue
        heading = re.sub(r"[*_`]+", "", match.group(1)).strip()
        if heading:
            headings.append(heading)
    links = [normalize_url(item) for item in re.findall(r"\[[^\]]+\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)", markdown)]
    links.extend(normalize_url(item) for item in URL_PATTERN.findall(markdown))
    explicit_targets = set(links)
    for address in re.findall(r"(?<![\w@./+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![\w@.-])", markdown):
        if not any(address in target for target in explicit_targets):
            links.append("mailto:" + address)
    return {
        "headings": headings,
        "links": sorted(set(links)),
        "visible_blocks": markdown_visible_blocks(markdown),
    }


def _visible_inline(value: str) -> str:
    value = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = URL_PATTERN.sub(lambda match: re.sub(r"^https?://", "", normalize_url(match.group(0)), flags=re.IGNORECASE).rstrip("/"), value)
    value = re.sub(r"(`+)(.*?)\1", r"\2", value)
    value = value.replace("**", "").replace("__", "")
    value = re.sub(r"(?<!\\)[*_]", "", value)
    return value.strip()


def _normalized_visible(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", html_unescape(value)).lower()
    return "".join(character for character in normalized if character.isalnum() or CJK_PATTERN.match(character))


def html_unescape(value: str) -> str:
    # Avoid importing an HTML parser for a tiny, deterministic normalization.
    return value.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")


def markdown_visible_blocks(markdown: str) -> List[Dict[str, Any]]:
    """Return every user-visible Markdown block for source-to-PDF comparison."""

    blocks: List[Dict[str, Any]] = []
    paragraph: List[str] = []

    def flush() -> None:
        nonlocal paragraph
        if paragraph:
            visible = _visible_inline(" ".join(paragraph))
            normalized = _normalized_visible(visible)
            if normalized:
                blocks.append({"text": visible, "normalized": normalized})
        paragraph = []

    for raw in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            flush()
            continue
        if re.fullmatch(r"([-*_])(?:\s*\1){2,}", line):
            flush()
            continue
        heading = re.match(r"^#{1,6}\s+(.+?)\s*#*$", line)
        item = re.match(r"^(?:[-+*]|\d+[.)])\s+(.+)$", line)
        if heading or item:
            flush()
            visible = _visible_inline((heading or item).group(1))
            normalized = _normalized_visible(visible)
            if normalized:
                blocks.append({"text": visible, "normalized": normalized})
            continue
        paragraph.append(line.rstrip("\\").rstrip())
    flush()
    return blocks


def _issue(code: str, message: str, **details: Any) -> Dict[str, Any]:
    item: Dict[str, Any] = {"code": code, "message": message}
    if details:
        item["details"] = details
    return item


def _check(check_id: str, status: str, message: str, **details: Any) -> Dict[str, Any]:
    item: Dict[str, Any] = {"id": check_id, "status": status, "message": message}
    if details:
        item["details"] = details
    return item


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_PATTERN.fullmatch(value))


def _path_metadata(path: Path, label: str, errors: List[Dict[str, Any]], require_absolute: bool = True) -> Optional[Dict[str, Any]]:
    """Return a hash-bound regular-file record without following symlinks.

    Signoff files are an audit trail.  Treating a symlink as an input would let
    an apparently reviewed path silently resolve to a later replacement, so
    every persisted resource is required to be a regular, absolute file.
    """

    if require_absolute and not path.is_absolute():
        errors.append(_issue("SIGNOFF_RESOURCE_PATH_NOT_ABSOLUTE", "{0} path must be absolute.".format(label), path=str(path)))
        return None
    try:
        if path.is_symlink():
            errors.append(_issue("SIGNOFF_RESOURCE_SYMLINK_REFUSED", "{0} cannot be a symbolic link.".format(label), path=str(path)))
            return None
        if not path.exists():
            errors.append(_issue("SIGNOFF_RESOURCE_NOT_FOUND", "{0} does not exist.".format(label), path=str(path)))
            return None
        if not path.is_file():
            errors.append(_issue("SIGNOFF_RESOURCE_NOT_FILE", "{0} must be a regular file.".format(label), path=str(path)))
            return None
        stat = path.stat()
        return {
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "size_bytes": stat.st_size,
        }
    except OSError as exc:
        errors.append(_issue("SIGNOFF_RESOURCE_READ_FAILED", "Could not inspect {0}.".format(label), path=str(path), reason=str(exc)))
        return None


def _record_metadata(record: Any, label: str, errors: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Validate a persisted {path, sha256, size_bytes} resource record."""

    if not isinstance(record, dict):
        errors.append(_issue("SIGNOFF_RESOURCE_RECORD_INVALID", "{0} resource metadata must be an object.".format(label)))
        return None
    expected_keys = {"path", "sha256", "size_bytes"}
    if set(record) != expected_keys:
        errors.append(
            _issue(
                "SIGNOFF_RESOURCE_RECORD_INVALID",
                "{0} resource metadata must contain exactly path, sha256, and size_bytes.".format(label),
            )
        )
        return None
    raw_path = record.get("path")
    expected_hash = record.get("sha256")
    expected_size = record.get("size_bytes")
    if not isinstance(raw_path, str) or not raw_path.strip() or not _valid_sha256(expected_hash) or not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
        errors.append(_issue("SIGNOFF_RESOURCE_RECORD_INVALID", "{0} resource metadata has an invalid path, SHA-256, or size.".format(label)))
        return None
    actual = _path_metadata(Path(raw_path), label, errors)
    if not actual:
        return None
    if actual["sha256"].lower() != expected_hash.lower() or actual["size_bytes"] != expected_size:
        errors.append(
            _issue(
                "SIGNOFF_RESOURCE_HASH_MISMATCH",
                "{0} no longer matches its recorded SHA-256 or size.".format(label),
                path=actual["path"],
                expected_sha256=expected_hash.lower(),
                actual_sha256=actual["sha256"],
                expected_size=expected_size,
                actual_size=actual["size_bytes"],
            )
        )
        return None
    return actual


def _resource_records_equal(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    return (
        left.get("path") == right.get("path")
        and str(left.get("sha256", "")).lower() == str(right.get("sha256", "")).lower()
        and left.get("size_bytes") == right.get("size_bytes")
    )


def _read_json_file(path: Path, label: str, errors: List[Dict[str, Any]], require_absolute: bool = False) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Read a small regular JSON file and return its durable metadata."""

    metadata = _path_metadata(path, label, errors, require_absolute=require_absolute)
    if not metadata:
        return None, None
    if metadata["size_bytes"] > MAX_SIGNOFF_JSON_BYTES:
        errors.append(
            _issue(
                "SIGNOFF_JSON_TOO_LARGE",
                "{0} exceeds the {1} byte audit-file limit.".format(label, MAX_SIGNOFF_JSON_BYTES),
                path=metadata["path"],
            )
        )
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        errors.append(_issue("SIGNOFF_JSON_NOT_UTF8", "{0} must be UTF-8 JSON.".format(label), path=metadata["path"]))
        return None, None
    except json.JSONDecodeError as exc:
        errors.append(
            _issue(
                "SIGNOFF_JSON_INVALID",
                "{0} is not valid JSON.".format(label),
                path=metadata["path"],
                line=exc.lineno,
                column=exc.colno,
            )
        )
        return None, None
    except OSError as exc:
        errors.append(_issue("SIGNOFF_RESOURCE_READ_FAILED", "Could not read {0}.".format(label), path=metadata["path"], reason=str(exc)))
        return None, None
    if not isinstance(payload, dict):
        errors.append(_issue("SIGNOFF_JSON_ROOT_INVALID", "{0} must contain a JSON object.".format(label), path=metadata["path"]))
        return None, None
    # A file can be replaced after the initial hash/read.  Detect that race
    # before using it as an audit input.
    current = _path_metadata(Path(metadata["path"]), label, errors)
    if not current or not _resource_records_equal(metadata, current):
        if current:
            errors.append(_issue("SIGNOFF_RESOURCE_CHANGED_DURING_READ", "{0} changed while it was being read.".format(label), path=metadata["path"]))
        return None, None
    return payload, metadata


def _source_markdown_metadata(source_markdown: Optional[str], source_markdown_path: Optional[Path]) -> Dict[str, Any]:
    """Describe the exact Markdown source without storing its private text."""

    if source_markdown is None:
        return {
            "supplied": False,
            "path": None,
            "sha256": None,
            "size_bytes": None,
            "checked_content_sha256": None,
            "file_bound": False,
            "snapshot_matches_checked_content": False,
        }
    content_bytes = source_markdown.encode("utf-8")
    content_hash = hashlib.sha256(content_bytes).hexdigest()
    metadata: Dict[str, Any] = {
        "supplied": True,
        "path": None,
        "sha256": content_hash,
        "size_bytes": len(content_bytes),
        "checked_content_sha256": content_hash,
        "file_bound": False,
        "snapshot_matches_checked_content": False,
    }
    if not source_markdown_path:
        return metadata
    errors: List[Dict[str, Any]] = []
    file_metadata = _path_metadata(source_markdown_path.resolve(), "source Markdown", errors)
    if file_metadata:
        metadata.update(file_metadata)
        metadata["snapshot_matches_checked_content"] = file_metadata["sha256"] == content_hash and file_metadata["size_bytes"] == len(content_bytes)
        metadata["file_bound"] = bool(metadata["snapshot_matches_checked_content"])
    return metadata


def _report_resource_binding(report: Dict[str, Any], errors: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract and verify all durable resources from an automatic report."""

    source = report.get("source")
    source_markdown = report.get("source_markdown")
    hashes = report.get("artifact_hashes")
    artifacts = report.get("artifacts")
    if not isinstance(source, dict) or not isinstance(source_markdown, dict) or not isinstance(hashes, dict) or not isinstance(artifacts, dict):
        errors.append(_issue("AUTOMATIC_VALIDATION_REPORT_INVALID", "The automatic validation report is missing durable source or artifact metadata."))
        return None
    pdf = _record_metadata(hashes.get("pdf"), "automatic-report PDF", errors)
    markdown = _record_metadata(hashes.get("markdown"), "automatic-report Markdown", errors)
    if not pdf or not markdown:
        return None
    if source.get("path") != pdf["path"] or str(source.get("sha256", "")).lower() != pdf["sha256"]:
        errors.append(_issue("AUTOMATIC_VALIDATION_REPORT_INCONSISTENT", "The report PDF source metadata does not match its artifact hash."))
    if (
        source_markdown.get("supplied") is not True
        or source_markdown.get("file_bound") is not True
        or source_markdown.get("path") != markdown["path"]
        or str(source_markdown.get("sha256", "")).lower() != markdown["sha256"]
    ):
        errors.append(_issue("AUTOMATIC_VALIDATION_REPORT_INCONSISTENT", "The report Markdown source metadata does not match its artifact hash."))

    previews: List[Dict[str, Any]] = []
    for key, kind in (("page_pngs", "color_page"), ("grayscale_pngs", "grayscale_page")):
        hash_records = hashes.get(key)
        artifact_paths = artifacts.get(key)
        if not isinstance(hash_records, list) or not hash_records or not isinstance(artifact_paths, list) or not artifact_paths:
            errors.append(_issue("AUTOMATIC_VALIDATION_PREVIEWS_MISSING", "The automatic validation report must retain {0}.".format(key)))
            continue
        verified = [_record_metadata(record, "automatic-report {0}".format(kind), errors) for record in hash_records]
        verified = [record for record in verified if record]
        if len(verified) != len(hash_records):
            continue
        reported_paths = [str(item) for item in artifact_paths]
        verified_paths = [item["path"] for item in verified]
        if reported_paths != verified_paths:
            errors.append(_issue("AUTOMATIC_VALIDATION_REPORT_INCONSISTENT", "The report preview paths do not match their hash records.", preview_kind=kind))
            continue
        previews.extend({"kind": kind, "page_index": index, **record} for index, record in enumerate(verified, start=1))
    if errors:
        return None
    return {"pdf": pdf, "markdown": markdown, "preview_resources": previews}


def _automatic_report_pending_invariant(report: Any) -> bool:
    """Return whether a report is an unsigned, delivery-blocked automatic result."""

    if not isinstance(report, dict):
        return False
    scope = report.get("qualification_scope")
    return bool(
        report.get("kind") == "pdf_validation"
        and report.get("schema_version") == "1.0"
        and report.get("automatic_qualified") is True
        and report.get("status") == "visual_signoff_pending"
        and report.get("qualified") is False
        and report.get("delivery_blocked") is True
        and report.get("visual_signoff_pending") is True
        and isinstance(scope, dict)
        and scope.get("automatic_checks_passed") is True
        and scope.get("source_to_pdf_integrity_checked") is True
    )


def _automatic_report_binding(validation_report_path: Path, expected_sha256: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Validate an unsigned automatic report before it can be signed or reused."""

    errors: List[Dict[str, Any]] = []
    report, metadata = _read_json_file(validation_report_path, "automatic validation report", errors)
    if report is None or metadata is None:
        return None, errors
    if expected_sha256 and metadata["sha256"].lower() != expected_sha256.lower():
        errors.append(
            _issue(
                "AUTOMATIC_VALIDATION_REPORT_HASH_MISMATCH",
                "The automatic validation report no longer matches the signed report hash.",
                expected_sha256=expected_sha256.lower(),
                actual_sha256=metadata["sha256"],
            )
        )
    if not _automatic_report_pending_invariant(report):
        errors.append(
            _issue(
                "AUTOMATIC_VALIDATION_REPORT_NOT_SIGNABLE",
                "The report is not an automatic-qualified, unsigned visual-signoff-pending validation result.",
            )
        )
    resources = _report_resource_binding(report, errors)
    if errors or not resources:
        return None, errors
    return {"report": metadata, **resources}, errors


def build_pdf_visual_signoff(validation_report_path: Path, confirmed_at: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Create hash-bound content for a user-confirmed visual signoff file."""

    binding, errors = _automatic_report_binding(validation_report_path)
    if errors or not binding:
        return None, errors
    return (
        {
            "schema_version": PDF_VISUAL_SIGNOFF_SCHEMA_VERSION,
            "kind": PDF_VISUAL_SIGNOFF_KIND,
            "confirmed_by_user": True,
            "confirmed_at": confirmed_at,
            "automatic_validation_report": binding["report"],
            "pdf": binding["pdf"],
            "markdown": binding["markdown"],
            "preview_resources": binding["preview_resources"],
        },
        [],
    )


def _valid_confirmed_at(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _signoff_resource_record(record: Any, label: str, errors: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Validate signoff resource syntax before comparing it to a trusted report."""

    if not isinstance(record, dict) or set(record) != {"path", "sha256", "size_bytes"}:
        errors.append(_issue("PDF_VISUAL_SIGNOFF_INVALID", "{0} must contain exactly path, sha256, and size_bytes.".format(label)))
        return None
    if (
        not isinstance(record.get("path"), str)
        or not Path(record["path"]).is_absolute()
        or not _valid_sha256(record.get("sha256"))
        or not isinstance(record.get("size_bytes"), int)
        or isinstance(record.get("size_bytes"), bool)
        or record["size_bytes"] < 0
    ):
        errors.append(_issue("PDF_VISUAL_SIGNOFF_INVALID", "{0} has an invalid path, SHA-256, or size.".format(label)))
        return None
    # Do not resolve here: resolving a symlink before the durable-record
    # verifier sees it would turn a forbidden indirection into an accepted
    # target path.
    return {"path": str(Path(record["path"])), "sha256": record["sha256"].lower(), "size_bytes": record["size_bytes"]}


def _signoff_payload(path: Path) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    errors: List[Dict[str, Any]] = []
    payload, _metadata = _read_json_file(path, "visual signoff", errors)
    if payload is None:
        return None, errors
    required = {
        "schema_version",
        "kind",
        "confirmed_by_user",
        "confirmed_at",
        "automatic_validation_report",
        "pdf",
        "markdown",
        "preview_resources",
    }
    if set(payload) != required:
        errors.append(_issue("PDF_VISUAL_SIGNOFF_INVALID", "Visual signoff fields do not match the supported schema."))
        return None, errors
    if (
        payload.get("schema_version") != PDF_VISUAL_SIGNOFF_SCHEMA_VERSION
        or payload.get("kind") != PDF_VISUAL_SIGNOFF_KIND
        or payload.get("confirmed_by_user") is not True
        or not _valid_confirmed_at(payload.get("confirmed_at"))
    ):
        errors.append(_issue("PDF_VISUAL_SIGNOFF_INVALID", "Visual signoff identity, user confirmation, or confirmation time is invalid."))
    report = _signoff_resource_record(payload.get("automatic_validation_report"), "automatic validation report", errors)
    pdf = _signoff_resource_record(payload.get("pdf"), "PDF", errors)
    markdown = _signoff_resource_record(payload.get("markdown"), "Markdown", errors)
    raw_previews = payload.get("preview_resources")
    previews: List[Dict[str, Any]] = []
    if not isinstance(raw_previews, list) or not raw_previews:
        errors.append(_issue("PDF_VISUAL_SIGNOFF_INVALID", "Visual signoff must retain reviewed color and grayscale preview resources."))
    else:
        seen: set[Tuple[str, int]] = set()
        kinds: set[str] = set()
        for item in raw_previews:
            if (
                not isinstance(item, dict)
                or set(item) != {"kind", "page_index", "path", "sha256", "size_bytes"}
                or item.get("kind") not in {"color_page", "grayscale_page"}
                or not isinstance(item.get("page_index"), int)
                or isinstance(item.get("page_index"), bool)
                or item["page_index"] < 1
            ):
                errors.append(_issue("PDF_VISUAL_SIGNOFF_INVALID", "A visual signoff preview resource has an unsupported shape."))
                continue
            resource = _signoff_resource_record({key: item[key] for key in ("path", "sha256", "size_bytes")}, "preview resource", errors)
            if not resource:
                continue
            identity = (str(item["kind"]), int(item["page_index"]))
            if identity in seen:
                errors.append(_issue("PDF_VISUAL_SIGNOFF_INVALID", "Visual signoff preview resources cannot be duplicated.", kind=item["kind"], page_index=item["page_index"]))
                continue
            seen.add(identity)
            kinds.add(str(item["kind"]))
            previews.append({"kind": item["kind"], "page_index": item["page_index"], **resource})
        if kinds != {"color_page", "grayscale_page"}:
            errors.append(_issue("PDF_VISUAL_SIGNOFF_INVALID", "Visual signoff must include both color and grayscale preview resources."))
    if errors or not report or not pdf or not markdown:
        return None, errors
    return {"payload": payload, "report": report, "pdf": pdf, "markdown": markdown, "preview_resources": previews}, errors


def _same_preview_resources(left: List[Dict[str, Any]], right: List[Dict[str, Any]]) -> bool:
    def sort_key(item: Dict[str, Any]) -> Tuple[str, int, str, str, int]:
        return (
            str(item.get("kind")),
            int(item.get("page_index", -1)),
            str(item.get("path")),
            str(item.get("sha256", "")).lower(),
            int(item.get("size_bytes", -1)),
        )

    return sorted(left, key=sort_key) == sorted(right, key=sort_key)


def _same_preview_content(left: List[Dict[str, Any]], right: List[Dict[str, Any]]) -> bool:
    """Compare regenerated previews without requiring their versioned paths.

    A fresh `validate_pdf` run intentionally writes previews to a new output
    directory.  Their path can therefore differ while their page kind, bytes,
    and size must still match the reviewed preview set.
    """

    def sort_key(item: Dict[str, Any]) -> Tuple[str, int, str, int]:
        return (
            str(item.get("kind")),
            int(item.get("page_index", -1)),
            str(item.get("sha256", "")).lower(),
            int(item.get("size_bytes", -1)),
        )

    return sorted((sort_key(item) for item in left)) == sorted((sort_key(item) for item in right))


def evaluate_pdf_visual_signoff(automatic_report: Dict[str, Any], signoff_path: Optional[Path]) -> Dict[str, Any]:
    """Check a user signoff against an automatic result and the current files.

    A signoff proves only that a user explicitly reviewed the retained preview
    resources.  It is deliberately content-bound: changing any signed PDF or
    Markdown byte, preview file, or automatic report revokes qualification.
    """

    automatic_qualified = automatic_report.get("automatic_qualified") is True
    if not automatic_qualified:
        return {
            "required": True,
            "provided": signoff_path is not None,
            "status": "not_eligible",
            "valid": False,
            "errors": [],
        }
    if not _automatic_report_pending_invariant(automatic_report):
        return {
            "required": True,
            "provided": signoff_path is not None,
            "status": "invalid",
            "valid": False,
            "errors": [
                _issue(
                    "CURRENT_AUTOMATIC_VALIDATION_REPORT_NOT_SIGNABLE",
                    "Current automatic validation metadata is not an unsigned, delivery-blocked visual-signoff-pending result.",
                )
            ],
        }
    if signoff_path is None:
        return {
            "required": True,
            "provided": False,
            "status": "pending",
            "valid": False,
            "errors": [],
            "next_action": "Open every retained color and grayscale preview, obtain explicit user confirmation, then record a hash-bound visual signoff.",
        }

    signoff, errors = _signoff_payload(signoff_path)
    if not signoff:
        return {"required": True, "provided": True, "status": "invalid", "valid": False, "errors": errors}
    report_binding, report_errors = _automatic_report_binding(
        Path(signoff["report"]["path"]),
        expected_sha256=signoff["report"]["sha256"],
    )
    errors.extend(report_errors)
    current_errors: List[Dict[str, Any]] = []
    current_resources = _report_resource_binding(automatic_report, current_errors)
    errors.extend(current_errors)
    if report_binding and not _resource_records_equal(signoff["report"], report_binding["report"]):
        errors.append(_issue("PDF_VISUAL_SIGNOFF_REPORT_BINDING_MISMATCH", "Visual signoff does not bind the automatic validation report it references."))
    if report_binding:
        for label in ("pdf", "markdown"):
            if not _resource_records_equal(signoff[label], report_binding[label]):
                errors.append(_issue("PDF_VISUAL_SIGNOFF_REPORT_BINDING_MISMATCH", "Visual signoff {0} does not match the signed automatic report.".format(label)))
        if not _same_preview_resources(signoff["preview_resources"], report_binding["preview_resources"]):
            errors.append(_issue("PDF_VISUAL_SIGNOFF_REPORT_BINDING_MISMATCH", "Visual signoff preview resources do not match the signed automatic report."))
    if current_resources:
        for label in ("pdf", "markdown"):
            if (
                signoff[label].get("sha256", "").lower() != current_resources[label].get("sha256", "").lower()
                or signoff[label].get("size_bytes") != current_resources[label].get("size_bytes")
            ):
                errors.append(
                    _issue(
                        "PDF_VISUAL_SIGNOFF_CURRENT_ARTIFACT_MISMATCH",
                        "Current {0} content no longer matches the user-reviewed signoff.".format(label),
                        signed_sha256=signoff[label].get("sha256"),
                        current_sha256=current_resources[label].get("sha256"),
                        signed_size=signoff[label].get("size_bytes"),
                        current_size=current_resources[label].get("size_bytes"),
                    )
                )
        if not _same_preview_content(signoff["preview_resources"], current_resources["preview_resources"]):
            errors.append(
                _issue(
                    "PDF_VISUAL_SIGNOFF_CURRENT_PREVIEW_MISMATCH",
                    "Current rendered preview bytes no longer match the user-reviewed signoff previews.",
                )
            )
    if errors:
        return {"required": True, "provided": True, "status": "invalid", "valid": False, "errors": errors}
    return {
        "required": True,
        "provided": True,
        "status": "valid",
        "valid": True,
        "errors": [],
        "signoff_path": str(signoff_path.resolve()),
        "confirmed_at": signoff["payload"]["confirmed_at"],
    }


def apply_pdf_visual_signoff(automatic_report: Dict[str, Any], signoff_path: Optional[Path]) -> Dict[str, Any]:
    """Apply visual-signoff state without changing automatic-check results."""

    state = evaluate_pdf_visual_signoff(automatic_report, signoff_path)
    automatic_qualified = automatic_report.get("automatic_qualified") is True
    automatic_report["visual_signoff"] = state
    automatic_report["visual_signoff_pending"] = automatic_qualified and state["status"] == "pending"
    scope = automatic_report.get("qualification_scope")
    if isinstance(scope, dict):
        scope["human_visual_signoff_required"] = True
        scope["human_visual_signoff_valid"] = state["valid"]
    if state["valid"]:
        automatic_report.update(
            {
                "ok": True,
                "status": "qualified",
                "qualified": True,
                "delivery_blocked": False,
                "next_action": "The current PDF, Markdown, and reviewed previews match the explicit user visual signoff; the PDF may be delivered.",
            }
        )
        return automatic_report
    automatic_report["qualified"] = False
    automatic_report["delivery_blocked"] = True
    if automatic_qualified and state["status"] == "pending":
        automatic_report.update(
            {
                "ok": True,
                "status": "visual_signoff_pending",
                "next_action": state["next_action"],
            }
        )
    elif automatic_qualified:
        automatic_report["ok"] = False
        automatic_report["status"] = "visual_signoff_invalid"
        automatic_report["errors"] = list(automatic_report.get("errors", [])) + list(state.get("errors", []))
        automatic_report["next_action"] = "Do not deliver this PDF. Regenerate or restore the signed artifacts, then record a new visual signoff after explicit user review."
    return automatic_report


def _parse_pdfinfo(text: str) -> Dict[str, Any]:
    fields: Dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip().lower()] = value.strip()
    pages = 0
    try:
        pages = int(fields.get("pages", "0"))
    except ValueError:
        pages = 0
    size_match = re.search(
        r"([0-9.]+)\s+x\s+([0-9.]+)\s+pts",
        fields.get("page size", ""),
        re.IGNORECASE,
    )
    width = float(size_match.group(1)) if size_match else None
    height = float(size_match.group(2)) if size_match else None
    return {
        "pages": pages,
        "width_points": width,
        "height_points": height,
        "tagged": fields.get("tagged"),
        "encrypted": fields.get("encrypted"),
        "raw": fields,
    }


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _bbox_geometry(path: Path) -> Dict[str, Any]:
    root = ElementTree.parse(str(path)).getroot()
    pages: List[Dict[str, Any]] = []
    clipped_words: List[Dict[str, Any]] = []
    overlapping_lines: List[Dict[str, Any]] = []
    for page_number, page in enumerate((item for item in root.iter() if _local_name(item.tag) == "page"), start=1):
        width = float(page.attrib.get("width", "0") or 0)
        height = float(page.attrib.get("height", "0") or 0)
        lines: List[Tuple[float, float, float, float, str]] = []
        word_count = 0
        for element in page.iter():
            local = _local_name(element.tag)
            if local not in {"word", "line"}:
                continue
            try:
                box = (
                    float(element.attrib["xMin"]),
                    float(element.attrib["yMin"]),
                    float(element.attrib["xMax"]),
                    float(element.attrib["yMax"]),
                )
            except (KeyError, ValueError):
                continue
            text = "".join(element.itertext()).strip()
            if local == "word":
                word_count += 1
                if box[0] < -0.25 or box[1] < -0.25 or box[2] > width + 0.25 or box[3] > height + 0.25:
                    clipped_words.append({"page": page_number, "text": text[:80], "box": list(box)})
            else:
                lines.append((*box, text[:100]))
        lines.sort(key=lambda item: (item[1], item[0]))
        for index, first in enumerate(lines):
            for second in lines[index + 1 : index + 5]:
                if second[1] >= first[3]:
                    break
                vertical = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
                minimum_height = max(0.01, min(first[3] - first[1], second[3] - second[1]))
                horizontal = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
                if vertical / minimum_height > 0.62 and horizontal > 8.0:
                    overlapping_lines.append(
                        {
                            "page": page_number,
                            "first": first[4],
                            "second": second[4],
                            "vertical_overlap_ratio": round(vertical / minimum_height, 3),
                        }
                    )
        content_top = min((item[1] for item in lines), default=None)
        content_bottom = max((item[3] for item in lines), default=None)
        content_span_ratio = (
            (content_bottom - content_top) / height
            if content_top is not None and content_bottom is not None and height > 0
            else 0.0
        )
        pages.append(
            {
                "page": page_number,
                "width_points": width,
                "height_points": height,
                "words": word_count,
                "lines": len(lines),
                "content_top_points": round(content_top, 3) if content_top is not None else None,
                "content_bottom_points": round(content_bottom, 3) if content_bottom is not None else None,
                "content_span_ratio": round(content_span_ratio, 6),
            }
        )
    return {
        "pages": pages,
        "clipped_words": clipped_words[:20],
        "overlapping_lines": overlapping_lines[:20],
    }


def _paeth(left: int, above: int, upper_left: int) -> int:
    prediction = left + above - upper_left
    distance_left = abs(prediction - left)
    distance_above = abs(prediction - above)
    distance_upper_left = abs(prediction - upper_left)
    if distance_left <= distance_above and distance_left <= distance_upper_left:
        return left
    if distance_above <= distance_upper_left:
        return above
    return upper_left


def inspect_grayscale_png(path: Path) -> Dict[str, Any]:
    """Decode a non-interlaced 8-bit PNG and calculate print-readability signals.

    Poppler's ``pdftoppm -gray -png`` does not use one stable PNG color type
    across platforms: some builds emit native grayscale data, while others
    emit RGB/RGBA pixels whose channels represent the grayscale preview.  The
    validator therefore converts every supported representation to luminance
    before applying the same contrast, blank-page, and page-edge checks.
    """

    payload = path.read_bytes()
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG file")
    position = 8
    width = height = bit_depth = color_type = 0
    compression = png_filter = interlace = -1
    compressed = bytearray()
    while position + 12 <= len(payload):
        length = struct.unpack(">I", payload[position : position + 4])[0]
        kind = payload[position + 4 : position + 8]
        data = payload[position + 8 : position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, compression, png_filter, interlace = struct.unpack(">IIBBBBB", data)
        elif kind == b"IDAT":
            compressed.extend(data)
        elif kind == b"IEND":
            break
    if width <= 0 or height <= 0:
        raise ValueError("PNG is missing valid dimensions")
    if bit_depth != 8 or color_type not in {0, 2, 4, 6}:
        raise ValueError("expected an 8-bit grayscale, RGB, grayscale-alpha, or RGBA PNG")
    if compression != 0 or png_filter != 0 or interlace != 0:
        raise ValueError("unsupported PNG encoding")
    channels_by_color_type = {0: 1, 2: 3, 4: 2, 6: 4}
    color_type_names = {0: "grayscale", 2: "rgb", 4: "grayscale_alpha", 6: "rgba"}
    channels = channels_by_color_type[color_type]
    row_bytes = width * channels
    decoded = zlib.decompress(bytes(compressed))
    expected = (row_bytes + 1) * height
    if len(decoded) != expected:
        raise ValueError("unexpected PNG scanline size")
    previous = bytearray(row_bytes)
    minimum = 255
    maximum = 0
    ink = 0
    dark = 0
    edge_ink = 0
    total = width * height
    offset = 0
    edge = max(2, min(width, height) // 500)
    for y in range(height):
        filter_type = decoded[offset]
        raw = decoded[offset + 1 : offset + 1 + row_bytes]
        offset += row_bytes + 1
        reconstructed = bytearray(row_bytes)
        for index, value in enumerate(raw):
            left = reconstructed[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                result = value
            elif filter_type == 1:
                result = (value + left) & 0xFF
            elif filter_type == 2:
                result = (value + above) & 0xFF
            elif filter_type == 3:
                result = (value + ((left + above) // 2)) & 0xFF
            elif filter_type == 4:
                result = (value + _paeth(left, above, upper_left)) & 0xFF
            else:
                raise ValueError("unsupported PNG filter")
            reconstructed[index] = result
        for x in range(width):
            pixel = x * channels
            if color_type == 0:
                luminance = reconstructed[pixel]
            elif color_type == 4:
                gray = reconstructed[pixel]
                alpha = reconstructed[pixel + 1]
                luminance = (gray * alpha + 255 * (255 - alpha) + 127) // 255
            else:
                red = reconstructed[pixel]
                green = reconstructed[pixel + 1]
                blue = reconstructed[pixel + 2]
                luminance = (299 * red + 587 * green + 114 * blue + 500) // 1000
                if color_type == 6:
                    alpha = reconstructed[pixel + 3]
                    luminance = (luminance * alpha + 255 * (255 - alpha) + 127) // 255
            minimum = min(minimum, luminance)
            maximum = max(maximum, luminance)
            if luminance < 245:
                ink += 1
                if x < edge or x >= width - edge or y < edge or y >= height - edge:
                    edge_ink += 1
            if luminance < 105:
                dark += 1
        previous = reconstructed
    return {
        "width": width,
        "height": height,
        "color_type": color_type_names[color_type],
        "minimum_luminance": minimum,
        "maximum_luminance": maximum,
        "contrast_span": maximum - minimum,
        "ink_ratio": round(ink / max(1, total), 6),
        "dark_ratio": round(dark / max(1, total), 6),
        "edge_ink_pixels": edge_ink,
    }


def _page_texts(text: str) -> List[str]:
    pages = text.replace("\r\n", "\n").replace("\r", "\n").split("\f")
    while pages and not pages[-1].strip():
        pages.pop()
    return pages


def _orphan_signals(text: str) -> List[Dict[str, Any]]:
    signals: List[Dict[str, Any]] = []
    pages = _page_texts(text)
    heading_words = {
        "个人简介",
        "专业技能",
        "技术能力",
        "工作经历",
        "项目经历",
        "教育经历",
        "实习经历",
        "开源经历",
        "论文与专利",
        "证书与奖项",
    }
    for page_number, page in enumerate(pages, start=1):
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        if not lines:
            signals.append({"page": page_number, "kind": "empty_page"})
            continue
        last = lines[-1]
        if last.rstrip(":：") in heading_words:
            signals.append({"page": page_number, "kind": "heading_at_page_end", "text": last})
        if len(last) == 1 and CJK_PATTERN.search(last):
            signals.append({"page": page_number, "kind": "single_cjk_at_page_end", "text": last})
        if page_number > 1:
            first = lines[0]
            if first[:1] in "，。；：、)]）】":
                signals.append({"page": page_number, "kind": "punctuation_at_page_start", "text": first[:30]})
            if first[:1] in "•◦▪●‣" or re.match(r"^[-+*]\s", first):
                signals.append({"page": page_number, "kind": "bullet_at_page_start", "text": first[:80]})
            if len(first) == 1 and CJK_PATTERN.search(first):
                signals.append({"page": page_number, "kind": "single_cjk_at_page_start", "text": first})
    return signals


def _font_summary(text: str) -> Dict[str, Any]:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= 2:
        return {"fonts": [], "all_embedded": None}
    fonts: List[Dict[str, Any]] = []
    for line in lines[2:]:
        match = re.match(
            r"^(.*?)\s{2,}(.*?)\s{2,}(.*?)\s{2,}(yes|no)\s+(yes|no)\s+(yes|no)\s+\d+\s+\d+\s*$",
            line,
            re.IGNORECASE,
        )
        if not match:
            continue
        fonts.append(
            {
                "name": match.group(1).strip(),
                "type": match.group(2).strip(),
                "encoding": match.group(3).strip(),
                "embedded": match.group(4).lower() == "yes",
                "subset": match.group(5).lower() == "yes",
                "unicode_map": match.group(6).lower() == "yes",
            }
        )
    return {"fonts": fonts, "all_embedded": bool(fonts) and all(item["embedded"] for item in fonts)}


def validate_pdf_artifact(
    pdf_path: Path,
    output_dir: Path,
    artifact_stem: str,
    source_markdown: Optional[str] = None,
    pdftotext_request: Optional[str] = None,
    pdfinfo_request: Optional[str] = None,
    pdftoppm_request: Optional[str] = None,
    pdffonts_request: Optional[str] = None,
    source_markdown_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Validate a local resume PDF and materialize visual-review images.

    Supplying the Markdown used to render the PDF is required before this
    result can be called fully qualified. Without it, the function preserves
    useful automatic checks but reports an automatic-only scope.
    """

    capabilities = {
        "pdftotext": resolve_command(pdftotext_request, ("pdftotext",)),
        "pdfinfo": resolve_command(pdfinfo_request, ("pdfinfo",)),
        "pdftoppm": resolve_command(pdftoppm_request, ("pdftoppm",)),
        "pdffonts": resolve_command(pdffonts_request, ("pdffonts",)),
    }
    checks: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    source_markdown_supplied = source_markdown is not None
    source_markdown_metadata = _source_markdown_metadata(source_markdown, source_markdown_path)
    source_to_pdf_integrity_checked = source_markdown_supplied and source_markdown_metadata["file_bound"]
    if source_markdown is not None and source_markdown_path is not None and not source_markdown_metadata["snapshot_matches_checked_content"]:
        errors.append(
            _issue(
                "MARKDOWN_SOURCE_SNAPSHOT_MISMATCH",
                "The source Markdown file changed or did not match the exact Markdown content checked for this PDF validation.",
                checked_content_sha256=source_markdown_metadata["checked_content_sha256"],
                source_path=source_markdown_metadata["path"],
                source_sha256=source_markdown_metadata["sha256"],
            )
        )
    if source_markdown_supplied and not source_to_pdf_integrity_checked:
        warnings.append(
            _issue(
                "PDF_SOURCE_MARKDOWN_FILE_BINDING_REQUIRED_FOR_QUALIFICATION",
                "Source Markdown must remain a readable file snapshot whose bytes match the content checked for the PDF.",
            )
        )
    missing = [name for name in ("pdftotext", "pdfinfo", "pdftoppm", "pdffonts") if not capabilities[name]]
    if missing:
        errors.append(
            _issue(
                "PDF_VALIDATION_CAPABILITY_UNAVAILABLE",
                "Complete PDF validation requires local pdftotext, pdfinfo, pdftoppm, and pdffonts capabilities.",
                missing=missing,
            )
        )
        checks.append(_check("capabilities", "fail", "Required local validation capabilities are missing.", missing=missing))
        report = {
            "ok": False,
            "kind": "pdf_validation",
            "schema_version": "1.0",
            "status": "capability_unavailable",
            "automatic_qualified": False,
            "visual_signoff_pending": False,
            "qualified": False,
            "delivery_blocked": True,
            "qualification_scope": {
                "automatic_checks_passed": False,
                "source_markdown_supplied": source_markdown_supplied,
                "source_to_pdf_integrity_checked": False,
            },
            "source": {"path": str(pdf_path.resolve()), "sha256": sha256_file(pdf_path), "size_bytes": pdf_path.stat().st_size},
            "source_markdown": source_markdown_metadata,
            "capabilities": capabilities,
            "checks": checks,
            "errors": errors,
            "warnings": warnings,
            "artifacts": {"page_pngs": [], "grayscale_pngs": []},
            "artifact_hashes": {},
            "next_action": "Keep the confirmed Markdown and printable HTML; install the missing local capability before claiming a qualified PDF.",
        }
        return apply_pdf_visual_signoff(report, None)

    checks.append(_check("capabilities", "pass", "All required local validation capabilities are available."))
    checksum_before = sha256_file(pdf_path)
    expectations = markdown_expectations(source_markdown or "")
    page_pngs: List[str] = []
    gray_pngs: List[str] = []
    page_count = 0
    extracted_text = ""
    pdfinfo_data: Dict[str, Any] = {}
    bbox_data: Dict[str, Any] = {"pages": [], "clipped_words": [], "overlapping_lines": []}
    image_stats: List[Dict[str, Any]] = []
    link_annotations: List[str] = []
    font_data: Dict[str, Any] = {"fonts": [], "all_embedded": None}

    with tempfile.TemporaryDirectory(prefix=".pdf-validation-", dir=str(output_dir)) as temporary_name:
        temporary = Path(temporary_name)
        info_result = run_local([str(capabilities["pdfinfo"]), str(pdf_path)])
        if info_result.returncode != 0:
            errors.append(_issue("PDFINFO_FAILED", "pdfinfo could not inspect the PDF.", stderr=info_result.stderr[-500:]))
        else:
            pdfinfo_data = _parse_pdfinfo(info_result.stdout)
            page_count = pdfinfo_data["pages"]

        text_result = run_local([str(capabilities["pdftotext"]), "-enc", "UTF-8", str(pdf_path), "-"])
        if text_result.returncode != 0:
            errors.append(_issue("PDF_TEXT_EXTRACTION_FAILED", "pdftotext could not extract resume text.", stderr=text_result.stderr[-500:]))
        else:
            extracted_text = text_result.stdout

        bbox_path = temporary / "layout.xhtml"
        bbox_result = run_local([str(capabilities["pdftotext"]), "-bbox-layout", str(pdf_path), str(bbox_path)])
        if bbox_result.returncode != 0 or not bbox_path.is_file():
            errors.append(_issue("PDF_LAYOUT_EXTRACTION_FAILED", "Text geometry could not be inspected for clipping and overlap."))
        else:
            try:
                bbox_data = _bbox_geometry(bbox_path)
            except (ElementTree.ParseError, OSError, ValueError) as exc:
                errors.append(_issue("PDF_LAYOUT_PARSE_FAILED", "Text geometry output was invalid.", reason=str(exc)))

        url_result = run_local([str(capabilities["pdfinfo"]), "-url", str(pdf_path)])
        if url_result.returncode == 0:
            link_annotations = sorted({normalize_url(item) for item in URL_PATTERN.findall(url_result.stdout)})
        else:
            warnings.append(_issue("PDF_LINK_CHECK_UNAVAILABLE", "PDF link annotations could not be inspected."))

        font_result = run_local([str(capabilities["pdffonts"]), str(pdf_path)])
        if font_result.returncode == 0:
            font_data = _font_summary(font_result.stdout)
        else:
            errors.append(_issue("PDF_FONT_CHECK_FAILED", "pdffonts could not inspect font embedding."))

        color_prefix = temporary / (artifact_stem + "-page")
        gray_prefix = temporary / (artifact_stem + "-gray-page")
        color_result = run_local([str(capabilities["pdftoppm"]), "-png", "-r", "144", str(pdf_path), str(color_prefix)])
        gray_result = run_local([str(capabilities["pdftoppm"]), "-gray", "-png", "-r", "144", str(pdf_path), str(gray_prefix)])
        if color_result.returncode != 0 or gray_result.returncode != 0:
            errors.append(_issue("PDF_RASTERIZATION_FAILED", "PDF pages could not be rendered for visual validation."))
        else:
            color_paths = sorted(temporary.glob(artifact_stem + "-page-*.png"))
            gray_paths = sorted(temporary.glob(artifact_stem + "-gray-page-*.png"))
            if not color_paths or len(color_paths) != len(gray_paths):
                errors.append(_issue("PDF_RASTERIZATION_INCOMPLETE", "Color and grayscale page previews are incomplete."))
            else:
                for source in color_paths + gray_paths:
                    destination = output_dir / source.name
                    os.replace(str(source), str(destination))
                    if "-gray-page-" in source.name:
                        gray_pngs.append(str(destination.resolve()))
                    else:
                        page_pngs.append(str(destination.resolve()))
                for gray_path in gray_pngs:
                    try:
                        stats = inspect_grayscale_png(Path(gray_path))
                        stats["path"] = gray_path
                        image_stats.append(stats)
                    except (OSError, ValueError, zlib.error) as exc:
                        errors.append(_issue("GRAYSCALE_PREVIEW_INVALID", "A grayscale preview could not be analyzed.", path=gray_path, reason=str(exc)))

    checksum_after = sha256_file(pdf_path)
    if checksum_after != checksum_before:
        errors.append(_issue("PDF_CHANGED_DURING_VALIDATION", "The PDF changed while it was being validated."))

    if page_count in {1, 2}:
        checks.append(_check("page_count", "pass", "Resume is within the one-to-two-page delivery limit.", pages=page_count))
    else:
        errors.append(_issue("PDF_PAGE_COUNT_OUT_OF_RANGE", "A delivery-ready PDF must contain one or two pages.", pages=page_count))
        checks.append(_check("page_count", "fail", "Resume is outside the one-to-two-page delivery limit.", pages=page_count))

    width = pdfinfo_data.get("width_points")
    height = pdfinfo_data.get("height_points")
    a4 = bool(width and height and abs(width - 595.28) <= 8 and abs(height - 841.89) <= 8)
    if a4:
        checks.append(_check("page_size", "pass", "PDF page size is A4 portrait.", width_points=width, height_points=height))
    else:
        errors.append(_issue("PDF_PAGE_SIZE_NOT_A4", "PDF must use A4 portrait pages.", width_points=width, height_points=height))
        checks.append(_check("page_size", "fail", "PDF page size is not A4 portrait."))

    compact_text = re.sub(r"\s+", "", extracted_text)
    cjk_count = len(CJK_PATTERN.findall(extracted_text))
    if len(compact_text) >= 80 and cjk_count >= 8:
        checks.append(_check("extractable_text", "pass", "PDF contains selectable Chinese resume text.", non_whitespace_characters=len(compact_text), cjk_characters=cjk_count))
    else:
        errors.append(_issue("PDF_TEXT_NOT_RELIABLY_EXTRACTABLE", "PDF lacks enough extractable Chinese text for ATS delivery.", non_whitespace_characters=len(compact_text), cjk_characters=cjk_count))
        checks.append(_check("extractable_text", "fail", "Selectable Chinese text check failed."))

    extracted_visible = _normalized_visible(extracted_text)
    visible_blocks = expectations.get("visible_blocks", [])
    missing_blocks: List[Dict[str, Any]] = []
    matched_characters = 0
    total_characters = sum(len(item["normalized"]) for item in visible_blocks)
    search_from = 0
    for block in visible_blocks:
        normalized = block["normalized"]
        found = extracted_visible.find(normalized, search_from)
        if found < 0:
            found = extracted_visible.find(normalized)
        if found < 0:
            missing_blocks.append({"text": block["text"][:180], "normalized_characters": len(normalized)})
        else:
            matched_characters += len(normalized)
            search_from = found + len(normalized)
    content_coverage = matched_characters / max(1, total_characters)
    significant_missing = [item for item in missing_blocks if item["normalized_characters"] >= 4]
    if visible_blocks and content_coverage >= 0.995 and not significant_missing:
        checks.append(
            _check(
                "full_source_content",
                "pass",
                "All significant visible Markdown blocks remain extractable from the PDF.",
                coverage=round(content_coverage, 6),
                blocks=len(visible_blocks),
            )
        )
    elif visible_blocks:
        errors.append(
            _issue(
                "PDF_SOURCE_BODY_INCOMPLETE",
                "The extracted PDF does not contain the full visible Markdown body.",
                coverage=round(content_coverage, 6),
                missing_blocks=significant_missing[:8],
            )
        )
        checks.append(_check("full_source_content", "fail", "Full Markdown-to-PDF body coverage failed.", coverage=round(content_coverage, 6)))
    else:
        warnings.append(
            _issue(
                "PDF_SOURCE_MARKDOWN_REQUIRED_FOR_QUALIFICATION",
                "No source Markdown was supplied; automatic PDF checks cannot establish full source-to-PDF integrity or a qualified delivery-ready PDF.",
            )
        )
        warnings.append(_issue("PDF_FULL_SOURCE_NOT_CHECKED", "No source Markdown was supplied; full visible body coverage was not checked."))
        checks.append(_check("full_source_content", "warn", "Full source content was not supplied."))

    broken_glyphs = {character: extracted_text.count(character) for character in ("�", "□", "■") if character in extracted_text}
    if broken_glyphs:
        errors.append(_issue("PDF_GLYPH_CORRUPTION", "Extracted text contains likely missing or corrupt glyphs.", glyphs=broken_glyphs))
        checks.append(_check("chinese_glyphs", "fail", "Potential missing Chinese glyphs were detected."))
    else:
        checks.append(_check("chinese_glyphs", "pass", "No replacement or missing-glyph markers were found."))

    missing_headings = [heading for heading in expectations["headings"] if _normalized_visible(heading) not in extracted_visible]
    if missing_headings:
        errors.append(_issue("PDF_SOURCE_CONTENT_MISSING", "Expected Markdown headings are absent from extracted PDF text.", headings=missing_headings))
        checks.append(_check("source_content", "fail", "Source-to-PDF heading coverage is incomplete."))
    elif expectations["headings"]:
        checks.append(_check("source_content", "pass", "All Markdown headings remain extractable from the PDF.", headings=len(expectations["headings"])))
    else:
        warnings.append(_issue("PDF_SOURCE_CONTENT_NOT_CHECKED", "No source Markdown was supplied; source coverage was not checked."))
        checks.append(_check("source_content", "warn", "Source Markdown was not supplied."))

    missing_links = [item for item in expectations["links"] if item not in link_annotations]
    if missing_links:
        errors.append(_issue("PDF_LINK_ANNOTATION_MISSING", "One or more Markdown links are not clickable in the PDF.", links=missing_links))
        checks.append(_check("links", "fail", "Expected clickable link annotations are missing."))
    elif expectations["links"]:
        checks.append(_check("links", "pass", "All expected Markdown links are present as PDF annotations.", links=link_annotations))
    else:
        checks.append(_check("links", "pass", "No source links required annotation validation.", detected_links=link_annotations))

    if bbox_data["clipped_words"]:
        errors.append(_issue("PDF_TEXT_CLIPPING_RISK", "Text boxes extend outside a page boundary.", samples=bbox_data["clipped_words"][:5]))
        checks.append(_check("text_geometry", "fail", "Out-of-page text geometry was detected."))
    elif bbox_data["overlapping_lines"]:
        errors.append(_issue("PDF_TEXT_OVERLAP_RISK", "Text-line geometry indicates possible overlap.", samples=bbox_data["overlapping_lines"][:5]))
        checks.append(_check("text_geometry", "fail", "Potential overlapping text lines were detected."))
    elif bbox_data["pages"]:
        checks.append(_check("text_geometry", "pass", "Text geometry stays within page bounds without line overlap."))

    orphan_signals = _orphan_signals(extracted_text)
    severe_orphans = [
        item
        for item in orphan_signals
        if item["kind"] in {"empty_page", "heading_at_page_end", "bullet_at_page_start"}
    ]
    if severe_orphans:
        errors.append(_issue("PDF_ORPHAN_LAYOUT_RISK", "Page-boundary heuristics found a blocking orphan or empty page.", signals=severe_orphans))
        checks.append(_check("page_breaks", "fail", "Blocking page-break signals were detected."))
    elif orphan_signals:
        warnings.append(_issue("PDF_POTENTIAL_ORPHAN", "Review possible page-boundary orphan signals in the rendered previews.", signals=orphan_signals))
        checks.append(_check("page_breaks", "warn", "Potential orphan signals require preview review."))
    else:
        checks.append(_check("page_breaks", "pass", "No page-boundary orphan signals were detected."))

    if page_count == 2 and len(bbox_data.get("pages", [])) >= 2:
        second_page = bbox_data["pages"][1]
        second_page_span = float(second_page.get("content_span_ratio") or 0.0)
        if second_page_span < 0.28:
            errors.append(
                _issue(
                    "PDF_SECOND_PAGE_UNDERFILLED",
                    "The second page contains too little vertically distributed content for a polished two-page resume.",
                    content_span_ratio=round(second_page_span, 6),
                    minimum_ratio=0.28,
                )
            )
            checks.append(_check("page_balance", "fail", "The two-page layout is visibly underfilled on page two."))
        else:
            checks.append(
                _check(
                    "page_balance",
                    "pass",
                    "The second page has enough content distribution for visual review.",
                    content_span_ratio=round(second_page_span, 6),
                )
            )

    image_failures: List[Dict[str, Any]] = []
    for stats in image_stats:
        aspect = stats["width"] / max(1, stats["height"])
        if stats["width"] < 800 or not 0.68 <= aspect <= 0.73:
            image_failures.append({"path": stats["path"], "reason": "unexpected_page_geometry"})
        elif stats["contrast_span"] < 120 or stats["dark_ratio"] < 0.0003:
            image_failures.append({"path": stats["path"], "reason": "insufficient_grayscale_contrast"})
        elif stats["ink_ratio"] > 0.5:
            image_failures.append({"path": stats["path"], "reason": "excessive_page_density"})
        elif stats["edge_ink_pixels"]:
            image_failures.append({"path": stats["path"], "reason": "ink_touches_page_edge"})
    if image_failures or not image_stats:
        errors.append(_issue("PDF_VISUAL_HEURISTICS_FAILED", "Rendered grayscale pages failed automatic visual heuristics.", failures=image_failures))
        checks.append(_check("rendered_visuals", "fail", "Raster and grayscale visual checks did not pass."))
    else:
        checks.append(_check("rendered_visuals", "pass", "Every page rendered in color and grayscale with printable contrast and clear page edges.", pages=len(image_stats)))

    if font_data.get("all_embedded") is False:
        errors.append(_issue("PDF_FONT_NOT_EMBEDDED", "Every used PDF font must be embedded for portable Chinese rendering.", fonts=font_data.get("fonts", [])))
        checks.append(_check("fonts", "fail", "One or more used fonts are not embedded."))
    elif font_data.get("all_embedded") is True:
        checks.append(_check("fonts", "pass", "All reported PDF fonts are embedded."))
    else:
        errors.append(_issue("PDF_FONT_EMBEDDING_UNKNOWN", "Font embedding could not be established."))
        checks.append(_check("fonts", "fail", "Font embedding could not be fully inspected."))

    automatic_checks_passed = not errors
    automatic_qualified = automatic_checks_passed and source_to_pdf_integrity_checked
    if automatic_qualified:
        status = "visual_signoff_pending"
    elif automatic_checks_passed:
        status = "automatic_checks_only"
    else:
        status = "failed"
    artifact_hashes = {
        "pdf": {
            "path": str(pdf_path.resolve()),
            "sha256": checksum_before,
            "size_bytes": pdf_path.stat().st_size,
        },
        "page_pngs": [
            {"path": item, "sha256": sha256_file(Path(item)), "size_bytes": Path(item).stat().st_size}
            for item in page_pngs
            if Path(item).is_file()
        ],
        "grayscale_pngs": [
            {"path": item, "sha256": sha256_file(Path(item)), "size_bytes": Path(item).stat().st_size}
            for item in gray_pngs
            if Path(item).is_file()
        ],
    }
    if source_markdown_metadata["file_bound"]:
        artifact_hashes["markdown"] = {
            "path": source_markdown_metadata["path"],
            "sha256": source_markdown_metadata["sha256"],
            "size_bytes": source_markdown_metadata["size_bytes"],
        }
    report = {
        "ok": automatic_qualified,
        "kind": "pdf_validation",
        "schema_version": "1.0",
        "status": status,
        "automatic_qualified": automatic_qualified,
        "visual_signoff_pending": automatic_qualified,
        "qualified": False,
        "delivery_blocked": True,
        "qualification_scope": {
            "automatic_checks_passed": automatic_checks_passed,
            "source_markdown_supplied": source_markdown_supplied,
            "source_to_pdf_integrity_checked": source_to_pdf_integrity_checked,
        },
        "source": {
            "path": str(pdf_path.resolve()),
            "size_bytes": pdf_path.stat().st_size,
            "sha256": checksum_before,
            "opened_read_only": True,
            "unchanged": checksum_before == checksum_after,
        },
        "source_markdown": source_markdown_metadata,
        "capabilities": capabilities,
        "summary": {
            "pages": page_count,
            "a4_portrait": a4,
            "extractable_characters": len(compact_text),
            "cjk_characters": cjk_count,
            "expected_links": expectations["links"],
            "detected_link_annotations": link_annotations,
            "fonts": font_data,
            "source_body_coverage": round(content_coverage, 6) if visible_blocks else None,
            "page_content_geometry": bbox_data.get("pages", []),
        },
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "artifacts": {
            "page_pngs": page_pngs,
            "grayscale_pngs": gray_pngs,
            "image_statistics": image_stats,
        },
        "artifact_hashes": artifact_hashes,
        "visual_review": {
            "rasterized": bool(page_pngs) and bool(gray_pngs),
            "automatic_heuristics_passed": not image_failures and bool(image_stats),
            "human_style_signoff": "required_before_delivery",
        },
        "next_action": (
            "Review the rendered page PNGs and record explicit user visual signoff before delivering the PDF."
            if automatic_qualified
            else (
                "Automatic PDF checks passed, but no source Markdown was supplied. Rerun with --source-markdown before calling this PDF qualified or delivery-ready."
                if automatic_checks_passed and not source_markdown_supplied
                else "Do not call this PDF qualified; correct every error and rerun validation, or deliver Markdown and printable HTML as an explicit degradation."
            )
        ),
    }
    return apply_pdf_visual_signoff(report, None)
