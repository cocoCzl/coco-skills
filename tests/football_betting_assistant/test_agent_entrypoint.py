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
            self.assertEqual(report_payload["status"], "degraded")
            self.assertEqual(report_payload["data_status"], "usable-but-downgraded")
            self.assertEqual(report_payload["data_status"], report_payload["data"]["data_status"])
            self.assertIn("未运行", " ".join(report_payload["data"]["chat_summary"]))
            self.assertTrue(report_payload["next_action"])
            report_input = json.loads(Path(report_payload["data"]["report_input_path"]).read_text())
            for analysis in report_input["match_analyses"]:
                self.assertIn("尚未运行", analysis["poisson_summary"])
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

    def test_snapshot_without_offered_odds_remains_degraded(self) -> None:
        snapshot = json.loads((FIXTURES / "football-snapshot-sporttery.json").read_text())
        for match in snapshot["data"]["matches"]:
            for market in match["markets"]:
                market["selections"] = []
                market["availability"] = {"status": "unavailable", "reason": "not_offered"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "no-odds.json"
            path.write_text(json.dumps(snapshot))
            result, payload = self.run_entry("report", str(path), "--report-out-dir", str(root / "reports"), "--data-out-dir", str(root / "data"))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(payload["status"], "degraded")
            self.assertEqual(payload["data_status"], "no-actual-odds-lines")
            self.assertIn("未运行", " ".join(payload["data"]["chat_summary"]))

    def test_unsupported_fetch_never_silently_uses_sporttery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "snapshots"
            for mode in ("international-odds", "analysis-only"):
                result, payload = self.run_entry("fetch", "--mode", mode, "--out", str(out), "--raw-input", "missing.json")
                self.assertEqual(result.returncode, 3)
                self.assertEqual(payload["error_code"], "SOURCE_MODE_UNSUPPORTED")
                self.assertEqual(payload["data"]["requested_mode"], mode)
                self.assertEqual(payload["artifacts"], [])
                self.assertFalse(out.exists())

    def test_each_route_has_an_executable_or_explicit_degraded_next_step(self) -> None:
        for prompt, expected, supported in (
            ("中国竞彩查赔率", "fetch --mode china-lottery", True),
            ("用 The Odds API 查海外赔率", "fetch 不支持海外赔率", False),
            ("解释 A vs B 的概率分析", "无赔率时不做价值判断", False),
            ("我有赛前预测 JSON，回测校准", "backtest <samples.json>", False),
            ("复盘昨天的主单", "运行 review", False),
        ):
            with self.subTest(prompt=prompt):
                _, payload = self.run_entry("route", prompt)
                self.assertIn(expected, payload["next_action"])
                self.assertEqual(payload["data"]["fetch_supported"], supported)


if __name__ == "__main__":
    unittest.main()
