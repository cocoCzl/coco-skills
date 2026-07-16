#!/usr/bin/env python3
"""External-behavior tests for official lottery synchronization and generation."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "lottery-number-recommendation" / "scripts" / "lottery_skill.py"
SPEC = importlib.util.spec_from_file_location("lottery_skill", SCRIPT)
assert SPEC and SPEC.loader
lottery_skill = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lottery_skill
SPEC.loader.exec_module(lottery_skill)


def dlt_payload() -> dict:
    return {
        "success": True,
        "value": {
            "total": 2,
            "list": [
                {"lotteryDrawNum": "07002", "lotteryDrawTime": "2007-06-02", "lotteryDrawResult": "02 04 06 08 10 01 12", "poolBalanceAfterdraw": "1000000.00", "drawPdfUrl": "https://official.example/07002.pdf"},
                {"lotteryDrawNum": "07001", "lotteryDrawTime": "2007-05-30", "lotteryDrawResult": "01 02 03 04 05 06 07"},
            ],
        },
    }


def ssq_official_available_payload() -> dict:
    return {
        "state": 0,
        "total": 2,
        "result": [
            {"code": "2013002", "date": "2013-01-03(四)", "red": "02,04,06,08,10,12", "blue": "09"},
            {"code": "2013001", "date": "2013-01-01(二)", "red": "01,02,03,04,05,06", "blue": "07"},
        ],
    }


class LotterySkillTests(unittest.TestCase):
    def test_dlt_official_snapshot_is_ready_and_archived(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            status = lottery_skill.sync_official_history(data_dir, "dlt", fetch=lambda *_: dlt_payload(), sleep=lambda _: None)
            self.assertTrue(status["ready"])
            archive = lottery_skill.read_json(lottery_skill.archive_path(data_dir, "dlt"))
            self.assertEqual([draw["issue"] for draw in archive["draws"]], ["07001", "07002"])
            self.assertTrue((data_dir / archive["syncs"][-1]["raw_file"]).exists())
            self.assertEqual(archive["public_context"]["pool_balance_after_draw"], "1000000.00")

    def test_ssq_official_available_history_is_ready_and_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            status = lottery_skill.sync_official_history(data_dir, "ssq", fetch=lambda *_: ssq_official_available_payload(), sleep=lambda _: None)
            self.assertTrue(status["ready"])
            self.assertTrue(status["complete"])
            self.assertEqual(status["history_coverage"]["kind"], "official_available_history")
            self.assertEqual(status["history_coverage"]["from_issue"], "2013001")

    def test_ssq_automatically_promotes_to_full_history_when_official_source_expands(self) -> None:
        payload = ssq_official_available_payload()
        payload["result"] = [
            {"code": "2003002", "date": "2003-02-27(四)", "red": "02,04,06,08,10,12", "blue": "09"},
            {"code": "2003001", "date": "2003-02-23(日)", "red": "01,02,03,04,05,06", "blue": "07"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            status = lottery_skill.sync_official_history(Path(tmp), "ssq", fetch=lambda *_: payload, sleep=lambda _: None)
            self.assertTrue(status["ready"])
            self.assertEqual(status["history_coverage"]["kind"], "full_history")
            self.assertEqual(status["history_coverage"]["from_issue"], "2003001")

    def test_random_recommendation_is_valid_and_historically_unseen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            lottery_skill.sync_official_history(data_dir, "dlt", fetch=lambda *_: dlt_payload(), sleep=lambda _: None)
            archive = lottery_skill.load_ready_archive(data_dir, "dlt")
            numbers, _ = lottery_skill.generate("dlt", archive, 2, "random", 100, "medium", 99, set())
            existing = lottery_skill.historical_keys("dlt", archive["draws"])
            self.assertEqual(len({lottery_skill.canonical_key("dlt", value) for value in numbers}), 2)
            for value in numbers:
                self.assertNotIn(lottery_skill.canonical_key("dlt", value), existing)
                self.assertEqual(value["front"], sorted(value["front"]))
                self.assertEqual(value["back"], sorted(value["back"]))

    def test_waf_response_is_refused(self) -> None:
        def blocked(*_args):
            raise lottery_skill.LotteryError("官方数据源触发访问限制；未尝试绕过，暂不能同步")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(lottery_skill.LotteryError, "未尝试绕过"):
                lottery_skill.sync_official_history(Path(tmp), "dlt", fetch=blocked, sleep=lambda _: None)

    def test_hot_and_cold_include_compact_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            lottery_skill.sync_official_history(data_dir, "dlt", fetch=lambda *_: dlt_payload(), sleep=lambda _: None)
            archive = lottery_skill.load_ready_archive(data_dir, "dlt")
            for mode in ("hot", "cold"):
                with self.subTest(mode=mode):
                    values, _ = lottery_skill.generate("dlt", archive, 1, mode, 2, "medium", 22, set())
                    stats = lottery_skill.stats_for_number("dlt", values[0], archive["draws"], mode, 2)
                    self.assertIn("front", stats)
                    self.assertIn("back", stats)

    def test_daily_full_then_incremental_sync_and_version_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            first_day = datetime(2026, 7, 16, tzinfo=timezone.utc)
            lottery_skill.sync_official_history(data_dir, "dlt", fetch=lambda *_: dlt_payload(), sleep=lambda _: None, now=first_day)
            archive = lottery_skill.read_json(lottery_skill.archive_path(data_dir, "dlt"))
            first_version = archive["data_version"]
            self.assertEqual(archive["syncs"][-1]["sync_kind"], "full")
            lottery_skill.sync_official_history(data_dir, "dlt", fetch=lambda *_: dlt_payload(), sleep=lambda _: None, now=first_day)
            archive = lottery_skill.read_json(lottery_skill.archive_path(data_dir, "dlt"))
            self.assertEqual(archive["syncs"][-1]["sync_kind"], "incremental")
            corrected = dlt_payload()
            corrected["value"]["list"][0]["lotteryDrawResult"] = "02 04 06 08 11 01 12"
            lottery_skill.sync_official_history(data_dir, "dlt", fetch=lambda *_: corrected, sleep=lambda _: None, now=datetime(2026, 7, 17, tzinfo=timezone.utc))
            archive = lottery_skill.read_json(lottery_skill.archive_path(data_dir, "dlt"))
            self.assertEqual(archive["syncs"][-1]["sync_kind"], "full")
            self.assertNotEqual(archive["data_version"], first_version)
            self.assertTrue(lottery_skill.history_version_path(data_dir, "dlt", first_version).exists())

    def test_parse_request_supports_aliases_and_rejects_conflicts(self) -> None:
        parsed = lottery_skill.parse_request_text("双色球给我 3 注最近 50 期强热号，避开以前推荐；大乐透 2 注稍微偏冷")
        self.assertEqual(parsed["action"], "recommend")
        self.assertEqual(parsed["requests"][0]["game"], "dlt")
        self.assertEqual(parsed["requests"][1]["count"], 3)
        self.assertEqual(parsed["requests"][1]["mode"], "hot")
        self.assertTrue(parsed["requests"][1]["avoid_history"])
        refusal = lottery_skill.parse_request_text("给我一注大乐透，保证中奖")
        self.assertEqual(refusal["action"], "refuse")
        with self.assertRaisesRegex(lottery_skill.LotteryError, "不能同时使用"):
            lottery_skill.parse_request_text("大乐透热号和冷号各来一注")

    def test_backtest_reports_prize_hits_and_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            lottery_skill.sync_official_history(data_dir, "dlt", fetch=lambda *_: dlt_payload(), sleep=lambda _: None)
            args = SimpleNamespace(data_dir=str(data_dir), game="dlt", window=1, seed=1, from_issue="07002", to_issue="07002")
            original_sync = lottery_skill.sync_official_history
            lottery_skill.sync_official_history = lambda *_args, **_kwargs: lottery_skill.status_for_game(data_dir, "dlt")
            try:
                result = lottery_skill.backtest(args)
            finally:
                lottery_skill.sync_official_history = original_sync
            self.assertEqual(result["periods"], 1)
            self.assertIn("prize_hits", result["results"][0])
            self.assertTrue(result["data_version"])

    def test_recommendation_allows_partial_success_and_audits_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            lottery_skill.sync_official_history(data_dir, "dlt", fetch=lambda *_: dlt_payload(), sleep=lambda _: None)
            original_sync = lottery_skill.sync_official_history

            def sync_for_recommend(_dir, game, **_kwargs):
                if game == "ssq":
                    raise lottery_skill.LotteryError("双色球严格历史未就绪")
                return lottery_skill.status_for_game(data_dir, "dlt")

            lottery_skill.sync_official_history = sync_for_recommend
            try:
                args = SimpleNamespace(data_dir=str(data_dir), game=None, count=1, mode="random", window=100, strength="medium", seed=4, avoid_history=False)
                result = lottery_skill.recommend(args)
            finally:
                lottery_skill.sync_official_history = original_sync
            self.assertEqual(result["games"][0]["game"], "dlt")
            self.assertEqual(result["unavailable_games"][0]["game"], "ssq")
            audit = (data_dir / "audit" / "recommendations.jsonl").read_text(encoding="utf-8")
            self.assertIn("data_version", audit)

    def test_ssq_recommendation_reports_official_available_history_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            lottery_skill.sync_official_history(data_dir, "ssq", fetch=lambda *_: ssq_official_available_payload(), sleep=lambda _: None)
            original_sync = lottery_skill.sync_official_history
            lottery_skill.sync_official_history = lambda *_args, **_kwargs: lottery_skill.status_for_game(data_dir, "ssq")
            try:
                args = SimpleNamespace(data_dir=str(data_dir), game="ssq", count=1, mode="random", window=100, strength="medium", seed=5, avoid_history=False)
                result = lottery_skill.recommend(args)
            finally:
                lottery_skill.sync_official_history = original_sync
            scope = result["games"][0]["data_status"]["history_coverage"]
            self.assertEqual(scope["kind"], "official_available_history")
            self.assertEqual(scope["from_issue"], "2013001")

    def test_parse_status_and_backtest_clarification(self) -> None:
        status = lottery_skill.parse_request_text("检查大乐透和双色球的数据状态")
        self.assertEqual(status["action"], "status")
        clarification = lottery_skill.parse_request_text("回测效果怎么样")
        self.assertEqual(clarification["action"], "clarify")

    def test_common_parameters_apply_to_both_games_and_local_parameters_override(self) -> None:
        common = lottery_skill.parse_request_text("大乐透和双色球各 3 注最近 50 期强热号，避开以前推荐")
        self.assertEqual([(item["count"], item["window"], item["mode"], item["strength"], item["avoid_history"]) for item in common["requests"]], [(3, 50, "hot", "strong", True), (3, 50, "hot", "strong", True)])
        separate = lottery_skill.parse_request_text("双色球给我 3 注最近 50 期强热号；大乐透给我 2 注稍微偏冷")
        self.assertEqual([(item["game"], item["count"], item["mode"], item["window"], item["strength"]) for item in separate["requests"]], [("dlt", 2, "cold", 100, "mild"), ("ssq", 3, "hot", 50, "strong")])

    def test_default_dual_recommendation_returns_both_games(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            lottery_skill.sync_official_history(data_dir, "dlt", fetch=lambda *_: dlt_payload(), sleep=lambda _: None)
            lottery_skill.sync_official_history(data_dir, "ssq", fetch=lambda *_: ssq_official_available_payload(), sleep=lambda _: None)
            original_sync = lottery_skill.sync_official_history
            lottery_skill.sync_official_history = lambda _dir, game, **_kwargs: lottery_skill.status_for_game(data_dir, game)
            try:
                args = SimpleNamespace(data_dir=str(data_dir), game=None, count=1, mode="random", window=100, strength="medium", seed=6, avoid_history=False)
                result = lottery_skill.recommend(args)
            finally:
                lottery_skill.sync_official_history = original_sync
            self.assertEqual([item["game"] for item in result["games"]], ["dlt", "ssq"])
            self.assertFalse(result["unavailable_games"])
            self.assertEqual(result["disclaimer"], "仅供娱乐与参考，不保证中奖。")

    def test_sync_failure_marks_existing_snapshot_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            lottery_skill.sync_official_history(data_dir, "dlt", fetch=lambda *_: dlt_payload(), sleep=lambda _: None)
            args = SimpleNamespace(data_dir=str(data_dir), game="dlt")
            original_sync = lottery_skill.sync_official_history
            lottery_skill.sync_official_history = lambda *_args, **_kwargs: (_ for _ in ()).throw(lottery_skill.LotteryError("官方数据源触发访问限制；未尝试绕过，暂不能同步"))
            try:
                result = lottery_skill.sync(args)
            finally:
                lottery_skill.sync_official_history = original_sync
            self.assertFalse(result["games"][0]["status"]["ready"])
            self.assertIn("访问限制", result["games"][0]["status"]["reason"])
            self.assertIsNotNone(result["games"][0]["status"]["last_sync_failure"])

    def test_incomplete_official_page_is_refused_and_no_third_party_source_exists(self) -> None:
        incomplete = dlt_payload()
        incomplete["value"]["total"] = 3
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(lottery_skill.LotteryError, "拒绝使用不完整快照"):
                lottery_skill.sync_official_history(Path(tmp), "dlt", fetch=lambda *_: incomplete, sleep=lambda _: None)
        domains = {urlparse(source["endpoint"]).netloc for source in lottery_skill.OFFICIAL_SOURCES.values()}
        self.assertEqual(domains, {"webapi.sporttery.cn", "www.cwl.gov.cn"})

    def test_text_renderer_shows_scope_context_and_compact_statistics(self) -> None:
        result = {
            "games": [{
                "label": "双色球", "mode": "hot", "window": 50, "strength": "strong",
                "data_status": {"latest_issue": "2013002", "latest_date": "2013-01-03", "history_coverage": {"kind": "official_available_history", "from_issue": "2013001"}, "public_context": {"pool_balance": "1000000", "draw_notice_path": "/notice"}},
                "recommendations": [{"index": 1, "display": "红球 01 02 03 04 05 06 ｜ 蓝球 07", "stats": {"red": {"01": 3}, "blue": {"07": 1}}}],
            }], "unavailable_games": [], "disclaimer": "仅供娱乐与参考，不保证中奖。",
        }
        text = lottery_skill.render_recommendation(result)
        self.assertIn("官网历史 2013001 至 2013002", text)
        self.assertIn("官方奖池：1000000", text)
        self.assertIn("热度：红球 01(3)；蓝球 07(1)", text)
        self.assertTrue(text.endswith("仅供娱乐与参考，不保证中奖。"))

    def test_public_context_does_not_change_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            lottery_skill.sync_official_history(data_dir, "dlt", fetch=lambda *_: dlt_payload(), sleep=lambda _: None)
            archive = lottery_skill.load_ready_archive(data_dir, "dlt")
            altered = {**archive, "public_context": {"pool_balance_after_draw": "999999999"}}
            first, _ = lottery_skill.generate("dlt", archive, 1, "hot", 2, "medium", 42, set())
            second, _ = lottery_skill.generate("dlt", altered, 1, "hot", 2, "medium", 42, set())
            self.assertEqual(first, second)

    def test_backtest_is_reproducible_and_does_not_read_later_draws(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            lottery_skill.sync_official_history(data_dir, "dlt", fetch=lambda *_: dlt_payload(), sleep=lambda _: None)
            args = SimpleNamespace(data_dir=str(data_dir), game="dlt", window=1, seed=3, from_issue="07002", to_issue="07002")
            original_sync = lottery_skill.sync_official_history
            lottery_skill.sync_official_history = lambda *_args, **_kwargs: lottery_skill.status_for_game(data_dir, "dlt")
            try:
                first = lottery_skill.backtest(args)
                second = lottery_skill.backtest(args)
                archive = lottery_skill.read_json(lottery_skill.archive_path(data_dir, "dlt"))
                archive["draws"].append({"issue": "99999", "sequence": 3, "draw_date": "2099-01-01", "front": [1, 2, 3, 4, 5], "back": [1, 2]})
                lottery_skill.write_json(lottery_skill.archive_path(data_dir, "dlt"), archive)
                after_later_change = lottery_skill.backtest(args)
            finally:
                lottery_skill.sync_official_history = original_sync
            self.assertEqual(first, second)
            self.assertEqual(first["results"], after_later_change["results"])
            self.assertIn("前区 平均命中", lottery_skill.render_backtest(first))


if __name__ == "__main__":
    unittest.main()
