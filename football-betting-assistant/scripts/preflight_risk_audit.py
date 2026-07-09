#!/usr/bin/env python3
"""Audit pre-match ticket plans for avoidable protection and tail-risk misses."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from handicap_rules import (
    handicap_text_conflicts,
    mapping_table_text,
    missing_handicap_outcomes,
    parse_handicap_line,
    score_tuple,
    split_scores,
)

MAIN_PLAN_MARKERS = ("模型最稳", "model_best", "稳健方向", "stable")
LOW_DATA_FLAGS = {"single_source_odds", "lineup_unconfirmed", "ordinary_result_odds_not_visible"}
HIGH_TAIL_FLAGS = {
    "high_total_xg_tail",
    "five_plus_goal_tail",
    "deep_handicap_tail",
    "goal_difference_pressure_tail",
    "red_card_tail",
    "penalty_tail",
    "weather_delay_tail",
    "altitude_tail",
    "home_crowd_tail",
    "chase_game_tail",
    "late_goal_expansion",
}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _split_scores(value: Any) -> list[str]:
    return split_scores(value)


def _score_tuple(score: str) -> tuple[int, int] | None:
    return score_tuple(score)


def _selected_totals(value: Any) -> set[int]:
    return {int(item) for item in re.findall(r"\d+", _text(value))}


def _parse_line(*values: Any) -> float | None:
    return parse_handicap_line(*values)


def _result_label(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "胜"
    if home_goals == away_goals:
        return "平"
    return "负"


def _normalize_match_name(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("：", ":").lower()


def _fixture_name(record: dict[str, Any]) -> str:
    if record.get("match"):
        return str(record["match"])
    fixture = record.get("fixture") or {}
    home = fixture.get("home_team") or record.get("home_team")
    away = fixture.get("away_team") or record.get("away_team")
    if home and away:
        return f"{home} vs {away}"
    return str(record.get("name") or "")


def _record_scores(record: dict[str, Any]) -> list[str]:
    for key in ("score_candidates", "core_scores", "enhanced_scores", "score_coverage"):
        scores = _split_scores(record.get(key))
        if scores:
            return scores
    return []


def _record_grade(record: dict[str, Any]) -> str:
    return str(record.get("grade") or record.get("reference_grade") or "")


def _record_flags(record: dict[str, Any]) -> set[str]:
    flags: set[str] = set()
    for key in ("risk_flags", "tail_risk_flags", "downgrade_reasons", "risk_points"):
        flags.update(str(item) for item in _as_list(record.get(key)))
    return flags


def _extract_records(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    data = document.get("data") if isinstance(document.get("data"), dict) else {}
    for root in (document, data):
        model_outputs = root.get("model_outputs") if isinstance(root.get("model_outputs"), dict) else {}
        candidates.extend(item for item in _as_list(model_outputs.get("match_records")) if isinstance(item, dict))
        candidates.extend(item for item in _as_list(model_outputs.get("match_analyses")) if isinstance(item, dict))
        candidates.extend(item for item in _as_list(root.get("match_analyses")) if isinstance(item, dict))

    records: dict[str, dict[str, Any]] = {}
    for record in candidates:
        name = _fixture_name(record)
        if name:
            records[_normalize_match_name(name)] = record
    return records


def _extract_ticket_plans(document: dict[str, Any]) -> list[dict[str, Any]]:
    data = document.get("data") if isinstance(document.get("data"), dict) else {}
    plans: list[dict[str, Any]] = []
    for root in (document, data):
        plans.extend(item for item in _as_list(root.get("ticket_plans")) if isinstance(item, dict))
        model_outputs = root.get("model_outputs") if isinstance(root.get("model_outputs"), dict) else {}
        plans.extend(item for item in _as_list(model_outputs.get("ticket_plans")) if isinstance(item, dict))
    return plans


def _parse_string_leg(value: str) -> dict[str, Any]:
    match = re.match(r"\s*(.*?)\s*[：:]\s*(.*)\s*$", value)
    if not match:
        return {"match": value, "selection": ""}
    selection = match.group(2).strip()
    market = ""
    if "让" in selection or re.search(r"[-+]\d", selection):
        market = "让球胜平负"
    elif "进球" in selection or re.search(r"\b\d\s*/\s*\d", selection):
        market = "总进球"
    elif re.search(r"\d+\s*:\s*\d+", selection):
        market = "比分"
    else:
        market = "胜平负"
    return {"match": match.group(1).strip(), "market": market, "selection": selection}


def _plan_legs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    legs: list[dict[str, Any]] = []
    for item in _as_list(plan.get("legs")):
        if isinstance(item, dict):
            legs.append(dict(item))
        elif isinstance(item, str):
            legs.append(_parse_string_leg(item))
    return legs


def _is_main_plan(plan: dict[str, Any]) -> bool:
    text = " ".join(_text(plan.get(key)) for key in ("name", "type", "risk_level"))
    return any(marker in text for marker in MAIN_PLAN_MARKERS)


def _find_record_for_leg(leg: dict[str, Any], records: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    match_text = _normalize_match_name(str(leg.get("match") or ""))
    if match_text in records:
        return records[match_text]
    for key, record in records.items():
        if match_text and (match_text in key or key in match_text):
            return record
    return None


def _issue(match_name: str, plan_name: str, severity: str, code: str, message: str, action: str) -> dict[str, str]:
    return {
        "match": match_name,
        "plan": plan_name,
        "severity": severity,
        "code": code,
        "message": message,
        "recommended_action": action,
    }


def _audit_leg(plan: dict[str, Any], leg: dict[str, Any], record: dict[str, Any] | None) -> list[dict[str, str]]:
    plan_name = str(plan.get("name") or plan.get("type") or "unnamed_plan")
    match_name = str(leg.get("match") or (record and _fixture_name(record)) or "unknown_match")
    market = _text(leg.get("market") or leg.get("source_snapshot_market") or "")
    selection = _text(leg.get("selection") or leg.get("protected_selection") or "")
    issues: list[dict[str, str]] = []
    if not record:
        issues.append(_issue(match_name, plan_name, "warning", "match_record_missing", "No structured match record found for this leg.", "Downgrade the leg unless the analysis record is supplied."))
        return issues

    scores = _record_scores(record)
    flags = _record_flags(record)
    grade = _record_grade(record)
    is_main = _is_main_plan(plan)

    if is_main and grade.startswith("B") and (flags & LOW_DATA_FLAGS):
        issues.append(_issue(match_name, plan_name, "block", "b_grade_low_data_in_main", "B-grade/B-minus leg with single-source odds or unconfirmed lineup appears in a main/stable plan.", "Move the leg to backup or reduce the plan label from model-best/stable."))

    if is_main and grade in {"C", "C+"}:
        issues.append(_issue(match_name, plan_name, "block", "c_grade_in_main", "C-grade leg appears in a main/stable plan.", "Exclude from conservative main plans."))

    if "总进球" in market or "total_goals" in market or "进球" in selection:
        selected = _selected_totals(selection)
        score_totals = {sum(pair) for score in scores if (pair := _score_tuple(score))}
        if 1 in score_totals and selected and 1 not in selected:
            issues.append(_issue(match_name, plan_name, "block", "one_goal_total_omitted", "Score candidates include a 1-goal path but the total-goals selection omits 1.", "Add total goals 1, create a backup leg, or downgrade this totals leg."))
        if (flags & HIGH_TAIL_FLAGS) and selected and max(selected) < 5:
            issues.append(_issue(match_name, plan_name, "warning", "five_goal_tail_omitted", "Tail-risk flags are present but the total-goals selection stops below 5.", "Add 4/5 protection where buyable or move totals to a high-variance backup plan."))

    if "让" in market or "handicap" in market or re.search(r"[-+]\d", selection):
        line = _parse_line(
            leg.get("source_line"),
            leg.get("line"),
            leg.get("handicap_line"),
            record.get("handicap_line") if record else None,
            record.get("handicap_pick") if record else None,
            market,
            selection,
        )
        if line is not None and scores:
            omitted = missing_handicap_outcomes(selection, scores, line, limit=5)
            if omitted:
                issues.append(_issue(match_name, plan_name, "block", "handicap_protection_omitted", f"Top score candidates imply handicap outcomes {', '.join(omitted)} that are not selected.", "Expand the handicap selection or remove this leg from the main plan."))
            mapping = mapping_table_text(scores, line, limit=5)
            conflict_text = " ".join(
                _text(value)
                for value in (
                    market,
                    selection,
                    leg.get("reason"),
                    leg.get("analysis"),
                )
            )
            conflicts = handicap_text_conflicts(conflict_text, line)
            if conflicts:
                issues.append(
                    _issue(
                        match_name,
                        plan_name,
                        "block",
                        "handicap_text_mapping_conflict",
                        f"Handicap prose conflicts with the handicap formula. Mapping: {mapping}. Conflict: {'; '.join(conflicts)}.",
                        "Rewrite the handicap explanation and ticket selection using the score-to-handicap mapping.",
                    )
                )

    if "比分" in market or "correct_score" in market:
        selected_scores = set(_split_scores(selection))
        candidate_scores = set(scores[:5])
        if selected_scores and not selected_scores & candidate_scores:
            issues.append(_issue(match_name, plan_name, "warning", "score_selection_off_matrix", "Selected score is outside the top score candidate set.", "Explain the cold-score thesis or move it to an optional high-variance ticket."))

    if flags & {"underdog_transition_threat", "opponent_transition_threat"}:
        underdog_two_goal = any(pair and pair[1] >= 2 for score in scores for pair in [_score_tuple(score)])
        if not underdog_two_goal and is_main:
            issues.append(_issue(match_name, plan_name, "warning", "transition_two_goal_path_missing", "The analysis flags underdog transition threat but no opponent two-goal path is in score coverage.", "Add a two-goal opponent path to coverage or downgrade the direction leg."))

    return issues


def audit(document: dict[str, Any]) -> dict[str, Any]:
    records = _extract_records(document)
    plans = _extract_ticket_plans(document)
    issues: list[dict[str, str]] = []
    for plan in plans:
        for leg in _plan_legs(plan):
            record = _find_record_for_leg(leg, records)
            issues.extend(_audit_leg(plan, leg, record))

    blocks = [item for item in issues if item["severity"] == "block"]
    warnings = [item for item in issues if item["severity"] == "warning"]
    return {
        "kind": "risk_audit_record",
        "summary": {
            "match_records_found": len(records),
            "ticket_plans_found": len(plans),
            "issues": len(issues),
            "blocks": len(blocks),
            "warnings": len(warnings),
            "main_plan_allowed": not blocks,
        },
        "issues": issues,
        "notes": [
            "This audit catches avoidable portfolio-construction mistakes; it does not predict match outcomes.",
            "A block means the leg needs protection, downgrade, or removal before it can be labelled a conservative/model-best main plan.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit pre-match football ticket plans for protection and tail-risk misses.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        document = json.loads(args.path.read_text(encoding="utf-8"))
        result = audit(document)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
