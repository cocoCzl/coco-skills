#!/usr/bin/env python3
"""Offline, deterministic latency checks for the three agent entrypoints."""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def measure(command: list[str], iterations: int = 5) -> dict[str, object]:
    durations = []
    for _ in range(iterations):
        started = time.perf_counter()
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        durations.append((time.perf_counter() - started) * 1000)
        if result.returncode != 0:
            raise RuntimeError(result.stdout + result.stderr)
    return {
        "iterations": iterations,
        "mean_ms": round(statistics.mean(durations), 3),
        "max_ms": round(max(durations), 3),
    }


def main() -> int:
    python = sys.executable
    with tempfile.TemporaryDirectory() as tmp:
        checks = {
            "resume_doctor": measure([python, "ai-resume-expert/scripts/resume_skill.py", "doctor"]),
            "resume_route": measure([python, "ai-resume-expert/scripts/resume_skill.py", "route", "优化 Java 后端简历"]),
            "football_doctor": measure([python, "football-betting-assistant/scripts/football_skill.py", "doctor"]),
            "football_route": measure([python, "football-betting-assistant/scripts/football_skill.py", "route", "明天竞彩四串一"]),
            "lottery_doctor": measure([python, "lottery-number-recommendation/scripts/lottery_skill.py", "--data-dir", tmp, "doctor"]),
            "lottery_parse": measure([python, "lottery-number-recommendation/scripts/lottery_skill.py", "parse-request", "双色球三注最近50期强热号"]),
        }
    limits = {"doctor_and_route_max_ms": 500}
    passed = all(float(item["max_ms"]) < 500 for item in checks.values())
    output = {"passed": passed, "limits": limits, "checks": checks}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
