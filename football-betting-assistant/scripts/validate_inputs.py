#!/usr/bin/env python3
"""Validate football assistant JSON inputs and data-quality rules.

The validator intentionally uses only the Python standard library so the skill
package remains portable. It checks the schema-required fields and the project
specific data-quality warnings used by the assistant.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_REQUIRED: dict[str, list[str]] = {
    "fixture": ["home_team", "away_team", "competition", "kickoff_time", "timezone", "venue_type", "source", "observed_at"],
    "team_context": ["team", "last_5_summary", "last_10_summary", "lineup_status", "source", "observed_at"],
    "match_analysis": ["fixture", "home_xg", "away_xg", "bayesian_adjustments", "result_probabilities", "score_candidates", "model_confidence", "data_confidence", "reference_grade", "risk_points"],
    "portfolio": ["matches", "correlation_notes", "ticket_tiers", "more_combination_candidates", "excluded_matches", "portfolio_risk_tier"],
    "backtest_sample": ["sample_id", "fixture", "prediction", "actual_result"],
    "football_snapshot": ["snapshot_id", "mode", "provider", "sport", "observed_at", "timezone", "sources", "matches"],
    "prediction_snapshot": ["report_id", "generated_at", "source_snapshot_id", "source_provider", "html_report_path", "html_report_input_path", "pre_match_data", "model_outputs"],
    "competition_context": ["competition", "observed_at", "qualification_rules", "groups"]
}

CONFIDENCE = {"high", "medium", "low"}
REFERENCE_GRADES = {"A", "B", "C", "Pass"}
LINEUP_STATUSES = {"confirmed", "expected", "unconfirmed", "unavailable"}
VENUE_TYPES = {"home_away", "neutral", "unknown"}
MARKET_TYPES = {"ordinary_result", "handicap_result", "correct_score", "over_under", "total_goals", "half_time_full_time", "mixed", "analysis_only"}
SNAPSHOT_MODES = {"china-lottery", "international-odds", "analysis-only"}
SNAPSHOT_PROVIDERS = {"sporttery", "the-odds-api", "api-football", "football-data", "manual", "public-web", "custom"}
SNAPSHOT_MARKETS = {"match_result", "handicap_match_result", "correct_score", "over_under", "total_goals", "half_time_full_time", "unsupported_market"}
SNAPSHOT_AVAILABILITY = {"available", "unavailable", "unknown", "parse_failed"}
SNAPSHOT_AVAILABILITY_REASONS = {"available", "not_offered", "source_missing", "waf_blocked", "parser_error", "stale_source", "unknown"}
SNAPSHOT_SOURCE_STATUSES = {"ok", "blocked", "missing", "parse_failed", "stale"}
TEAM_TYPES = {"club", "national", "unknown", "unsupported"}
MOTIVATION_FLAGS = {
    "completed",
    "already_in_advance_zone",
    "route_selection_risk",
    "draw_may_be_sufficient",
    "third_place_race",
    "must_avoid_loss",
    "must_win_pressure",
}
PROTECTION_RISK_FLAGS = {
    "must_protect",
    "one_goal_margin_risk",
    "draw_weight_high",
    "score_distribution_diffuse",
    "favorite_cover_risk",
    "underdog_transition_threat",
    "missed_path_protection",
}

# Read the portable odds contract once; these are focused checks, not a
# general JSON Schema implementation. Other kinds retain business validation.
ODDS_SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "odds.schema.json").read_text(encoding="utf-8"))


def _price_error(value: Any, path: str, errors: list[str]) -> None:
    if value is not None and (type(value) not in (int, float) or (isinstance(value, float) and not math.isfinite(value)) or value <= 1):
        errors.append(f"{path}: must be a finite number greater than 1 or null")


def _validate_selections(value: Any, path: str, *, snapshot: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, list):
        return [f"{path}: must be an array"]
    allowed = set(ODDS_SCHEMA["properties"]["selections"]["items"]["properties"])
    if snapshot:
        allowed.add("available")
    for i, item in enumerate(value):
        label = f"{path}[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{label}: must be an object")
            continue
        for key in sorted(set(item) - allowed):
            errors.append(f"{label}: unexpected field '{key}'")
        for key in ("name", "odds"):
            if key not in item:
                errors.append(f"{label}: missing required field '{key}'")
        if "name" in item and (not isinstance(item["name"], str) or not item["name"]):
            errors.append(f"{label}.name: must be a non-empty string")
        if "odds" in item:
            _price_error(item["odds"], f"{label}.odds", errors)
        if "source_name" in item and not isinstance(item["source_name"], str):
            errors.append(f"{label}.source_name: must be a string")
        if snapshot and "available" in item and not isinstance(item["available"], bool):
            errors.append(f"{label}.available: must be a boolean")
    return errors


def _missing(record: dict[str, Any], fields: list[str]) -> list[str]:
    return [field for field in fields if field not in record or record[field] in ("", None)]


def _warn_timestamp(record: dict[str, Any], label: str, warnings: list[str]) -> None:
    if not record.get("observed_at"):
        warnings.append(f"{label}: missing source timestamp")


def _warn_unprotected_ticket_leg(leg: dict[str, Any], path: str, warnings: list[str]) -> None:
    risk_flags = {str(flag) for flag in (leg.get("risk_flags") or leg.get("tail_risk_flags") or [])}
    has_protection_signal = bool(risk_flags & PROTECTION_RISK_FLAGS)
    has_backup = bool(
        leg.get("protection_candidates")
        or leg.get("must_protect_selections")
        or leg.get("protected_selection")
        or leg.get("protection_action") == "expanded_with_risk_protection"
        or "/" in str(leg.get("selection") or "")
    )
    if has_protection_signal and not has_backup:
        warnings.append(f"{path}: risk flags require backup selection, protection action, or downgrade reason")


def validate_fixture(record: dict[str, Any], path: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for field in _missing(record, SCHEMA_REQUIRED["fixture"]):
        errors.append(f"{path}: missing required field '{field}'")
    if record.get("venue_type") not in VENUE_TYPES:
        errors.append(f"{path}: venue_type must be one of {sorted(VENUE_TYPES)}")
    _warn_timestamp(record, path, warnings)
    if record.get("venue_type") == "unknown":
        warnings.append(f"{path}: venue type unknown; downgrade data confidence")
    return errors, warnings


def validate_odds(record: dict[str, Any], path: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(record, dict):
        return [f"{path}: must be an object"], []
    properties = ODDS_SCHEMA["properties"]
    for field in ODDS_SCHEMA["required"]:
        if field not in record:
            errors.append(f"{path}: missing required field '{field}'")
    for field in sorted(set(record) - set(properties)):
        errors.append(f"{path}: unexpected field '{field}'")
    for field in ("market", "confidence"):
        if field in record and record[field] not in properties[field]["enum"]:
            errors.append(f"{path}.{field}: must be one of {properties[field]['enum']}")
    for field in ("bookmaker_or_source", "observed_at", "notes"):
        if field in record and (not isinstance(record[field], str) or (field != "notes" and not record[field])):
            errors.append(f"{path}.{field}: must be a {'non-empty ' if field != 'notes' else ''}string")
    if isinstance(record.get("observed_at"), str):
        try:
            stamp = record["observed_at"]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)", stamp):
                raise ValueError("invalid date-time format")
            parsed = datetime.fromisoformat(stamp.upper().replace("Z", "+00:00"))
            if "T" not in stamp.upper() or parsed.tzinfo is None:
                raise ValueError("timestamp needs time and timezone")
        except ValueError:
            errors.append(f"{path}.observed_at: must be an RFC 3339 date-time with timezone")
    if "line" in record and record["line"] is not None:
        line = record["line"]
        if not isinstance(line, str) and (type(line) not in (int, float) or (isinstance(line, float) and not math.isfinite(line))):
            errors.append(f"{path}.line: must be a finite number, string or null")
    for field in ("home_price", "draw_price", "away_price", "over_price", "under_price"):
        if field in record:
            _price_error(record[field], f"{path}.{field}", errors)
    if "selections" in record:
        errors.extend(_validate_selections(record["selections"], f"{path}.selections"))
    _warn_timestamp(record, path, warnings)
    if record.get("confidence") == "low":
        warnings.append(f"{path}: low odds confidence; downgrade value judgment")
    prices = [record.get(name) for name in ("home_price", "draw_price", "away_price", "over_price", "under_price")]
    selections = record.get("selections")
    if isinstance(selections, list):
        prices.extend(item.get("odds") for item in selections if isinstance(item, dict))
    if not any(price is not None for price in prices):
        warnings.append(f"{path}: no prices supplied; value judgment unavailable")
    if record.get("market") == "half_time_full_time" and len([price for price in prices if price is not None]) < 9:
        warnings.append(f"{path}: half_time_full_time needs all nine prices for full value judgment")
    return errors, warnings


def validate_team_context(record: dict[str, Any], path: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for field in _missing(record, SCHEMA_REQUIRED["team_context"]):
        errors.append(f"{path}: missing required field '{field}'")
    if record.get("lineup_status") not in LINEUP_STATUSES:
        errors.append(f"{path}: lineup_status must be one of {sorted(LINEUP_STATUSES)}")
    _warn_timestamp(record, path, warnings)
    if record.get("lineup_status") in {"unconfirmed", "unavailable"}:
        warnings.append(f"{path}: lineup not confirmed; A grade unavailable near kickoff")
    if record.get("xg_for") is None or record.get("xg_against") is None:
        warnings.append(f"{path}: xG/xGA unavailable; use goals data and downgrade model precision")
    return errors, warnings


def validate_match_analysis(record: dict[str, Any], path: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for field in _missing(record, SCHEMA_REQUIRED["match_analysis"]):
        errors.append(f"{path}: missing required field '{field}'")
    if record.get("reference_grade") not in REFERENCE_GRADES:
        errors.append(f"{path}: reference_grade must be A, B, C, or Pass")
    scores = record.get("score_candidates", [])
    if len(scores) != 3:
        errors.append(f"{path}: score_candidates must contain exactly three entries")
    if record.get("data_confidence") == "low" and record.get("reference_grade") == "A":
        errors.append(f"{path}: A grade cannot be used with low data confidence")
    model_record = record.get("model_record") or {}
    if model_record:
        prior = model_record.get("prior") or {}
        final_xg = prior.get("final_xg") or {}
        if final_xg:
            for source_key, record_key in (("home_xg", "home_xg"), ("away_xg", "away_xg")):
                if record.get(record_key) is not None and final_xg.get(source_key) is not None:
                    if abs(record[record_key] - final_xg[source_key]) > 0.03:
                        warnings.append(f"{path}: {record_key} differs from model_record.prior.final_xg.{source_key}")
        grade = model_record.get("grade") or {}
        if grade.get("reference_grade") and grade["reference_grade"] != record.get("reference_grade"):
            warnings.append(f"{path}: reference_grade differs from model_record.grade.reference_grade")
        if grade.get("value_judgment_available") is False and grade.get("edge") is not None:
            warnings.append(f"{path}: edge present while value judgment is marked unavailable")
    return errors, warnings


def validate_portfolio(record: dict[str, Any], path: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for field in _missing(record, SCHEMA_REQUIRED["portfolio"]):
        errors.append(f"{path}: missing required field '{field}'")
    matches = record.get("matches", [])
    if len(matches) < 1:
        errors.append(f"{path}: portfolio must contain at least one match")
    for i, tier in enumerate(record.get("ticket_tiers", []), start=1):
        unit_count = tier.get("unit_count")
        total_amount = tier.get("total_amount")
        unit_price = tier.get("unit_price")
        if unit_count and unit_price and total_amount and abs((unit_count * unit_price) - total_amount) > 0.01:
            errors.append(f"{path}.ticket_tiers[{i}]: total_amount must equal unit_count x unit_price")
        if tier.get("stake_label") in {"稳健方向单", "基础比分覆盖", "增强比分覆盖", "补洞单", "搏冷/高赔率小单"}:
            if not unit_count:
                warnings.append(f"{path}.ticket_tiers[{i}]: named portfolio variants should show unit_count")
        legs = tier.get("legs", [])
        if len(legs) > 8:
            errors.append(f"{path}.ticket_tiers[{i}]: direction-style tickets must contain at most eight legs")
        correct_score_legs = [leg for leg in legs if leg.get("market_type") == "correct_score"]
        if correct_score_legs and len(correct_score_legs) == len(legs) and len(legs) > 4:
            errors.append(f"{path}.ticket_tiers[{i}]: exact-score tickets must contain at most four legs")
        if "比分" in str(tier.get("stake_label", "")) and len(legs) > 4:
            errors.append(f"{path}.ticket_tiers[{i}]: score-labeled tickets must contain at most four legs")
        for leg_index, leg in enumerate(legs, start=1):
            coverage = leg.get("score_coverage", [])
            if len(coverage) > 4:
                errors.append(f"{path}.ticket_tiers[{i}].legs[{leg_index}]: score_coverage must have at most four scores")
            if leg.get("market_type") and leg["market_type"] not in MARKET_TYPES:
                errors.append(f"{path}.ticket_tiers[{i}].legs[{leg_index}]: market_type is invalid")
            if leg.get("market_available") is False and leg.get("market_type") != "analysis_only":
                errors.append(f"{path}.ticket_tiers[{i}].legs[{leg_index}]: unavailable markets cannot be used in purchase plans")
            selection_text = " ".join(str(leg.get(field, "")) for field in ("market", "selection", "selection_basis"))
            if any(marker in selection_text for marker in ("加 ", "加:", "加：")):
                warnings.append(f"{path}.ticket_tiers[{i}].legs[{leg_index}]: write complete score sets instead of shorthand additions")
            _warn_unprotected_ticket_leg(leg, f"{path}.ticket_tiers[{i}].legs[{leg_index}]", warnings)
    for variant_name in ("more_combination_candidates",):
        variants = record.get(variant_name) or []
        for variant_index, variant in enumerate(variants, start=1):
            if variant.get("unit_count") and variant.get("unit_price") and variant.get("total_amount"):
                if abs((variant["unit_count"] * variant["unit_price"]) - variant["total_amount"]) > 0.01:
                    errors.append(f"{path}.{variant_name}[{variant_index}]: total_amount must equal unit_count x unit_price")
            for i, leg in enumerate(variant.get("legs", []), start=1):
                coverage = leg.get("score_coverage", [])
                if len(coverage) > 4:
                    errors.append(f"{path}.{variant_name}[{variant_index}].legs[{i}]: score_coverage must have at most four scores")
                if leg.get("market_type") and leg["market_type"] not in MARKET_TYPES:
                    errors.append(f"{path}.{variant_name}[{variant_index}].legs[{i}]: market_type is invalid")
                if leg.get("market_available") is False and leg.get("market_type") != "analysis_only":
                    errors.append(f"{path}.{variant_name}[{variant_index}].legs[{i}]: unavailable markets cannot be used in purchase plans")
                _warn_unprotected_ticket_leg(leg, f"{path}.{variant_name}[{variant_index}].legs[{i}]", warnings)
    if record.get("portfolio_risk_tier") == "high":
        warnings.append(f"{path}: high portfolio risk tier; ensure aggressive framing is explicit")
    return errors, warnings


def validate_backtest_sample(record: dict[str, Any], path: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for field in _missing(record, SCHEMA_REQUIRED["backtest_sample"]):
        errors.append(f"{path}: missing required field '{field}'")
    prediction = record.get("prediction") or {}
    actual = record.get("actual_result") or {}
    probabilities = prediction.get("result_probabilities") or {}
    probability_total = sum(probabilities.get(key, 0.0) for key in ("home_win", "draw", "away_win"))
    if probabilities and abs(probability_total - 1.0) > 0.03:
        warnings.append(f"{path}: result probabilities sum to {probability_total:.3f}; check calibration input")
    if prediction.get("reference_grade") not in REFERENCE_GRADES:
        errors.append(f"{path}: prediction.reference_grade must be A, B, C, or Pass")
    for field in ("home_goals", "away_goals"):
        if field not in actual:
            errors.append(f"{path}: actual_result missing '{field}'")
        elif not isinstance(actual[field], int) or actual[field] < 0:
            errors.append(f"{path}: actual_result.{field} must be a non-negative integer")
    if not prediction.get("observed_at"):
        errors.append(f"{path}: prediction.observed_at is required to prove pre-match timing")
    if not prediction.get("score_candidates"):
        warnings.append(f"{path}: no score candidates supplied; score coverage cannot be evaluated")
    return errors, warnings


def _validate_snapshot_source(record: dict[str, Any], path: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for field in _missing(record, ["name", "url", "observed_at", "status"]):
        errors.append(f"{path}: missing required field '{field}'")
    if record.get("status") not in SNAPSHOT_SOURCE_STATUSES:
        errors.append(f"{path}: status must be one of {sorted(SNAPSHOT_SOURCE_STATUSES)}")
    if record.get("status") in {"blocked", "missing", "parse_failed"} and not record.get("notes"):
        warnings.append(f"{path}: failed source should include notes")
    return errors, warnings


def _validate_snapshot_source_ref(record: dict[str, Any], path: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for field in _missing(record, ["name", "url", "observed_at"]):
        errors.append(f"{path}: missing required field '{field}'")
    return errors, warnings


def _validate_snapshot_market(record: dict[str, Any], path: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for field in _missing(record, ["market", "source_market_name", "availability", "selections"]):
        errors.append(f"{path}: missing required field '{field}'")
    if record.get("market") not in SNAPSHOT_MARKETS:
        errors.append(f"{path}: market must be one of {sorted(SNAPSHOT_MARKETS)}")
    availability = record.get("availability") or {}
    if not isinstance(availability, dict):
        errors.append(f"{path}.availability: must be an object")
        availability = {}
    if availability.get("status") not in SNAPSHOT_AVAILABILITY:
        errors.append(f"{path}.availability: status must be one of {sorted(SNAPSHOT_AVAILABILITY)}")
    if availability.get("reason") not in SNAPSHOT_AVAILABILITY_REASONS:
        errors.append(f"{path}.availability: reason must be one of {sorted(SNAPSHOT_AVAILABILITY_REASONS)}")
    if availability.get("status") == "available" and availability.get("reason") != "available":
        errors.append(f"{path}.availability: available status must use reason 'available'")
    if availability.get("status") != "available" and availability.get("reason") == "available":
        errors.append(f"{path}.availability: unavailable status cannot use reason 'available'")
    selections = record.get("selections", [])
    if not isinstance(selections, list):
        errors.append(f"{path}.selections: must be a list")
        selections = []
    if availability.get("status") == "available" and not selections:
        warnings.append(f"{path}: available market has no selections; value judgment unavailable")
    if availability.get("status") in {"unavailable", "parse_failed"} and selections:
        warnings.append(f"{path}: non-available market should normally not include selections")
    errors.extend(_validate_selections(selections, f"{path}.selections", snapshot=True))
    if record.get("source"):
        e, w = _validate_snapshot_source_ref(record["source"], f"{path}.source")
        errors.extend(e)
        warnings.extend(w)
    return errors, warnings


def _validate_snapshot_match(record: dict[str, Any], path: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    required = [
        "match_id",
        "match_no",
        "competition",
        "kickoff_time",
        "timezone",
        "home_team",
        "away_team",
        "team_type",
        "markets",
        "source",
        "data_confidence",
    ]
    for field in _missing(record, required):
        if field == "match_no" and field in record:
            continue
        errors.append(f"{path}: missing required field '{field}'")
    if record.get("venue_type") and record.get("venue_type") not in VENUE_TYPES:
        errors.append(f"{path}: venue_type must be one of {sorted(VENUE_TYPES)}")
    if record.get("team_type") not in TEAM_TYPES:
        errors.append(f"{path}: team_type must be one of {sorted(TEAM_TYPES)}")
    if record.get("team_type") == "unsupported":
        warnings.append(f"{path}: unsupported team type; formal purchase plans should be withheld")
    if record.get("data_confidence") not in CONFIDENCE:
        errors.append(f"{path}: data_confidence must be one of {sorted(CONFIDENCE)}")
    if record.get("source"):
        e, w = _validate_snapshot_source_ref(record["source"], f"{path}.source")
        errors.extend(e)
        warnings.extend(w)
    markets = record.get("markets", [])
    if not isinstance(markets, list):
        errors.append(f"{path}.markets: must be a list")
        markets = []
    seen_markets: set[str] = set()
    for i, market in enumerate(markets):
        e, w = _validate_snapshot_market(market, f"{path}.markets[{i}]")
        errors.extend(e)
        warnings.extend(w)
        market_name = market.get("market")
        if market_name in seen_markets and market_name != "unsupported_market":
            warnings.append(f"{path}.markets[{i}]: duplicate market '{market_name}'")
        seen_markets.add(str(market_name))
    return errors, warnings


def validate_football_snapshot(record: dict[str, Any], path: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for field in _missing(record, SCHEMA_REQUIRED["football_snapshot"]):
        errors.append(f"{path}: missing required field '{field}'")
    if record.get("mode") not in SNAPSHOT_MODES:
        errors.append(f"{path}: mode must be one of {sorted(SNAPSHOT_MODES)}")
    if record.get("provider") not in SNAPSHOT_PROVIDERS and record.get("provider"):
        warnings.append(f"{path}: provider '{record.get('provider')}' is not a built-in provider; treat as custom")
    if record.get("sport") != "football":
        errors.append(f"{path}: sport must be 'football'")
    if record.get("confidence") and record.get("confidence") not in CONFIDENCE:
        errors.append(f"{path}: confidence must be one of {sorted(CONFIDENCE)}")
    sources = record.get("sources", [])
    if not isinstance(sources, list) or not sources:
        errors.append(f"{path}.sources: must be a non-empty list")
        sources = []
    for i, source in enumerate(sources):
        e, w = _validate_snapshot_source(source, f"{path}.sources[{i}]")
        errors.extend(e)
        warnings.extend(w)
    matches = record.get("matches", [])
    if not isinstance(matches, list):
        errors.append(f"{path}.matches: must be a list")
        matches = []
    for i, match in enumerate(matches):
        e, w = _validate_snapshot_match(match, f"{path}.matches[{i}]")
        errors.extend(e)
        warnings.extend(w)
    if not matches and not record.get("errors"):
        warnings.append(f"{path}: no matches found and no error details supplied")
    if record.get("competition_context"):
        e, w = validate_competition_context(record["competition_context"], f"{path}.competition_context")
        errors.extend(e)
        warnings.extend(w)
    return errors, warnings


def validate_competition_context(record: dict[str, Any], path: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for field in _missing(record, SCHEMA_REQUIRED["competition_context"]):
        errors.append(f"{path}: missing required field '{field}'")
    rules = record.get("qualification_rules") or {}
    if rules.get("advance_top_n") is not None and not isinstance(rules.get("advance_top_n"), int):
        errors.append(f"{path}.qualification_rules.advance_top_n: must be an integer")
    if rules.get("best_third_places") is not None and not isinstance(rules.get("best_third_places"), int):
        errors.append(f"{path}.qualification_rules.best_third_places: must be an integer")
    groups = record.get("groups", [])
    if not isinstance(groups, list) or not groups:
        errors.append(f"{path}.groups: must be a non-empty list")
        groups = []
    for group_index, group in enumerate(groups):
        label = f"{path}.groups[{group_index}]"
        if not group.get("group"):
            errors.append(f"{label}: missing group")
        standings = group.get("standings", [])
        if not isinstance(standings, list) or not standings:
            errors.append(f"{label}.standings: must be a non-empty list")
            standings = []
        ranks: set[int] = set()
        for team_index, team in enumerate(standings):
            team_path = f"{label}.standings[{team_index}]"
            for field in ("team", "rank", "played", "wins", "draws", "losses", "points", "goal_difference", "qualification_pressure", "rotation_risk"):
                if field not in team:
                    errors.append(f"{team_path}: missing required field '{field}'")
            if isinstance(team.get("rank"), int):
                ranks.add(team["rank"])
            for field in ("played", "wins", "draws", "losses", "points", "goal_difference"):
                if field in team and not isinstance(team[field], int):
                    errors.append(f"{team_path}.{field}: must be an integer")
            flags = team.get("motivation_flags", [])
            if not isinstance(flags, list):
                errors.append(f"{team_path}.motivation_flags: must be a list")
            else:
                for flag in flags:
                    if flag not in MOTIVATION_FLAGS:
                        warnings.append(f"{team_path}.motivation_flags: unknown flag '{flag}'")
        if ranks and ranks != set(range(1, len(ranks) + 1)):
            warnings.append(f"{label}: ranks are not contiguous")
    return errors, warnings


def validate_prediction_snapshot(record: dict[str, Any], path: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for field in _missing(record, SCHEMA_REQUIRED["prediction_snapshot"]):
        errors.append(f"{path}: missing required field '{field}'")
    pre_match = record.get("pre_match_data") or {}
    if not isinstance(pre_match, dict):
        errors.append(f"{path}.pre_match_data: must be an object")
        pre_match = {}
    if not isinstance(pre_match.get("fixtures"), list) or not pre_match.get("fixtures"):
        errors.append(f"{path}.pre_match_data.fixtures: must be a non-empty list")
    if not isinstance(pre_match.get("data_gaps", []), list):
        errors.append(f"{path}.pre_match_data.data_gaps: must be a list")
    model_outputs = record.get("model_outputs") or {}
    if not isinstance(model_outputs, dict):
        errors.append(f"{path}.model_outputs: must be an object")
        model_outputs = {}
    if not isinstance(model_outputs.get("match_analyses"), list) or not model_outputs.get("match_analyses"):
        errors.append(f"{path}.model_outputs.match_analyses: must be a non-empty list")
    match_records = model_outputs.get("match_records", [])
    if not isinstance(match_records, list):
        errors.append(f"{path}.model_outputs.match_records: must be a list when present")
        match_records = []
    elif not match_records:
        warnings.append(f"{path}.model_outputs.match_records: missing structured match records; post-match review/backtesting will be limited")
    for index, match_record in enumerate(match_records):
        record_path = f"{path}.model_outputs.match_records[{index}]"
        for field in ("match", "score_candidates", "reference_grade", "model_confidence", "data_confidence"):
            if field not in match_record:
                warnings.append(f"{record_path}: missing '{field}'")
        probabilities = match_record.get("result_probabilities")
        if probabilities is not None:
            probability_total = sum(float(probabilities.get(key) or 0.0) for key in ("home_win", "draw", "away_win"))
            if abs(probability_total - 1.0) > 0.03:
                warnings.append(f"{record_path}.result_probabilities: sum is {probability_total:.3f}; check calibration input")
        if match_record.get("tail_risk_flags") and not match_record.get("risk_points"):
            warnings.append(f"{record_path}: tail_risk_flags should also be explained in risk_points")
    ticket_plans = model_outputs.get("ticket_plans", [])
    if not isinstance(ticket_plans, list):
        errors.append(f"{path}.model_outputs.ticket_plans: must be a list")
        ticket_plans = []
    for index, plan in enumerate(ticket_plans):
        for field in ("name", "type", "legs", "odds_status", "risk_level", "reason"):
            if field not in plan:
                errors.append(f"{path}.model_outputs.ticket_plans[{index}]: missing required field '{field}'")
        for leg_index, leg in enumerate(plan.get("legs", []) or []):
            market_status = leg.get("market_available")
            if market_status is False:
                errors.append(f"{path}.model_outputs.ticket_plans[{index}].legs[{leg_index}]: unavailable markets cannot be used in purchase plans")
            if not leg.get("source_snapshot_market"):
                warnings.append(f"{path}.model_outputs.ticket_plans[{index}].legs[{leg_index}]: missing source_snapshot_market")
            _warn_unprotected_ticket_leg(leg, f"{path}.model_outputs.ticket_plans[{index}].legs[{leg_index}]", warnings)
    if not record.get("html_report_path"):
        errors.append(f"{path}: html_report_path is required")
    if not record.get("html_report_input_path"):
        errors.append(f"{path}: html_report_input_path is required")
    return errors, warnings


VALIDATORS = {
    "fixture": validate_fixture,
    "odds": validate_odds,
    "team_context": validate_team_context,
    "match_analysis": validate_match_analysis,
    "portfolio": validate_portfolio,
    "backtest_sample": validate_backtest_sample,
    "football_snapshot": validate_football_snapshot,
    "prediction_snapshot": validate_prediction_snapshot
    ,
    "competition_context": validate_competition_context
}

BUNDLE_KEYS = {
    "fixture": "fixture",
    "fixtures": "fixture",
    "odds": "odds",
    "team_context": "team_context",
    "team_contexts": "team_context",
    "match_analysis": "match_analysis",
    "match_analyses": "match_analysis",
    "portfolio": "portfolio",
    "portfolios": "portfolio",
    "samples": "backtest_sample",
    "football_snapshot": "football_snapshot",
    "football_snapshots": "football_snapshot",
    "prediction_snapshot": "prediction_snapshot",
    "prediction_snapshots": "prediction_snapshot",
    "competition_context": "competition_context",
    "competition_contexts": "competition_context"
}


def validate_document(document: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(document, dict):
        return {"valid": False, "errors": ["document must be an object"], "warnings": []}
    kind = document.get("kind")
    if not isinstance(kind, str) or not isinstance(document.get("data"), dict):
        return {"valid": False, "errors": ["kind must be a string and data must be an object"], "warnings": []}
    if kind in VALIDATORS:
        e, w = VALIDATORS[kind](document.get("data", {}), "data")
        errors.extend(e)
        warnings.extend(w)
    elif kind == "backtest_samples":
        samples = document.get("data", {}).get("samples", [])
        if not isinstance(samples, list) or not samples:
            errors.append("data.samples must be a non-empty list")
        for i, item in enumerate(samples):
            e, w = validate_backtest_sample(item, f"data.samples[{i}]")
            errors.extend(e)
            warnings.extend(w)
    elif kind == "bundle":
        for key, value in document.get("data", {}).items():
            items = value if isinstance(value, list) else [value]
            validator_key = BUNDLE_KEYS.get(key)
            validator = VALIDATORS.get(validator_key or "")
            if not validator:
                warnings.append(f"data.{key}: no validator registered")
                continue
            for i, item in enumerate(items):
                e, w = validator(item, f"data.{key}[{i}]")
                errors.extend(e)
                warnings.extend(w)
    else:
        errors.append("top-level 'kind' must be one of fixture, odds, team_context, match_analysis, portfolio, football_snapshot, competition_context, prediction_snapshot, backtest_samples, bundle")

    return {"valid": not errors, "errors": errors, "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate football assistant JSON input.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    try:
        document = json.loads(args.path.read_text(encoding="utf-8"))
        result = validate_document(document)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        result = {"valid": False, "errors": [f"Invalid input: {exc}"], "warnings": []}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
