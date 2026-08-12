#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "football-betting-assistant" / "scripts" / "football_skill.py"
FIXTURES = ROOT / "tests" / "fixtures" / "football_betting_assistant"


class FootballAgentEntrypointTests(unittest.TestCase):
    def run_entry(self, *args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(["python3", str(ENTRY), *args], cwd=ROOT, text=True, capture_output=True, check=False)
        return result, json.loads(result.stdout)

    def test_doctor_is_offline_fast_and_explicit(self) -> None:
        result, payload = self.run_entry("doctor")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["data"]["offline_ready"])
        self.assertTrue(payload["data"]["network_not_tested"])
        self.assertLess(payload["metrics"]["elapsed_ms"], 500)

    def test_route_separates_backtest_and_portfolio(self) -> None:
        _, backtest = self.run_entry("route", "我有历史赛前预测 JSON，帮我回测校准命中率")
        _, portfolio = self.run_entry("route", "西班牙 vs 日本做竞彩四串一购买参考")
        _, international = self.run_entry("route", "用 The Odds API 查博彩公司海外赔率")
        self.assertEqual(backtest["data"]["mode"], "backtest")
        self.assertEqual(portfolio["data"]["mode"], "portfolio")
        self.assertEqual(portfolio["data"]["runtime_mode"], "china-lottery")
        self.assertEqual(international["data"]["runtime_mode"], "international-odds")

    def test_offline_fetch_and_report_are_validated_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_dir = Path(tmp) / "snapshots"
            report_dir = Path(tmp) / "reports"
            data_dir = Path(tmp) / "data"
            fetched, fetch_payload = self.run_entry(
                "fetch", "--raw-input", str(FIXTURES / "raw" / "sporttery-football-sample.json"), "--out", str(snapshot_dir)
            )
            self.assertEqual(fetched.returncode, 0, fetched.stderr)
            self.assertEqual(fetch_payload["status"], "completed")
            snapshot = fetch_payload["data"]["snapshot_path"]
            reported, report_payload = self.run_entry(
                "report", snapshot, "--report-out-dir", str(report_dir), "--data-out-dir", str(data_dir)
            )
            self.assertEqual(reported.returncode, 0, reported.stderr)
            self.assertTrue(report_payload["data"]["validation"]["valid"])
            self.assertIn("main_plan_allowed", report_payload["data"]["risk_audit"]["summary"])
            self.assertTrue(Path(report_payload["data"]["html_report_path"]).is_file())
            self.assertLess(report_payload["metrics"]["elapsed_ms"], 2000)

    def test_audit_block_is_exposed_as_stable_orchestration_status(self) -> None:
        blocked = {
            "kind": "prediction_snapshot",
            "data": {
                "model_outputs": {
                "match_records": [{
                        "match": "A vs B",
                        "reference_grade": "B",
                        "data_confidence": "low",
                        "risk_flags": ["single_source_odds", "lineup_unconfirmed"],
                        "score_candidates": [{"score": "1:0", "probability": 0.2}],
                    }],
                    "ticket_plans": [{
                        "name": "模型最稳主单",
                        "type": "model_best",
                        "legs": [{"match": "A vs B", "market": "胜平负", "selection": "主胜"}],
                    }],
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blocked.json"
            path.write_text(json.dumps(blocked), encoding="utf-8")
            result, payload = self.run_entry("audit", str(path))
        self.assertEqual(result.returncode, 3)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["error_code"], "RISK_AUDIT_BLOCKED")


if __name__ == "__main__":
    unittest.main()
