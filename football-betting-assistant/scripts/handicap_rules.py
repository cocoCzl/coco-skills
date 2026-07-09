#!/usr/bin/env python3
"""Shared handicap-result helpers for China Sports Lottery style reports."""

from __future__ import annotations

import re
from typing import Any


HANDICAP_OUTCOMES = ("让胜", "让平", "让负")


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return str(value)
    return str(value)


def parse_handicap_line(*values: Any) -> float | None:
    for value in values:
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text(value))
        if match:
            return float(match.group(0))
    return None


def split_scores(value: Any) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"/|,|，|\s+", text(value))
    scores: list[str] = []
    for item in items:
        raw = item.get("score") if isinstance(item, dict) else item
        match = re.search(r"(\d+)\s*:\s*(\d+)", text(raw))
        if match:
            scores.append(f"{int(match.group(1))}:{int(match.group(2))}")
    return scores


def score_tuple(score: str) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\s*:\s*(\d+)", score)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def handicap_result(home_goals: int, away_goals: int, line: float) -> str:
    adjusted = home_goals + line - away_goals
    if adjusted > 0:
        return "让胜"
    if adjusted == 0:
        return "让平"
    return "让负"


def handicap_result_for_score(score: str, line: float) -> str | None:
    pair = score_tuple(score)
    if pair is None:
        return None
    return handicap_result(pair[0], pair[1], line)


def selected_handicap_outcomes(selection: Any) -> set[str]:
    selection_text = text(selection)
    return {outcome for outcome in HANDICAP_OUTCOMES if outcome in selection_text}


def inferred_handicap_outcomes(scores: list[str], line: float, limit: int | None = None) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for score in scores[:limit]:
        outcome = handicap_result_for_score(score, line)
        if outcome:
            result.append((score, outcome))
    return result


def missing_handicap_outcomes(selection: Any, scores: list[str], line: float, limit: int | None = None) -> list[str]:
    selected = selected_handicap_outcomes(selection)
    inferred = [outcome for _, outcome in inferred_handicap_outcomes(scores, line, limit)]
    return ordered_unique([outcome for outcome in inferred if outcome not in selected])


def ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def mapping_table_text(scores: list[str], line: float, limit: int | None = None) -> str:
    mappings = inferred_handicap_outcomes(scores, line, limit)
    return "；".join(f"{score}->{outcome}" for score, outcome in mappings)


def handicap_text_conflicts(source_text: Any, line: float) -> list[str]:
    """Find score/outcome claims that contradict the handicap formula.

    This intentionally flags compact betting prose such as "-1 让负，1:0/2:1
    支持让负" because those one-goal wins map to 让平, not 让负.
    """

    prose = text(source_text)
    if not prose:
        return []
    selected = selected_handicap_outcomes(prose)
    if not selected:
        return []
    conflicts: list[str] = []
    for score in split_scores(prose):
        actual = handicap_result_for_score(score, line)
        if actual and actual not in selected:
            claimed = " / ".join(outcome for outcome in HANDICAP_OUTCOMES if outcome in selected)
            conflicts.append(f"{score} maps to {actual}, not {claimed}")
    return ordered_unique(conflicts)
