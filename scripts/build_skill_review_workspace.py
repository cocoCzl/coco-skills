#!/usr/bin/env python3
"""Build deterministic review runs for the three optimized agent interfaces.

This is intentionally not a model-quality A/B benchmark. It gives the human
reviewer real, reproducible routing/doctor/offline outputs while model executor
runs are unavailable, and records that limitation in the benchmark notes.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


CASES = [
    {
        "id": 1,
        "name": "resume-target-role-gate",
        "prompt": "我做过几个 Java 项目，帮我写一份简历。",
        "expectations": ["路由为 generation", "未把 Java 背景误当目标岗位", "下一步只要求确认目标岗位"],
        "command": ["python3", "ai-resume-expert/scripts/resume_skill.py", "route", "我做过几个 Java 项目，帮我写一份简历。"],
        "checks": [("data.mode", "generation"), ("data.target_role_present", False)],
    },
    {
        "id": 2,
        "name": "football-market-routing",
        "prompt": "西班牙 vs 日本做竞彩四串一，截图里有让球但没有普通胜平负。",
        "expectations": ["路由为 portfolio", "选择 china-lottery", "先确认完整赛程和可购买市场"],
        "command": ["python3", "football-betting-assistant/scripts/football_skill.py", "route", "西班牙 vs 日本做竞彩四串一，截图里有让球但没有普通胜平负。"],
        "checks": [("data.mode", "portfolio"), ("data.runtime_mode", "china-lottery")],
    },
    {
        "id": 3,
        "name": "lottery-offline-doctor",
        "prompt": "检查本地大乐透和双色球缓存是否可用，不要联网。",
        "expectations": ["只进行无联网诊断", "没有缓存时不生成号码", "返回明确同步下一步"],
        "command": None,
        "checks": [("data.network_tested", False), ("data.ready_games", [])],
    },
]


def lookup(payload: dict[str, Any], dotted: str) -> Any:
    current: Any = payload
    for part in dotted.split("."):
        current = current[part]
    return current


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit(f"Refusing to overwrite existing workspace: {workspace}")
    workspace.mkdir(parents=True)

    runs = []
    with tempfile.TemporaryDirectory() as tmp:
        for case in CASES:
            eval_dir = workspace / f"eval-{case['id']}-{case['name']}"
            run_dir = eval_dir / "with_skill" / "run-1"
            outputs = run_dir / "outputs"
            outputs.mkdir(parents=True)
            command = case["command"] or ["python3", "lottery-number-recommendation/scripts/lottery_skill.py", "--data-dir", tmp, "doctor"]
            started = time.perf_counter()
            process = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
            duration = time.perf_counter() - started
            if process.returncode != 0:
                raise RuntimeError(process.stdout + process.stderr)
            payload = json.loads(process.stdout)
            (outputs / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            metadata = {"eval_id": case["id"], "eval_name": case["name"], "prompt": case["prompt"], "assertions": case["expectations"]}
            (eval_dir / "eval_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (run_dir / "eval_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            graded = []
            for index, expectation in enumerate(case["expectations"]):
                if index < len(case["checks"]):
                    path, expected = case["checks"][index]
                    actual = lookup(payload, path)
                    passed = actual == expected
                    evidence = f"{path}={actual!r}; expected {expected!r}"
                else:
                    passed = bool(payload.get("next_action"))
                    evidence = f"next_action={payload.get('next_action')!r}"
                graded.append({"text": expectation, "passed": passed, "evidence": evidence})
            passed_count = sum(item["passed"] for item in graded)
            grading = {"expectations": graded, "summary": {"passed": passed_count, "failed": len(graded) - passed_count, "total": len(graded), "pass_rate": passed_count / len(graded)}}
            (run_dir / "grading.json").write_text(json.dumps(grading, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (run_dir / "timing.json").write_text(json.dumps({"total_tokens": 0, "duration_ms": round(duration * 1000, 3), "total_duration_seconds": round(duration, 4)}, indent=2) + "\n", encoding="utf-8")
            runs.append({"eval_id": case["id"], "run_number": 1, "config": "with_skill", "result": {"pass_rate": grading["summary"]["pass_rate"], "passed": passed_count, "failed": len(graded) - passed_count, "total": len(graded)}, "time_seconds": round(duration, 4), "tokens": 0, "expectations": graded})

    rates = [item["result"]["pass_rate"] for item in runs]
    times = [item["time_seconds"] for item in runs]
    benchmark = {
        "metadata": {"skill_name": "coco-skills unified agent interfaces", "runs_per_configuration": 1, "evals_run": [1, 2, 3]},
        "run_summary": {
            "with_skill": {
                "pass_rate": {"mean": sum(rates) / len(rates), "stddev": 0.0, "min": min(rates), "max": max(rates)},
                "time_seconds": {"mean": sum(times) / len(times), "stddev": 0.0, "min": min(times), "max": max(times)},
                "tokens": {"mean": 0.0, "stddev": 0.0, "min": 0.0, "max": 0.0}
            }
        },
        "runs": runs,
        "notes": ["Deterministic interface review only; no model-output A/B baseline was fabricated.", "Use skill-creator run_loop when a model executor and network are available for trigger optimization."],
    }
    (workspace / "benchmark.json").write_text(json.dumps(benchmark, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
