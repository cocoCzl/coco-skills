#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "lottery-number-recommendation" / "scripts" / "lottery_skill.py"


class LotteryAgentEntrypointTests(unittest.TestCase):
    def test_doctor_is_offline_fast_and_uses_result_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["python3", str(ENTRY), "--data-dir", tmp, "doctor"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["skill"], "lottery-number-recommendation")
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["error_code"], "DATA_NOT_READY")
        self.assertEqual(payload["data"]["ready_games"], [])
        self.assertFalse(payload["data"]["network_tested"])
        self.assertLess(payload["metrics"]["elapsed_ms"], 500)

    def test_failure_has_stable_error_and_no_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["python3", str(ENTRY), "--data-dir", tmp, "backtest", "dlt", "--trials", "1", "--bootstrap-samples", "1"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["status"], "blocked")
        self.assertIsNotNone(payload["error_code"])
        self.assertNotIn("numbers", payload)

    def test_parse_clarification_uses_blocked_state_without_cli_failure(self) -> None:
        result = subprocess.run(
            ["python3", str(ENTRY), "parse-request", "回测效果怎么样"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["error_code"], "REQUEST_CLARIFICATION_REQUIRED")


if __name__ == "__main__":
    unittest.main()
