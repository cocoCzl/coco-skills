#!/usr/bin/env python3
"""Repository-wide contract for behavior and trigger evaluation sets."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("ai_resume_expert", "football_betting_assistant", "lottery_number_recommendation")


class EvalContractTests(unittest.TestCase):
    def test_behavior_evals_have_objective_expectations(self) -> None:
        for skill in SKILLS:
            with self.subTest(skill=skill):
                payload = json.loads((ROOT / "evals" / skill / "evals.json").read_text(encoding="utf-8"))
                self.assertGreaterEqual(len(payload["evals"]), 10)
                ids = [str(item["id"]) for item in payload["evals"]]
                self.assertEqual(len(ids), len(set(ids)))
                for item in payload["evals"]:
                    self.assertTrue(item["prompt"].strip())
                    self.assertTrue(item["expected_output"].strip())
                    self.assertGreaterEqual(len(item.get("expectations", [])), 3, (skill, item["id"]))

    def test_trigger_evals_are_balanced_realistic_near_neighbors(self) -> None:
        for skill in SKILLS:
            with self.subTest(skill=skill):
                payload = json.loads((ROOT / "evals" / skill / "trigger-evals.json").read_text(encoding="utf-8"))
                queries = payload["queries"]
                self.assertGreaterEqual(len(queries), 20)
                positives = [item for item in queries if item["should_trigger"] is True]
                negatives = [item for item in queries if item["should_trigger"] is False]
                self.assertEqual(len(positives), len(negatives))
                self.assertEqual(len({item["id"] for item in queries}), len(queries))
                for item in queries:
                    self.assertGreaterEqual(len(item["query"]), 15)
                    self.assertTrue(item["reason"].strip())

    def test_trigger_sets_export_to_skill_creator_array(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "trigger-set.json"
            result = subprocess.run(
                ["python3", str(ROOT / "scripts" / "export_trigger_eval_set.py"), str(ROOT / "evals" / "football_betting_assistant" / "trigger-evals.json"), str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            queries = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(queries), 20)
            self.assertEqual(set(queries[0]), {"query", "should_trigger"})


if __name__ == "__main__":
    unittest.main()
