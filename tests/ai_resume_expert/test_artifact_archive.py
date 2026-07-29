#!/usr/bin/env python3
"""Contracts for versioned formal-delivery artifact archiving."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ARCHIVER = ROOT / "ai-resume-expert" / "scripts" / "archive_resume_artifacts.py"


class ArtifactArchiveTests(unittest.TestCase):
    def invoke(self, manifest: Path, output: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            [sys.executable, "-B", str(ARCHIVER), "--manifest", str(manifest), "--output-dir", str(output), *extra],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        return result, json.loads(result.stdout)

    def write_manifest(self, directory: Path, artifacts: list[dict]) -> Path:
        manifest = directory / "input.json"
        manifest.write_text(json.dumps({"artifacts": artifacts}), encoding="utf-8")
        return manifest

    def test_archives_formal_delivery_artifacts_with_hash_manifest_and_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            draft = temporary / "resume.md"
            trace = temporary / "trace.json"
            draft.write_text("# 李雷\n\n后端工程师\n", encoding="utf-8")
            trace.write_text('{"facts": []}\n', encoding="utf-8")
            manifest = self.write_manifest(temporary, [
                {"kind": "markdown_draft", "filename": "resume.md", "source": str(draft)},
                {"kind": "evidence_trace", "filename": "evidence-trace.json", "source": str(trace)},
            ])
            output = temporary / "reports" / "ai-resume-expert"
            first, payload = self.invoke(manifest, output, "--authorized")
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            version = Path(payload["version_directory"])
            self.assertEqual(version.name, "draft-001")
            archived = version / "resume.md"
            self.assertEqual(archived.read_text(encoding="utf-8"), draft.read_text(encoding="utf-8"))
            report = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(report["artifacts"][0]["sha256"], hashlib.sha256(draft.read_bytes()).hexdigest())
            second, second_payload = self.invoke(manifest, output, "--authorized")
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(Path(second_payload["version_directory"]).name, "draft-002")

    def test_requires_persistence_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            draft = temporary / "resume.md"
            draft.write_text("# Draft\n", encoding="utf-8")
            manifest = self.write_manifest(temporary, [{"kind": "markdown_draft", "filename": "resume.md", "source": str(draft)}])
            result, payload = self.invoke(manifest, temporary / "reports")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["error"]["code"], "PERSISTENCE_NOT_AUTHORIZED")

    def test_rejects_unsafe_or_nonformal_artifacts_without_creating_a_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            draft = temporary / "resume.md"
            draft.write_text("# Draft\n", encoding="utf-8")
            manifest = self.write_manifest(temporary, [{"kind": "raw_resume", "filename": "../resume.md", "source": str(draft)}])
            output = temporary / "reports"
            result, payload = self.invoke(manifest, output, "--authorized")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["error"]["code"], "UNSUPPORTED_ARTIFACT_KIND")
            self.assertFalse(output.exists())

    def test_rejects_a_symbolic_link_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            draft = temporary / "resume.md"
            draft.write_text("# Draft\n", encoding="utf-8")
            manifest = self.write_manifest(temporary, [{"kind": "markdown_draft", "filename": "resume.md", "source": str(draft)}])
            real_output = temporary / "real-reports"
            real_output.mkdir()
            linked_output = temporary / "reports-link"
            linked_output.symlink_to(real_output, target_is_directory=True)
            result, payload = self.invoke(manifest, linked_output, "--authorized")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["error"]["code"], "SYMLINK_OUTPUT_REFUSED")

    def test_defaults_to_the_current_working_directory_reports_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            draft = temporary / "resume.md"
            draft.write_text("# Draft\n", encoding="utf-8")
            manifest = self.write_manifest(temporary, [{"kind": "markdown_draft", "filename": "resume.md", "source": str(draft)}])
            result = subprocess.run(
                [sys.executable, "-B", str(ARCHIVER), "--manifest", str(manifest), "--authorized"],
                cwd=temporary,
                capture_output=True,
                text=True,
                check=False,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(Path(payload["version_directory"]), (temporary / "reports" / "ai-resume-expert" / "draft-001").resolve())

    def test_rejects_symbolic_link_artifact_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            real_draft = temporary / "real-resume.md"
            real_draft.write_text("# Draft\n", encoding="utf-8")
            linked_draft = temporary / "resume.md"
            linked_draft.symlink_to(real_draft)
            manifest = self.write_manifest(temporary, [{"kind": "markdown_draft", "filename": "resume.md", "source": str(linked_draft)}])
            result, payload = self.invoke(manifest, temporary / "reports", "--authorized")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["error"]["code"], "SYMLINK_INPUT_REFUSED")


if __name__ == "__main__":
    unittest.main()
