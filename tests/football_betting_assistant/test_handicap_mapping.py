#!/usr/bin/env python3
"""Regression tests for handicap match-result mapping."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "football-betting-assistant"
SCRIPTS = SKILL / "scripts"
PREFLIGHT = SCRIPTS / "preflight_risk_audit.py"
RENDERER = SCRIPTS / "render_html_report.py"
sys.path.insert(0, str(SCRIPTS))

from handicap_rules import handicap_result, handicap_text_conflicts  # noqa: E402


def minimal_document(selection: str, reason: str = "") -> dict:
    return {
        "match_analyses": [
            {
                "match": "西班牙 vs 比利时",
                "handicap_line": "-1",
                "handicap_pick": "西班牙 -1：市场更偏让负，但一球胜对应让平",
                "score_candidates": "1:0 / 1:1 / 2:1",
                "risk_flags": ["one_goal_margin_risk"],
            }
        ],
        "ticket_plans": [
            {
                "name": "让球方向单",
                "type": "result_handicap",
                "legs": [
                    {
                        "match": "西班牙 vs 比利时",
                        "market": "让球胜平负",
                        "line": "-1",
                        "selection": selection,
                        "reason": reason,
                    }
                ],
            }
        ],
    }


class HandicapMappingTests(unittest.TestCase):
    def test_minus_one_mapping(self) -> None:
        self.assertEqual(handicap_result(1, 0, -1), "让平")
        self.assertEqual(handicap_result(1, 1, -1), "让负")
        self.assertEqual(handicap_result(2, 1, -1), "让平")
        self.assertEqual(handicap_result(2, 0, -1), "让胜")

    def test_plus_one_mapping(self) -> None:
        self.assertEqual(handicap_result(0, 0, 1), "让胜")
        self.assertEqual(handicap_result(0, 1, 1), "让平")
        self.assertEqual(handicap_result(0, 2, 1), "让负")

    def test_text_conflict_catches_minus_one_let_loss_claim(self) -> None:
        conflicts = handicap_text_conflicts("西班牙 -1 让负，1:0/1:1/2:1 都支持让负或不穿路径", -1)
        self.assertTrue(any("1:0 maps to 让平" in item for item in conflicts))
        self.assertTrue(any("2:1 maps to 让平" in item for item in conflicts))

    def test_preflight_blocks_unprotected_minus_one_let_loss(self) -> None:
        document = minimal_document("让负", "1:0/1:1/2:1 都支持让负或不穿路径")
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False)
            handle.flush()
            result = subprocess.run(
                ["python3", str(PREFLIGHT), handle.name],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        codes = {item["code"] for item in payload["issues"]}
        self.assertIn("handicap_protection_omitted", codes)
        self.assertIn("handicap_text_mapping_conflict", codes)
        self.assertGreater(payload["summary"]["blocks"], 0)

    def test_preflight_allows_protected_minus_one_paths(self) -> None:
        document = minimal_document("让负 / 让平", "1:0/2:1 对应让平，1:1 对应让负")
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False)
            handle.flush()
            result = subprocess.run(
                ["python3", str(PREFLIGHT), handle.name],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["blocks"], 0, payload)

    def test_renderer_rejects_unprotected_handicap_ticket(self) -> None:
        document = {
            "report": {
                "title": "test",
                "date": "2026-07-09",
                "topic": "西班牙 vs 比利时",
                "data_status": "usable-but-downgraded",
            },
            "fixtures": [{"kickoff_time": "未确认", "match": "西班牙 vs 比利时"}],
            "match_analyses": [
                {
                    "match": "西班牙 vs 比利时",
                    "kickoff_time": "未确认",
                    "competition": "世界杯",
                    "data_confidence": "中",
                    "result_pick": "西班牙胜倾向",
                    "result_protection": "防平",
                    "handicap_line": "-1",
                    "handicap_pick": "西班牙 -1：让负低赔，但一球胜是让平",
                    "totals_pick": "2/3",
                    "score_candidates": "1:0 / 1:1 / 2:1",
                    "bayesian_adjustments": ["降级"],
                    "poisson_summary": "1:0/1:1/2:1 接近",
                    "risk_notes": ["一球胜路径"],
                }
            ],
            "ticket_plans": [
                {
                    "name": "让球方向单",
                    "type": "result_handicap",
                    "legs": [
                        {
                            "match": "西班牙 vs 比利时",
                            "market": "让球胜平负",
                            "line": "-1",
                            "selection": "让负",
                            "reason": "1:0/1:1/2:1 支持让负或不穿",
                        }
                    ],
                    "unit_math": "1 注",
                    "amount_text": "1 注 x 2 元/注 = 2 元",
                    "odds_status": "测试",
                    "risk_level": "中",
                    "reason": "测试",
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False)
            handle.flush()
            result = subprocess.run(
                ["python3", str(RENDERER), handle.name, "--out-dir", tempfile.gettempdir()],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("handicap", result.stderr)


if __name__ == "__main__":
    unittest.main()
