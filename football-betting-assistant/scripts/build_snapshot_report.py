#!/usr/bin/env python3
"""Build an HTML report and prediction snapshot from a football snapshot.

This is the first snapshot-backed report path. It does not pretend to perform
full team-form/xG modeling; it turns verified China lottery market data into a
source-aware report, blocks unavailable markets from purchase plans, and saves
a prediction record for future review.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


try:
    from select_snapshot_matches import select_matches
    from prediction_snapshot_tools import structured_match_record
except ImportError:  # pragma: no cover - direct package execution fallback
    from scripts.select_snapshot_matches import select_matches  # type: ignore
    from scripts.prediction_snapshot_tools import structured_match_record  # type: ignore


BEIJING_TZ = "Asia/Shanghai"
UNIT_PRICE = 2
MARKET_LABELS = {
    "match_result": "胜平负",
    "handicap_match_result": "让球胜平负",
    "correct_score": "比分",
    "over_under": "大小球",
    "total_goals": "总进球",
}
GROUP_STAGE_KEYWORDS = ("小组", "第3轮", "第三轮", "收官", "出线")
HIGH_RISK_FLAGS = {
    "already_in_advance_zone",
    "draw_may_be_sufficient",
    "route_selection_risk",
}


def load_snapshot(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("kind") != "football_snapshot":
        raise ValueError("snapshot kind must be football_snapshot")
    return document["data"]


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def match_name(match: dict[str, Any]) -> str:
    return f"{match.get('home_team')} vs {match.get('away_team')}"


def confidence_zh(value: str | None) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(str(value), "低")


def _find_team_context(competition_context: dict[str, Any], team: str) -> dict[str, Any] | None:
    for group in competition_context.get("groups", []) or []:
        for standing in group.get("standings", []) or []:
            if standing.get("team") == team:
                item = dict(standing)
                item["group"] = group.get("group")
                return item
    return None


def requires_group_context(match: dict[str, Any], topic: str) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in (
            match.get("competition"),
            match.get("round"),
            match.get("stage"),
            match.get("notes"),
            topic,
        )
    )
    return any(keyword in haystack for keyword in GROUP_STAGE_KEYWORDS)


def has_complete_group_context(context: dict[str, Any]) -> bool:
    required = ("rank", "points", "wins", "draws", "losses", "goal_difference", "qualification_pressure", "rotation_risk")
    home = context.get("home")
    away = context.get("away")
    if not home or not away:
        return False
    return all(field in home and field in away for field in required)


def group_context_for_match(match: dict[str, Any], competition_context: dict[str, Any]) -> dict[str, Any]:
    home = _find_team_context(competition_context, str(match.get("home_team") or ""))
    away = _find_team_context(competition_context, str(match.get("away_team") or ""))
    return {"home": home, "away": away}


def standings_line(item: dict[str, Any] | None) -> str:
    if not item:
        return "未确认"
    return (
        f"{item.get('team')} 第{item.get('rank')}，{item.get('points')}分，"
        f"{item.get('wins')}-{item.get('draws')}-{item.get('losses')}，"
        f"净胜球{item.get('goal_difference')}；{item.get('qualification_pressure')}"
    )


def motivation_notes(context: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for side in ("home", "away"):
        item = context.get(side)
        if not item:
            continue
        flags = set(item.get("motivation_flags") or [])
        team = item.get("team")
        if "draw_may_be_sufficient" in flags:
            notes.append(f"{team} 处于直接晋级区边缘，平局可能够用，需提高平局/小比分权重。")
        if "already_in_advance_zone" in flags:
            notes.append(f"{team} 处于直接晋级区，需关注轮换、控节奏和路线选择风险。")
        if "must_win_pressure" in flags:
            notes.append(f"{team} 当前出线压力高，落后或久攻不下时开放性会上升。")
        if "third_place_race" in flags:
            notes.append(f"{team} 处于第三名竞争区，净胜球和避免输球重要。")
    return notes or ["小组积分/出线形势未确认，不能做动机修正。"]


def group_context_gap(name: str, context: dict[str, Any]) -> str:
    missing = []
    if not context.get("home"):
        missing.append("主队")
    if not context.get("away"):
        missing.append("客队")
    detail = "、".join(missing) if missing else "字段不完整"
    return f"{name}：group_context_missing（{detail}缺少完整排名/积分/净胜球/出线压力/轮换风险），不能进入稳健主单。"


def leg_has_group_risk(context: dict[str, Any]) -> bool:
    for side in ("home", "away"):
        item = context.get(side) or {}
        flags = set(item.get("motivation_flags") or [])
        if flags & HIGH_RISK_FLAGS:
            return True
        if "高" in str(item.get("rotation_risk") or ""):
            return True
    return False


def available_markets(match: dict[str, Any]) -> list[dict[str, Any]]:
    markets = []
    for market in match.get("markets", []):
        availability = market.get("availability") or {}
        selections = market.get("selections") or []
        if availability.get("status") == "available" and selections:
            markets.append(market)
    return markets


def blocked_markets(match: dict[str, Any]) -> list[dict[str, Any]]:
    markets = []
    for market in match.get("markets", []):
        if market.get("market") not in MARKET_LABELS:
            continue
        availability = market.get("availability") or {}
        selections = market.get("selections") or []
        if availability.get("status") != "available" or not selections:
            markets.append(market)
    return markets


def selection_text(market: dict[str, Any]) -> str:
    selections = market.get("selections") or []
    return " / ".join(f"{item.get('name')} {item.get('odds')}" for item in selections if item.get("odds") is not None)


def market_line_text(market: dict[str, Any]) -> str:
    line = market.get("line")
    return f"（{line}）" if line not in (None, "") else ""


def main_market_pick(match: dict[str, Any]) -> tuple[str, str, str, dict[str, Any] | None]:
    if match.get("team_type") == "unsupported":
        reason = match.get("unsupported_reason") or "unsupported_team_type"
        return "analysis_only", "不支持正式购买方案", f"该比赛队伍类型为 unsupported（{reason}），不生成正式竞彩购买方案。", None
    markets = {market.get("market"): market for market in available_markets(match)}
    if "match_result" in markets:
        market = markets["match_result"]
        cheapest = min(market.get("selections") or [], key=lambda item: float(item.get("odds") or 999))
        return "胜平负", str(cheapest.get("name")), f"竞彩胜平负可买，当前最低奖金项为 {cheapest.get('name')} {cheapest.get('odds')}，只能作为市场中心参考。", market
    if "handicap_match_result" in markets:
        market = markets["handicap_match_result"]
        cheapest = min(market.get("selections") or [], key=lambda item: float(item.get("odds") or 999))
        return "让球胜平负", f"{market_line_text(market)}{cheapest.get('name')}", f"普通胜平负未确认可买，使用可买让球市场；当前最低奖金项为 {cheapest.get('name')} {cheapest.get('odds')}。", market
    if "total_goals" in markets:
        market = markets["total_goals"]
        cheapest = min(market.get("selections") or [], key=lambda item: float(item.get("odds") or 999))
        return "总进球", str(cheapest.get("name")), f"方向市场不足，保留总进球市场中心 {cheapest.get('name')} {cheapest.get('odds')}。", market
    return "analysis_only", "无可买赔率", "当前快照未取得可用于购买方案的竞彩赔率。", None


def build_stable_reduced_plan(ticket_legs: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [leg for leg in ticket_legs if not leg.get("high_risk")]
    used_fallback = False
    if len(eligible) < 2:
        eligible = ticket_legs
        used_fallback = True
    if len(eligible) < 2:
        return None
    selected_count = 3 if len(eligible) >= 3 else 2
    selected = eligible[:selected_count]
    name = "更稳三串一" if selected_count == 3 else "更稳二串一"
    reason = "从主单中去掉高风险或低上下文确定性的腿，只保留更适合保守参考的方向。"
    if used_fallback:
        reason = "低风险腿不足以单独成单，先减少串关腿数来降低组合波动；仍需关注小组赛轮换和路线选择风险。"
    if selected_count == 2:
        reason = "合格低风险腿不足三场，降为二串一，不硬凑三串一。"
    return {
        "name": name,
        "type": "stable_small_combo",
        "legs": selected,
        "unit_math": "1 x " * (selected_count - 1) + "1 = 1 注",
        "amount_text": f"1 注 x {UNIT_PRICE} 元/注 = {UNIT_PRICE} 元",
        "odds_status": "使用快照中确认可买的竞彩市场",
        "risk_level": "中",
        "reason": reason,
    }


def build_report(snapshot: dict[str, Any], matches: list[dict[str, Any]], topic: str, report_id: str, competition_context: dict[str, Any] | None = None) -> dict[str, Any]:
    generated_at = now_text()
    competition_context = competition_context or snapshot.get("competition_context") or {}
    fixtures = []
    direction_summary = []
    analyses = []
    ticket_legs = []
    data_gaps: list[str] = []
    risks: list[str] = [
        "本报告由竞彩快照生成，尚未接入完整球队近期状态、伤停、首发和 xG 增强模型。",
        "赔率最低项仅表示市场中心，不等同于模型概率最高或存在投注价值。",
    ]

    for match in matches:
        name = match_name(match)
        group_context = group_context_for_match(match, competition_context)
        home_context = group_context.get("home")
        away_context = group_context.get("away")
        context_text = f"{standings_line(home_context)}；{standings_line(away_context)}"
        motivation = motivation_notes(group_context)
        group_context_required = requires_group_context(match, topic)
        group_context_complete = has_complete_group_context(group_context)
        pick_market, pick_selection, reason, source_market = main_market_pick(match)
        available = available_markets(match)
        blocked = blocked_markets(match)
        if group_context_required and not group_context_complete:
            data_gaps.append(group_context_gap(name, group_context))
        if not available:
            data_gaps.append(f"{name}：未取得可买竞彩赔率/盘口，不能生成购买方案。")
        if match.get("team_type") == "unsupported":
            data_gaps.append(f"{name}：队伍类型 unsupported / {match.get('unsupported_reason') or 'unsupported_team_type'}，不生成正式购买方案。")
        for market in blocked:
            label = MARKET_LABELS.get(str(market.get("market")), str(market.get("source_market_name")))
            availability = market.get("availability") or {}
            data_gaps.append(f"{name}：{label} {availability.get('status')} / {availability.get('reason')}。")

        fixtures.append(
            {
                "match": f"{match.get('match_no') or ''} {name}".strip(),
                "kickoff_time": match.get("kickoff_time"),
                "competition": match.get("competition"),
                "group": (home_context or away_context or {}).get("group") or "未确认",
                "records": context_text,
                "venue": match.get("notes") or match.get("venue_type") or "未确认",
                "data_confidence": confidence_zh(match.get("data_confidence")),
            }
        )
        direction_summary.append(
            {
                "match": name,
                "main_direction": f"{pick_market}：{pick_selection}",
                "protection": "等待球队数据和模型概率后确认",
                "handicap_pick": selection_text(next((m for m in available if m.get("market") == "handicap_match_result"), {})) or "未取得",
                "totals_pick": selection_text(next((m for m in available if m.get("market") == "total_goals"), {})) or "未取得",
                "score_lean": "比分赔率未取得或未做泊松覆盖",
                "stability": "降级",
                "risk": " / ".join(motivation[:2]) if group_context_complete or not group_context_required else "group_context_missing：小组上下文不完整，稳健主单禁用",
            }
        )
        analyses.append(
            {
                "match": name,
                "kickoff_time": match.get("kickoff_time"),
                "competition": match.get("competition"),
                "data_confidence": confidence_zh(match.get("data_confidence")),
                "result_pick": selection_text(next((m for m in available if m.get("market") == "match_result"), {})) or "普通胜平负未确认可买",
                "result_protection": "未接入完整模型，不给强保护结论",
                "handicap_pick": selection_text(next((m for m in available if m.get("market") == "handicap_match_result"), {})) or "让球赔率未取得",
                "totals_pick": selection_text(next((m for m in available if m.get("market") == "total_goals"), {})) or "总进球赔率未取得",
                "score_candidates": ["未计算", "等待 xG/泊松模型", "不可作为比分购买方案"],
                "bayesian_adjustments": motivation,
                "poisson_summary": "本快照报告尚未运行 xG/泊松模型；只能确认竞彩市场和赔率可买性。",
                "risk_notes": [
                    reason,
                    "小组赛末轮缺少完整结构化小组上下文时，不得进入稳健主单。" if group_context_required and not group_context_complete else "小组上下文已匹配到双方球队。" if group_context_complete else "非强制小组上下文场景或上下文未提供。",
                    "缺少球队近期状态、赛事积分/战意、伤停首发时，Reference Grade 不能上调。",
                ],
                "analysis": f"已从 {snapshot.get('provider')} 快照确认 {name} 的赛程与部分竞彩可买市场。小组形势：{context_text}。{reason}",
                "model_confidence": "低",
                "odds_status": "竞彩快照可用" if available else "缺少可买赔率",
            }
        )
        if pick_market != "analysis_only" and not (group_context_required and not group_context_complete):
            ticket_legs.append(
                {
                    "match": name,
                    "market": pick_market,
                    "selection": pick_selection,
                    "reason": reason,
                    "high_risk": leg_has_group_risk(group_context),
                    "market_available": True,
                    "source_snapshot_market": source_market.get("market") if source_market else None,
                    "source_market_name": source_market.get("source_market_name") if source_market else None,
                    "source_line": source_market.get("line") if source_market else None,
                    "source_snapshot_id": snapshot.get("snapshot_id"),
                }
            )

    ticket_plans = []
    if ticket_legs:
        unit_count = 1
        main_legs = ticket_legs[:8]
        high_risk_in_main = any(leg.get("high_risk") for leg in main_legs) or len(main_legs) >= 4
        ticket_plans.append(
            {
                "name": "竞彩快照可买市场主单",
                "type": "result_handicap",
                "legs": main_legs,
                "unit_math": f"{unit_count} 注",
                "amount_text": f"{unit_count} 注 x {UNIT_PRICE} 元/注 = {unit_count * UNIT_PRICE} 元",
                "odds_status": "使用快照中确认可买的竞彩市场",
                "risk_level": "中高",
                "reason": "这是市场可买性主单，不是完整模型强推；需等球队数据、xG 和赔率价值判断后再升级。",
            }
        )
        stable_plan = build_stable_reduced_plan(main_legs) if high_risk_in_main else None
        if stable_plan:
            ticket_plans.append(stable_plan)

    data_status = "usable-but-downgraded" if ticket_legs else "no-actual-odds-lines"
    return {
        "report": {
            "report_id": report_id,
            "title": f"{topic} - 竞彩快照报告",
            "date": generated_at[:10],
            "topic": topic,
            "generated_at": generated_at,
            "data_status": data_status,
            "odds_status": "部分竞彩赔率可用" if ticket_legs else "未取得可买赔率",
            "risk_level": "中高",
            "summary": "本报告先完成竞彩赛程、可买市场和赔率快照核验；模型结论按数据不足降级。",
            "chat_summary": [
                f"已从 {snapshot.get('provider')} 快照读取 {len(matches)} 场比赛。",
                "已阻止未确认可买或缺赔率的市场进入购买方案。",
            ],
        },
        "fixtures": fixtures,
        "competition_context": build_competition_context_section(competition_context),
        "direction_summary": direction_summary,
        "model_rankings": {
            "result": [row["main_direction"] for row in direction_summary],
            "totals": ["总进球市场未完整取得或未建模"],
            "score_concentration": ["比分覆盖尚未运行泊松模型"],
        },
        "match_analyses": analyses,
        "ticket_plans": ticket_plans,
        "selection_rationale": [
            "只使用 availability=available 且存在赔率 selection 的竞彩市场。",
            "unknown/source_missing/parse_failed 市场不会进入购买方案。",
        ],
        "backup_replacements": [],
        "optional_small_combinations": [],
        "risks": risks,
        "data_gaps": data_gaps or ["未发现关键市场缺口。"],
    }


def build_competition_context_section(competition_context: dict[str, Any]) -> dict[str, Any]:
    groups = competition_context.get("groups") or []
    if not groups:
        return {
            "title": "赛事背景",
            "summary": "未接入积分榜/出线形势数据；报告必须按数据不足降级。",
            "items": ["小组排名、积分、净胜球、轮换风险和淘汰赛路线均未确认。"],
        }
    items: list[str] = []
    for group in groups:
        standings = []
        for team in group.get("standings", []) or []:
            standings.append(
                f"{team.get('team')} 第{team.get('rank')}，{team.get('points')}分，"
                f"{team.get('wins')}-{team.get('draws')}-{team.get('losses')}，"
                f"净胜球{team.get('goal_difference')}，{team.get('qualification_pressure')}，"
                f"轮换风险：{team.get('rotation_risk')}"
            )
        items.append(f"{group.get('group') or '未确认'}：{'；'.join(standings)}")
    rules = competition_context.get("qualification_rules") or {}
    return {
        "title": "小组积分 / 出线形势",
        "summary": (
            f"积分数据已接入；晋级规则：小组前 {rules.get('advance_top_n', 2)} "
            f"直接晋级，最好第三名名额 {rules.get('best_third_places', 0)}。"
        ),
        "items": items,
    }


def write_json_unique(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        target = path
    else:
        for index in range(2, 1000):
            candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
            if not candidate.exists():
                target = candidate
                break
        else:
            raise RuntimeError(f"Could not create unique file for {path}")
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def render_html(report_input: Path, out_dir: Path) -> Path:
    renderer = Path(__file__).with_name("render_html_report.py")
    result = subprocess.run(
        ["python3", str(renderer), str(report_input), "--out-dir", str(out_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "HTML render failed")
    return Path(result.stdout.strip())


def build_prediction_snapshot(report: dict[str, Any], snapshot: dict[str, Any], html_path: Path, report_input_path: Path) -> dict[str, Any]:
    fixtures_by_match = {
        fixture.get("match"): fixture
        for fixture in report.get("fixtures", [])
        if isinstance(fixture, dict) and fixture.get("match")
    }
    match_records = [
        structured_match_record(analysis, fixtures_by_match.get(analysis.get("match")), report.get("report", {}))
        for analysis in report.get("match_analyses", [])
        if isinstance(analysis, dict)
    ]
    return {
        "kind": "prediction_snapshot",
        "data": {
            "report_id": report["report"].get("report_id"),
            "generated_at": report["report"].get("generated_at"),
            "source_snapshot_id": snapshot.get("snapshot_id"),
            "source_provider": snapshot.get("provider"),
            "html_report_path": str(html_path),
            "html_report_input_path": str(report_input_path),
            "pre_match_data": {
                "fixtures": report.get("fixtures", []),
                "direction_summary": report.get("direction_summary", []),
                "data_gaps": report.get("data_gaps", []),
            },
            "model_outputs": {
                "match_analyses": report.get("match_analyses", []),
                "match_records": match_records,
                "ticket_plans": report.get("ticket_plans", []),
                "risks": report.get("risks", []),
            },
            "post_match_result": None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an HTML report from a normalized football snapshot.")
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--date", help="today, tomorrow, or YYYY-MM-DD in Beijing time")
    parser.add_argument("--match-no")
    parser.add_argument("--team")
    parser.add_argument("--competition")
    parser.add_argument("--competition-context", type=Path, help="Optional calculated competition_context JSON.")
    parser.add_argument("--topic", default="football-betting")
    parser.add_argument("--report-out-dir", type=Path, default=Path("reports/football-betting-assistant"))
    parser.add_argument("--data-out-dir", type=Path, default=Path("data/football"))
    args = parser.parse_args()

    snapshot = load_snapshot(args.snapshot)
    competition_context = None
    if args.competition_context:
        context_document = json.loads(args.competition_context.read_text(encoding="utf-8"))
        competition_context = context_document.get("data", context_document)
    matches = select_matches(snapshot, date=args.date, match_no=args.match_no, team=args.team, competition=args.competition)
    if not matches:
        print(json.dumps({"error": "no matching fixtures in snapshot", "snapshot_id": snapshot.get("snapshot_id")}, ensure_ascii=False, indent=2))
        return 2

    report_id = f"{snapshot.get('snapshot_id')}-{len(matches)}matches"
    report = build_report(snapshot, matches, args.topic, report_id, competition_context=competition_context)
    report_input_path = write_json_unique(args.data_out_dir / "report-inputs" / f"{report_id}.html-report.json", report)
    html_path = render_html(report_input_path, args.report_out_dir)
    prediction = build_prediction_snapshot(report, snapshot, html_path, report_input_path)
    prediction_path = write_json_unique(args.data_out_dir / "predictions" / f"{report_id}.prediction.json", prediction)
    output = {
        "report_id": report_id,
        "matches": len(matches),
        "html_report_path": str(html_path),
        "report_input_path": str(report_input_path),
        "prediction_snapshot_path": str(prediction_path),
        "chat_summary": report["report"].get("chat_summary", []),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
