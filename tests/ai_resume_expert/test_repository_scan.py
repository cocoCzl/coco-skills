#!/usr/bin/env python3
"""Black-box safety and coverage tests for static repository scanning."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCANNER = ROOT / "ai-resume-expert" / "scripts" / "scan_repository.py"
VALIDATOR = ROOT / "ai-resume-expert" / "scripts" / "validate_resume_package.py"
EVIDENCE_SCHEMA = ROOT / "ai-resume-expert" / "schemas" / "evidence-record.schema.json"
FIXTURE = ROOT / "tests" / "fixtures" / "ai_resume_expert" / "sample_repository"
OBJECTIVE_C_FIXTURE = ROOT / "tests" / "fixtures" / "ai_resume_expert" / "ios_objective_c_repository"
VALID_PACKAGE = ROOT / "tests" / "fixtures" / "ai_resume_expert" / "resume-package-valid.json"


class RepositoryScanTests(unittest.TestCase):
    def run_scanner(self, target: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            ["python3", "-B", str(SCANNER), str(target), *extra],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertTrue(result.stdout.strip(), result.stderr)
        return result, json.loads(result.stdout)

    def copied_fixture(self, directory: Path) -> Path:
        target = directory / "sample_repository"
        shutil.copytree(FIXTURE, target)
        return target

    def test_authorization_gate_runs_before_any_scan(self) -> None:
        result, payload = self.run_scanner(FIXTURE)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "MATERIAL_AUTHORIZATION_REQUIRED")

    def test_static_scan_finds_project_facts_without_claiming_contribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copied_fixture(Path(tmp))
            result, payload = self.run_scanner(target, "--authorized")
            marker = target / "EXECUTED_MARKER"
            self.assertFalse(marker.exists())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["safety"]["mode"], "static_read_only")
        for key in ("executed_code", "ran_builds", "ran_tests", "ran_scripts", "ran_containers", "used_network", "modified_target"):
            self.assertFalse(payload["safety"][key])
        self.assertGreater(payload["project_facts"].__len__(), 0)
        self.assertTrue(all(fact["ownership_status"] == "pending_confirmation" for fact in payload["project_facts"]))
        self.assertTrue(all(not fact["resume_eligible"] for fact in payload["project_facts"]))
        self.assertTrue(all(item["candidate_only"] for item in payload["contribution_candidates"]))
        self.assertEqual(payload["git_hints"]["status"], "not_read")
        self.assertGreaterEqual(payload["scan_coverage"]["read_scope_counts"].get("container_configuration", 0), 2)
        self.assertTrue(any(fact["id"] == "pf-containers" for fact in payload["project_facts"]))
        self.assertEqual(len(payload["evidence_records"]), len(payload["project_facts"]))
        allowed_record_fields = set(json.loads(EVIDENCE_SCHEMA.read_text(encoding="utf-8"))["properties"])
        for record in payload["evidence_records"]:
            self.assertLessEqual(set(record), allowed_record_fields)
            self.assertEqual(record["fact_type"], "project_fact")
            self.assertEqual(record["status"], "observed_project_fact")
            self.assertFalse(record["resume_eligible"])
            self.assertFalse(record["ownership"]["confirmed_by_user"])
            self.assertTrue(record["sources"])
            self.assertEqual(
                [source["locator"] for source in record["sources"]],
                next(fact["source_hints"] for fact in payload["project_facts"] if fact["id"] == record["id"]),
            )

    def test_static_scan_reads_objective_c_m_source_files(self) -> None:
        result, payload = self.run_scanner(OBJECTIVE_C_FIXTURE, "--authorized")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(payload["scan_coverage"]["files_read"], 1)
        self.assertEqual(payload["scan_coverage"]["read_scope_counts"].get("source"), 1)
        self.assertNotIn("unsupported_type", payload["scan_coverage"]["skipped_counts"])
        objective_c_fact = next(
            fact
            for fact in payload["project_facts"]
            if fact["statement"] == "仓库包含 Objective-C 源文件；这只说明项目技术构成，不证明个人贡献。"
        )
        self.assertEqual(len(objective_c_fact["source_hints"]), 1)
        self.assertRegex(objective_c_fact["source_hints"][0], r"^<source:[0-9a-f]{12}\.m>$")

    def test_sensitive_dependencies_build_outputs_and_source_text_are_excluded(self) -> None:
        result, payload = self.run_scanner(FIXTURE, "--authorized")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("TEST_ONLY_NOT_A_REAL_SECRET", rendered)
        self.assertNotIn("SpringApplication.run(TaskService.class", rendered)
        self.assertNotIn("touch EXECUTED_MARKER", rendered)
        self.assertNotIn("FAKE_SCANNER_SECRET_VALUE", rendered)
        self.assertNotIn("FAKE_SCANNER_BEARER_VALUE", rendered)
        self.assertNotIn("FAKE_SCANNER_TOKEN_VALUE", rendered)
        self.assertNotIn("InternalProjectOrion", rendered)
        self.assertNotIn("InternalProjectNebula", rendered)
        self.assertNotIn("OpenAI-compatible API", rendered)
        skipped = payload["scan_coverage"]["skipped_counts"]
        self.assertGreaterEqual(skipped.get("sensitive_file", 0), 1)
        self.assertGreaterEqual(skipped.get("excluded_directory", 0), 2)
        self.assertGreaterEqual(skipped.get("content_sensitive", 0), 2)
        self.assertGreater(
            payload["scan_coverage"]["files_opened_for_static_inspection"],
            payload["scan_coverage"]["files_read"],
        )
        self.assertEqual(payload["scan_coverage"]["skipped_examples"]["sensitive_file"], ["<redacted-sensitive-path>"])
        self.assertEqual(
            payload["scan_coverage"]["skipped_examples"]["content_sensitive"],
            ["<redacted-content-sensitive-path>"],
        )

    def test_scanned_evidence_record_cannot_support_personal_claim_without_confirmation(self) -> None:
        scan_result, scan = self.run_scanner(FIXTURE, "--authorized")
        self.assertEqual(scan_result.returncode, 0, scan_result.stdout + scan_result.stderr)
        record = copy.deepcopy(scan["evidence_records"][0])
        # Clear disclosure only to isolate the ownership rule. It remains an
        # observed project fact with pending personal attribution.
        record["disclosure"] = {"status": "approved", "confirmed_by_user": True}
        package = json.loads(VALID_PACKAGE.read_text(encoding="utf-8"))
        package["career_facts"].append(record)
        package["claims"][0]["fact_ids"] = [record["id"]]
        package["claims"][0]["ownership_required"] = False
        package["evidence_trace"][0]["fact_ids"] = [record["id"]]
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "package.json"
            package_path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
            validation = subprocess.run(
                ["python3", "-B", str(VALIDATOR), str(package_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(validation.returncode, 1)
        payload = json.loads(validation.stdout)
        codes = {item["code"] for item in payload["errors"]}
        self.assertIn("PROJECT_FACT_CANNOT_PROVE_OWNERSHIP", codes)
        self.assertIn("MISSING_CONFIRMED_EXPERIENCE_EVIDENCE", codes)

    def test_scan_discloses_bounded_coverage_and_file_limit(self) -> None:
        result, payload = self.run_scanner(FIXTURE, "--authorized", "--max-files", "1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        coverage = payload["scan_coverage"]
        self.assertEqual(coverage["files_read"], 1)
        self.assertTrue(coverage["file_limit_reached"])
        self.assertFalse(coverage["complete_full_repository_claim"])
        self.assertIn("跳过项", coverage["coverage_statement"])

    def test_git_requires_independent_authorization_before_any_scan(self) -> None:
        result, payload = self.run_scanner(FIXTURE, "--authorized", "--include-git-hints")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["error"]["code"], "GIT_AUTHORIZATION_REQUIRED")

    def test_authorized_git_output_is_redacted_clue_not_personal_contribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copied_fixture(Path(tmp))
            log_dir = target / ".git" / "logs"
            log_dir.mkdir(parents=True)
            (log_dir / "HEAD").write_text(
                "0" * 40
                + " "
                + "1" * 40
                + " Alex Example <alex@example.invalid> 1700000000 +0800\tcommit: feat: internal-codename\n",
                encoding="utf-8",
            )
            result, payload = self.run_scanner(
                target,
                "--authorized",
                "--include-git-hints",
                "--git-authorized",
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        hint = payload["git_hints"]
        self.assertEqual(hint["status"], "available")
        self.assertTrue(hint["clue_only"])
        self.assertEqual(hint["ownership_status"], "pending_confirmation")
        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("alex@example.invalid", rendered.lower())
        self.assertNotIn("internal-codename", rendered)
        self.assertNotIn("1" * 40, rendered)


if __name__ == "__main__":
    unittest.main()
