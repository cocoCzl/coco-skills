#!/usr/bin/env python3
"""Black-box delivery-gate tests for AI Resume Expert evidence tooling."""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "ai-resume-expert" / "scripts" / "validate_resume_package.py"
SCHEMAS = ROOT / "ai-resume-expert" / "schemas"
FIXTURE = ROOT / "tests" / "fixtures" / "ai_resume_expert" / "resume-package-valid.json"


class EvidenceToolTests(unittest.TestCase):
    def run_validator(self, path: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            ["python3", "-B", str(VALIDATOR), str(path), *extra],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertTrue(result.stdout.strip(), result.stderr)
        return result, json.loads(result.stdout)

    def write_variant(self, directory: Path, payload: dict, name: str = "package.json") -> Path:
        path = directory / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def load_valid(self) -> dict:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def codes(self, payload: dict) -> set[str]:
        return {item["code"] for item in payload.get("errors", [])}

    def test_valid_markdown_package_passes_with_optional_contact_warning(self) -> None:
        result, payload = self.run_validator(FIXTURE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(payload["valid"])
        self.assertFalse(payload["delivery_blocked"])
        self.assertIn("CONTACT_OPTIONAL_AT_MARKDOWN", {item["code"] for item in payload["warnings"]})

    def test_schema_and_cli_guide_is_installable_and_discoverable(self) -> None:
        expected = {
            "evidence-record.schema.json",
            "resume-package.schema.json",
            "evidence-trace.schema.json",
            "career-evidence-store.schema.json",
        }
        self.assertTrue(all((SCHEMAS / name).is_file() for name in expected))
        guide = (SCHEMAS / "README.md").read_text(encoding="utf-8")
        for marker in (
            "## 目录",
            "## 何时读取哪个 Schema",
            "## CLI 速查",
            "## 仓库扫描到证据记录的映射",
            "## 最小有效 `resume_package`",
            "## 最小有效独立 `evidence_trace`",
            "career_store.py create",
            "career_store.py update",
            "career_store.py reuse",
        ):
            self.assertIn(marker, guide)

    def test_unconfirmed_contribution_blocks_delivery(self) -> None:
        document = self.load_valid()
        document["claims"][0]["ownership_confirmed"] = False
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), document))
        self.assertEqual(result.returncode, 1)
        self.assertIn("UNCONFIRMED_PERSONAL_CONTRIBUTION", self.codes(payload))

    def test_pending_personal_contribution_fact_blocks_delivery(self) -> None:
        document = self.load_valid()
        document["career_facts"][1]["status"] = "pending_confirmation"
        document["career_facts"][1]["ownership"] = {"status": "pending", "confirmed_by_user": False}
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), document))
        self.assertEqual(result.returncode, 1)
        self.assertIn("UNCONFIRMED_PERSONAL_CONTRIBUTION", self.codes(payload))
        self.assertIn("UNCONFIRMED_FACT_REFERENCE", self.codes(payload))

    def test_observed_project_fact_cannot_bypass_personal_contribution_confirmation(self) -> None:
        document = self.load_valid()
        project_fact = copy.deepcopy(document["career_facts"][1])
        project_fact["id"] = "fact-project-only"
        project_fact["fact_type"] = "project_fact"
        project_fact["status"] = "observed_project_fact"
        project_fact["ownership"] = {"status": "pending", "confirmed_by_user": False}
        project_fact.pop("star", None)
        document["career_facts"] = [project_fact, document["career_facts"][2]]
        document["claims"][0]["fact_ids"] = ["fact-project-only"]
        document["claims"][0]["ownership_required"] = False
        document["evidence_trace"][0]["fact_ids"] = ["fact-project-only"]
        document["skills"][0]["fact_ids"] = ["fact-project-only"]
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), document))
        self.assertEqual(result.returncode, 1)
        codes = self.codes(payload)
        self.assertIn("PROJECT_FACT_CANNOT_PROVE_OWNERSHIP", codes)
        self.assertIn("MISSING_CONFIRMED_EXPERIENCE_EVIDENCE", codes)
        self.assertIn("SKILL_LACKS_PERSONAL_EXPERIENCE_EVIDENCE", codes)

    def test_unresolved_conflict_blocks_claim_instead_of_choosing_a_source(self) -> None:
        document = self.load_valid()
        document["career_facts"][1]["status"] = "conflict"
        document["career_facts"][1]["conflict"] = {
            "status": "unresolved",
            "conflicting_source_ids": ["source-user-2", "source-code-1"],
        }
        document["conflicts"] = [
            {"id": "conflict-1", "status": "unresolved", "fact_ids": ["fact-contribution-1"]}
        ]
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), document))
        self.assertEqual(result.returncode, 1)
        self.assertIn("UNRESOLVED_CONFLICT", self.codes(payload))

    def test_unselected_unresolved_fact_still_blocks_markdown_gate(self) -> None:
        document = self.load_valid()
        unresolved = copy.deepcopy(document["career_facts"][0])
        unresolved["id"] = "fact-unselected-conflict"
        unresolved["status"] = "conflict"
        unresolved["conflict"] = {
            "status": "unresolved",
            "conflicting_source_ids": ["source-user-1", "source-other"],
        }
        document["career_facts"].append(unresolved)
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), document))
        self.assertEqual(result.returncode, 1)
        self.assertIn("UNRESOLVED_CONFLICT", self.codes(payload))

    def test_confidentiality_blocker_and_redaction_need_block_delivery(self) -> None:
        document = self.load_valid()
        document["career_facts"][1]["disclosure"] = {"status": "needs_redaction"}
        document["claims"][0]["disclosure_status"] = "needs_redaction"
        document["confidentiality_blockers"] = ["内部项目代号尚未脱敏"]
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), document))
        self.assertEqual(result.returncode, 1)
        self.assertIn("CONFIDENTIALITY_BLOCK", self.codes(payload))

    def test_disclosure_clearance_requires_explicit_user_confirmation(self) -> None:
        document = self.load_valid()
        document["career_facts"][1]["disclosure"] = {"status": "approved", "confirmed_by_user": False}
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), document))
        self.assertEqual(result.returncode, 1)
        self.assertIn("DISCLOSURE_NOT_USER_CONFIRMED", self.codes(payload))

    def test_sanitized_disclosure_requires_a_safe_replacement_statement(self) -> None:
        document = self.load_valid()
        document["career_facts"][1]["disclosure"] = {"status": "sanitized", "confirmed_by_user": True}
        document["claims"][0]["disclosure_status"] = "sanitized"
        document["evidence_trace"][0]["disclosure_status"] = "sanitized"
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), document))
        self.assertEqual(result.returncode, 1)
        self.assertIn("SANITIZED_STATEMENT_REQUIRED", self.codes(payload))

    def test_resolved_conflicts_need_a_user_confirmed_resolution(self) -> None:
        document = self.load_valid()
        document["career_facts"][1]["conflict"] = {"status": "resolved"}
        document["conflicts"] = [
            {"id": "conflict-1", "status": "resolved", "fact_ids": ["fact-contribution-1"]}
        ]
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), document))
        self.assertEqual(result.returncode, 1)
        self.assertIn("UNCONFIRMED_CONFLICT_RESOLUTION", self.codes(payload))

    def test_numeric_result_without_basis_is_rejected_as_pseudo_quantification(self) -> None:
        document = self.load_valid()
        document["claims"][0]["text"] = "将接口响应时间降低 90%。"
        document["claims"][0]["quantification"] = {
            "kind": "numeric",
            "value": 90,
            "unit": "%",
            "confirmed_by_user": False,
        }
        document["evidence_trace"][0]["quantification_confirmed"] = False
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), document))
        self.assertEqual(result.returncode, 1)
        self.assertIn("UNVERIFIED_QUANTIFICATION", self.codes(payload))

    def test_numeric_basis_must_reference_a_real_source(self) -> None:
        document = self.load_valid()
        document["claims"][0]["text"] = "将任务等待时间降低 20%。"
        document["claims"][0]["quantification"] = {
            "kind": "numeric",
            "value": 20,
            "unit": "%",
            "basis": "由改造前后同口径任务记录计算。",
            "source_ids": ["source-that-does-not-exist"],
            "confirmed_by_user": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), document))
        self.assertEqual(result.returncode, 1)
        self.assertIn("UNKNOWN_QUANTIFICATION_SOURCE", self.codes(payload))

    def test_trace_must_match_claim_and_reference_known_facts(self) -> None:
        document = self.load_valid()
        document["evidence_trace"][0]["fact_ids"] = ["fact-does-not-exist"]
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), document))
        self.assertEqual(result.returncode, 1)
        self.assertIn("TRACE_FACT_MISMATCH", self.codes(payload))

    def test_standalone_trace_validates_without_resume_copy(self) -> None:
        document = self.load_valid()
        trace = {
            "schema_version": "1.0",
            "kind": "evidence_trace",
            "facts": document["career_facts"],
            "claims": [
                {
                    "id": "claim-experience-1",
                    "claim_type": "experience",
                    "included": True,
                    "fact_ids": ["fact-contribution-1"],
                }
            ],
            "entries": document["evidence_trace"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), trace, "trace.json"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(payload["kind"], "evidence_trace_validation")

    def test_pdf_gate_requires_markdown_confirmation_and_contact(self) -> None:
        document = self.load_valid()
        document["stage"] = "pdf_ready"
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), document))
        self.assertEqual(result.returncode, 1)
        self.assertIn("MARKDOWN_NOT_CONFIRMED", self.codes(payload))
        self.assertIn("MISSING_CONTACT", self.codes(payload))
        self.assertIn("CONTACT_NOT_CONFIRMED", self.codes(payload))
        self.assertIn("$.contact.city", {item["path"] for item in payload["errors"]})
        self.assertIn("MISSING_CONFIRMED_MARKDOWN_HASH", self.codes(payload))

    def test_pdf_gate_passes_after_explicit_confirmation_and_contact(self) -> None:
        document = self.load_valid()
        document["stage"] = "pdf_ready"
        document["markdown"]["confirmed_by_user"] = True
        document["markdown"]["path"] = "confirmed-resume.md"
        document["markdown"]["sha256"] = "a" * 64
        document["markdown"]["confirmed_at"] = "2026-07-26T12:00:00Z"
        document["contact"] = {
            "name": "林晓（虚构）",
            "phone": "13800000000",
            "email": "linxiao@example.invalid",
            "city": "上海",
            "confirmed_by_user": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), document), "--stage", "pdf")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["stage"], "pdf")

    def test_unknown_claim_and_version_types_cannot_bypass_gates(self) -> None:
        document = self.load_valid()
        document["target"]["version_type"] = "ats_magic"
        document["claims"][0]["claim_type"] = "unowned_project_claim"
        document["claims"][0]["ownership_required"] = False
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.run_validator(self.write_variant(Path(tmp), document))
        self.assertEqual(result.returncode, 1)
        self.assertIn("INVALID_VERSION_TYPE", self.codes(payload))
        self.assertIn("INVALID_CLAIM_TYPE", self.codes(payload))

    def test_invalid_json_returns_machine_readable_nonzero_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text("{broken", encoding="utf-8")
            result, payload = self.run_validator(path)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INVALID_JSON")


if __name__ == "__main__":
    unittest.main()
