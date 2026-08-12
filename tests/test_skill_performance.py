#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillPerformanceTests(unittest.TestCase):
    def test_offline_agent_entrypoints_meet_latency_budget(self) -> None:
        result = subprocess.run(
            ["python3", str(ROOT / "scripts" / "benchmark_skill_entrypoints.py")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["passed"])


if __name__ == "__main__":
    unittest.main()
