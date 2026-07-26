#!/usr/bin/env python3
"""Render a football betting HTML report from structured JSON.

The renderer intentionally uses only the Python standard library so the skill
package remains portable. It validates the domain-specific ticket limits and
escapes all report content before writing a self-contained HTML file.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from handicap_rules import (
    handicap_text_conflicts,
    mapping_table_text,
    missing_handicap_outcomes,
    parse_handicap_line,
    split_scores,
)

SCORE_TYPES = {"score_4fold", "score_coverage"}
DIRECTION_TYPES = {
    "model_best",
    "result_handicap",
    "totals",
    "stable_small_combo",
    "aggressive",
    "big_score",
    "backup",
    "mixed",
}
DATA_STATUS_LABELS = {
    "complete": "完整",
    "usable-but-downgraded": "可用但降级",
    "no-actual-odds-lines": "无实际赔率/盘口",
    "insufficient-data": "数据不足",
}
REQUIRED_REPORT_FIELDS = ("title", "date", "topic", "data_status")
REQUIRED_MATCH_FIELDS = (
    "match",
    "kickoff_time",
    "competition",
    "data_confidence",
    "result_pick",
    "result_protection",
    "handicap_pick",
    "totals_pick",
    "score_candidates",
    "bayesian_adjustments",
    "poisson_summary",
    "risk_notes",
)
REQUIRED_TICKET_FIELDS = (
    "name",
    "type",
    "legs",
    "unit_math",
    "amount_text",
    "odds_status",
    "risk_level",
    "reason",
)


class ReportValidationError(ValueError):
    """Raised when report JSON violates the HTML report contract."""


def text(value: Any, fallback: str = "未确认") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return html.escape(value if value.strip() else fallback)
    if isinstance(value, (int, float)):
        return html.escape(str(value))
    if isinstance(value, list):
        if not value:
            return fallback
        return html.escape(" / ".join(str(item) for item in value))
    return html.escape(str(value))


def raw_text(value: Any, fallback: str = "未确认") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value if value.strip() else fallback
    if isinstance(value, list):
        return " / ".join(str(item) for item in value) if value else fallback
    return str(value)


def list_items(items: Any, fallback: str = "未确认") -> str:
    if not isinstance(items, list) or not items:
        return f"<li>{text(fallback)}</li>"
    return "".join(f"<li>{text(item)}</li>" for item in items)


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "football-betting-report"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 2
    while True:
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def validate_required(record: dict[str, Any], fields: tuple[str, ...], label: str) -> None:
    missing = [field for field in fields if field not in record]
    if missing:
        raise ReportValidationError(f"{label} missing required fields: {', '.join(missing)}")


def validate_ticket_plan(plan: dict[str, Any], index: int) -> None:
    validate_required(plan, REQUIRED_TICKET_FIELDS, f"ticket_plans[{index}]")
    plan_type = plan.get("type")
    legs = plan.get("legs")
    if not isinstance(legs, list):
        raise ReportValidationError(f"ticket_plans[{index}].legs must be a list")
    if plan_type in SCORE_TYPES and len(legs) > 4:
        raise ReportValidationError(f"ticket_plans[{index}] exact-score tickets may contain at most 4 legs")
    if plan_type in DIRECTION_TYPES and len(legs) > 8:
        raise ReportValidationError(f"ticket_plans[{index}] direction tickets may contain at most 8 legs")
    if plan_type not in SCORE_TYPES and plan_type not in DIRECTION_TYPES:
        raise ReportValidationError(f"ticket_plans[{index}].type is unsupported: {plan_type}")


def normalize_match_name(value: Any) -> str:
    return re.sub(r"\s+", "", raw_text(value, "")).replace("：", ":").lower()


def find_match_analysis(leg: dict[str, Any], analyses: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    match_text = normalize_match_name(leg.get("match"))
    if match_text in analyses:
        return analyses[match_text]
    for key, analysis in analyses.items():
        if match_text and (match_text in key or key in match_text):
            return analysis
    return None


def validate_handicap_consistency(document: dict[str, Any]) -> None:
    analyses = {
        normalize_match_name(item.get("match")): item
        for item in document.get("match_analyses", [])
        if isinstance(item, dict) and item.get("match")
    }
    for plan_index, plan in enumerate(document.get("ticket_plans", []) or []):
        for leg_index, leg in enumerate(plan.get("legs") or []):
            if not isinstance(leg, dict):
                continue
            market = raw_text(leg.get("market"), "")
            selection = raw_text(leg.get("selection"), "")
            if "让" not in market and "handicap" not in market and "让" not in selection:
                continue
            analysis = find_match_analysis(leg, analyses)
            line = parse_handicap_line(
                leg.get("source_line"),
                leg.get("line"),
                leg.get("handicap_line"),
                analysis.get("handicap_line") if analysis else None,
                analysis.get("handicap_pick") if analysis else None,
                market,
                selection,
            )
            if line is None or not analysis:
                continue
            scores = split_scores(
                leg.get("score_candidates")
                or leg.get("score_coverage")
                or analysis.get("score_candidates")
            )
            if not scores:
                continue
            missing = missing_handicap_outcomes(selection, scores, line, limit=5)
            if missing:
                mapping = mapping_table_text(scores, line, limit=5)
                raise ReportValidationError(
                    f"ticket_plans[{plan_index}].legs[{leg_index}] handicap selection omits {', '.join(missing)} from score mapping: {mapping}"
                )
            prose = " ".join(
                raw_text(value, "")
                for value in (
                    market,
                    selection,
                    leg.get("reason"),
                )
            )
            conflicts = handicap_text_conflicts(prose, line)
            if conflicts:
                mapping = mapping_table_text(scores, line, limit=5)
                raise ReportValidationError(
                    f"ticket_plans[{plan_index}].legs[{leg_index}] handicap prose conflicts with mapping {mapping}: {'; '.join(conflicts)}"
                )


def validate_report(document: dict[str, Any]) -> None:
    if not isinstance(document, dict):
        raise ReportValidationError("report document must be an object")
    report = document.get("report")
    if not isinstance(report, dict):
        raise ReportValidationError("report must be an object")
    validate_required(report, REQUIRED_REPORT_FIELDS, "report")
    if report.get("data_status") not in DATA_STATUS_LABELS:
        raise ReportValidationError("report.data_status is invalid")
    fixtures = document.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise ReportValidationError("fixtures must be a non-empty list")
    match_analyses = document.get("match_analyses")
    if not isinstance(match_analyses, list) or not match_analyses:
        raise ReportValidationError("match_analyses must be a non-empty list")
    for index, match in enumerate(match_analyses):
        if not isinstance(match, dict):
            raise ReportValidationError(f"match_analyses[{index}] must be an object")
        validate_required(match, REQUIRED_MATCH_FIELDS, f"match_analyses[{index}]")
    ticket_plans = document.get("ticket_plans", [])
    if not isinstance(ticket_plans, list):
        raise ReportValidationError("ticket_plans must be a list")
    for index, plan in enumerate(ticket_plans):
        if not isinstance(plan, dict):
            raise ReportValidationError(f"ticket_plans[{index}] must be an object")
        validate_ticket_plan(plan, index)
    for index, plan in enumerate(document.get("optional_small_combinations", []) or []):
        if not isinstance(plan, dict):
            raise ReportValidationError(f"optional_small_combinations[{index}] must be an object")
        validate_ticket_plan(plan, index)
    validate_handicap_consistency(document)


def render_fixture_rows(fixtures: list[dict[str, Any]]) -> str:
    rows = []
    for item in fixtures:
        rows.append(
            "<tr>"
            f"<td>{text(item.get('kickoff_time'))}</td>"
            f"<td>{text(item.get('match'))}</td>"
            f"<td>{text(item.get('competition'))}</td>"
            f"<td>{text(item.get('group'))}</td>"
            f"<td>{text(item.get('records'))}</td>"
            f"<td>{text(item.get('venue'))}</td>"
            f"<td>{text(item.get('data_confidence'))}</td>"
            "</tr>"
        )
    return "".join(rows)


def render_direction_rows(rows_data: list[dict[str, Any]]) -> str:
    rows = []
    for item in rows_data:
        rows.append(
            "<tr>"
            f"<td>{text(item.get('match'))}</td>"
            f"<td>{text(item.get('main_direction'))}</td>"
            f"<td>{text(item.get('protection'))}</td>"
            f"<td>{text(item.get('handicap_pick'))}</td>"
            f"<td>{text(item.get('totals_pick'))}</td>"
            f"<td>{text(item.get('score_lean'))}</td>"
            f"<td>{text(item.get('stability'))}</td>"
            f"<td>{text(item.get('risk'))}</td>"
            "</tr>"
        )
    return "".join(rows)


def render_match_cards(matches: list[dict[str, Any]]) -> str:
    cards = []
    for item in matches:
        cards.append(
            "<article class='match-card'>"
            f"<h3>{text(item.get('match'))}</h3>"
            "<div class='meta'>"
            f"<span>{text(item.get('kickoff_time'))}</span>"
            f"<span>{text(item.get('competition'))}</span>"
            f"<span>数据置信度：{text(item.get('data_confidence'))}</span>"
            f"<span>模型置信度：{text(item.get('model_confidence'))}</span>"
            f"<span>赔率状态：{text(item.get('odds_status'), '未取得')}</span>"
            "</div>"
            f"<p>{text(item.get('analysis'))}</p>"
            "<div class='pick-grid'>"
            f"<div><strong>胜平负</strong><br>{text(item.get('result_pick'))}</div>"
            f"<div><strong>防范</strong><br>{text(item.get('result_protection'))}</div>"
            f"<div><strong>让球</strong><br>{text(item.get('handicap_pick'))}</div>"
            f"<div><strong>大小球/总进球</strong><br>{text(item.get('totals_pick'))}</div>"
            f"<div><strong>比分候选</strong><br>{text(item.get('score_candidates'))}</div>"
            "</div>"
            "<h4>贝叶斯修正</h4>"
            f"<ul>{list_items(item.get('bayesian_adjustments'))}</ul>"
            "<h4>泊松模型</h4>"
            f"<p>{text(item.get('poisson_summary'))}</p>"
            "<h4>风险点</h4>"
            f"<ul>{list_items(item.get('risk_notes'))}</ul>"
            "</article>"
        )
    return "".join(cards)


def render_ticket_plan(plan: dict[str, Any]) -> str:
    legs = plan.get("legs") or []
    leg_rows = "".join(
        "<tr>"
        f"<td>{text(leg.get('match'))}</td>"
        f"<td>{text(leg.get('market'))}</td>"
        f"<td>{text(leg.get('selection'))}</td>"
        f"<td>{text(leg.get('reason'))}</td>"
        "</tr>"
        for leg in legs
    )
    return (
        "<article class='ticket-card'>"
        f"<h3>{text(plan.get('name'))}</h3>"
        "<div class='meta'>"
        f"<span>类型：{text(plan.get('type'))}</span>"
        f"<span>注数：{text(plan.get('unit_math'))}</span>"
        f"<span>合计：{text(plan.get('amount_text'))}</span>"
        f"<span>赔率状态：{text(plan.get('odds_status'))}</span>"
        f"<span>风险：{text(plan.get('risk_level'))}</span>"
        "</div>"
        f"<p>{text(plan.get('reason'))}</p>"
        "<table><thead><tr><th>比赛</th><th>市场</th><th>选择</th><th>理由</th></tr></thead>"
        f"<tbody>{leg_rows}</tbody></table>"
        "</article>"
    )


def render_ticket_plans(plans: list[dict[str, Any]]) -> str:
    order = {
        "model_best": 1,
        "result_handicap": 2,
        "totals": 3,
        "score_4fold": 4,
        "score_coverage": 5,
        "stable_small_combo": 6,
        "aggressive": 7,
        "big_score": 8,
        "backup": 9,
        "mixed": 10,
    }
    sorted_plans = sorted(plans, key=lambda item: order.get(str(item.get("type")), 99))
    return "".join(render_ticket_plan(plan) for plan in sorted_plans)


def render_rankings(rankings: dict[str, Any]) -> str:
    return (
        "<div class='rank-grid'>"
        f"<div><h3>胜平负/让球排序</h3><ol>{list_items(rankings.get('result'))}</ol></div>"
        f"<div><h3>大小球/总进球排序</h3><ol>{list_items(rankings.get('totals'))}</ol></div>"
        f"<div><h3>比分集中度排序</h3><ol>{list_items(rankings.get('score_concentration'))}</ol></div>"
        "</div>"
    )


def render_backup(items: list[dict[str, Any]]) -> str:
    if not items:
        return "<p>未提供备选/替换。</p>"
    rows = []
    for item in items:
        rows.append(
            "<tr>"
            f"<td>{text(item.get('original'))}</td>"
            f"<td>{text(item.get('replacement'))}</td>"
            f"<td>{text(item.get('effect'))}</td>"
            f"<td>{text(item.get('reason'))}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>原选择</th><th>替换</th><th>影响</th><th>理由</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def render_html(document: dict[str, Any]) -> str:
    report = document["report"]
    data_status = str(report.get("data_status"))
    data_status_label = DATA_STATUS_LABELS.get(data_status, data_status)
    context = document.get("competition_context") or {}
    rankings_html = render_rankings(document.get("model_rankings") or {})
    no_odds_warning = ""
    if data_status == "no-actual-odds-lines":
        no_odds_warning = (
            "<div class='warning'><strong>赔率/盘口提示：</strong>"
            "本次未取得实际赔率和盘口，不能做完整赔率价值判断；购买方案仅作概率倾向和参考结构。</div>"
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{text(report.get('title'))}</title>
  <style>
    :root {{ color-scheme: light; --ink:#17202a; --muted:#657080; --line:#d9dee7; --soft:#f4f7fb; --brand:#0f766e; --risk:#b42318; --warn:#9a6700; }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,"Noto Sans SC",sans-serif; color:var(--ink); background:#eef2f6; line-height:1.55; }}
    .page {{ max-width:1180px; margin:0 auto; padding:28px; }}
    header {{ background:#0f172a; color:#fff; padding:28px; border-radius:8px; }}
    header h1 {{ margin:0 0 10px; font-size:28px; }}
    header p {{ margin:0; color:#cbd5e1; }}
    section, .match-card, .ticket-card {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:20px; margin-top:18px; }}
    h2 {{ margin:0 0 14px; font-size:21px; }}
    h3 {{ margin:0 0 10px; font-size:17px; }}
    h4 {{ margin:16px 0 6px; font-size:14px; color:#334155; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th, td {{ border-bottom:1px solid var(--line); padding:10px; vertical-align:top; text-align:left; }}
    th {{ background:var(--soft); font-weight:650; }}
    .summary-grid, .pick-grid, .rank-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; }}
    .metric, .pick-grid div, .rank-grid div {{ background:var(--soft); border:1px solid var(--line); border-radius:8px; padding:12px; }}
    .meta {{ display:flex; flex-wrap:wrap; gap:8px; margin:8px 0 12px; }}
    .meta span {{ background:#ecfeff; color:#155e75; border:1px solid #a5f3fc; border-radius:999px; padding:3px 9px; font-size:12px; }}
    .warning {{ border:1px solid #facc15; background:#fefce8; color:#713f12; border-radius:8px; padding:12px; margin-top:14px; }}
    .risk {{ border-left:4px solid var(--risk); background:#fff7f7; padding:10px 12px; }}
    .muted {{ color:var(--muted); }}
    ol, ul {{ margin:8px 0 0 20px; padding:0; }}
  </style>
</head>
<body>
<div class="page">
  <header>
    <h1>{text(report.get('title'))}</h1>
    <p>{text(report.get('summary'))}</p>
  </header>
  <section>
    <h2>报告摘要</h2>
    <div class="summary-grid">
      <div class="metric"><strong>日期</strong><br>{text(report.get('date'))}</div>
      <div class="metric"><strong>主题</strong><br>{text(report.get('topic'))}</div>
      <div class="metric"><strong>数据状态</strong><br>{text(data_status_label)}</div>
      <div class="metric"><strong>赔率状态</strong><br>{text(report.get('odds_status'), '未取得')}</div>
      <div class="metric"><strong>整体风险</strong><br>{text(report.get('risk_level'))}</div>
      <div class="metric"><strong>生成时间</strong><br>{text(report.get('generated_at'), datetime.now().isoformat(timespec='seconds'))}</div>
    </div>
    {no_odds_warning}
  </section>
  <section>
    <h2>北京时间比赛清单</h2>
    <table><thead><tr><th>时间</th><th>比赛</th><th>赛事</th><th>分组</th><th>战绩</th><th>场地</th><th>数据</th></tr></thead>
    <tbody>{render_fixture_rows(document.get('fixtures', []))}</tbody></table>
  </section>
  <section>
    <h2>赛制背景总分析</h2>
    <h3>{text(context.get('title'), 'Competition Context Analysis')}</h3>
    <p>{text(context.get('summary'))}</p>
    <ul>{list_items(context.get('items'))}</ul>
  </section>
  <section>
    <h2>先给方向总表</h2>
    <table><thead><tr><th>比赛</th><th>主方向</th><th>防范</th><th>让球</th><th>大小球/总进球</th><th>比分倾向</th><th>稳度</th><th>风险</th></tr></thead>
    <tbody>{render_direction_rows(document.get('direction_summary', []))}</tbody></table>
  </section>
  <section>
    <h2>模型排序</h2>
    {rankings_html}
  </section>
  <section>
    <h2>逐场深度分析</h2>
    {render_match_cards(document.get('match_analyses', []))}
  </section>
  <section>
    <h2>购买方案</h2>
    {render_ticket_plans(document.get('ticket_plans', []))}
  </section>
  <section>
    <h2>入选与排除理由</h2>
    <ul>{list_items(document.get('selection_rationale'))}</ul>
  </section>
  <section>
    <h2>备选/替换与可选小组合</h2>
    {render_backup(document.get('backup_replacements') or [])}
    <h3>可选小组合</h3>
    {render_ticket_plans(document.get('optional_small_combinations') or [])}
  </section>
  <section>
    <h2>风险与数据缺口</h2>
    <div class="risk"><strong>风险点</strong><ul>{list_items(document.get('risks'))}</ul></div>
    <div class="risk"><strong>数据缺口</strong><ul>{list_items(document.get('data_gaps'))}</ul></div>
  </section>
</div>
</body>
</html>
"""


def output_path(document: dict[str, Any], out_dir: Path) -> Path:
    report = document["report"]
    date_part = slugify(raw_text(report.get("date"), datetime.now().date().isoformat()))
    topic_part = slugify(raw_text(report.get("topic"), "football-betting"))
    match_count = len(document.get("fixtures") or [])
    path = out_dir / f"{date_part}-{topic_part}-{match_count}matches.html"
    return unique_path(path)


def render_to_file(document: dict[str, Any], out_dir: Path) -> Path:
    validate_report(document)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = output_path(document, out_dir)
    path.write_text(render_html(document), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a football betting HTML report from JSON")
    parser.add_argument("input", type=Path, help="Path to html-report JSON")
    parser.add_argument("--out-dir", type=Path, default=Path.cwd() / "reports" / "football-betting-assistant")
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.input.read_text(encoding="utf-8"))
        path = render_to_file(document, args.out_dir)
    except (OSError, json.JSONDecodeError, ReportValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
