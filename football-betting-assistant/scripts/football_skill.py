#!/usr/bin/env python3
"""Single orchestration entry point for Football Betting Assistant agents."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SKILL = "football-betting-assistant"
SCRIPT_DIR = Path(__file__).resolve().parent
SCHEMA_VERSION = "1.0"


def result(command: str, started: float, *, status: str, data_status: str, next_action: str | None,
           data: Any = None, artifacts: list[str] | None = None, warnings: list[str] | None = None,
           error_code: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "command": command,
        "status": status,
        "data_status": data_status,
        "next_action": next_action,
        "artifacts": artifacts or [],
        "warnings": warnings or [],
        "error_code": error_code,
        "metrics": {"elapsed_ms": round((time.perf_counter() - started) * 1000, 3)},
    }
    if data is not None:
        payload["data"] = data
    return payload


def route_request(text: str) -> dict[str, Any]:
    lowered = text.lower()
    if any(word in lowered for word in ("复盘", "昨天买", "赛后")):
        mode = "post_match_review"
        next_action = "优先扫描已保存预测；核实赛果后运行 review。"
    elif any(word in lowered for word in ("回测", "校准", "命中率", "历史预测")):
        mode = "backtest"
        next_action = "取得只含赛前信息且附真实赛果的样本 JSON 后运行 backtest。"
    elif any(word in lowered for word in ("串关", "四串一", "组合", "多场")):
        mode = "portfolio"
        next_action = "确认完整赛程、可购买市场和赔率；再生成组合报告。"
    else:
        mode = "single_match"
        next_action = "确认比赛身份、开赛时间、球队背景和当前可购买赔率。"
    if any(word in lowered for word in ("博彩公司", "bookmaker", "the odds api", "海外赔率", "international odds")):
        runtime_mode = "international-odds"
    elif any(word in lowered for word in ("竞彩", "体育彩票", "让球胜平负", "总进球")):
        runtime_mode = "china-lottery"
    else:
        runtime_mode = "analysis-only"
    has_fixture = any(sep in text for sep in (" vs ", " VS ", "对阵", "对")) or "比赛" in text
    asks_value = any(word in lowered for word in ("价值", "购买", "买", "赔率", "串"))
    return {
        "mode": mode,
        "runtime_mode": runtime_mode,
        "fixture_present": has_fixture,
        "value_or_ticket_requested": asks_value,
        "stages": ["probability_analysis", "value_judgment", "reference_purchase_plan"],
        "next_action": next_action if has_fixture else "先发现或确认具体比赛，不从记忆虚构赛程。",
    }


def doctor() -> dict[str, Any]:
    required = ["fetch_match_data.py", "build_snapshot_report.py", "validate_inputs.py", "preflight_risk_audit.py"]
    credentials = {name: bool(os.environ.get(name)) for name in ("THE_ODDS_API_KEY", "FOOTBALL_DATA_API_KEY", "API_FOOTBALL_KEY")}
    return {
        "python": sys.version.split()[0],
        "required_scripts": {name: (SCRIPT_DIR / name).is_file() for name in required},
        "missing_required": [name for name in required if not (SCRIPT_DIR / name).is_file()],
        "optional_credentials_configured": credentials,
        "curl_available": bool(shutil.which("curl")),
        "offline_ready": all((SCRIPT_DIR / name).is_file() for name in required),
        "network_not_tested": True,
    }


def run_child(script: str, arguments: list[str]) -> tuple[int, Any, str]:
    process = subprocess.run([sys.executable, str(SCRIPT_DIR / script), *arguments], text=True, capture_output=True, check=False)
    stream = process.stdout.strip() or process.stderr.strip()
    try:
        payload: Any = json.loads(stream)
    except json.JSONDecodeError:
        payload = {"raw_output": stream}
    return process.returncode, payload, process.stderr.strip()


def child_error_code(command: str, payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    if "no matching fixtures" in text:
        return "FIXTURE_NOT_FOUND"
    if command == "fetch":
        return "SOURCE_UNAVAILABLE"
    if command == "validate":
        return "DATA_VALIDATION_FAILED"
    if command == "report":
        return "REPORT_GENERATION_FAILED"
    if command == "backtest":
        return "BACKTEST_INPUT_INVALID"
    return "CHILD_COMMAND_FAILED"


def collect_artifacts(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    return [value for key, value in payload.items() if isinstance(value, str) and (key.endswith("_path") or key.endswith("_file"))]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check local capabilities without contacting providers.")
    route = commands.add_parser("route", help="Classify a natural-language football request.")
    route.add_argument("text")
    fetch = commands.add_parser("fetch", help="Fetch or parse a normalized China Sports Lottery snapshot.")
    fetch.add_argument("--raw-input")
    fetch.add_argument("--out", default="data/football/snapshots")
    report = commands.add_parser("report", help="Build an HTML report and linked prediction snapshot.")
    report.add_argument("snapshot")
    report.add_argument("--date")
    report.add_argument("--match-no")
    report.add_argument("--team")
    report.add_argument("--competition")
    report.add_argument("--competition-context")
    report.add_argument("--topic", default="football-betting")
    report.add_argument("--report-out-dir", default="reports/football-betting-assistant")
    report.add_argument("--data-out-dir", default="data/football")
    validate = commands.add_parser("validate", help="Validate structured football JSON.")
    validate.add_argument("input")
    audit = commands.add_parser("audit", help="Run the mandatory preflight portfolio risk audit.")
    audit.add_argument("input")
    backtest = commands.add_parser("backtest", help="Backtest pre-match samples with final results.")
    backtest.add_argument("input")
    review = commands.add_parser("review", help="Build zero-operation post-match review artifacts.")
    review.add_argument("--predictions-dir", default="data/football/predictions")
    review.add_argument("--results-input")
    review.add_argument("--review-out-dir", default="data/football/reviews")
    review.add_argument("--report-out-dir", default="reports/football-betting-assistant")
    review.add_argument("--all-history", action="store_true")
    return parser


def main() -> int:
    started = time.perf_counter()
    args = build_parser().parse_args()
    if args.command == "doctor":
        data = doctor()
        status = "ready" if data["offline_ready"] else "blocked"
        output = result("doctor", started, status=status, data_status="capabilities_checked", next_action=None if status == "ready" else "Restore missing bundled scripts.", data=data, error_code=None if status == "ready" else "DEPENDENCY_MISSING")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if status == "ready" else 2
    if args.command == "route":
        data = route_request(args.text)
        output = result("route", started, status="ready", data_status="request_classified", next_action=data["next_action"], data=data)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    if args.command == "fetch":
        script, child = "fetch_match_data.py", ["--mode", "china-lottery", "--provider", "sporttery", "--football", "--out", args.out]
        if args.raw_input:
            child += ["--raw-input", args.raw_input]
    elif args.command == "report":
        script, child = "build_snapshot_report.py", [args.snapshot, "--topic", args.topic, "--report-out-dir", args.report_out_dir, "--data-out-dir", args.data_out_dir]
        for option in ("date", "match_no", "team", "competition", "competition_context"):
            value = getattr(args, option)
            if value:
                child += ["--" + option.replace("_", "-"), value]
    elif args.command == "validate":
        script, child = "validate_inputs.py", [args.input]
    elif args.command == "audit":
        script, child = "preflight_risk_audit.py", [args.input]
    elif args.command == "backtest":
        script, child = "backtest_predictions.py", [args.input]
    else:
        script, child = "auto_post_match_review.py", ["--predictions-dir", args.predictions_dir, "--review-out-dir", args.review_out_dir, "--report-out-dir", args.report_out_dir]
        if args.results_input:
            child += ["--results-input", args.results_input]
        if args.all_history:
            child += ["--all-history"]

    code, payload, stderr = run_child(script, child)
    if code == 0 and args.command == "report" and isinstance(payload, dict):
        # The HTML renderer has already enforced html-report.schema.json. The
        # cross-workflow validator checks the linked prediction snapshot used
        # by review and backtesting.
        validation_code, validation, _ = run_child("validate_inputs.py", [str(payload.get("prediction_snapshot_path", ""))])
        audit_code, audit, _ = run_child("preflight_risk_audit.py", [str(payload.get("prediction_snapshot_path", ""))])
        payload = {**payload, "validation": validation, "risk_audit": audit}
        if validation_code != 0:
            code = validation_code
        elif audit_code != 0:
            code = audit_code
    artifacts = collect_artifacts(payload)
    if code == 0:
        audit_result = payload.get("risk_audit", {}) if args.command == "report" and isinstance(payload, dict) else payload
        if args.command in {"audit", "report"} and isinstance(audit_result, dict) and not audit_result.get("summary", {}).get("main_plan_allowed", True):
            status, data_status, next_action, error_code = "blocked", "risk_audit_blocked", "Protect, downgrade, or remove every blocked leg before naming a main plan.", "RISK_AUDIT_BLOCKED"
            code = 3
        elif args.command == "fetch" and isinstance(payload, dict) and payload.get("errors"):
            status, data_status, next_action, error_code = "degraded", "partial_snapshot", "Resolve source or parser errors before treating every market as verified.", "PARTIAL_SOURCE_DATA"
        else:
            status, data_status, next_action, error_code = "completed", "validated_output", None, None
    else:
        status, data_status, next_action, error_code = "blocked", "child_command_failed", "Inspect missing fixtures, markets, data validity, or provider availability before retrying.", child_error_code(args.command, payload)
    warnings = [stderr] if stderr and not isinstance(payload, dict) else []
    output = result(args.command, started, status=status, data_status=data_status, next_action=next_action, data=payload, artifacts=artifacts, warnings=warnings, error_code=error_code)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
