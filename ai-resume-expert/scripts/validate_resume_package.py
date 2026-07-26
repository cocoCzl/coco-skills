#!/usr/bin/env python3
"""Validate resume evidence traceability and Markdown/PDF delivery gates.

This is deliberately a deterministic contract validator, not a resume writer.
It accepts either a ``resume_package`` or a standalone ``evidence_trace`` JSON
document and prints one JSON result.  A non-zero exit status means delivery is
blocked; warnings alone do not block delivery.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from _json_cli import CliFailure, JsonArgumentParser, emit, emit_failure, load_json, parse_json_cli


APPROVED_DISCLOSURE = {"approved", "sanitized"}
CONFIRMED_FACT_STATUSES = {"confirmed"}
PERSONAL_EXPERIENCE_FACT_TYPES = {"personal_contribution", "star_evidence"}
PERSONAL_CLAIM_TYPES = {"experience", "summary", "skill", "employment", "education", "other"}
CLAIM_TYPES = PERSONAL_CLAIM_TYPES | {"project_fact"}
VERSION_TYPES = {"role_baseline", "jd_tailored"}
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
FACT_STATUSES = {
    "observed_project_fact",
    "confirmed",
    "pending_confirmation",
    "information_gap",
    "conflict",
    "evidence_gap",
    "rejected",
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
SELF_REVIEW_CHECKS = {
    "facts",
    "target_alignment",
    "confidentiality",
    "duplication",
    "length",
    "defensibility",
}
PLACEHOLDER_RE = re.compile(r"(?:\bTBD\b|\bTODO\b|\[待补|待补充|请填写|<[^>]{1,40}>)", re.IGNORECASE)
QUANTIFIED_RESULT_RE = re.compile(
    r"(?:"
    r"\d+(?:\.\d+)?\s*(?:%|％|倍|万|亿|毫秒|ms|秒|分钟|小时|天|条|次|个|台|节点|QPS|TPS)"
    r"|(?:提升|降低|缩短|减少|增加|优化|节省|处理|支持|覆盖|达到|从).{0,18}\d+(?:\.\d+)?"
    r")",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def issue(code: str, path: str, message: str) -> Dict[str, str]:
    return {"code": code, "path": path, "message": message}


def require_mapping(value: Any, path: str, errors: List[Dict[str, str]]) -> Dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(issue("INVALID_TYPE", path, "Expected an object."))
        return {}
    return value


def require_list(value: Any, path: str, errors: List[Dict[str, str]]) -> List[Any]:
    if not isinstance(value, list):
        errors.append(issue("INVALID_TYPE", path, "Expected an array."))
        return []
    return value


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_fact_structure(
    facts_value: Any,
    errors: List[Dict[str, str]],
    warnings: List[Dict[str, str]],
) -> Tuple[Dict[str, Dict[str, Any]], Set[str]]:
    facts = require_list(facts_value, "$.career_facts", errors)
    fact_map: Dict[str, Dict[str, Any]] = {}
    unresolved: Set[str] = set()
    for index, raw in enumerate(facts):
        path = "$.career_facts[{0}]".format(index)
        fact = require_mapping(raw, path, errors)
        fact_id = fact.get("id")
        if not nonempty_string(fact_id):
            errors.append(issue("MISSING_FACT_ID", path + ".id", "Every fact needs a stable id."))
            continue
        if fact_id in fact_map:
            errors.append(issue("DUPLICATE_FACT_ID", path + ".id", "Fact id is duplicated: {0}".format(fact_id)))
            continue
        fact_map[fact_id] = fact
        if not nonempty_string(fact.get("statement")):
            errors.append(issue("EMPTY_FACT", path + ".statement", "Fact statement cannot be empty."))
        status = fact.get("status")
        if fact.get("fact_type") not in FACT_TYPES:
            errors.append(issue("INVALID_FACT_TYPE", path + ".fact_type", "Unknown fact_type is not allowed."))
        if status not in FACT_STATUSES:
            errors.append(issue("INVALID_FACT_STATUS", path + ".status", "Unknown fact status is not allowed."))
        sources = fact.get("sources") if isinstance(fact.get("sources"), list) else []
        if not sources:
            errors.append(issue("MISSING_FACT_SOURCE", path + ".sources", "Every fact needs at least one source locator."))
        seen_source_ids: Set[str] = set()
        for source_index, source in enumerate(sources):
            source_path = path + ".sources[{0}]".format(source_index)
            if not isinstance(source, dict):
                errors.append(issue("INVALID_FACT_SOURCE", source_path, "Fact source must be an object."))
                continue
            source_id = source.get("source_id")
            if not nonempty_string(source_id) or not nonempty_string(source.get("locator")):
                errors.append(issue("INVALID_FACT_SOURCE", source_path, "Fact source needs source_id and locator."))
            elif source_id in seen_source_ids:
                errors.append(issue("DUPLICATE_SOURCE_ID", source_path + ".source_id", "Source id is duplicated within this fact."))
            else:
                seen_source_ids.add(source_id)
            if source.get("type") not in SOURCE_TYPES:
                errors.append(issue("INVALID_SOURCE_TYPE", source_path + ".type", "Unknown source type is not allowed."))
        conflict = fact.get("conflict") if isinstance(fact.get("conflict"), dict) else {}
        if conflict.get("status") not in {"none", "unresolved", "resolved"}:
            errors.append(issue("INVALID_CONFLICT_STATUS", path + ".conflict.status", "Fact conflict status is missing or invalid."))
        if conflict.get("status") == "resolved" and (
            conflict.get("resolved_by_user") is not True or not nonempty_string(conflict.get("resolution"))
        ):
            errors.append(
                issue(
                    "UNCONFIRMED_CONFLICT_RESOLUTION",
                    path + ".conflict",
                    "A resolved conflict needs a user-confirmed resolution before its facts can be used.",
                )
            )
        if status == "conflict" or conflict.get("status") == "unresolved":
            unresolved.add(fact_id)
            errors.append(
                issue(
                    "UNRESOLVED_CONFLICT",
                    path + ".conflict",
                    "Every unresolved fact conflict blocks the Markdown draft, even when the fact is not currently selected.",
                )
            )
        ownership = fact.get("ownership") if isinstance(fact.get("ownership"), dict) else {}
        if ownership.get("status") not in {"confirmed", "pending", "not_applicable", "rejected"} or not isinstance(ownership.get("confirmed_by_user"), bool):
            errors.append(issue("INVALID_OWNERSHIP_STATUS", path + ".ownership", "Ownership status and confirmation boolean are required."))
        if fact.get("fact_type") == "personal_contribution":
            if status != "confirmed" or ownership.get("status") != "confirmed" or ownership.get("confirmed_by_user") is not True:
                errors.append(
                    issue(
                        "UNCONFIRMED_PERSONAL_CONTRIBUTION",
                        path,
                        "A personal contribution must be explicitly confirmed by the user.",
                    )
                )
        disclosure = fact.get("disclosure") if isinstance(fact.get("disclosure"), dict) else {}
        disclosure_status = disclosure.get("status")
        if disclosure_status not in {"approved", "sanitized", "needs_redaction", "blocked", "unknown"}:
            errors.append(issue("INVALID_DISCLOSURE_STATUS", path + ".disclosure.status", "Disclosure status is missing or invalid."))
        if disclosure_status in APPROVED_DISCLOSURE and disclosure.get("confirmed_by_user") is not True:
            errors.append(
                issue(
                    "DISCLOSURE_NOT_USER_CONFIRMED",
                    path + ".disclosure.confirmed_by_user",
                    "Approved or sanitized disclosure requires explicit user confirmation.",
                )
            )
        if disclosure_status == "sanitized" and not nonempty_string(disclosure.get("sanitized_statement")):
            errors.append(
                issue(
                    "SANITIZED_STATEMENT_REQUIRED",
                    path + ".disclosure.sanitized_statement",
                    "A sanitized fact needs the user-confirmed statement that is safe to disclose.",
                )
            )
        if disclosure_status in {"needs_redaction", "blocked", "unknown"}:
            warnings.append(
                issue(
                    "FACT_DISCLOSURE_NOT_CLEARED",
                    path + ".disclosure.status",
                    "This fact cannot support an included claim until disclosure is approved or sanitized.",
                )
            )
        statement = fact.get("statement") if isinstance(fact.get("statement"), str) else ""
        quantification = fact.get("quantification") if isinstance(fact.get("quantification"), dict) else None
        appears_quantified = bool(QUANTIFIED_RESULT_RE.search(statement))
        numeric_kind = quantification and quantification.get("kind") in {"numeric", "range"}
        if appears_quantified or numeric_kind:
            source_ids = quantification.get("source_ids") if quantification else None
            known_source_ids = {
                source.get("source_id")
                for source in fact.get("sources", [])
                if isinstance(source, dict) and nonempty_string(source.get("source_id"))
            }
            if (
                not quantification
                or not nonempty_string(quantification.get("basis"))
                or quantification.get("confirmed_by_user") is not True
                or not isinstance(source_ids, list)
                or not source_ids
            ):
                errors.append(
                    issue(
                        "UNVERIFIED_QUANTIFICATION",
                        path + ".quantification",
                        "A quantified fact needs a traceable basis, source ids, and user confirmation.",
                    )
                )
            elif not set(source_ids).issubset(known_source_ids):
                errors.append(
                    issue(
                        "UNKNOWN_QUANTIFICATION_SOURCE",
                        path + ".quantification.source_ids",
                        "Every quantification source id must resolve to a source on the same fact.",
                    )
                )
    return fact_map, unresolved


def validate_trace_contract(
    claims_value: Any,
    trace_value: Any,
    fact_map: Dict[str, Dict[str, Any]],
    unresolved_fact_ids: Set[str],
    errors: List[Dict[str, str]],
) -> None:
    claims = require_list(claims_value, "$.claims", errors)
    traces = require_list(trace_value, "$.evidence_trace", errors)
    trace_map: Dict[str, Dict[str, Any]] = {}
    for index, raw in enumerate(traces):
        path = "$.evidence_trace[{0}]".format(index)
        trace = require_mapping(raw, path, errors)
        claim_id = trace.get("claim_id")
        if not nonempty_string(claim_id):
            errors.append(issue("MISSING_TRACE_CLAIM_ID", path + ".claim_id", "Trace entry needs a claim id."))
            continue
        if claim_id in trace_map:
            errors.append(issue("DUPLICATE_TRACE", path, "Only one trace entry is allowed per claim."))
        trace_map[claim_id] = trace

    seen_claim_ids: Set[str] = set()
    for index, raw in enumerate(claims):
        path = "$.claims[{0}]".format(index)
        claim = require_mapping(raw, path, errors)
        claim_id = claim.get("id")
        if not nonempty_string(claim_id):
            errors.append(issue("MISSING_CLAIM_ID", path + ".id", "Every claim needs a stable id."))
            continue
        if claim_id in seen_claim_ids:
            errors.append(issue("DUPLICATE_CLAIM_ID", path + ".id", "Claim id is duplicated."))
        seen_claim_ids.add(claim_id)
        if claim.get("included") is not True:
            continue
        claim_type = claim.get("claim_type")
        if claim_type not in CLAIM_TYPES:
            errors.append(issue("INVALID_CLAIM_TYPE", path + ".claim_type", "Unknown claim_type cannot bypass ownership rules."))
        fact_ids_raw = claim.get("fact_ids")
        fact_ids = fact_ids_raw if isinstance(fact_ids_raw, list) else []
        if not fact_ids:
            errors.append(issue("UNTRACED_CLAIM", path + ".fact_ids", "An included claim must cite at least one fact."))
        for fact_id in fact_ids:
            if fact_id not in fact_map:
                errors.append(issue("UNKNOWN_FACT_REFERENCE", path + ".fact_ids", "Unknown fact id: {0}".format(fact_id)))
            elif fact_id in unresolved_fact_ids:
                errors.append(issue("UNRESOLVED_CONFLICT", path + ".fact_ids", "Claim uses a fact with an unresolved conflict: {0}".format(fact_id)))
            elif fact_map[fact_id].get("status") not in CONFIRMED_FACT_STATUSES:
                errors.append(
                    issue(
                        "UNCONFIRMED_FACT_REFERENCE",
                        path + ".fact_ids",
                        "Included claim uses an unconfirmed fact: {0}".format(fact_id),
                    )
                )
            if fact_id in fact_map:
                disclosure = fact_map[fact_id].get("disclosure")
                disclosure_status = disclosure.get("status") if isinstance(disclosure, dict) else None
                if disclosure_status not in APPROVED_DISCLOSURE:
                    errors.append(
                        issue(
                            "CONFIDENTIALITY_BLOCK",
                            path + ".fact_ids",
                            "Fact {0} is not approved or sanitized for disclosure.".format(fact_id),
                        )
                    )
                elif disclosure.get("confirmed_by_user") is not True:
                    errors.append(
                        issue(
                            "DISCLOSURE_NOT_USER_CONFIRMED",
                            path + ".fact_ids",
                            "Fact {0} lacks explicit user confirmation for disclosure.".format(fact_id),
                        )
                    )
                elif disclosure_status == "sanitized" and not nonempty_string(disclosure.get("sanitized_statement")):
                    errors.append(
                        issue(
                            "SANITIZED_STATEMENT_REQUIRED",
                            path + ".fact_ids",
                            "Fact {0} is sanitized but has no safe replacement statement.".format(fact_id),
                        )
                    )

        trace = trace_map.get(claim_id)
        if trace is None:
            errors.append(issue("MISSING_TRACE_ENTRY", path, "Included claim has no evidence trace entry."))
            continue
        trace_fact_ids = trace.get("fact_ids") if isinstance(trace.get("fact_ids"), list) else []
        if set(trace_fact_ids) != set(fact_ids):
            errors.append(
                issue(
                    "TRACE_FACT_MISMATCH",
                    "$.evidence_trace",
                    "Trace fact ids must exactly match claim {0}.".format(claim_id),
                )
            )
        ownership_is_required = claim_type != "project_fact" or claim.get("ownership_required") is True
        referenced_facts = [fact_map[fact_id] for fact_id in fact_ids if fact_id in fact_map]
        confirmed_owned_facts = [
            fact
            for fact in referenced_facts
            if fact.get("status") == "confirmed"
            and isinstance(fact.get("ownership"), dict)
            and fact["ownership"].get("status") == "confirmed"
            and fact["ownership"].get("confirmed_by_user") is True
        ]
        if ownership_is_required:
            if claim.get("ownership_confirmed") is not True or trace.get("ownership_confirmed") is not True:
                errors.append(
                    issue(
                        "UNCONFIRMED_PERSONAL_CONTRIBUTION",
                        path,
                        "A claimed personal contribution needs user ownership confirmation in both claim and trace.",
                    )
                )
            if not confirmed_owned_facts:
                errors.append(
                    issue(
                        "PROJECT_FACT_CANNOT_PROVE_OWNERSHIP",
                        path + ".fact_ids",
                        "Observed project facts may be contextual evidence, but a personal claim also needs a user-confirmed owned fact.",
                    )
                )
        if claim_type == "experience" and not any(
            fact.get("fact_type") in PERSONAL_EXPERIENCE_FACT_TYPES for fact in confirmed_owned_facts
        ):
            errors.append(
                issue(
                    "MISSING_CONFIRMED_EXPERIENCE_EVIDENCE",
                    path + ".fact_ids",
                    "An experience claim needs a confirmed personal_contribution or STAR evidence fact; repository capability alone is insufficient.",
                )
            )
        if claim.get("disclosure_status") not in APPROVED_DISCLOSURE or trace.get("disclosure_status") not in APPROVED_DISCLOSURE:
            errors.append(issue("CONFIDENTIALITY_BLOCK", path, "Claim disclosure is not approved or sanitized."))

        text = claim.get("text") if isinstance(claim.get("text"), str) else ""
        quantification = claim.get("quantification") if isinstance(claim.get("quantification"), dict) else None
        appears_quantified = bool(QUANTIFIED_RESULT_RE.search(text))
        numeric_kind = quantification and quantification.get("kind") in {"numeric", "range"}
        if appears_quantified or numeric_kind:
            source_ids = quantification.get("source_ids") if quantification else None
            known_source_ids = {
                source.get("source_id")
                for fact in referenced_facts
                for source in fact.get("sources", [])
                if isinstance(source, dict) and nonempty_string(source.get("source_id"))
            }
            if (
                not quantification
                or not nonempty_string(quantification.get("basis"))
                or quantification.get("confirmed_by_user") is not True
                or not isinstance(source_ids, list)
                or not source_ids
                or trace.get("quantification_confirmed") is not True
            ):
                errors.append(
                    issue(
                        "UNVERIFIED_QUANTIFICATION",
                        path + ".quantification",
                        "A numeric or range result needs a traceable basis, source ids, and user confirmation.",
                    )
                )
            elif not set(source_ids).issubset(known_source_ids):
                errors.append(
                    issue(
                        "UNKNOWN_QUANTIFICATION_SOURCE",
                        path + ".quantification.source_ids",
                        "Every claim quantification source id must resolve through its cited facts.",
                    )
                )


def validate_resume_package(document: Dict[str, Any], requested_stage: Optional[str]) -> Dict[str, Any]:
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    if document.get("schema_version") != "1.0":
        errors.append(issue("UNSUPPORTED_SCHEMA_VERSION", "$.schema_version", "Expected schema_version 1.0."))
    if document.get("kind") != "resume_package":
        errors.append(issue("INVALID_KIND", "$.kind", "Expected kind resume_package."))

    document_stage = document.get("stage")
    if requested_stage is None:
        stage = "pdf" if document_stage == "pdf_ready" else "markdown"
    else:
        stage = requested_stage
    expected_document_stage = "pdf_ready" if stage == "pdf" else "markdown_draft"
    if document_stage != expected_document_stage:
        errors.append(
            issue(
                "STAGE_MISMATCH",
                "$.stage",
                "Validation stage {0} requires package stage {1}.".format(stage, expected_document_stage),
            )
        )

    target = require_mapping(document.get("target"), "$.target", errors)
    for name in ("role", "level", "market", "language", "version_type"):
        if not nonempty_string(target.get(name)):
            errors.append(issue("MISSING_TARGET", "$.target." + name, "Target {0} is required.".format(name)))
    if target.get("version_type") not in VERSION_TYPES:
        errors.append(issue("INVALID_VERSION_TYPE", "$.target.version_type", "version_type must be role_baseline or jd_tailored."))

    timeline = require_list(document.get("timeline"), "$.timeline", errors)
    if not timeline:
        errors.append(issue("MISSING_TIMELINE", "$.timeline", "At least one employment, education, or internship timeline item is required."))
    for index, raw in enumerate(timeline):
        entry = require_mapping(raw, "$.timeline[{0}]".format(index), errors)
        if entry.get("confirmed_by_user") is not True:
            errors.append(issue("UNCONFIRMED_TIMELINE", "$.timeline[{0}]".format(index), "Timeline item must be confirmed by the user."))
        for name in ("organization", "role", "start", "end"):
            if not nonempty_string(entry.get(name)):
                errors.append(issue("INCOMPLETE_TIMELINE", "$.timeline[{0}].{1}".format(index, name), "Timeline value is required."))

    fact_map, unresolved_fact_ids = validate_fact_structure(document.get("career_facts"), errors, warnings)
    validate_trace_contract(document.get("claims"), document.get("evidence_trace"), fact_map, unresolved_fact_ids, errors)

    claims = document.get("claims") if isinstance(document.get("claims"), list) else []
    included_claims = [claim for claim in claims if isinstance(claim, dict) and claim.get("included") is True]
    if not included_claims:
        errors.append(issue("NO_INCLUDED_CLAIMS", "$.claims", "A draft needs at least one included claim."))
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict) or claim.get("included") is not True:
            continue
        path = "$.claims[{0}]".format(index)
        text = claim.get("text") if isinstance(claim.get("text"), str) else ""
        if not text.strip():
            errors.append(issue("EMPTY_CLAIM", path + ".text", "Included claim text cannot be empty."))
        elif PLACEHOLDER_RE.search(text):
            errors.append(issue("PLACEHOLDER_IN_CLAIM", path + ".text", "Included claims cannot contain unresolved placeholders."))
        if claim.get("claim_type") == "experience":
            star = claim.get("star") if isinstance(claim.get("star"), dict) else {}
            for name in ("role", "action", "result"):
                if not nonempty_string(star.get(name)):
                    errors.append(issue("INCOMPLETE_STAR_EVIDENCE", path + ".star." + name, "Experience needs a confirmed role, action, and result."))
            if star.get("confirmed_by_user") is not True:
                errors.append(issue("UNCONFIRMED_STAR_EVIDENCE", path + ".star", "Experience STAR evidence must be user-confirmed."))
        if claim.get("interview_defensible") is not True:
            errors.append(issue("NOT_INTERVIEW_DEFENSIBLE", path, "Included claim has not passed interview-defensibility review."))

    skills = require_list(document.get("skills"), "$.skills", errors)
    for index, raw in enumerate(skills):
        path = "$.skills[{0}]".format(index)
        skill = require_mapping(raw, path, errors)
        fact_ids = skill.get("fact_ids") if isinstance(skill.get("fact_ids"), list) else []
        if not fact_ids:
            errors.append(issue("UNSUPPORTED_SKILL", path + ".fact_ids", "Every listed skill needs experience evidence."))
        supporting_facts: List[Dict[str, Any]] = []
        for fact_id in fact_ids:
            if fact_id not in fact_map or fact_map[fact_id].get("status") != "confirmed":
                errors.append(issue("UNSUPPORTED_SKILL", path + ".fact_ids", "Skill references an unknown or unconfirmed fact: {0}".format(fact_id)))
            else:
                supporting_facts.append(fact_map[fact_id])
        personal_experience_support = [
            fact
            for fact in supporting_facts
            if fact.get("fact_type") in PERSONAL_EXPERIENCE_FACT_TYPES
            and isinstance(fact.get("ownership"), dict)
            and fact["ownership"].get("status") == "confirmed"
            and fact["ownership"].get("confirmed_by_user") is True
        ]
        if not personal_experience_support:
            errors.append(
                issue(
                    "SKILL_LACKS_PERSONAL_EXPERIENCE_EVIDENCE",
                    path + ".fact_ids",
                    "A listed skill needs a confirmed personal contribution or STAR evidence, not only a project capability or self-labelled skill fact.",
                )
            )
        if skill.get("confirmed_by_user") is not True:
            errors.append(issue("UNCONFIRMED_SKILL", path, "Skill and proficiency must be user-confirmed."))
        if skill.get("proficiency") == "expert" and skill.get("expertise_confirmed_by_user") is not True:
            errors.append(issue("UNSUPPORTED_EXPERTISE", path, "Expert-level wording needs separate strong-evidence confirmation."))
        name = skill.get("name") if isinstance(skill.get("name"), str) else ""
        if re.search(r"\b\d{1,3}\s*%", name):
            errors.append(issue("SKILL_PERCENTAGE_FORBIDDEN", path + ".name", "Skill percentages are not evidence-backed proficiency."))

    conflicts = require_list(document.get("conflicts"), "$.conflicts", errors)
    for index, conflict in enumerate(conflicts):
        path = "$.conflicts[{0}]".format(index)
        if not isinstance(conflict, dict):
            errors.append(issue("INVALID_CONFLICT", path, "Conflict entry must be an object."))
            continue
        if conflict.get("status") == "unresolved":
            errors.append(issue("UNRESOLVED_CONFLICT", path, "All fact conflicts must be resolved before a draft."))
        elif conflict.get("status") == "resolved" and (
            conflict.get("resolved_by_user") is not True or not nonempty_string(conflict.get("resolution"))
        ):
            errors.append(
                issue(
                    "UNCONFIRMED_CONFLICT_RESOLUTION",
                    path,
                    "A resolved conflict needs a user-confirmed resolution before delivery.",
                )
            )
    blockers = require_list(document.get("confidentiality_blockers"), "$.confidentiality_blockers", errors)
    if blockers:
        errors.append(issue("CONFIDENTIALITY_BLOCK", "$.confidentiality_blockers", "Confidentiality blockers must be cleared before delivery."))

    markdown = require_mapping(document.get("markdown"), "$.markdown", errors)
    review = require_mapping(markdown.get("self_review"), "$.markdown.self_review", errors)
    for check in sorted(SELF_REVIEW_CHECKS):
        if review.get(check) is not True:
            errors.append(issue("SELF_REVIEW_INCOMPLETE", "$.markdown.self_review." + check, "This self-review check must pass before delivery."))

    contact = require_mapping(document.get("contact"), "$.contact", errors)
    if stage == "pdf":
        if markdown.get("confirmed_by_user") is not True:
            errors.append(issue("MARKDOWN_NOT_CONFIRMED", "$.markdown.confirmed_by_user", "Explicit Markdown confirmation is required before PDF generation."))
        if contact.get("confirmed_by_user") is not True:
            errors.append(issue("CONTACT_NOT_CONFIRMED", "$.contact.confirmed_by_user", "Contact details must be user-confirmed before PDF generation."))
        for name in ("name", "phone", "email", "city"):
            if not nonempty_string(contact.get(name)):
                errors.append(issue("MISSING_CONTACT", "$.contact." + name, "Final PDF requires {0}.".format(name)))
        if not nonempty_string(markdown.get("path")):
            errors.append(issue("MISSING_CONFIRMED_MARKDOWN_PATH", "$.markdown.path", "Final PDF requires the confirmed Markdown file path."))
        markdown_hash = markdown.get("sha256")
        if not isinstance(markdown_hash, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", markdown_hash):
            errors.append(issue("MISSING_CONFIRMED_MARKDOWN_HASH", "$.markdown.sha256", "Final PDF requires the SHA-256 of the confirmed Markdown content."))
        if not nonempty_string(markdown.get("confirmed_at")):
            errors.append(issue("MISSING_MARKDOWN_CONFIRMATION_TIME", "$.markdown.confirmed_at", "Final PDF requires an explicit Markdown confirmation timestamp."))
        if nonempty_string(contact.get("email")) and not EMAIL_RE.match(contact["email"]):
            errors.append(issue("INVALID_EMAIL", "$.contact.email", "Email address format is invalid."))
        if nonempty_string(contact.get("phone")):
            digits = re.sub(r"\D", "", contact["phone"])
            if len(digits) < 7:
                errors.append(issue("INVALID_PHONE", "$.contact.phone", "Phone number is too short."))
    else:
        if not all(nonempty_string(contact.get(name)) for name in ("name", "phone", "email")):
            warnings.append(issue("CONTACT_OPTIONAL_AT_MARKDOWN", "$.contact", "Contact details may be completed at Markdown review, but are mandatory before PDF."))

    return {
        "ok": not errors,
        "kind": "resume_package_validation",
        "stage": stage,
        "valid": not errors,
        "delivery_blocked": bool(errors),
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "facts": len(fact_map),
            "included_claims": len(included_claims),
            "skills": len(skills),
            "blocking_errors": len(errors),
        },
    }


def validate_standalone_trace(document: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    if document.get("schema_version") != "1.0":
        errors.append(issue("UNSUPPORTED_SCHEMA_VERSION", "$.schema_version", "Expected schema_version 1.0."))
    if document.get("kind") != "evidence_trace":
        errors.append(issue("INVALID_KIND", "$.kind", "Expected kind evidence_trace."))
    facts = document.get("facts")
    fact_map, unresolved = validate_fact_structure(facts, errors, warnings)
    # Standalone trace claims intentionally contain only identity and fact
    # links. Enrich an in-memory copy from the trace entry so shared reference,
    # conflict, ownership, and disclosure checks remain just as strict without
    # requiring resume wording in the trace artifact.
    entries = document.get("entries") if isinstance(document.get("entries"), list) else []
    entry_map = {
        entry.get("claim_id"): entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("claim_id"), str)
    }
    enriched_claims: List[Dict[str, Any]] = []
    raw_claims = document.get("claims") if isinstance(document.get("claims"), list) else []
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, dict):
            enriched_claims.append(raw_claim)
            continue
        trace = entry_map.get(raw_claim.get("id"), {})
        claim = dict(raw_claim)
        claim["ownership_required"] = True
        claim["ownership_confirmed"] = trace.get("ownership_confirmed") is True
        claim["disclosure_status"] = trace.get("disclosure_status")
        enriched_claims.append(claim)
    validate_trace_contract(enriched_claims, entries, fact_map, unresolved, errors)
    return {
        "ok": not errors,
        "kind": "evidence_trace_validation",
        "valid": not errors,
        "delivery_blocked": bool(errors),
        "errors": errors,
        "warnings": warnings,
        "summary": {"facts": len(fact_map), "blocking_errors": len(errors)},
    }


def build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(description="Validate AI Resume Expert package and evidence trace JSON.")
    parser.add_argument("input", help="Path to resume_package or evidence_trace JSON.")
    parser.add_argument(
        "--stage",
        choices=("markdown", "pdf"),
        help="Override the delivery gate inferred from resume_package.stage.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    command = "validate_resume_package"
    try:
        args = parse_json_cli(build_parser(), argv)
        document = load_json(Path(args.input))
        if not isinstance(document, dict):
            raise CliFailure("INVALID_DOCUMENT", "Top-level JSON value must be an object.", 2)
        if document.get("kind") == "evidence_trace":
            if args.stage:
                raise CliFailure("INVALID_ARGUMENTS", "--stage is only valid for a resume_package.", 2)
            result = validate_standalone_trace(document)
        else:
            result = validate_resume_package(document, args.stage)
        emit(result)
        return 0 if result["valid"] else 1
    except CliFailure as failure:
        return emit_failure(failure, command)


if __name__ == "__main__":
    sys.exit(main())
