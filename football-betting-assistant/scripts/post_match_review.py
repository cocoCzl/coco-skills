#!/usr/bin/env python3
"""Attach final scores to a prediction snapshot and compute review metrics."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from prediction_snapshot_tools import normalize_prediction_snapshot
except ImportError:  # pragma: no cover - package execution fallback
    from scripts.prediction_snapshot_tools import normalize_prediction_snapshot  # type: ignore


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _match_result(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "胜"
    if home_goals == away_goals:
        return "平"
    return "负"


def _handicap_result(home_goals: int, away_goals: int, line: float) -> str:
    adjusted = home_goals + line - away_goals
    if adjusted > 0:
        return "让胜"
    if adjusted == 0:
        return "让平"
    return "让负"


def _parse_line(value: Any) -> float | None:
    if value in (None, ""):
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _score_set(value: Any) -> list[str]:
    if isinstance(value, dict):
        scores: list[str] = []
        if value.get("score"):
            scores.append(str(value["score"]))
        for key in ("primary", "core", "enhanced", "backup", "candidates", "scores"):
            if key in value:
                scores.extend(_score_set(value.get(key)))
        seen: set[str] = set()
        result: list[str] = []
        for score in scores:
            if score not in seen:
                result.append(score)
                seen.add(score)
        return result
    if isinstance(value, list):
        scores = []
        for item in value:
            if isinstance(item, dict):
                if item.get("score"):
                    scores.append(str(item["score"]))
                else:
                    scores.extend(_score_set(item))
            else:
                scores.append(str(item))
        return scores
    if value is None:
        return []
    return [item.strip() for item in re.split(r"/|,|，|\s+", str(value)) if item.strip()]


def _total_goals_set(value: Any) -> set[int]:
    if isinstance(value, list):
        values: set[int] = set()
        for item in value:
            values.update(_total_goals_set(item))
        return values
    return {int(item) for item in re.findall(r"\d+", str(value or ""))}


def _market_text(leg: dict[str, Any]) -> str:
    return " ".join(str(leg.get(key) or "") for key in ("source_snapshot_market", "market")).strip()


def _market_kind(leg: dict[str, Any]) -> str:
    market_text = _market_text(leg)
    if "比分" in market_text or "correct_score" in market_text:
        return "correct_score"
    if "总进球" in market_text or "total_goals" in market_text:
        return "total_goals"
    if "大小球" in market_text or "over_under" in market_text:
        return "over_under"
    if "让球" in market_text or "handicap_match_result" in market_text:
        return "handicap_result"
    if "胜平负" in market_text or "match_result" in market_text:
        return "match_result"
    return "unknown"


def _find_match_record(prediction: dict[str, Any], match_name: str) -> dict[str, Any] | None:
    data = prediction.get("data") or {}
    for record in ((data.get("model_outputs") or {}).get("match_records") or []):
        if isinstance(record, dict) and record.get("match") == match_name:
            return record
    return None


def _evaluate_leg(leg: dict[str, Any], home_goals: int, away_goals: int) -> dict[str, Any]:
    market = _market_kind(leg)
    selection = str(leg.get("selection") or "")
    final_score = f"{home_goals}:{away_goals}"
    total = home_goals + away_goals
    hit: bool | None = None
    metric = "unknown"

    if market == "match_result":
        metric = "match_result"
        hit = _match_result(home_goals, away_goals) in selection
    elif market == "handicap_result":
        metric = "handicap_result"
        line = _parse_line(leg.get("source_line") or leg.get("line") or leg.get("handicap_line") or leg.get("market"))
        if line is not None:
            hit = _handicap_result(home_goals, away_goals, line) in selection
    elif market == "total_goals":
        metric = "total_goals"
        selected_totals = _total_goals_set(selection)
        hit = total in selected_totals if selected_totals else f"{total}球" in selection or str(total) == selection
    elif market == "over_under":
        metric = "over_under"
    elif market == "correct_score":
        metric = "correct_score"
        hit = final_score in _score_set(selection)

    return {
        "match": leg.get("match"),
        "market": leg.get("market"),
        "source_snapshot_market": leg.get("source_snapshot_market"),
        "selection": selection,
        "metric": metric,
        "hit": hit,
    }


def build_review(prediction: dict[str, Any], match_name: str, home_goals: int, away_goals: int, result_source: str | None) -> dict[str, Any]:
    prediction = normalize_prediction_snapshot(prediction) or prediction
    data = prediction.get("data") or {}
    model_outputs = data.get("model_outputs") or {}
    analyses = model_outputs.get("match_analyses") or []
    ticket_plans = model_outputs.get("ticket_plans") or []
    final_score = f"{home_goals}:{away_goals}"
    score_candidates: list[str] = []
    match_record = _find_match_record(prediction, match_name)
    if match_record:
        score_candidates = _score_set(match_record.get("score_candidates"))
    for analysis in analyses:
        if not score_candidates and analysis.get("match") == match_name:
            score_candidates = _score_set(analysis.get("score_candidates"))
            break

    evaluated_legs = []
    for plan in ticket_plans:
        for leg in plan.get("legs", []) or []:
            if leg.get("match") == match_name:
                evaluated_legs.append(_evaluate_leg(leg, home_goals, away_goals))

    score_top1_hit = bool(score_candidates[:1] and final_score == score_candidates[0])
    score_top3_hit = final_score in score_candidates[:3]
    score_coverage_hit = final_score in score_candidates
    result_probabilities = (match_record or {}).get("result_probabilities") or {}
    predicted_result = None
    actual_result = _match_result(home_goals, away_goals)
    if result_probabilities:
        top_key = max(("home_win", "draw", "away_win"), key=lambda key: float(result_probabilities.get(key) or 0.0))
        predicted_result = {"home_win": "胜", "draw": "平", "away_win": "负"}[top_key]
    over_under_review = None
    ou_record = (match_record or {}).get("over_under_probabilities") or {}
    if "line" in ou_record:
        line = float(ou_record["line"])
        total = home_goals + away_goals
        actual_ou = "push" if total == line else ("over" if total > line else "under")
        predicted_ou = "over" if float(ou_record.get("over") or 0.0) >= float(ou_record.get("under") or 0.0) else "under"
        over_under_review = {"line": line, "predicted": predicted_ou, "actual": actual_ou, "hit": predicted_ou == actual_ou if actual_ou != "push" else None}

    return {
        "kind": "post_match_review",
        "data": {
            "report_id": data.get("report_id"),
            "reviewed_at": _now(),
            "source_prediction_snapshot": data.get("report_id"),
            "result_source": result_source or "user-provided",
            "match": match_name,
            "final_score": {
                "home_goals": home_goals,
                "away_goals": away_goals,
                "score": final_score,
                "match_result": _match_result(home_goals, away_goals),
                "total_goals": home_goals + away_goals,
            },
            "score_review": {
                "candidates": score_candidates,
                "top1_hit": score_top1_hit,
                "top3_hit": score_top3_hit,
                "coverage_hit": score_coverage_hit,
            },
            "result_review": {
                "predicted": predicted_result,
                "actual": actual_result,
                "hit": predicted_result == actual_result if predicted_result else None,
                "probabilities": result_probabilities or None,
            },
            "over_under_review": over_under_review,
            "leg_reviews": evaluated_legs,
            "grade_breakdown_fields": {
                "reference_grade": (match_record or {}).get("reference_grade"),
                "model_confidence": (match_record or {}).get("model_confidence"),
                "data_confidence": (match_record or {}).get("data_confidence"),
                "market_type": None,
            },
            "tail_risk_flags": (match_record or {}).get("tail_risk_flags") or [],
        },
    }


def write_unique(path: Path, document: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path
    for index in range(2, 1000):
        if not target.exists():
            break
        target = path.with_name(f"{path.stem}-{index}{path.suffix}")
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Build post-match review from a prediction snapshot and final score.")
    parser.add_argument("prediction_snapshot", type=Path)
    parser.add_argument("--match", required=True)
    parser.add_argument("--home-goals", type=int, required=True)
    parser.add_argument("--away-goals", type=int, required=True)
    parser.add_argument("--result-source")
    parser.add_argument("--out-dir", type=Path, default=Path("data/football/reviews"))
    args = parser.parse_args()

    if args.home_goals < 0 or args.away_goals < 0:
        parser.error("goals must be non-negative")
        return 2
    raw_prediction = json.loads(args.prediction_snapshot.read_text(encoding="utf-8"))
    prediction = normalize_prediction_snapshot(raw_prediction, str(args.prediction_snapshot))
    if not prediction or prediction.get("kind") != "prediction_snapshot":
        parser.error("input kind must be prediction_snapshot")
        return 2
    review = build_review(prediction, args.match, args.home_goals, args.away_goals, args.result_source)
    report_id = review["data"].get("report_id") or "unknown-report"
    path = write_unique(args.out_dir / f"{report_id}.review.json", review)
    print(json.dumps({"review_path": str(path), "review": review["data"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
