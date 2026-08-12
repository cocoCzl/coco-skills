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


if __name__ == "__main__":
    unittest.main()
