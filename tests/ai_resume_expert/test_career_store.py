#!/usr/bin/env python3
"""Black-box opt-in persistence tests for the local career evidence store."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STORE_TOOL = ROOT / "ai-resume-expert" / "scripts" / "career_store.py"
VALID_INPUT = ROOT / "tests" / "fixtures" / "ai_resume_expert" / "resume-package-valid.json"


class CareerStoreTests(unittest.TestCase):
    def run_tool(self, *args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            ["python3", "-B", str(STORE_TOOL), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertTrue(result.stdout.strip(), result.stderr)
        return result, json.loads(result.stdout)

    def test_no_opt_in_does_not_create_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "career-evidence.json"
            result, payload = self.run_tool("create", "--path", str(path), "--input", str(VALID_INPUT))
            self.assertFalse(path.exists())
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["error"]["code"], "PERSISTENCE_OPT_IN_REQUIRED")

    def test_create_saves_only_confirmed_target_independent_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "career-evidence.json"
            result, payload = self.run_tool(
                "create",
                "--path",
                str(path),
                "--input",
                str(VALID_INPUT),
                "--opt-in",
            )
            store = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(payload["written"])
        self.assertTrue(store["target_independent"])
        self.assertEqual(store["kind"], "career_evidence_store")
        self.assertTrue(all(fact["status"] == "confirmed" for fact in store["facts"]))
        serialized = json.dumps(store, ensure_ascii=False).lower()
        self.assertNotIn("jd_text", serialized)
        self.assertNotIn("resume_markdown", serialized)
        self.assertNotIn("source_code", serialized)
        self.assertNotIn("星河软件", serialized)
        self.assertIn("某企业软件公司", serialized)

    def test_store_path_inside_skill_package_is_refused(self) -> None:
        path = ROOT / "ai-resume-expert" / "forbidden-career-evidence.json"
        result, payload = self.run_tool(
            "create",
            "--path",
            str(path),
            "--input",
            str(VALID_INPUT),
            "--opt-in",
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["error"]["code"], "SKILL_PACKAGE_WRITE_REFUSED")
        self.assertFalse(path.exists())

    def test_filter_removes_jd_copy_source_code_and_secret_like_fact(self) -> None:
        valid_document = json.loads(VALID_INPUT.read_text(encoding="utf-8"))
        safe_fact = valid_document["career_facts"][1]
        safe_fact["source_code"] = "public void internalMethod() {}"
        unsafe_fact = dict(valid_document["career_facts"][2])
        unsafe_fact["id"] = "fact-secret"
        unsafe_fact["statement"] = "api_key=TEST_ONLY_NONFUNCTIONAL_PLACEHOLDER"
        document = {
            "facts": [safe_fact, unsafe_fact],
            "jd_text": "要求熟悉某关键词；这段岗位文案不得进入事实库。",
            "resume_markdown": "这不是职业事实真源。",
        }
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            output_path = Path(tmp) / "career-evidence.json"
            input_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            result, payload = self.run_tool(
                "create",
                "--path",
                str(output_path),
                "--input",
                str(input_path),
                "--opt-in",
            )
            store = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([fact["id"] for fact in store["facts"]], ["fact-contribution-1"])
        reasons = {entry["reason"] for entry in payload["filter_report"]["filtered_fields"]}
        self.assertIn("source_resume_or_jd_content_not_persisted", reasons)
        self.assertIn("fact-secret", {entry["id"] for entry in payload["filter_report"]["skipped_facts"]})

    def test_sanitized_disclosure_never_persists_raw_internal_statement(self) -> None:
        document = json.loads(VALID_INPUT.read_text(encoding="utf-8"))
        fact = document["career_facts"][0]
        fact["statement"] = "为内部客户代号 Project-Nebula 维护私有结算系统。"
        fact["disclosure"] = {
            "status": "sanitized",
            "confirmed_by_user": True,
            "sanitized_statement": "为企业客户维护结算类系统。",
        }
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            store_path = Path(tmp) / "career-evidence.json"
            input_path.write_text(json.dumps({"facts": [fact]}, ensure_ascii=False), encoding="utf-8")
            result, _payload = self.run_tool(
                "create", "--path", str(store_path), "--input", str(input_path), "--opt-in"
            )
            stored = store_path.read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Project-Nebula", stored)
        self.assertNotIn("内部客户代号", stored)
        self.assertIn("为企业客户维护结算类系统", stored)

    def test_confirmed_status_without_user_confirmation_is_not_persisted(self) -> None:
        document = json.loads(VALID_INPUT.read_text(encoding="utf-8"))
        fact = document["career_facts"][0]
        fact["id"] = "fact-model-marked-confirmed"
        fact["fact_type"] = "project_fact"
        fact["ownership"] = {"status": "not_applicable", "confirmed_by_user": False}
        fact["disclosure"] = {"status": "approved", "confirmed_by_user": False}
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            store_path = Path(tmp) / "career-evidence.json"
            input_path.write_text(json.dumps({"facts": [fact]}, ensure_ascii=False), encoding="utf-8")
            result, payload = self.run_tool(
                "create", "--path", str(store_path), "--input", str(input_path), "--opt-in"
            )
            self.assertFalse(store_path.exists())
        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "NO_PERSISTABLE_FACTS")

    def test_update_merges_by_stable_fact_id(self) -> None:
        document = json.loads(VALID_INPUT.read_text(encoding="utf-8"))
        extra_fact = json.loads(json.dumps(document["career_facts"][2], ensure_ascii=False))
        extra_fact["id"] = "fact-skill-postgresql"
        extra_fact["statement"] = "在后端项目中使用 PostgreSQL 完成数据访问开发。"
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "career-evidence.json"
            create_result, _ = self.run_tool(
                "create", "--path", str(store_path), "--input", str(VALID_INPUT), "--opt-in"
            )
            self.assertEqual(create_result.returncode, 0)
            update_input = Path(tmp) / "update.json"
            update_input.write_text(json.dumps({"facts": [extra_fact]}, ensure_ascii=False), encoding="utf-8")
            result, payload = self.run_tool(
                "update", "--path", str(store_path), "--input", str(update_input), "--opt-in"
            )
            store = json.loads(store_path.read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("fact-skill-postgresql", payload["added_fact_ids"])
        self.assertIn("fact-skill-postgresql", {fact["id"] for fact in store["facts"]})

    def test_reuse_for_two_target_roles_never_persists_target_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "career-evidence.json"
            result, _ = self.run_tool(
                "create", "--path", str(store_path), "--input", str(VALID_INPUT), "--opt-in"
            )
            self.assertEqual(result.returncode, 0)
            before = hashlib.sha256(store_path.read_bytes()).hexdigest()
            first_result, first = self.run_tool(
                "reuse", "--path", str(store_path), "--target-role", "Java 后端开发工程师", "--opt-in"
            )
            second_result, second = self.run_tool(
                "reuse", "--path", str(store_path), "--target-role", "AI 应用开发工程师", "--opt-in"
            )
            after = hashlib.sha256(store_path.read_bytes()).hexdigest()
            stored_text = store_path.read_text(encoding="utf-8")
        self.assertEqual(first_result.returncode, 0)
        self.assertEqual(second_result.returncode, 0)
        self.assertEqual(before, after)
        self.assertTrue(first["store_unchanged"])
        self.assertTrue(second["store_unchanged"])
        self.assertNotIn("Java 后端开发工程师", stored_text)
        self.assertNotIn("AI 应用开发工程师", stored_text)
        self.assertEqual([fact["id"] for fact in first["facts"]], [fact["id"] for fact in second["facts"]])

    def test_reuse_rejects_manually_polluted_or_legacy_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "career-evidence.json"
            create_result, _ = self.run_tool(
                "create", "--path", str(store_path), "--input", str(VALID_INPUT), "--opt-in"
            )
            self.assertEqual(create_result.returncode, 0)
            store = json.loads(store_path.read_text(encoding="utf-8"))
            store["facts"][0]["source_code"] = "private internal source excerpt"
            store["facts"][0]["conflict"] = {
                "status": "unresolved",
                "conflicting_source_ids": ["source-user-1", "source-other"],
            }
            store_path.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
            result, payload = self.run_tool("reuse", "--path", str(store_path), "--opt-in")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["error"]["code"], "POLLUTED_STORE_REFUSED")
        self.assertNotIn("facts", payload)


if __name__ == "__main__":
    unittest.main()
