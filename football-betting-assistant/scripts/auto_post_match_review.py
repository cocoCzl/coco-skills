#!/usr/bin/env python3
"""Auto-discover prediction snapshots, attach final scores, and render review HTML."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from post_match_review import build_review
from prediction_snapshot_tools import normalize_prediction_snapshot


DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_TIMEZONE = timezone(timedelta(hours=8))


def now_local(value: str | None = None) -> datetime:
    if value:
        return parse_time(value) or datetime.now(DEFAULT_TIMEZONE)
    return datetime.now(DEFAULT_TIMEZONE)


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    text_value = text_value.replace(" 北京时间", "+08:00").replace("Z", "+00:00")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}\+08:00", text_value):
        text_value = text_value.replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(text_value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=DEFAULT_TIMEZONE)
    return parsed.astimezone(DEFAULT_TIMEZONE)


def stamp_for_filename(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace(":", "").replace("+", "+")


def write_unique(path: Path, document: dict[str, Any] | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path
    for index in range(2, 1000):
        if not target.exists():
            break
        target = path.with_name(f"{path.stem}-{index}{path.suffix}")
    if isinstance(document, str):
        target.write_text(document, encoding="utf-8")
    else:
        target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_team(value: Any) -> str:
    text_value = re.sub(r"\s+", "", str(value or "").lower())
    return text_value.replace("　", "")


def split_match_name(value: str) -> tuple[str, str] | None:
    parts = re.split(r"\s+(?:vs|v|VS|V)\s+|对|vs|VS| v ", value.strip())
    if len(parts) != 2:
        return None
    home, away = parts[0].strip(), parts[1].strip()
    return (home, away) if home and away else None


def extract_candidates(prediction_path: Path, prediction: dict[str, Any]) -> list[dict[str, Any]]:
    data = prediction.get("data") or {}
    pre_match = data.get("pre_match_data") or {}
    fixtures = {
        item.get("match"): item
        for item in pre_match.get("fixtures", []) or []
        if isinstance(item, dict) and item.get("match")
    }
    model_outputs = data.get("model_outputs") or {}
    records = model_outputs.get("match_records") or []
    analyses = model_outputs.get("match_analyses") or []
    candidates: list[dict[str, Any]] = []
    if isinstance(records, list) and records:
        for record in records:
            if not isinstance(record, dict):
                continue
            match_name = str(record.get("match") or "").strip()
            if not match_name:
                continue
            fixture = fixtures.get(match_name, {})
            kickoff = parse_time(record.get("kickoff_time") or fixture.get("kickoff_time"))
            split = split_match_name(match_name)
            candidates.append(
                {
                    "prediction_path": prediction_path,
                    "prediction": prediction,
                    "report_id": data.get("report_id") or prediction_path.stem.replace(".prediction", ""),
                    "match": match_name,
                    "home_team": record.get("home_team") or (split[0] if split else fixture.get("home_team")),
                    "away_team": record.get("away_team") or (split[1] if split else fixture.get("away_team")),
                    "competition": record.get("competition") or fixture.get("competition"),
                    "kickoff_time": kickoff,
                    "analysis": record,
                }
            )
        return candidates
    for analysis in analyses:
        if not isinstance(analysis, dict):
            continue
        match_name = str(analysis.get("match") or "").strip()
        if not match_name:
            continue
        fixture = fixtures.get(match_name, {})
        kickoff = parse_time(analysis.get("kickoff_time") or fixture.get("kickoff_time"))
        split = split_match_name(match_name)
        candidates.append(
            {
                "prediction_path": prediction_path,
                "prediction": prediction,
                "report_id": data.get("report_id") or prediction_path.stem.replace(".prediction", ""),
                "match": match_name,
                "home_team": split[0] if split else fixture.get("home_team"),
                "away_team": split[1] if split else fixture.get("away_team"),
                "competition": analysis.get("competition") or fixture.get("competition"),
                "kickoff_time": kickoff,
                "analysis": analysis,
            }
        )
    return candidates


def load_prediction_candidates(predictions_dir: Path, current_time: datetime, all_history: bool, window_days: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    cutoff = current_time - timedelta(days=window_days)
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for path in sorted(predictions_dir.glob("*.prediction.json")):
        try:
            raw_prediction = load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            skipped.append({"path": str(path), "reason": f"prediction_json_invalid: {exc}"})
            continue
        prediction = normalize_prediction_snapshot(raw_prediction, str(path))
        if not prediction or prediction.get("kind") != "prediction_snapshot":
            skipped.append({"path": str(path), "reason": "not_prediction_snapshot"})
            continue
        generated_at = parse_time((prediction.get("data") or {}).get("generated_at"))
        if not all_history and generated_at and generated_at < cutoff:
            skipped.append({"path": str(path), "reason": "outside_default_30_day_window"})
            continue
        for candidate in extract_candidates(path, prediction):
            kickoff = candidate.get("kickoff_time")
            if kickoff and kickoff > current_time:
                skipped.append({"path": str(path), "match": candidate["match"], "reason": "not_finished"})
                continue
            candidates.append(candidate)
    return candidates, skipped


def load_results_input(path: Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    document = load_json(path)
    if document.get("kind") == "match_results":
        return list((document.get("data") or {}).get("results") or [])
    if isinstance(document.get("results"), list):
        return list(document["results"])
    return []


def fetch_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = Request(url, headers=headers or {"User-Agent": "football-betting-assistant/1.0"})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def fetch_football_data_results(candidate: dict[str, Any], token: str) -> list[dict[str, Any]]:
    kickoff = candidate.get("kickoff_time")
    if not kickoff:
        return []
    query = urlencode({"dateFrom": kickoff.date().isoformat(), "dateTo": kickoff.date().isoformat()})
    payload = fetch_json(
        f"https://api.football-data.org/v4/matches?{query}",
        headers={"X-Auth-Token": token, "User-Agent": "football-betting-assistant/1.0"},
    )
    results = []
    for item in payload.get("matches", []) or []:
        score = ((item.get("score") or {}).get("fullTime") or {})
        if score.get("home") is None or score.get("away") is None:
            continue
        results.append(
            {
                "home_team": ((item.get("homeTeam") or {}).get("name")),
                "away_team": ((item.get("awayTeam") or {}).get("name")),
                "competition": ((item.get("competition") or {}).get("name")),
                "kickoff_time": item.get("utcDate"),
                "home_goals": score.get("home"),
                "away_goals": score.get("away"),
                "source": "football-data.org",
                "source_url": "https://api.football-data.org/v4/matches",
            }
        )
    return results


def fetch_api_football_results(candidate: dict[str, Any], token: str) -> list[dict[str, Any]]:
    kickoff = candidate.get("kickoff_time")
    if not kickoff:
        return []
    query = urlencode({"date": kickoff.date().isoformat()})
    payload = fetch_json(
        f"https://v3.football.api-sports.io/fixtures?{query}",
        headers={"x-apisports-key": token, "User-Agent": "football-betting-assistant/1.0"},
    )
    results = []
    for item in payload.get("response", []) or []:
        goals = item.get("goals") or {}
        if goals.get("home") is None or goals.get("away") is None:
            continue
        fixture = item.get("fixture") or {}
        teams = item.get("teams") or {}
        league = item.get("league") or {}
        results.append(
            {
                "home_team": ((teams.get("home") or {}).get("name")),
                "away_team": ((teams.get("away") or {}).get("name")),
                "competition": league.get("name"),
                "kickoff_time": fixture.get("date"),
                "home_goals": goals.get("home"),
                "away_goals": goals.get("away"),
                "source": "API-Football",
                "source_url": "https://v3.football.api-sports.io/fixtures",
            }
        )
    return results


def fetch_the_odds_scores(candidate: dict[str, Any], token: str, sports: list[str]) -> list[dict[str, Any]]:
    results = []
    for sport_key in sports:
        query = urlencode({"apiKey": token, "daysFrom": 3})
        try:
            payload = fetch_json(f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/?{query}")
        except Exception:
            continue
        if not isinstance(payload, list):
            continue
        for item in payload:
            scores = item.get("scores") or []
            if not item.get("completed") or len(scores) < 2:
                continue
            score_by_name = {entry.get("name"): entry.get("score") for entry in scores}
            home = item.get("home_team")
            away = item.get("away_team")
            if home not in score_by_name or away not in score_by_name:
                continue
            results.append(
                {
                    "home_team": home,
                    "away_team": away,
                    "competition": sport_key,
                    "kickoff_time": item.get("commence_time"),
                    "home_goals": score_by_name[home],
                    "away_goals": score_by_name[away],
                    "source": f"The Odds API:{sport_key}",
                    "source_url": f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores",
                }
            )
    return results


def collect_provider_results(candidate: dict[str, Any], sports: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    results: list[dict[str, Any]] = []
    notes: list[str] = []
    football_data_key = os.environ.get("FOOTBALL_DATA_API_KEY")
    api_football_key = os.environ.get("API_FOOTBALL_KEY")
    odds_key = os.environ.get("THE_ODDS_API_KEY")
    if football_data_key:
        try:
            results.extend(fetch_football_data_results(candidate, football_data_key))
        except Exception as exc:
            notes.append(f"football-data.org failed: {exc}")
    else:
        notes.append("FOOTBALL_DATA_API_KEY not configured")
    if api_football_key:
        try:
            results.extend(fetch_api_football_results(candidate, api_football_key))
        except Exception as exc:
            notes.append(f"API-Football failed: {exc}")
    else:
        notes.append("API_FOOTBALL_KEY not configured")
    if odds_key:
        results.extend(fetch_the_odds_scores(candidate, odds_key, sports))
    else:
        notes.append("THE_ODDS_API_KEY not configured")
    return results, notes


def match_confidence(candidate: dict[str, Any], result: dict[str, Any]) -> tuple[float, str]:
    candidate_home = normalize_team(candidate.get("home_team"))
    candidate_away = normalize_team(candidate.get("away_team"))
    result_home = normalize_team(result.get("home_team"))
    result_away = normalize_team(result.get("away_team"))
    candidate_match = normalize_team(candidate.get("match"))
    result_match = normalize_team(result.get("match"))
    score = 0.0
    reasons: list[str] = []
    if candidate_home and candidate_home == result_home:
        score += 0.35
        reasons.append("home_team")
    if candidate_away and candidate_away == result_away:
        score += 0.35
        reasons.append("away_team")
    if result_match and candidate_match == result_match:
        score += 0.55
        reasons.append("match_name")
    candidate_time = candidate.get("kickoff_time")
    result_time = parse_time(result.get("kickoff_time"))
    if candidate_time and result_time:
        hours = abs((candidate_time - result_time).total_seconds()) / 3600
        if hours <= 3:
            score += 0.2
            reasons.append("kickoff_time")
        elif hours <= 36:
            score += 0.08
            reasons.append("kickoff_date")
    if normalize_team(candidate.get("competition")) and normalize_team(candidate.get("competition")) == normalize_team(result.get("competition")):
        score += 0.1
        reasons.append("competition")
    return min(score, 1.0), ", ".join(reasons) or "no strong identity match"


def find_result(candidate: dict[str, Any], static_results: list[dict[str, Any]], sports: list[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    provider_notes: list[str] = []
    provider_results: list[dict[str, Any]] = []
    if not static_results:
        provider_results, provider_notes = collect_provider_results(candidate, sports)
    best_result: dict[str, Any] | None = None
    best_score = 0.0
    best_reason = ""
    for result in static_results + provider_results:
        confidence, reason = match_confidence(candidate, result)
        if confidence > best_score:
            best_result = result
            best_score = confidence
            best_reason = reason
    meta = {
        "match_confidence": round(best_score, 2),
        "match_reason": best_reason,
        "provider_notes": provider_notes,
    }
    if best_result and best_score >= 0.7:
        return best_result, meta
    return None, meta


def summarize_leg_reviews(leg_reviews: list[dict[str, Any]]) -> dict[str, int]:
    known = [item for item in leg_reviews if item.get("hit") is not None]
    hits = [item for item in known if item.get("hit") is True]
    misses = [item for item in known if item.get("hit") is False]
    return {"known": len(known), "hits": len(hits), "misses": len(misses)}


def summarize_legs_by_metric(reviewed: list[dict[str, Any]]) -> dict[str, dict[str, int | float | None]]:
    stats: dict[str, dict[str, int]] = {}
    for item in reviewed:
        for leg in item.get("leg_reviews") or []:
            metric = str(leg.get("metric") or "unknown")
            hit = leg.get("hit")
            if hit is None:
                continue
            bucket = stats.setdefault(metric, {"known": 0, "hits": 0, "misses": 0})
            bucket["known"] += 1
            if hit:
                bucket["hits"] += 1
            else:
                bucket["misses"] += 1
    return {
        metric: {
            **bucket,
            "hit_rate": round(bucket["hits"] / bucket["known"], 4) if bucket["known"] else None,
        }
        for metric, bucket in sorted(stats.items())
    }


def build_aggregate_review(candidates: list[dict[str, Any]], static_results: list[dict[str, Any]], sports: list[str], current_time: datetime) -> dict[str, Any]:
    reviewed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for candidate in candidates:
        result, meta = find_result(candidate, static_results, sports)
        if not result:
            skipped.append({"match": candidate["match"], "report_id": candidate["report_id"], "reason": "final_result_not_verified", **meta})
            continue
        try:
            home_goals = int(result["home_goals"])
            away_goals = int(result["away_goals"])
        except (KeyError, TypeError, ValueError):
            skipped.append({"match": candidate["match"], "report_id": candidate["report_id"], "reason": "invalid_final_score", **meta})
            continue
        review = build_review(
            candidate["prediction"],
            candidate["match"],
            home_goals,
            away_goals,
            str(result.get("source") or "verified result"),
        )["data"]
        review["source_prediction_path"] = str(candidate["prediction_path"])
        review["match_confidence"] = meta["match_confidence"]
        review["match_reason"] = meta["match_reason"]
        review["result_source_url"] = result.get("source_url")
        review["leg_summary"] = summarize_leg_reviews(review.get("leg_reviews") or [])
        reviewed.append(review)
    leg_known = sum(item["leg_summary"]["known"] for item in reviewed)
    leg_hits = sum(item["leg_summary"]["hits"] for item in reviewed)
    result_known = sum(1 for item in reviewed if (item.get("result_review") or {}).get("hit") is not None)
    result_hits = sum(1 for item in reviewed if (item.get("result_review") or {}).get("hit") is True)
    ou_known = sum(1 for item in reviewed if (item.get("over_under_review") or {}).get("hit") is not None)
    ou_hits = sum(1 for item in reviewed if (item.get("over_under_review") or {}).get("hit") is True)
    score_top1 = sum(1 for item in reviewed if (item.get("score_review") or {}).get("top1_hit"))
    score_top3 = sum(1 for item in reviewed if (item.get("score_review") or {}).get("top3_hit"))
    score_coverage = sum(1 for item in reviewed if (item.get("score_review") or {}).get("coverage_hit"))
    return {
        "kind": "post_match_review_bundle",
        "data": {
            "generated_at": current_time.isoformat(timespec="seconds"),
            "reviewed_count": len(reviewed),
            "skipped_count": len(skipped),
            "summary": {
                "leg_known": leg_known,
                "leg_hits": leg_hits,
                "leg_hit_rate": round(leg_hits / leg_known, 4) if leg_known else None,
                "result_known": result_known,
                "result_hits": result_hits,
                "result_hit_rate": round(result_hits / result_known, 4) if result_known else None,
                "over_under_known": ou_known,
                "over_under_hits": ou_hits,
                "over_under_hit_rate": round(ou_hits / ou_known, 4) if ou_known else None,
                "score_top1_hits": score_top1,
                "score_top3_hits": score_top3,
                "score_coverage_hits": score_coverage,
            },
            "metric_breakdown": summarize_legs_by_metric(reviewed),
            "reviews": reviewed,
            "skipped": skipped,
        },
    }


def text(value: Any, fallback: str = "未确认") -> str:
    if value is None or value == "":
        return fallback
    if isinstance(value, list):
        return html.escape(" / ".join(str(item) for item in value)) if value else fallback
    return html.escape(str(value))


def render_review_html(bundle: dict[str, Any]) -> str:
    data = bundle["data"]
    summary = data.get("summary") or {}
    metric_breakdown = data.get("metric_breakdown") or {}
    review_rows = []
    detail_cards = []
    for item in data.get("reviews") or []:
        score_review = item.get("score_review") or {}
        final_score = item.get("final_score") or {}
        leg_summary = item.get("leg_summary") or {}
        result_review = item.get("result_review") or {}
        over_under_review = item.get("over_under_review") or {}
        leg_hit_text = f"{leg_summary.get('hits', 0)}/{leg_summary.get('known', 0)}"
        review_rows.append(
            "<tr>"
            f"<td>{text(item.get('match'))}</td>"
            f"<td>{text(final_score.get('score'))}</td>"
            f"<td>{text(final_score.get('match_result'))}</td>"
            f"<td>{'是' if result_review.get('hit') else '否' if result_review.get('hit') is False else '未判定'}</td>"
            f"<td>{'是' if over_under_review.get('hit') else '否' if over_under_review.get('hit') is False else '未判定'}</td>"
            f"<td>{'是' if score_review.get('top1_hit') else '否'}</td>"
            f"<td>{'是' if score_review.get('top3_hit') else '否'}</td>"
            f"<td>{'是' if score_review.get('coverage_hit') else '否'}</td>"
            f"<td>{text(leg_hit_text)}</td>"
            f"<td>{text(item.get('result_source'))}</td>"
            f"<td>{text(item.get('match_confidence'))}</td>"
            "</tr>"
        )
        detail_cards.append(
            "<article class='card'>"
            f"<h3>{text(item.get('match'))}</h3>"
            "<div class='meta'>"
            f"<span>赛果：{text(final_score.get('score'))}</span>"
            f"<span>赛果来源：{text(item.get('result_source'))}</span>"
            f"<span>匹配置信度：{text(item.get('match_confidence'))}</span>"
            "</div>"
            "<h4>1. 赛前判断回顾</h4>"
            f"<p>赛果预测：{text(result_review.get('predicted'))}，实际：{text(result_review.get('actual'))}；大小球预测：{text(over_under_review.get('predicted'))}，实际：{text(over_under_review.get('actual'))}。比分候选：{text(score_review.get('candidates'))}。票单可判定项：{text(leg_summary.get('known'))}，命中 {text(leg_summary.get('hits'))}，未中 {text(leg_summary.get('misses'))}。</p>"
            "<h4>2. 实际结果与关键转折</h4>"
            f"<p>最终比分 {text(final_score.get('score'))}，赛果为{text(final_score.get('match_result'))}，总进球 {text(final_score.get('total_goals'))}。</p>"
            "<h4>3. 模型偏差</h4>"
            f"<p>{'主比分命中，模型方向与比分集中区较一致。' if score_review.get('top1_hit') else '主比分未命中，需要检查赛前 xG、节奏和比分分布是否过窄。'}</p>"
            "<h4>4. 数据偏差</h4>"
            f"<p>复盘赛果匹配依据：{text(item.get('match_reason'))}。若赛前缺少首发、伤停、战意或天气，应在下次分析中继续降级处理。</p>"
            "<h4>5. 下次调整</h4>"
            f"<p>{'维持当前覆盖宽度，继续观察同等级样本。' if score_review.get('coverage_hit') else '扩大比分覆盖或降低比分票权重，避免把低置信集中区当成核心结论。'}</p>"
            "</article>"
        )
    skipped_rows = []
    for item in data.get("skipped") or []:
        skipped_rows.append(
            "<tr>"
            f"<td>{text(item.get('match'))}</td>"
            f"<td>{text(item.get('report_id'))}</td>"
            f"<td>{text(item.get('reason'))}</td>"
            f"<td>{text(item.get('match_confidence'))}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>足球竞彩赛后复盘</title>
  <style>
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,"Noto Sans SC",sans-serif; color:#17202a; background:#eef2f6; line-height:1.58; }}
    .page {{ max-width:1180px; margin:0 auto; padding:28px; }}
    header {{ background:#111827; color:#fff; padding:28px; border-radius:8px; }}
    h1 {{ margin:0 0 10px; font-size:28px; }}
    h2 {{ margin:0 0 14px; font-size:21px; }}
    h3 {{ margin:0 0 10px; font-size:17px; }}
    h4 {{ margin:16px 0 6px; font-size:14px; color:#334155; }}
    section, .card {{ background:#fff; border:1px solid #d9dee7; border-radius:8px; padding:20px; margin-top:18px; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th, td {{ border-bottom:1px solid #d9dee7; padding:10px; text-align:left; vertical-align:top; }}
    th {{ background:#f4f7fb; }}
    .meta {{ display:flex; flex-wrap:wrap; gap:8px; margin:8px 0 12px; }}
    .meta span {{ background:#f4f7fb; border:1px solid #d9dee7; border-radius:999px; padding:4px 10px; font-size:13px; }}
    .warning {{ border-left:4px solid #9a6700; background:#fff8db; padding:12px 14px; margin-top:16px; }}
  </style>
</head>
<body>
  <main class="page">
    <header>
      <h1>足球竞彩赛后复盘</h1>
      <p>生成时间：{text(data.get('generated_at'))}。本报告用于复盘模型与数据偏差，不提供追损、翻本或资金配置建议。</p>
    </header>
    <section>
      <h2>复盘摘要</h2>
      <div class="meta">
        <span>已复盘：{text(data.get('reviewed_count'))}</span>
        <span>跳过：{text(data.get('skipped_count'))}</span>
        <span>票单命中：{text(summary.get('leg_hits'))}/{text(summary.get('leg_known'))}</span>
        <span>赛果命中：{text(summary.get('result_hits'))}/{text(summary.get('result_known'))}</span>
        <span>大小球命中：{text(summary.get('over_under_hits'))}/{text(summary.get('over_under_known'))}</span>
        <span>比分Top1：{text(summary.get('score_top1_hits'))}</span>
        <span>比分Top3：{text(summary.get('score_top3_hits'))}</span>
        <span>比分覆盖：{text(summary.get('score_coverage_hits'))}</span>
      </div>
      <p>市场拆分：{text(metric_breakdown)}</p>
      <div class="warning">复盘结论只用于校准模型和数据流程；不得把单次命中或未命中解释为下一场确定性结果。</div>
    </section>
    <section>
      <h2>命中统计</h2>
      <table><thead><tr><th>比赛</th><th>比分</th><th>赛果</th><th>赛果预测</th><th>大小球</th><th>Top1</th><th>Top3</th><th>覆盖</th><th>票单</th><th>来源</th><th>匹配</th></tr></thead><tbody>{''.join(review_rows)}</tbody></table>
    </section>
    <section>
      <h2>逐场复盘</h2>
      {''.join(detail_cards) or '<p>没有可复盘比赛。</p>'}
    </section>
    <section>
      <h2>跳过项</h2>
      <table><thead><tr><th>比赛</th><th>报告</th><th>原因</th><th>匹配置信度</th></tr></thead><tbody>{''.join(skipped_rows)}</tbody></table>
    </section>
  </main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-build a post-match review bundle and Chinese HTML report.")
    parser.add_argument("--predictions-dir", type=Path, default=Path("data/football/predictions"))
    parser.add_argument("--results-input", type=Path, help="Optional local match_results JSON for tests or user-provided results.")
    parser.add_argument("--review-out-dir", type=Path, default=Path("data/football/reviews"))
    parser.add_argument("--report-out-dir", type=Path, default=Path("reports/football-betting-assistant"))
    parser.add_argument("--window-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--all-history", action="store_true")
    parser.add_argument("--now", help="Override current time for deterministic tests.")
    parser.add_argument("--the-odds-sports", default="soccer", help="Comma-separated The Odds API sport keys for scores fallback.")
    args = parser.parse_args()

    current_time = now_local(args.now)
    static_results = load_results_input(args.results_input)
    candidates, skipped = load_prediction_candidates(args.predictions_dir, current_time, args.all_history, args.window_days)
    bundle = build_aggregate_review(candidates, static_results, [item.strip() for item in args.the_odds_sports.split(",") if item.strip()], current_time)
    bundle["data"]["skipped"].extend(skipped)
    bundle["data"]["skipped_count"] = len(bundle["data"]["skipped"])
    stamp = stamp_for_filename(current_time)
    review_path = write_unique(args.review_out_dir / f"{stamp}-auto-post-match-review.review.json", bundle)
    html_path = write_unique(args.report_out_dir / f"{stamp}-auto-post-match-review.html", render_review_html(bundle))
    print(
        json.dumps(
            {
                "review_path": str(review_path),
                "html_report_path": str(html_path),
                "reviewed_count": bundle["data"]["reviewed_count"],
                "skipped_count": bundle["data"]["skipped_count"],
                "chat_summary": [
                    f"已自动复盘 {bundle['data']['reviewed_count']} 场，跳过 {len(bundle['data']['skipped'])} 项。",
                    f"HTML 复盘报告：{html_path}",
                    f"结构化复盘数据：{review_path}",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
