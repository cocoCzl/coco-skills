#!/usr/bin/env python3
"""Offline smoke test for the zero-operation snapshot-backed flow."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _competition_from_request(request: str) -> str | None:
    if "世界杯" in request:
        return "世界杯"
    return None


def run_flow(snapshot: Path, request: str, report_out_dir: Path, data_out_dir: Path, *, date: str) -> dict:
    builder = Path(__file__).resolve().parents[2] / "football-betting-assistant" / "scripts" / "build_snapshot_report.py"
    base_command = [
        sys.executable,
        str(builder),
        str(snapshot),
        "--topic",
        request[:60] or "football-betting",
        "--report-out-dir",
        str(report_out_dir),
        "--data-out-dir",
        str(data_out_dir),
    ]
    command = [*base_command]
    competition = _competition_from_request(request)
    if date:
        command.extend(["--date", date])
    if competition:
        command.extend(["--competition", competition])

    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return {
            "ok": False,
            "error": result.stderr.strip() or result.stdout.strip(),
            "snapshot_path": str(snapshot),
            "chat_response_lines": [
                "未能完成快照驱动 HTML 报告生成。",
                f"快照路径：{snapshot}",
            ],
        }

    payload = json.loads(result.stdout)
    return {
        "ok": True,
        "request": request,
        "selected_matches": payload.get("matches"),
        "html_report_path": payload.get("html_report_path"),
        "prediction_snapshot_path": payload.get("prediction_snapshot_path"),
        "chat_response_lines": [
            *payload.get("chat_summary", [])[:2],
            f"HTML 报告：{payload.get('html_report_path')}",
            f"预测快照：{payload.get('prediction_snapshot_path')}",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run offline zero-operation smoke flow against a fixture snapshot.")
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--request", default="检查历史夹具中的世界杯市场快照")
    parser.add_argument("--date", required=True, help="Explicit fixture date, YYYY-MM-DD; never retry without this filter.")
    parser.add_argument("--report-out-dir", type=Path, default=Path("reports/football-betting-assistant"))
    parser.add_argument("--data-out-dir", type=Path, default=Path("data/football"))
    args = parser.parse_args()

    output = run_flow(args.snapshot, args.request, args.report_out_dir, args.data_out_dir, date=args.date)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
