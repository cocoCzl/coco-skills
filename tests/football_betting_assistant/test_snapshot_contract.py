#!/usr/bin/env python3
"""Contract tests for football snapshot data."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "football-betting-assistant"
EXAMPLES = ROOT / "examples" / "football_betting_assistant"
FIXTURES = ROOT / "tests" / "fixtures" / "football_betting_assistant"
VALIDATOR = SKILL / "scripts" / "validate_inputs.py"
FETCHER = SKILL / "scripts" / "fetch_match_data.py"
SELECTOR = SKILL / "scripts" / "select_snapshot_matches.py"
INSPECTOR = SKILL / "scripts" / "inspect_snapshot_markets.py"
REPORT_BUILDER = SKILL / "scripts" / "build_snapshot_report.py"
TEAM_RULES = SKILL / "scripts" / "team_context_rules.py"
RECENT_FORM = SKILL / "scripts" / "recent_form_to_xg.py"
MARKET_GRADER = SKILL / "scripts" / "market_grade_calculator.py"
SCORE_COVERAGE = SKILL / "scripts" / "score_coverage_analyzer.py"
PORTFOLIO_BUILDER = SKILL / "scripts" / "portfolio_builder.py"
LATE_RULES = SKILL / "scripts" / "late_update_rules.py"
POST_MATCH_REVIEW = SKILL / "scripts" / "post_match_review.py"
AUTO_POST_MATCH_REVIEW = SKILL / "scripts" / "auto_post_match_review.py"
ZERO_OPERATION_SMOKE = SKILL / "scripts" / "zero_operation_smoke.py"
COMPETITION_CONTEXT = SKILL / "scripts" / "competition_context_calculator.py"


class SnapshotContractTests(unittest.TestCase):
    def validate(self, path: Path) -> dict:
        result = subprocess.run(
            ["python3", str(VALIDATOR), str(path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_example_snapshot_is_valid(self) -> None:
        result = self.validate(FIXTURES / "football-snapshot-sporttery.json")
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])

    def test_source_failure_snapshot_is_valid(self) -> None:
        result = self.validate(FIXTURES / "football-snapshot-source-failure.json")
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])

    def test_repository_level_development_examples_are_valid(self) -> None:
        for name in ("single-match-input.json", "portfolio-input.json", "backtest-sample.json"):
            with self.subTest(name=name):
                result = self.validate(EXAMPLES / name)
                self.assertTrue(result["valid"])
                self.assertEqual(result["errors"], [])

    def test_not_offered_and_parse_failed_remain_distinct(self) -> None:
        document = json.loads((FIXTURES / "football-snapshot-sporttery.json").read_text(encoding="utf-8"))
        markets = document["data"]["matches"][1]["markets"]
        ordinary = next(item for item in markets if item["market"] == "match_result")
        score = next(item for item in markets if item["market"] == "correct_score")
        self.assertEqual(ordinary["availability"]["status"], "unavailable")
        self.assertEqual(ordinary["availability"]["reason"], "not_offered")
        self.assertEqual(score["availability"]["status"], "parse_failed")
        self.assertEqual(score["availability"]["reason"], "parser_error")

    def test_fetcher_generates_valid_snapshot_from_raw_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    "python3",
                    str(FETCHER),
                    "--mode",
                    "china-lottery",
                    "--provider",
                    "sporttery",
                    "--football",
                    "--raw-input",
                    str(FIXTURES / "raw" / "sporttery-football-sample.json"),
                    "--out",
                    tmp,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            snapshot_path = Path(payload["snapshot_path"])
            self.assertTrue(snapshot_path.exists())
            self.assertTrue(Path(payload["raw_file"]).exists())
            validated = self.validate(snapshot_path)
            self.assertTrue(validated["valid"])
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["data"]["matches"][0]["match_no"], "周四001")
            self.assertEqual(snapshot["data"]["matches"][0]["markets"][0]["market"], "match_result")

    def test_fetcher_parses_sporttery_match_list_api_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    "python3",
                    str(FETCHER),
                    "--mode",
                    "china-lottery",
                    "--provider",
                    "sporttery",
                    "--football",
                    "--raw-input",
                    str(FIXTURES / "raw" / "sporttery-match-list-api-sample.json"),
                    "--out",
                    tmp,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            snapshot_path = Path(payload["snapshot_path"])
            validated = self.validate(snapshot_path)
            self.assertTrue(validated["valid"])
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            match = snapshot["data"]["matches"][0]
            self.assertEqual(match["match_no"], "周四055")
            self.assertEqual(match["competition"], "世界杯")
            self.assertEqual(match["team_type"], "national")
            markets = {item["market"]: item for item in match["markets"]}
            self.assertEqual(markets["match_result"]["selections"][0]["name"], "胜")
            self.assertEqual(markets["match_result"]["selections"][0]["odds"], 5.2)
            self.assertEqual(markets["handicap_match_result"]["line"], "+1.00")
            self.assertEqual(markets["handicap_match_result"]["selections"][0]["name"], "让胜")
            self.assertEqual(markets["correct_score"]["availability"]["status"], "unknown")
            self.assertEqual(markets["correct_score"]["availability"]["reason"], "source_missing")
            self.assertEqual(match["team_context"]["parameter_pool"], "national")
            self.assertEqual(match["team_context"]["confidence_cap"], "B")

    def test_selector_matches_by_match_no_and_team(self) -> None:
        snapshot = FIXTURES / "football-snapshot-sporttery.json"
        by_no = subprocess.run(
            ["python3", str(SELECTOR), str(snapshot), "--match-no", "周四002"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(by_no.returncode, 0, by_no.stdout + by_no.stderr)
        by_no_payload = json.loads(by_no.stdout)
        self.assertEqual(by_no_payload["selected_count"], 1)
        self.assertEqual(by_no_payload["matches"][0]["home_team"], "葡萄牙")

        by_team = subprocess.run(
            ["python3", str(SELECTOR), str(snapshot), "--team", "西班牙"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(by_team.returncode, 0, by_team.stdout + by_team.stderr)
        by_team_payload = json.loads(by_team.stdout)
        self.assertEqual(by_team_payload["selected_count"], 1)
        self.assertEqual(by_team_payload["matches"][0]["match_no"], "周四001")

    def test_market_inspector_blocks_unavailable_markets(self) -> None:
        snapshot = FIXTURES / "football-snapshot-sporttery.json"
        result = subprocess.run(
            ["python3", str(INSPECTOR), str(snapshot), "--match-no", "周四002"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        match = payload["matches"][0]
        buyable = {item["market"] for item in match["buyable_markets"]}
        blocked = {item["market"]: item for item in match["blocked_markets"]}
        self.assertIn("handicap_match_result", buyable)
        self.assertEqual(blocked["match_result"]["reason"], "not_offered")
        self.assertEqual(blocked["correct_score"]["reason"], "parser_error")
        self.assertTrue(match["can_build_purchase_plan"])

    def test_snapshot_report_builder_generates_html_and_prediction_snapshot(self) -> None:
        snapshot = FIXTURES / "football-snapshot-sporttery.json"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = subprocess.run(
                [
                    "python3",
                    str(REPORT_BUILDER),
                    str(snapshot),
                    "--match-no",
                    "周四001",
                    "--topic",
                    "test snapshot report",
                    "--report-out-dir",
                    str(tmp_path / "reports"),
                    "--data-out-dir",
                    str(tmp_path / "data"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            html_path = Path(payload["html_report_path"])
            report_input_path = Path(payload["report_input_path"])
            prediction_path = Path(payload["prediction_snapshot_path"])
            self.assertTrue(html_path.exists())
            self.assertTrue(report_input_path.exists())
            self.assertTrue(prediction_path.exists())
            self.assertEqual(payload["report_id"], json.loads(prediction_path.read_text(encoding="utf-8"))["data"]["report_id"])
            validated = self.validate(prediction_path)
            self.assertTrue(validated["valid"])

    def test_competition_context_calculator_outputs_standings_and_motivation(self) -> None:
        result = subprocess.run(
            ["python3", str(COMPETITION_CONTEXT), str(FIXTURES / "competition-context-input.json")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        context = payload["data"]
        validated_path = None
        with tempfile.TemporaryDirectory() as tmp:
            validated_path = Path(tmp) / "competition-context.json"
            validated_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            validated = self.validate(validated_path)
        self.assertTrue(validated["valid"])
        standings = context["groups"][0]["standings"]
        self.assertEqual(standings[0]["team"], "韩国")
        self.assertEqual(standings[0]["points"], 4)
        self.assertEqual(standings[0]["goal_difference"], 2)
        self.assertIn("already_in_advance_zone", standings[0]["motivation_flags"])
        south_africa = next(item for item in standings if item["team"] == "南非")
        self.assertIn("must_win_pressure", south_africa["motivation_flags"])

    def test_snapshot_report_builder_uses_competition_context(self) -> None:
        raw = {
            "matches": [
                {
                    "id": "group-ctx-001",
                    "matchNo": "周四888",
                    "competition": "世界杯",
                    "kickoffTime": "2026-06-26T22:00:00+08:00",
                    "homeTeam": "韩国",
                    "awayTeam": "南非",
                    "markets": [
                        {
                            "source_market_name": "胜平负",
                            "availability": {"status": "available", "reason": "available"},
                            "selections": [
                                {"name": "胜", "odds": 2.10},
                                {"name": "平", "odds": 3.00},
                                {"name": "负", "odds": 3.20},
                            ],
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw_path = tmp_path / "raw.json"
            raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            fetch_result = subprocess.run(
                [
                    "python3",
                    str(FETCHER),
                    "--mode",
                    "china-lottery",
                    "--provider",
                    "sporttery",
                    "--football",
                    "--raw-input",
                    str(raw_path),
                    "--out",
                    str(tmp_path / "snapshots"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(fetch_result.returncode, 0, fetch_result.stdout + fetch_result.stderr)
            snapshot_path = Path(json.loads(fetch_result.stdout)["snapshot_path"])
            context_result = subprocess.run(
                ["python3", str(COMPETITION_CONTEXT), str(FIXTURES / "competition-context-input.json")],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(context_result.returncode, 0, context_result.stdout + context_result.stderr)
            context_path = tmp_path / "competition-context.json"
            context_path.write_text(context_result.stdout, encoding="utf-8")
            report_result = subprocess.run(
                [
                    "python3",
                    str(REPORT_BUILDER),
                    str(snapshot_path),
                    "--match-no",
                    "周四888",
                    "--topic",
                    "group context report",
                    "--competition-context",
                    str(context_path),
                    "--report-out-dir",
                    str(tmp_path / "reports"),
                    "--data-out-dir",
                    str(tmp_path / "data"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(report_result.returncode, 0, report_result.stdout + report_result.stderr)
            payload = json.loads(report_result.stdout)
            report_input = json.loads(Path(payload["report_input_path"]).read_text(encoding="utf-8"))
            fixture = report_input["fixtures"][0]
            self.assertEqual(fixture["group"], "A组")
            self.assertIn("韩国 第1", fixture["records"])
            self.assertIn("南非", fixture["records"])
            adjustments = report_input["match_analyses"][0]["bayesian_adjustments"]
            self.assertTrue(any("轮换" in item or "出线压力" in item for item in adjustments))

    def test_group_final_round_missing_context_excludes_main_plan(self) -> None:
        raw = {
            "matches": [
                {
                    "id": "missing-group-ctx-001",
                    "matchNo": "周四777",
                    "competition": "世界杯小组赛第3轮",
                    "kickoffTime": "2026-06-26T22:00:00+08:00",
                    "homeTeam": "韩国",
                    "awayTeam": "南非",
                    "markets": [
                        {
                            "source_market_name": "胜平负",
                            "availability": {"status": "available", "reason": "available"},
                            "selections": [
                                {"name": "胜", "odds": 2.10},
                                {"name": "平", "odds": 3.00},
                                {"name": "负", "odds": 3.20},
                            ],
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw_path = tmp_path / "raw.json"
            raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            fetch_result = subprocess.run(
                [
                    "python3",
                    str(FETCHER),
                    "--mode",
                    "china-lottery",
                    "--provider",
                    "sporttery",
                    "--football",
                    "--raw-input",
                    str(raw_path),
                    "--out",
                    str(tmp_path / "snapshots"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(fetch_result.returncode, 0, fetch_result.stdout + fetch_result.stderr)
            snapshot_path = Path(json.loads(fetch_result.stdout)["snapshot_path"])
            report_result = subprocess.run(
                [
                    "python3",
                    str(REPORT_BUILDER),
                    str(snapshot_path),
                    "--match-no",
                    "周四777",
                    "--topic",
                    "世界杯小组赛第3轮",
                    "--report-out-dir",
                    str(tmp_path / "reports"),
                    "--data-out-dir",
                    str(tmp_path / "data"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(report_result.returncode, 0, report_result.stdout + report_result.stderr)
            payload = json.loads(report_result.stdout)
            report_input = json.loads(Path(payload["report_input_path"]).read_text(encoding="utf-8"))
            self.assertEqual(report_input["ticket_plans"], [])
            self.assertTrue(any("group_context_missing" in item for item in report_input["data_gaps"]))
            self.assertTrue(any("稳健主单" in item for item in report_input["match_analyses"][0]["risk_notes"]))

    def test_group_final_round_fourfold_adds_stable_threefold(self) -> None:
        teams = [("韩国", "南非"), ("德国", "厄瓜多尔"), ("韩国", "厄瓜多尔"), ("德国", "南非")]
        raw = {
            "matches": [
                {
                    "id": f"group-ctx-fourfold-{index}",
                    "matchNo": f"周四88{index}",
                    "competition": "世界杯小组赛第3轮",
                    "kickoffTime": "2026-06-26T22:00:00+08:00",
                    "homeTeam": home,
                    "awayTeam": away,
                    "markets": [
                        {
                            "source_market_name": "胜平负",
                            "availability": {"status": "available", "reason": "available"},
                            "selections": [
                                {"name": "胜", "odds": 2.10},
                                {"name": "平", "odds": 3.00},
                                {"name": "负", "odds": 3.20},
                            ],
                        }
                    ],
                }
                for index, (home, away) in enumerate(teams, start=1)
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw_path = tmp_path / "raw.json"
            raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            fetch_result = subprocess.run(
                [
                    "python3",
                    str(FETCHER),
                    "--mode",
                    "china-lottery",
                    "--provider",
                    "sporttery",
                    "--football",
                    "--raw-input",
                    str(raw_path),
                    "--out",
                    str(tmp_path / "snapshots"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(fetch_result.returncode, 0, fetch_result.stdout + fetch_result.stderr)
            snapshot_path = Path(json.loads(fetch_result.stdout)["snapshot_path"])
            context_result = subprocess.run(
                ["python3", str(COMPETITION_CONTEXT), str(FIXTURES / "competition-context-input.json")],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(context_result.returncode, 0, context_result.stdout + context_result.stderr)
            context_path = tmp_path / "competition-context.json"
            context_path.write_text(context_result.stdout, encoding="utf-8")
            report_result = subprocess.run(
                [
                    "python3",
                    str(REPORT_BUILDER),
                    str(snapshot_path),
                    "--competition",
                    "世界杯小组赛第3轮",
                    "--topic",
                    "世界杯小组赛第3轮",
                    "--competition-context",
                    str(context_path),
                    "--report-out-dir",
                    str(tmp_path / "reports"),
                    "--data-out-dir",
                    str(tmp_path / "data"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(report_result.returncode, 0, report_result.stdout + report_result.stderr)
            payload = json.loads(report_result.stdout)
            report_input = json.loads(Path(payload["report_input_path"]).read_text(encoding="utf-8"))
            plan_names = [plan["name"] for plan in report_input["ticket_plans"]]
            self.assertIn("更稳三串一", plan_names)
            stable_plan = next(plan for plan in report_input["ticket_plans"] if plan["name"] == "更稳三串一")
            self.assertEqual(len(stable_plan["legs"]), 3)
            self.assertEqual(stable_plan["type"], "stable_small_combo")

    def test_snapshot_report_builder_excludes_unavailable_market_from_ticket_plan(self) -> None:
        snapshot = FIXTURES / "football-snapshot-sporttery.json"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = subprocess.run(
                [
                    "python3",
                    str(REPORT_BUILDER),
                    str(snapshot),
                    "--match-no",
                    "周四002",
                    "--topic",
                    "test unavailable market",
                    "--report-out-dir",
                    str(tmp_path / "reports"),
                    "--data-out-dir",
                    str(tmp_path / "data"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            report_input = json.loads(Path(payload["report_input_path"]).read_text(encoding="utf-8"))
            ticket_legs = report_input["ticket_plans"][0]["legs"]
            self.assertEqual(ticket_legs[0]["market"], "让球胜平负")
            self.assertEqual(ticket_legs[0]["source_snapshot_market"], "handicap_match_result")
            self.assertTrue(ticket_legs[0]["market_available"])
            self.assertNotEqual(ticket_legs[0]["source_snapshot_market"], "match_result")
            self.assertTrue(any("胜平负 unavailable / not_offered" in item for item in report_input["data_gaps"]))

    def test_snapshot_report_builder_returns_exit_2_for_no_matching_fixture(self) -> None:
        snapshot = FIXTURES / "football-snapshot-sporttery.json"
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    "python3",
                    str(REPORT_BUILDER),
                    str(snapshot),
                    "--match-no",
                    "周四999",
                    "--report-out-dir",
                    str(Path(tmp) / "reports"),
                    "--data-out-dir",
                    str(Path(tmp) / "data"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["error"], "no matching fixtures in snapshot")

    def test_team_context_rules_classify_supported_and_unsupported_types(self) -> None:
        cases = [
            (["--competition", "英超"], "club", "club", True),
            (["--competition", "世界杯"], "national", "national", True),
            (["--competition", "未知杯赛"], "unknown", "same-type-default-required", True),
            (["--competition", "女足世界杯"], "unsupported", "unsupported", False),
            (["--competition", "U23亚洲杯"], "unsupported", "unsupported", False),
        ]
        for args, team_type, parameter_pool, allowed in cases:
            with self.subTest(args=args):
                result = subprocess.run(
                    ["python3", str(TEAM_RULES), *args],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["team_type"], team_type)
                self.assertEqual(payload["parameter_pool"], parameter_pool)
                self.assertEqual(payload["formal_purchase_allowed"], allowed)

    def test_unsupported_team_type_does_not_generate_ticket_plan(self) -> None:
        raw = {
            "matches": [
                {
                    "id": "u23-001",
                    "matchNo": "周五001",
                    "competition": "U23亚洲杯",
                    "kickoffTime": "2026-06-27T20:00:00+08:00",
                    "homeTeam": "中国U23",
                    "awayTeam": "日本U23",
                    "markets": [
                        {
                            "source_market_name": "胜平负",
                            "availability": {"status": "available", "reason": "available"},
                            "selections": [
                                {"name": "胜", "odds": 2.20},
                                {"name": "平", "odds": 3.10},
                                {"name": "负", "odds": 2.90},
                            ],
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw_path = tmp_path / "unsupported-raw.json"
            raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            fetch_result = subprocess.run(
                [
                    "python3",
                    str(FETCHER),
                    "--mode",
                    "china-lottery",
                    "--provider",
                    "sporttery",
                    "--football",
                    "--raw-input",
                    str(raw_path),
                    "--out",
                    str(tmp_path / "snapshots"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(fetch_result.returncode, 0, fetch_result.stdout + fetch_result.stderr)
            snapshot_path = Path(json.loads(fetch_result.stdout)["snapshot_path"])
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            match = snapshot["data"]["matches"][0]
            self.assertEqual(match["team_type"], "unsupported")
            self.assertEqual(match["team_context"]["reason"], "youth_team")
            report_result = subprocess.run(
                [
                    "python3",
                    str(REPORT_BUILDER),
                    str(snapshot_path),
                    "--match-no",
                    "周五001",
                    "--topic",
                    "unsupported team type",
                    "--report-out-dir",
                    str(tmp_path / "reports"),
                    "--data-out-dir",
                    str(tmp_path / "data"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(report_result.returncode, 0, report_result.stdout + report_result.stderr)
            payload = json.loads(report_result.stdout)
            report_input = json.loads(Path(payload["report_input_path"]).read_text(encoding="utf-8"))
            self.assertEqual(report_input["ticket_plans"], [])
            self.assertTrue(any("队伍类型 unsupported" in item for item in report_input["data_gaps"]))

    def test_recent_form_converter_uses_xg_when_available(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(RECENT_FORM),
                "--team-type",
                "club",
                "--matches",
                "10",
                "--xg-for",
                "17.5",
                "--xg-against",
                "9.0",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["source_precision"], "xg")
        self.assertEqual(payload["xg_for"], 1.75)
        self.assertEqual(payload["xg_against"], 0.9)
        self.assertEqual(payload["confidence_cap"], "B")

    def test_recent_form_converter_goals_proxy_downgrades_precision(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(RECENT_FORM),
                "--team-type",
                "national",
                "--matches",
                "8",
                "--goals-for",
                "14",
                "--goals-against",
                "6",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["source_precision"], "goals_proxy")
        self.assertEqual(payload["xg_for"], 1.75)
        self.assertEqual(payload["xg_against"], 0.75)
        self.assertEqual(payload["confidence_cap"], "C")

    def test_recent_form_converter_caps_small_samples_and_rejects_missing_inputs(self) -> None:
        small_sample = subprocess.run(
            [
                "python3",
                str(RECENT_FORM),
                "--team-type",
                "club",
                "--matches",
                "3",
                "--xg-for",
                "5.1",
                "--xg-against",
                "3.3",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(small_sample.returncode, 0, small_sample.stdout + small_sample.stderr)
        self.assertEqual(json.loads(small_sample.stdout)["confidence_cap"], "C")

        missing_inputs = subprocess.run(
            ["python3", str(RECENT_FORM), "--team-type", "club", "--matches", "10"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(missing_inputs.returncode, 0)
        self.assertIn("provide either xg_for/xg_against or goals_for/goals_against", missing_inputs.stderr)

    def test_market_grade_calculator_outputs_market_level_edges(self) -> None:
        document = {
            "markets": [
                {
                    "market": "match_result",
                    "source_market_name": "胜平负",
                    "availability": {"status": "available", "reason": "available"},
                    "selections": [
                        {"name": "胜", "odds": 2.10},
                        {"name": "平", "odds": 3.20},
                        {"name": "负", "odds": 3.60},
                    ],
                },
                {
                    "market": "total_goals",
                    "source_market_name": "总进球",
                    "availability": {"status": "unknown", "reason": "source_missing"},
                    "selections": [],
                },
            ],
            "model_probabilities": {
                "match_result": {"胜": 0.52, "平": 0.27, "负": 0.21},
                "total_goals": {"2球": 0.25},
            },
            "grading": {
                "model_confidence": "medium",
                "data_confidence": "medium",
                "odds_confidence": "medium",
                "market_strength_delta": 0.08,
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market-grade-input.json"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                ["python3", str(MARKET_GRADER), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        result_market = payload["markets"][0]
        missing_market = payload["markets"][1]
        self.assertEqual(result_market["status"], "complete")
        self.assertGreater(result_market["market_margin"], 0)
        win = result_market["selections"][0]
        self.assertEqual(win["market_strength_delta"], 0.03)
        self.assertIsNotNone(win["no_vig_probability"])
        self.assertIsNotNone(win["edge"])
        self.assertIsNotNone(win["grade"])
        self.assertEqual(missing_market["status"], "incomplete")
        self.assertFalse(missing_market["value_judgment_available"])

    def test_market_grade_calculator_passes_unresolved_market_conflict(self) -> None:
        document = {
            "markets": [
                {
                    "market": "over_under",
                    "source_market_name": "大小球",
                    "availability": {"status": "available", "reason": "available"},
                    "selections": [
                        {"name": "大", "odds": 1.90},
                        {"name": "小", "odds": 1.90},
                    ],
                }
            ],
            "model_probabilities": {"over_under": {"大": 0.58, "小": 0.42}},
            "grading": {"market_inconsistency": "unresolved"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market-conflict.json"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                ["python3", str(MARKET_GRADER), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["markets"][0]["selections"][0]["grade"]["reference_grade"], "Pass")

    def run_score_coverage(self, document: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "score-coverage.json"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                ["python3", str(SCORE_COVERAGE), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)["score_coverage"]

    def test_score_coverage_analyzer_marks_concentrated_matrix_strong(self) -> None:
        coverage = self.run_score_coverage(
            {
                "scores": [
                    {"score": "1:0", "probability": 0.16},
                    {"score": "2:0", "probability": 0.12},
                    {"score": "1:1", "probability": 0.10},
                    {"score": "2:1", "probability": 0.08},
                    {"score": "0:0", "probability": 0.07},
                ]
            }
        )
        self.assertEqual(coverage["single_score_strength"], "strong")
        self.assertEqual(coverage["coverage_quality"], "strong")
        self.assertTrue(coverage["core_portfolio_allowed"])
        self.assertEqual(coverage["primary_path"], "1:0")

    def test_score_coverage_analyzer_marks_moderate_matrix_not_core(self) -> None:
        coverage = self.run_score_coverage(
            {
                "scores": [
                    {"score": "1:1", "probability": 0.11},
                    {"score": "1:0", "probability": 0.08},
                    {"score": "2:1", "probability": 0.07},
                    {"score": "0:0", "probability": 0.04},
                    {"score": "2:0", "probability": 0.02},
                ]
            }
        )
        self.assertEqual(coverage["single_score_strength"], "moderate")
        self.assertEqual(coverage["coverage_quality"], "moderate")
        self.assertFalse(coverage["core_portfolio_allowed"])
        self.assertTrue(coverage["exact_score_ticket_allowed"])

    def test_score_coverage_analyzer_blocks_diffuse_score_ticket(self) -> None:
        coverage = self.run_score_coverage(
            {
                "scores": [
                    {"score": "1:1", "probability": 0.09},
                    {"score": "1:0", "probability": 0.08},
                    {"score": "2:1", "probability": 0.07},
                    {"score": "2:2", "probability": 0.04},
                    {"score": "0:1", "probability": 0.03},
                ]
            }
        )
        self.assertEqual(coverage["single_score_strength"], "weak")
        self.assertEqual(coverage["coverage_quality"], "weak")
        self.assertFalse(coverage["exact_score_ticket_allowed"])

    def test_score_coverage_analyzer_downgrades_high_total_xg_and_btts_path(self) -> None:
        coverage = self.run_score_coverage(
            {
                "total_xg": 3.4,
                "both_teams_score_path": True,
                "scores": [
                    {"score": "2:1", "probability": 0.15},
                    {"score": "2:2", "probability": 0.12},
                    {"score": "3:1", "probability": 0.11},
                    {"score": "3:2", "probability": 0.08},
                    {"score": "1:1", "probability": 0.07},
                ],
            }
        )
        self.assertEqual(coverage["single_score_strength"], "moderate")
        self.assertEqual(coverage["coverage_quality"], "moderate")
        self.assertTrue(any("High total xG" in item for item in coverage["warnings"]))
        self.assertTrue(any("Both teams" in item for item in coverage["warnings"]))

    def test_portfolio_builder_excludes_weak_and_unavailable_legs(self) -> None:
        document = {
            "risk_preference": "conservative",
            "legs": [
                {"match": "A vs B", "market": "handicap_match_result", "selection": "让胜", "grade": "B", "market_available": True, "data_confidence": "medium", "edge": 0.03},
                {"match": "C vs D", "market": "handicap_match_result", "selection": "让平", "grade": "C", "market_available": True, "data_confidence": "medium", "edge": 0.01},
                {"match": "E vs F", "market": "match_result", "selection": "胜", "grade": "A", "market_available": False, "data_confidence": "high", "edge": 0.06},
                {"match": "G vs H", "market": "total_goals", "selection": "2球", "grade": "Pass", "market_available": True, "data_confidence": "medium"},
                {"match": "I vs J", "market": "correct_score", "selection": "1:0", "grade": "B", "market_available": True, "data_confidence": "medium", "score_coverage_quality": "weak"},
                {"match": "K vs L", "market": "correct_score", "selection": "2:0 / 2:1", "selection_count": 2, "grade": "B", "market_available": True, "data_confidence": "medium", "score_coverage_quality": "strong"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                ["python3", str(PORTFOLIO_BUILDER), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        selected_matches = {leg["match"] for plan in payload["ticket_plans"] for leg in plan["legs"]}
        excluded_matches = {leg["match"]: leg["reason"] for leg in payload["excluded_legs"]}
        self.assertIn("A vs B", selected_matches)
        self.assertIn("K vs L", selected_matches)
        self.assertEqual(excluded_matches["C vs D"], "C grade excluded from conservative main plans")
        self.assertEqual(excluded_matches["E vs F"], "market unavailable")
        self.assertEqual(excluded_matches["G vs H"], "Pass grade")
        self.assertEqual(excluded_matches["I vs J"], "weak score coverage")

    def test_portfolio_builder_does_not_force_maximum_leg_count(self) -> None:
        document = {
            "risk_preference": "conservative",
            "legs": [
                {"match": "A vs B", "market": "match_result", "selection": "胜", "grade": "B", "market_available": True, "data_confidence": "medium"},
                {"match": "C vs D", "market": "match_result", "selection": "平", "grade": "B", "market_available": True, "data_confidence": "medium"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio-short.json"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                ["python3", str(PORTFOLIO_BUILDER), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(len(payload["ticket_plans"]), 1)
        self.assertEqual(len(payload["ticket_plans"][0]["legs"]), 2)
        self.assertEqual(payload["ticket_plans"][0]["unit_math"], "1 注")

    def test_portfolio_builder_expands_handicap_leg_for_one_goal_risk(self) -> None:
        document = {
            "risk_preference": "conservative",
            "legs": [
                {
                    "match": "科特迪瓦 vs 挪威",
                    "market": "handicap_match_result",
                    "source_line": "+1",
                    "selection": "让胜",
                    "grade": "B",
                    "market_available": True,
                    "data_confidence": "medium",
                    "risk_flags": ["one_goal_margin_risk", "score_distribution_diffuse"],
                    "score_candidates": ["1:1", "0:1", "1:2"],
                },
                {
                    "match": "法国 vs 瑞典",
                    "market": "match_result",
                    "selection": "胜",
                    "grade": "B",
                    "market_available": True,
                    "data_confidence": "medium",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio-protection.json"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                ["python3", str(PORTFOLIO_BUILDER), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        handicap_plan = next(plan for plan in payload["ticket_plans"] if plan["market_family"] == "handicap_match_result")
        leg = handicap_plan["legs"][0]
        self.assertEqual(leg["selection"], "让胜 / 让平")
        self.assertEqual(leg["selection_count"], 2)
        self.assertEqual(leg["protection_action"], "expanded_with_risk_protection")
        self.assertTrue(any(action["action"] == "expanded_with_risk_protection" for action in handicap_plan["protection_actions"]))

    def test_portfolio_builder_expands_minus_one_no_cover_when_cover_score_is_in_coverage(self) -> None:
        document = {
            "risk_preference": "conservative",
            "legs": [
                {
                    "match": "墨西哥 vs 厄瓜多尔",
                    "market": "handicap_match_result",
                    "source_line": "-1",
                    "selection": "让负",
                    "grade": "B",
                    "market_available": True,
                    "data_confidence": "medium",
                    "risk_flags": ["favorite_cover_risk"],
                    "score_candidates": ["1:0", "1:1", "0:0", "2:0"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio-minus-one.json"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                ["python3", str(PORTFOLIO_BUILDER), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        leg = payload["ticket_plans"][0]["legs"][0]
        self.assertEqual(leg["selection"], "让负 / 让平 / 让胜")
        self.assertEqual(leg["selection_count"], 3)
        self.assertEqual(payload["ticket_plans"][0]["unit_math"], "3 注")

    def test_backtest_reports_portfolio_construction_error_when_coverage_had_the_result(self) -> None:
        document = {
            "kind": "backtest_samples",
            "data": {
                "samples": [
                    {
                        "sample_id": "construction-error-001",
                        "fixture": {
                            "home_team": "科特迪瓦",
                            "away_team": "挪威",
                            "competition": "世界杯",
                            "kickoff_time": "2026-07-01T01:00:00+08:00",
                            "timezone": "Asia/Shanghai",
                            "venue_type": "neutral",
                        },
                        "prediction": {
                            "observed_at": "2026-06-30T12:20:00+08:00",
                            "result_probabilities": {"home_win": 0.257, "draw": 0.254, "away_win": 0.489},
                            "score_candidates": [
                                {"score": "1:1", "probability": 0.121},
                                {"score": "0:1", "probability": 0.115},
                                {"score": "1:2", "probability": 0.094},
                            ],
                            "ticket_plans": [
                                {
                                    "name": "模型最稳主单",
                                    "legs": [
                                        {
                                            "match": "科特迪瓦 vs 挪威",
                                            "market": "让球胜平负",
                                            "source_snapshot_market": "handicap_match_result",
                                            "source_line": "+1",
                                            "selection": "让胜",
                                            "protection_candidates": ["让平"],
                                        }
                                    ],
                                }
                            ],
                            "reference_grade": "B",
                            "model_confidence": "medium",
                            "data_confidence": "medium",
                        },
                        "actual_result": {"home_goals": 1, "away_goals": 2},
                    }
                ]
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backtest-construction-error.json"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                ["python3", str(SKILL / "scripts" / "backtest_predictions.py"), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["ticket_leg_sample_count"], 1)
        self.assertEqual(payload["ticket_leg_hit_rate"], 0.0)
        self.assertEqual(payload["missed_but_in_coverage_count"], 1)
        self.assertEqual(payload["protected_path_available_count"], 1)
        self.assertEqual(payload["portfolio_construction_error_count"], 1)

    def run_late_rules(self, document: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "late.json"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                ["python3", str(LATE_RULES), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_late_update_rules_cap_early_analysis_at_b(self) -> None:
        payload = self.run_late_rules(
            {
                "observed_at": "2026-06-25T08:00:00+08:00",
                "kickoff_time": "2026-06-26T03:00:00+08:00",
                "lineup_status": "expected",
            }
        )
        self.assertEqual(payload["grade_cap"], "B")
        self.assertFalse(payload["stop_new_purchase_plan"])

    def test_late_update_rules_require_updates_and_reevaluation_on_movement(self) -> None:
        payload = self.run_late_rules(
            {
                "observed_at": "2026-06-25T22:00:00+08:00",
                "kickoff_time": "2026-06-26T03:00:00+08:00",
                "lineup_status": "expected",
                "opening_match_result_odds": 2.10,
                "current_match_result_odds": 2.26,
                "handicap_line_moved": True,
            }
        )
        self.assertTrue(payload["reevaluation_required"])
        self.assertTrue(any("Two to six hours" in item for item in payload["warnings"]))
        self.assertTrue(any(">= 0.15" in item for item in payload["warnings"]))

    def test_late_update_rules_block_started_or_unavailable_sales(self) -> None:
        started = self.run_late_rules(
            {
                "observed_at": "2026-06-26T03:05:00+08:00",
                "kickoff_time": "2026-06-26T03:00:00+08:00",
                "lineup_status": "confirmed",
            }
        )
        self.assertEqual(started["grade_cap"], "Pass")
        self.assertTrue(started["stop_new_purchase_plan"])

        unavailable = self.run_late_rules(
            {
                "observed_at": "2026-06-26T02:30:00+08:00",
                "kickoff_time": "2026-06-26T03:00:00+08:00",
                "lineup_status": "unconfirmed",
                "sales_available": False,
            }
        )
        self.assertEqual(unavailable["grade_cap"], "Pass")
        self.assertTrue(unavailable["stop_new_purchase_plan"])

    def test_post_match_review_attaches_final_score_to_prediction_snapshot(self) -> None:
        snapshot = FIXTURES / "football-snapshot-sporttery.json"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_result = subprocess.run(
                [
                    "python3",
                    str(REPORT_BUILDER),
                    str(snapshot),
                    "--match-no",
                    "周四001",
                    "--topic",
                    "review test",
                    "--report-out-dir",
                    str(tmp_path / "reports"),
                    "--data-out-dir",
                    str(tmp_path / "data"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(report_result.returncode, 0, report_result.stdout + report_result.stderr)
            prediction_path = Path(json.loads(report_result.stdout)["prediction_snapshot_path"])
            review_result = subprocess.run(
                [
                    "python3",
                    str(POST_MATCH_REVIEW),
                    str(prediction_path),
                    "--match",
                    "西班牙 vs 沙特",
                    "--home-goals",
                    "2",
                    "--away-goals",
                    "0",
                    "--result-source",
                    "test fixture",
                    "--out-dir",
                    str(tmp_path / "reviews"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(review_result.returncode, 0, review_result.stdout + review_result.stderr)
            payload = json.loads(review_result.stdout)
            review_path = Path(payload["review_path"])
            self.assertTrue(review_path.exists())
            review = json.loads(review_path.read_text(encoding="utf-8"))
            self.assertEqual(review["kind"], "post_match_review")
            self.assertEqual(review["data"]["final_score"]["score"], "2:0")
            self.assertTrue(review["data"]["leg_reviews"])
            self.assertIn("score_review", review["data"])

    def test_post_match_review_handles_structured_scores_and_chinese_handicap_market(self) -> None:
        prediction = {
            "kind": "prediction_snapshot",
            "data": {
                "report_id": "structured-review-test",
                "generated_at": "2026-07-02T12:35:00+08:00",
                "model_outputs": {
                    "match_records": [
                        {
                            "match": "西班牙 vs 奥地利",
                            "score_candidates": {
                                "primary": "2:0",
                                "core": ["2:0", "1:0", "3:0"],
                                "enhanced": ["2:0", "1:0", "3:0", "2:1"],
                                "backup": ["1:1"],
                            },
                            "result_probabilities": {"home_win": 0.74, "draw": 0.17, "away_win": 0.09},
                        }
                    ],
                    "ticket_plans": [
                        {
                            "name": "比分与让球",
                            "legs": [
                                {
                                    "match": "西班牙 vs 奥地利",
                                    "market": "比分",
                                    "source_snapshot_market": "user-screenshot",
                                    "selection": "2:0 / 1:0 / 3:0",
                                },
                                {
                                    "match": "西班牙 vs 奥地利",
                                    "market": "让球胜平负 -1",
                                    "source_snapshot_market": "sporttery",
                                    "selection": "让胜 / 让平",
                                },
                            ],
                        }
                    ],
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            prediction_path = tmp_path / "prediction.json"
            prediction_path.write_text(json.dumps(prediction, ensure_ascii=False), encoding="utf-8")
            review_result = subprocess.run(
                [
                    "python3",
                    str(POST_MATCH_REVIEW),
                    str(prediction_path),
                    "--match",
                    "西班牙 vs 奥地利",
                    "--home-goals",
                    "3",
                    "--away-goals",
                    "0",
                    "--result-source",
                    "test fixture",
                    "--out-dir",
                    str(tmp_path / "reviews"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(review_result.returncode, 0, review_result.stdout + review_result.stderr)
        payload = json.loads(review_result.stdout)
        review = payload["review"]
        self.assertFalse(review["score_review"]["top1_hit"])
        self.assertTrue(review["score_review"]["top3_hit"])
        self.assertTrue(review["score_review"]["coverage_hit"])
        leg_metrics = {item["market"]: item for item in review["leg_reviews"]}
        self.assertTrue(leg_metrics["比分"]["hit"])
        self.assertEqual(leg_metrics["让球胜平负 -1"]["metric"], "handicap_result")
        self.assertTrue(leg_metrics["让球胜平负 -1"]["hit"])

    def test_auto_post_match_review_discovers_predictions_and_renders_html(self) -> None:
        snapshot = FIXTURES / "football-snapshot-sporttery.json"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_result = subprocess.run(
                [
                    "python3",
                    str(REPORT_BUILDER),
                    str(snapshot),
                    "--match-no",
                    "周四001",
                    "--topic",
                    "auto review test",
                    "--report-out-dir",
                    str(tmp_path / "reports"),
                    "--data-out-dir",
                    str(tmp_path / "data"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(report_result.returncode, 0, report_result.stdout + report_result.stderr)
            results_path = tmp_path / "results.json"
            results_path.write_text(
                json.dumps(
                    {
                        "kind": "match_results",
                        "data": {
                            "results": [
                                {
                                    "match": "西班牙 vs 沙特",
                                    "home_team": "西班牙",
                                    "away_team": "沙特",
                                    "competition": "世界杯",
                                    "kickoff_time": "2026-06-26T03:00:00+08:00",
                                    "home_goals": 2,
                                    "away_goals": 0,
                                    "source": "test fixture",
                                    "source_url": "file://results.json",
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            review_result = subprocess.run(
                [
                    "python3",
                    str(AUTO_POST_MATCH_REVIEW),
                    "--predictions-dir",
                    str(tmp_path / "data" / "predictions"),
                    "--results-input",
                    str(results_path),
                    "--review-out-dir",
                    str(tmp_path / "data" / "reviews"),
                    "--report-out-dir",
                    str(tmp_path / "reports"),
                    "--now",
                    "2026-06-27T12:00:00+08:00",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(review_result.returncode, 0, review_result.stdout + review_result.stderr)
            payload = json.loads(review_result.stdout)
            self.assertEqual(payload["reviewed_count"], 1)
            review_path = Path(payload["review_path"])
            html_path = Path(payload["html_report_path"])
            self.assertTrue(review_path.exists())
            self.assertTrue(html_path.exists())
            review = json.loads(review_path.read_text(encoding="utf-8"))
            self.assertEqual(review["kind"], "post_match_review_bundle")
            self.assertEqual(review["data"]["reviews"][0]["final_score"]["score"], "2:0")
            html = html_path.read_text(encoding="utf-8")
            self.assertIn("足球竞彩赛后复盘", html)
            self.assertIn("模型偏差", html)

    def test_zero_operation_smoke_generates_report_and_concise_chat_summary(self) -> None:
        snapshot = FIXTURES / "football-snapshot-sporttery.json"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = subprocess.run(
                [
                    "python3",
                    str(ZERO_OPERATION_SMOKE),
                    str(snapshot),
                    "--request",
                    "帮我看下北京时间明天的几场世界杯比赛",
                    "--report-out-dir",
                    str(tmp_path / "reports"),
                    "--data-out-dir",
                    str(tmp_path / "data"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["selected_matches"], 2)
            self.assertTrue(Path(payload["html_report_path"]).exists())
            self.assertTrue(Path(payload["prediction_snapshot_path"]).exists())
            self.assertLessEqual(len(payload["chat_response_lines"]), 4)


if __name__ == "__main__":
    unittest.main()
