#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "ai-resume-expert" / "scripts" / "resume_skill.py"


class ResumeAgentEntrypointTests(unittest.TestCase):
    def run_entry(self, *args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(["python3", str(ENTRY), *args], cwd=ROOT, text=True, capture_output=True, check=False)
        return result, json.loads(result.stdout)

    def test_doctor_uses_stable_fast_envelope(self) -> None:
        result, payload = self.run_entry("doctor")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["status"], "ready")
        self.assertLess(payload["metrics"]["elapsed_ms"], 500)
        self.assertIn("pdf_render_available", payload["data"])

    def test_route_stops_at_target_role_when_missing(self) -> None:
        result, payload = self.run_entry("route", "我做过几个 Java 项目，帮我写简历")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["data"]["mode"], "generation")
        self.assertFalse(payload["data"]["target_role_present"])
        self.assertIn("目标岗位", payload["next_action"])

    def test_extract_preserves_child_authorization_error(self) -> None:
        result, payload = self.run_entry("extract", "does-not-matter.md")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["error_code"], "MATERIAL_AUTHORIZATION_REQUIRED")
        self.assertEqual(payload["data"]["error"]["code"], "MATERIAL_AUTHORIZATION_REQUIRED")

    def test_pdf_input_and_negated_export_do_not_override_diagnosis(self) -> None:
        _, payload = self.run_entry("route", "请诊断这份 PDF 简历的问题，先不要导出新文件")
        self.assertEqual(payload["data"]["mode"], "diagnosis")
        self.assertEqual(payload["data"]["input_format_hint"], "pdf")
        self.assertFalse(payload["data"]["export_requested_hint"])
        self.assertNotIn("运行 render", payload["next_action"])

    def test_target_roles_are_reused_and_export_requires_action(self) -> None:
        for role in ("测试开发", "客户端开发"):
            with self.subTest(role=role):
                _, payload = self.run_entry("route", f"帮我优化{role}岗位简历")
                self.assertEqual(payload["data"]["mode"], "optimization")
                self.assertTrue(payload["data"]["target_role_present"])
                self.assertNotIn("询问目标岗位", payload["next_action"])
        _, exported = self.run_entry("route", "内容已确认，请导出 PDF")
        self.assertEqual(exported["data"]["mode"], "pdf_delivery")

    def test_explicit_agent_decision_preserves_prior_context(self) -> None:
        _, payload = self.run_entry("route", "继续处理这一份 PDF", "--intent", "diagnosis", "--target-role", "测试开发")
        self.assertTrue(payload["data"]["advisory_only"])
        self.assertTrue(payload["data"]["target_role_present"])
        self.assertEqual(payload["data"]["mode"], "diagnosis")


if __name__ == "__main__":
    unittest.main()
