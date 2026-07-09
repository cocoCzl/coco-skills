#!/usr/bin/env python3
"""Build conservative portfolio candidates from graded buyable legs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from handicap_rules import (
    handicap_result,
    ordered_unique,
    parse_handicap_line,
    score_tuple,
    split_scores,
)

GRADE_ORDER = {"Pass": 0, "C": 1, "B": 2, "A": 3}
MARKET_LIMITS = {
    "correct_score": 4,
    "match_result": 8,
    "handicap_match_result": 8,
    "over_under": 8,
    "total_goals": 8,
    "half_time_full_time": 4,
    "mixed": 8,
}


def _grade_value(grade: str | None) -> int:
    return GRADE_ORDER.get(str(grade or "Pass"), 0)


def _leg_reason_to_exclude(leg: dict[str, Any], risk_preference: str, include_half_time_full_time: bool = False) -> str | None:
    market = str(leg.get("market") or "")
    grade = str(leg.get("grade") or "Pass")
    if market == "half_time_full_time" and not include_half_time_full_time:
        return "half-time/full-time requires explicit user request"
    if leg.get("market_available") is False:
        return "market unavailable"
    if grade == "Pass":
        return "Pass grade"
    if risk_preference == "conservative" and grade == "C":
        return "C grade excluded from conservative main plans"
    if leg.get("data_confidence") == "low":
        return "low data confidence"
    if leg.get("manual_xg") and risk_preference == "conservative":
        return "manual xG excluded from conservative main plans"
    if leg.get("lineup_status") in {"missing", "unconfirmed"} and risk_preference == "conservative":
        return "lineup unconfirmed"
    tail_flags = set(leg.get("tail_risk_flags") or [])
    if tail_flags and risk_preference == "conservative":
        return "material total-goals tail risk: " + "/".join(sorted(tail_flags))
    if market == "correct_score" and leg.get("score_coverage_quality") == "weak":
        return "weak score coverage"
    if market == "correct_score" and leg.get("score_coverage_quality") != "strong" and risk_preference == "conservative":
        return "exact-score coverage is not strong enough for conservative core plans"
    if market in {"over_under", "total_goals"} and leg.get("selected_total_goals_max") is not None:
        selected_max = int(leg.get("selected_total_goals_max") or 0)
        five_plus = float(leg.get("five_plus_goal_probability") or 0.0)
        if selected_max < 5 and five_plus >= 0.12:
            return "total-goals selection omits material 5+ tail"
    if market == "half_time_full_time" and risk_preference == "conservative" and _grade_value(grade) < 2:
        return "half-time/full-time is high variance and needs at least B grade"
    return None


def _score_values(value: Any) -> list[tuple[int, int]]:
    scores: list[tuple[int, int]] = []
    for score in split_scores(value):
        pair = score_tuple(score)
        if pair:
            scores.append(pair)
    return scores


def _parse_handicap_line(value: Any) -> float | None:
    return parse_handicap_line(value)


def _handicap_outcome(home_goals: int, away_goals: int, line: float) -> str:
    return handicap_result(home_goals, away_goals, line)


def _ordered_unique(values: list[str]) -> list[str]:
    return ordered_unique(values)


def _explicit_protection_candidates(leg: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in ("must_protect_selections", "protection_candidates", "missed_path_protection"):
        value = leg.get(key)
        if isinstance(value, list):
            candidates.extend(str(item) for item in value)
        elif value:
            candidates.extend(item.strip() for item in re.split(r"/|,|，", str(value)) if item.strip())
    return _ordered_unique(candidates)


def _inferred_handicap_protection(leg: dict[str, Any]) -> list[str]:
    if str(leg.get("market") or "") != "handicap_match_result":
        return []
    line = _parse_handicap_line(leg.get("source_line") or leg.get("line") or leg.get("handicap_line"))
    if line is None:
        return []
    scores = _score_values(
        leg.get("score_candidates")
        or leg.get("enhanced_scores")
        or leg.get("score_coverage")
        or leg.get("coverage_scores")
    )
    if not scores:
        return []
    selection = str(leg.get("selection") or "")
    outcomes = [_handicap_outcome(home_goals, away_goals, line) for home_goals, away_goals in scores]
    return _ordered_unique([outcome for outcome in outcomes if outcome not in selection])


def _needs_protection(leg: dict[str, Any]) -> bool:
    flags = {str(flag) for flag in (leg.get("risk_flags") or leg.get("tail_risk_flags") or [])}
    protection_flags = {
        "must_protect",
        "one_goal_margin_risk",
        "draw_weight_high",
        "score_distribution_diffuse",
        "favorite_cover_risk",
        "underdog_transition_threat",
        "missed_path_protection",
    }
    return bool(flags & protection_flags) or bool(_explicit_protection_candidates(leg)) or bool(_inferred_handicap_protection(leg))


def _apply_protection(leg: dict[str, Any], risk_preference: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    protected = dict(leg)
    candidates = _ordered_unique(_explicit_protection_candidates(protected) + _inferred_handicap_protection(protected))
    if risk_preference != "conservative" or not _needs_protection(protected):
        protected["protection_action"] = "single_selection_retained"
        protected["protection_candidates"] = candidates
        return protected, None
    if not candidates:
        protected["protection_action"] = "single_selection_retained_no_candidate"
        protected["protection_candidates"] = []
        return protected, None
    if protected.get("allow_protection_expansion") is False:
        return None, {
            "match": protected.get("match"),
            "market": protected.get("market"),
            "selection": protected.get("selection"),
            "reason": "unprotected risk path requires backup selection or downgrade",
            "protection_candidates": candidates,
        }

    selections = _ordered_unique([str(protected.get("selection") or "")] + candidates)
    protected["selection"] = " / ".join(selections)
    protected["selection_count"] = len(selections)
    protected["protection_candidates"] = candidates
    protected["protected_selection"] = protected["selection"]
    protected["protection_action"] = "expanded_with_risk_protection"
    protected["portfolio_action_reason"] = "Conservative main plan inherited risk-path protection from score coverage or explicit risk flags."
    return protected, None


def _sort_legs(legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        legs,
        key=lambda item: (
            _grade_value(item.get("grade")),
            float(item.get("edge") or 0.0),
            float(item.get("model_probability") or 0.0),
        ),
        reverse=True,
    )


def build_portfolio(document: dict[str, Any]) -> dict[str, Any]:
    risk_preference = str(document.get("risk_preference") or "conservative")
    include_half_time_full_time = bool(document.get("include_half_time_full_time") or document.get("explicit_half_time_full_time_request"))
    unit_price = int(document.get("unit_price") or 2)
    raw_legs = document.get("legs")
    if not isinstance(raw_legs, list) or not raw_legs:
        raise ValueError("legs must be a non-empty list")

    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for leg in raw_legs:
        reason = _leg_reason_to_exclude(leg, risk_preference, include_half_time_full_time)
        if reason:
            excluded.append({"match": leg.get("match"), "market": leg.get("market"), "selection": leg.get("selection"), "reason": reason})
        else:
            protected_leg, protection_exclusion = _apply_protection(leg, risk_preference)
            if protection_exclusion:
                excluded.append(protection_exclusion)
            elif protected_leg:
                eligible.append(protected_leg)

    by_market: dict[str, list[dict[str, Any]]] = {}
    for leg in eligible:
        by_market.setdefault(str(leg.get("market") or "mixed"), []).append(leg)

    ticket_plans: list[dict[str, Any]] = []
    for market, market_legs in by_market.items():
        sorted_legs = _sort_legs(market_legs)
        limit = MARKET_LIMITS.get(market, 8)
        selected = sorted_legs[: min(limit, len(sorted_legs))]
        if not selected:
            continue
        if risk_preference == "conservative" and not any(_grade_value(leg.get("grade")) >= 2 for leg in selected):
            continue
        unit_count = 1
        for leg in selected:
            selections = leg.get("selection_count") or 1
            unit_count *= int(selections)
        ticket_plans.append(
            {
                "name": f"{market} conservative candidate",
                "type": "score_4fold" if market == "correct_score" else ("totals" if market in {"over_under", "total_goals"} else ("half_time_full_time" if market == "half_time_full_time" else "result_handicap")),
                "market_family": market,
                "legs": selected,
                "unit_math": f"{unit_count} 注",
                "amount_text": f"{unit_count} 注 x {unit_price} 元/注 = {unit_count * unit_price} 元",
                "risk_level": "中" if len(selected) <= 4 else "中高",
                "reason": "Selected from buyable, non-Pass, sufficient-data legs without forcing maximum leg count.",
                "protection_actions": [
                    {
                        "match": leg.get("match"),
                        "selection": leg.get("selection"),
                        "action": leg.get("protection_action", "single_selection_retained"),
                        "reason": leg.get("portfolio_action_reason"),
                    }
                    for leg in selected
                ],
            }
        )

    return {
        "kind": "portfolio_candidate_record",
        "risk_preference": risk_preference,
        "include_half_time_full_time": include_half_time_full_time,
        "ticket_plans": ticket_plans,
        "excluded_legs": excluded,
        "correlation_notes": document.get("correlation_notes", []),
        "notes": [
            "Conservative mode excludes C-grade, Pass, unavailable, low-data, and weak score-coverage legs from main plans.",
            "Half-time/full-time legs are excluded unless include_half_time_full_time or explicit_half_time_full_time_request is true.",
            "Ticket size is selected from eligible legs and is not forced to fourfold or eightfold.",
            "Conservative main plans inherit explicit or inferred risk-path protection before selecting ticket legs.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build conservative portfolio candidates from graded legs.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        document = json.loads(args.path.read_text(encoding="utf-8"))
        result = build_portfolio(document)
    except (json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
