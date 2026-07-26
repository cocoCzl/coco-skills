#!/usr/bin/env python3
"""Create, update, or reuse an opt-in local career evidence store.

Writes require an explicit ``--opt-in`` and user-selected ``--path``.  The
tool refuses to write anywhere inside the Skill package and persists only
confirmed, disclosure-cleared, target-role-independent facts.  Source code,
resume/JD prose, credentials, contact data, and unresolved facts are filtered
or rejected before an atomic write.
"""

from __future__ import annotations

import hashlib
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from _json_cli import (
    CliFailure,
    JsonArgumentParser,
    atomic_write_json,
    emit,
    emit_failure,
    inside_path,
    load_json,
    parse_json_cli,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]
FACT_TYPES = {
    "employment",
    "education",
    "project_fact",
    "personal_contribution",
    "skill",
    "star_evidence",
    "quantification",
    "award",
    "certification",
    "other",
}
SOURCE_TYPES = {
    "user_statement",
    "original_resume",
    "code",
    "project_document",
    "git_hint",
    "calculation",
    "public_portfolio",
    "other",
}
ALLOWED_FACT_KEYS = {
    "id",
    "fact_type",
    "statement",
    "status",
    "employment_id",
    "project_id",
    "sources",
    "ownership",
    "disclosure",
    "star",
    "quantification",
    "conflict",
    "tags",
}
FORBIDDEN_CONTENT_KEYS = {
    "api_key",
    "code",
    "credential",
    "credentials",
    "generated_copy",
    "jd",
    "jd_copy",
    "jd_text",
    "original_resume",
    "password",
    "private_key",
    "prompt",
    "raw_content",
    "resume_copy",
    "resume_markdown",
    "resume_text",
    "secret",
    "source_code",
    "source_excerpt",
    "snippet",
    "tailored_copy",
    "token",
}
SECRET_VALUE_RE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b|\bsk-[A-Za-z0-9_-]{16,}\b|"
    r"\b(?:api[_-]?key|password|passwd|secret|token)\s*[:=]\s*[^\s,;]{6,})",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
CN_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
CODE_FENCE_RE = re.compile(r"```|~~~")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def add_filtered(report: Dict[str, Any], path: str, reason: str) -> None:
    report["filtered_fields"].append({"path": path, "reason": reason})


def suspicious_text(text: str) -> Optional[str]:
    if SECRET_VALUE_RE.search(text):
        return "credential_or_secret_pattern"
    if EMAIL_RE.search(text) or CN_PHONE_RE.search(text):
        return "contact_or_personal_data"
    if CODE_FENCE_RE.search(text):
        return "source_code_or_fenced_content"
    return None


def sanitize_source(source: Any, path: str, report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(source, dict):
        add_filtered(report, path, "invalid_source_object")
        return None
    source_id = source.get("source_id")
    source_type = source.get("type")
    locator = source.get("locator")
    if not isinstance(source_id, str) or not source_id.strip():
        add_filtered(report, path, "missing_source_id")
        return None
    if source_type not in SOURCE_TYPES:
        add_filtered(report, path, "unsupported_source_type")
        return None
    if not isinstance(locator, str) or not locator.strip():
        add_filtered(report, path, "missing_source_locator")
        return None
    if suspicious_text(locator):
        add_filtered(report, path + ".locator", "sensitive_source_locator")
        return None
    clean: Dict[str, Any] = {
        "source_id": source_id.strip()[:128],
        "type": source_type,
        "locator": locator.strip()[:1000],
    }
    if isinstance(source.get("observed_at"), str) and source["observed_at"].strip():
        clean["observed_at"] = source["observed_at"].strip()
    # Deliberately do not persist note/excerpt/raw fields. A locator is enough
    # to revisit evidence without turning the store into a source archive.
    for key in source:
        if key not in {"source_id", "type", "locator", "observed_at"}:
            add_filtered(report, path + "." + str(key), "source_content_not_persisted")
    return clean


def sanitize_ownership(value: Any, fact_type: str, path: str, report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        add_filtered(report, path, "missing_ownership")
        return None
    status = value.get("status")
    confirmed = value.get("confirmed_by_user") is True
    if not confirmed:
        add_filtered(report, path, "ownership_status_not_user_confirmed")
        return None
    if fact_type in {"personal_contribution", "employment", "education", "skill", "star_evidence", "quantification"}:
        if status != "confirmed":
            add_filtered(report, path, "ownership_not_user_confirmed")
            return None
    elif status not in {"confirmed", "not_applicable"}:
        add_filtered(report, path, "ownership_not_cleared")
        return None
    clean: Dict[str, Any] = {"status": status, "confirmed_by_user": confirmed}
    if isinstance(value.get("confirmed_at"), str) and value["confirmed_at"].strip():
        clean["confirmed_at"] = value["confirmed_at"].strip()
    if isinstance(value.get("confirmation_source_id"), str) and value["confirmation_source_id"].strip():
        clean["confirmation_source_id"] = value["confirmation_source_id"].strip()
    return clean


def sanitize_disclosure(value: Any, path: str, report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        add_filtered(report, path, "missing_disclosure_review")
        return None
    status = value.get("status")
    if status not in {"approved", "sanitized"}:
        add_filtered(report, path, "disclosure_not_cleared")
        return None
    if value.get("confirmed_by_user") is not True:
        add_filtered(report, path, "disclosure_not_user_confirmed")
        return None
    clean: Dict[str, Any] = {"status": status, "confirmed_by_user": True}
    sanitized_statement = value.get("sanitized_statement")
    if status == "sanitized" and (not isinstance(sanitized_statement, str) or not sanitized_statement.strip()):
        add_filtered(report, path + ".sanitized_statement", "sanitized_statement_required")
        return None
    if isinstance(sanitized_statement, str) and sanitized_statement.strip():
        reason = suspicious_text(sanitized_statement)
        if reason:
            add_filtered(report, path + ".sanitized_statement", reason)
            return None
        clean["sanitized_statement"] = sanitized_statement.strip()[:4000]
    return clean


def sanitize_conflict(value: Any, path: str, report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        add_filtered(report, path, "missing_conflict_status")
        return None
    status = value.get("status")
    if status == "unresolved":
        add_filtered(report, path, "unresolved_conflict")
        return None
    if status not in {"none", "resolved"}:
        add_filtered(report, path, "invalid_conflict_status")
        return None
    clean: Dict[str, Any] = {"status": status}
    if status == "resolved":
        if value.get("resolved_by_user") is not True or not isinstance(value.get("resolution"), str) or not value["resolution"].strip():
            add_filtered(report, path, "conflict_resolution_not_user_confirmed")
            return None
        clean["resolved_by_user"] = True
        clean["resolution"] = value["resolution"].strip()[:1000]
    conflicting_ids = value.get("conflicting_source_ids")
    if isinstance(conflicting_ids, list):
        clean["conflicting_source_ids"] = [str(item)[:128] for item in conflicting_ids if str(item).strip()]
    return clean


def sanitize_star(value: Any, path: str, report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("confirmed_by_user") is not True:
        add_filtered(report, path, "star_not_user_confirmed")
        return None
    clean: Dict[str, Any] = {"confirmed_by_user": True}
    for key in ("situation", "task", "action", "result"):
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            add_filtered(report, path + "." + key, "incomplete_star")
            return None
        reason = suspicious_text(item)
        if reason:
            add_filtered(report, path + "." + key, reason)
            return None
        clean[key] = item.strip()[:3000]
    return clean


def sanitize_quantification(value: Any, path: str, report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        add_filtered(report, path, "invalid_quantification")
        return None
    kind = value.get("kind")
    if kind not in {"numeric", "range", "qualitative", "none"}:
        add_filtered(report, path, "invalid_quantification_kind")
        return None
    if value.get("confirmed_by_user") is not True:
        add_filtered(report, path, "quantification_not_user_confirmed")
        return None
    clean: Dict[str, Any] = {"kind": kind, "confirmed_by_user": True}
    if kind in {"numeric", "range"}:
        basis = value.get("basis")
        source_ids = value.get("source_ids")
        if not isinstance(basis, str) or not basis.strip() or not isinstance(source_ids, list) or not source_ids:
            add_filtered(report, path, "numeric_basis_or_sources_missing")
            return None
        if suspicious_text(basis):
            add_filtered(report, path + ".basis", "sensitive_quantification_basis")
            return None
        clean["basis"] = basis.strip()[:1000]
        clean["source_ids"] = [str(item)[:128] for item in source_ids if str(item).strip()]
        if not clean["source_ids"]:
            add_filtered(report, path + ".source_ids", "numeric_sources_missing")
            return None
    for key in ("value", "unit", "calculation"):
        item = value.get(key)
        if isinstance(item, (str, int, float)) and not isinstance(item, bool):
            if isinstance(item, str) and suspicious_text(item):
                add_filtered(report, path + "." + key, "sensitive_quantification_content")
                return None
            clean[key] = item if not isinstance(item, str) else item.strip()[:1000]
    return clean


def sanitize_fact(raw: Any, index: int, report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    path = "$.facts[{0}]".format(index)
    if not isinstance(raw, dict):
        report["skipped_facts"].append({"id": None, "reason": "invalid_fact_object"})
        return None
    fact_id = raw.get("id")
    if not isinstance(fact_id, str) or not fact_id.strip():
        report["skipped_facts"].append({"id": None, "reason": "missing_fact_id"})
        return None
    fact_id = fact_id.strip()[:128]
    for key in raw:
        if str(key).lower() in FORBIDDEN_CONTENT_KEYS:
            add_filtered(report, path + "." + str(key), "source_resume_or_jd_content_not_persisted")
        elif key not in ALLOWED_FACT_KEYS:
            add_filtered(report, path + "." + str(key), "field_not_in_career_fact_schema")
    if raw.get("status") != "confirmed":
        report["skipped_facts"].append({"id": fact_id, "reason": "fact_not_confirmed"})
        return None
    fact_type = raw.get("fact_type")
    if fact_type not in FACT_TYPES:
        report["skipped_facts"].append({"id": fact_id, "reason": "unsupported_fact_type"})
        return None
    statement = raw.get("statement")
    if not isinstance(statement, str) or not statement.strip():
        report["skipped_facts"].append({"id": fact_id, "reason": "empty_statement"})
        return None
    reason = suspicious_text(statement)
    if reason:
        report["skipped_facts"].append({"id": fact_id, "reason": reason})
        return None
    sources_value = raw.get("sources")
    sources: List[Dict[str, Any]] = []
    if isinstance(sources_value, list):
        for source_index, source in enumerate(sources_value):
            clean_source = sanitize_source(source, path + ".sources[{0}]".format(source_index), report)
            if clean_source:
                sources.append(clean_source)
    if not sources:
        report["skipped_facts"].append({"id": fact_id, "reason": "no_safe_source_locator"})
        return None
    ownership = sanitize_ownership(raw.get("ownership"), fact_type, path + ".ownership", report)
    disclosure = sanitize_disclosure(raw.get("disclosure"), path + ".disclosure", report)
    conflict = sanitize_conflict(raw.get("conflict"), path + ".conflict", report)
    if ownership is None or disclosure is None or conflict is None:
        report["skipped_facts"].append({"id": fact_id, "reason": "ownership_disclosure_or_conflict_not_cleared"})
        return None
    star = sanitize_star(raw.get("star"), path + ".star", report)
    if raw.get("star") is not None and star is None:
        report["skipped_facts"].append({"id": fact_id, "reason": "invalid_star_evidence"})
        return None
    quantification = sanitize_quantification(raw.get("quantification"), path + ".quantification", report)
    if raw.get("quantification") is not None and quantification is None:
        report["skipped_facts"].append({"id": fact_id, "reason": "invalid_quantification"})
        return None
    clean: Dict[str, Any] = {
        "id": fact_id,
        "fact_type": fact_type,
        # A sanitized disclosure is an instruction to persist only the safe
        # replacement. Keeping the original statement anywhere in the store
        # would defeat the user's confidentiality decision.
        "statement": (
            disclosure["sanitized_statement"]
            if disclosure.get("status") == "sanitized"
            else statement.strip()[:4000]
        ),
        "status": "confirmed",
        "sources": sources,
        "ownership": ownership,
        "disclosure": disclosure,
        "conflict": conflict,
    }
    for key in ("employment_id", "project_id"):
        if isinstance(raw.get(key), str) and raw[key].strip():
            clean[key] = raw[key].strip()[:256]
    if star is not None:
        clean["star"] = star
    if quantification is not None:
        clean["quantification"] = quantification
    if isinstance(raw.get("tags"), list):
        tags: List[str] = []
        for tag in raw["tags"]:
            if isinstance(tag, str) and tag.strip() and not suspicious_text(tag):
                tags.append(tag.strip()[:80])
        if tags:
            clean["tags"] = sorted(set(tags))
    return clean


def extract_input_facts(document: Any) -> List[Any]:
    if isinstance(document, list):
        return document
    if isinstance(document, dict) and isinstance(document.get("facts"), list):
        return document["facts"]
    if isinstance(document, dict) and isinstance(document.get("career_facts"), list):
        return document["career_facts"]
    raise CliFailure("INVALID_INPUT", "Input must be a fact array or an object containing facts/career_facts.", 2)


def sanitize_input(document: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    report: Dict[str, Any] = {"filtered_fields": [], "skipped_facts": []}
    if isinstance(document, dict):
        for key in document:
            if key not in {"facts", "career_facts", "schema_version", "kind"}:
                reason = "target_or_resume_copy_not_persisted" if str(key).lower() in FORBIDDEN_CONTENT_KEYS or "jd" in str(key).lower() else "top_level_metadata_not_persisted"
                add_filtered(report, "$." + str(key), reason)
    clean: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for index, raw in enumerate(extract_input_facts(document)):
        fact = sanitize_fact(raw, index, report)
        if fact is None:
            continue
        if fact["id"] in seen:
            report["skipped_facts"].append({"id": fact["id"], "reason": "duplicate_fact_id_in_input"})
            continue
        seen.add(fact["id"])
        clean.append(fact)
    return clean, report


def validate_existing_store(document: Any) -> Dict[str, Any]:
    if not isinstance(document, dict):
        raise CliFailure("INVALID_STORE", "Career store must be a JSON object.", 2)
    if document.get("schema_version") != "1.0" or document.get("kind") != "career_evidence_store":
        raise CliFailure("INVALID_STORE", "Unsupported career store schema or kind.", 2)
    if document.get("target_independent") is not True:
        raise CliFailure("TARGET_COPY_CONTAMINATION", "Career store must remain target_independent.", 2)
    allowed_store_keys = {
        "schema_version",
        "kind",
        "store_id",
        "created_at",
        "updated_at",
        "target_independent",
        "facts",
    }
    if set(document) != allowed_store_keys:
        raise CliFailure("INVALID_STORE", "Career store contains unsupported or target-specific top-level fields.", 2)
    for key in ("store_id", "created_at", "updated_at"):
        if not isinstance(document.get(key), str) or not document[key].strip():
            raise CliFailure("INVALID_STORE", "Career store field {0} is missing or invalid.".format(key), 2)
    facts = document.get("facts")
    if not isinstance(facts, list):
        raise CliFailure("INVALID_STORE", "Career store facts must be an array.", 2)
    seen: Set[str] = set()
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict) or not isinstance(fact.get("id"), str):
            raise CliFailure("INVALID_STORE", "Stored fact {0} is invalid.".format(index), 2)
        if fact["id"] in seen:
            raise CliFailure("INVALID_STORE", "Career store contains duplicate fact id: {0}".format(fact["id"]), 2)
        seen.add(fact["id"])
        if fact.get("status") != "confirmed":
            raise CliFailure("INVALID_STORE", "Career store contains an unconfirmed fact: {0}".format(fact["id"]), 2)
        disclosure = fact.get("disclosure") if isinstance(fact.get("disclosure"), dict) else {}
        if disclosure.get("status") not in {"approved", "sanitized"}:
            raise CliFailure("INVALID_STORE", "Career store contains a disclosure-blocked fact: {0}".format(fact["id"]), 2)
    # Re-run the same strict sanitizer used at write time. Any mutation that
    # would be filtered (source snippets, credentials, unresolved ownership or
    # conflicts, raw pre-sanitization statements, unknown fields) makes the
    # store unsafe to reuse.
    sanitized_facts, report = sanitize_input({"facts": facts})
    if report["filtered_fields"] or report["skipped_facts"] or sanitized_facts != facts:
        raise CliFailure(
            "POLLUTED_STORE_REFUSED",
            "Career store failed strict ownership/source/conflict/confidentiality revalidation and was not reused.",
            2,
        )
    return document


def validated_output_path(raw_path: str, must_exist: Optional[bool]) -> Path:
    path = Path(raw_path).expanduser()
    if path.suffix.lower() != ".json":
        raise CliFailure("INVALID_STORE_PATH", "Career evidence store path must end in .json.", 2)
    resolved = path.resolve()
    if inside_path(resolved, SKILL_ROOT):
        raise CliFailure(
            "SKILL_PACKAGE_WRITE_REFUSED",
            "Career evidence stores must not be written inside the Skill package. Choose a user work directory.",
            2,
        )
    if must_exist is True and not path.is_file():
        raise CliFailure("STORE_NOT_FOUND", "Career evidence store does not exist: {0}".format(path), 2)
    if must_exist is False and path.exists():
        raise CliFailure("STORE_ALREADY_EXISTS", "Store already exists; use the update command instead.", 2)
    if path.is_symlink():
        raise CliFailure("SYMLINK_STORE_REFUSED", "Career evidence store cannot be a symbolic link.", 2)
    return path


def create_store(path: Path, input_path: Path) -> Dict[str, Any]:
    document = load_json(input_path)
    facts, report = sanitize_input(document)
    if not facts:
        raise CliFailure("NO_PERSISTABLE_FACTS", "No confirmed, disclosure-cleared facts were eligible for persistence.", 1, report)
    timestamp = now_iso()
    store = {
        "schema_version": "1.0",
        "kind": "career_evidence_store",
        "store_id": "career-store-{0}".format(uuid.uuid4().hex),
        "created_at": timestamp,
        "updated_at": timestamp,
        "target_independent": True,
        "facts": sorted(facts, key=lambda item: item["id"]),
    }
    atomic_write_json(path, store)
    return {
        "ok": True,
        "kind": "career_store_operation",
        "action": "create",
        "path": str(path.resolve()),
        "written": True,
        "saved_fact_count": len(facts),
        "saved_fact_ids": [fact["id"] for fact in store["facts"]],
        "filter_report": report,
        "target_independent": True,
    }


def update_store(path: Path, input_path: Path) -> Dict[str, Any]:
    existing = validate_existing_store(load_json(path))
    incoming, report = sanitize_input(load_json(input_path))
    if not incoming:
        raise CliFailure("NO_PERSISTABLE_FACTS", "No confirmed, disclosure-cleared facts were eligible for persistence.", 1, report)
    merged: Dict[str, Dict[str, Any]] = {fact["id"]: fact for fact in existing["facts"]}
    added: List[str] = []
    replaced: List[str] = []
    for fact in incoming:
        if fact["id"] in merged:
            replaced.append(fact["id"])
        else:
            added.append(fact["id"])
        merged[fact["id"]] = fact
    updated = dict(existing)
    updated["updated_at"] = now_iso()
    updated["facts"] = sorted(merged.values(), key=lambda item: item["id"])
    atomic_write_json(path, updated)
    return {
        "ok": True,
        "kind": "career_store_operation",
        "action": "update",
        "path": str(path.resolve()),
        "written": True,
        "saved_fact_count": len(updated["facts"]),
        "added_fact_ids": sorted(added),
        "replaced_fact_ids": sorted(replaced),
        "filter_report": report,
        "target_independent": True,
    }


def reuse_store(path: Path, target_role: Optional[str], fact_types: Optional[List[str]]) -> Dict[str, Any]:
    before = file_digest(path)
    store = validate_existing_store(load_json(path))
    selected = list(store["facts"])
    if fact_types:
        allowed = set(fact_types)
        selected = [fact for fact in selected if fact.get("fact_type") in allowed]
    after = file_digest(path)
    if before != after:
        raise CliFailure("STORE_CHANGED_DURING_READ", "Career store changed while it was being reused; retry.", 2)
    return {
        "ok": True,
        "kind": "career_store_reuse",
        "action": "reuse",
        "path": str(path.resolve()),
        "written": False,
        "store_unchanged": True,
        "store_sha256": before,
        "request_context": {
            "target_role": target_role,
            "persisted_to_store": False,
            "note": "Target role and JD wording are request context only; derive new resume copy without changing fact meaning.",
        },
        "facts": selected,
        "fact_count": len(selected),
        "target_independent": True,
    }


def build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(description="Opt-in local career evidence store operations.")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for name in ("create", "update"):
        sub = subparsers.add_parser(name, help="{0} a career evidence store.".format(name.capitalize()))
        sub.add_argument("--path", required=True, help="User-selected .json store path outside the Skill package.")
        sub.add_argument("--input", required=True, help="JSON facts or resume package to sanitize and persist.")
        sub.add_argument("--opt-in", action="store_true", help="Confirm explicit user consent for this write.")
    reuse = subparsers.add_parser("reuse", help="Read confirmed facts without modifying the store.")
    reuse.add_argument("--path", required=True, help="User-selected .json store path.")
    reuse.add_argument("--opt-in", action="store_true", help="Confirm explicit user consent to reuse these facts.")
    reuse.add_argument("--target-role", help="Request-only target role; never persisted into the fact store.")
    reuse.add_argument("--fact-type", action="append", choices=sorted(FACT_TYPES), help="Optional repeatable fact-type filter.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    command = "career_store"
    try:
        args = parse_json_cli(build_parser(), argv)
        # Opt-in is checked before resolving paths or reading either input.
        if not args.opt_in:
            raise CliFailure(
                "PERSISTENCE_OPT_IN_REQUIRED",
                "No file was read or written. Career evidence storage/reuse requires explicit --opt-in and a user-selected path.",
                2,
            )
        if args.operation == "create":
            path = validated_output_path(args.path, must_exist=False)
            result = create_store(path, Path(args.input))
        elif args.operation == "update":
            path = validated_output_path(args.path, must_exist=True)
            result = update_store(path, Path(args.input))
        else:
            path = validated_output_path(args.path, must_exist=True)
            result = reuse_store(path, args.target_role, args.fact_type)
        emit(result)
        return 0
    except CliFailure as failure:
        return emit_failure(failure, command)


if __name__ == "__main__":
    sys.exit(main())
