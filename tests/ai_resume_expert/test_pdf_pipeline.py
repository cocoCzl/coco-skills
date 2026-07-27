#!/usr/bin/env python3
"""Black-box contracts for the local HTML/PDF resume delivery pipeline."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, Tuple
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
RENDERER = ROOT / "ai-resume-expert" / "scripts" / "render_resume.py"
VALIDATOR = ROOT / "ai-resume-expert" / "scripts" / "validate_pdf.py"
SIGNOFF_RECORDER = ROOT / "ai-resume-expert" / "scripts" / "record_pdf_visual_signoff.py"
SCRIPTS = ROOT / "ai-resume-expert" / "scripts"
FIXTURES = ROOT / "tests" / "fixtures" / "ai_resume_expert"
ONE_PAGE = FIXTURES / "pdf_one_page.md"
TWO_PAGE = FIXTURES / "pdf_two_page.md"
PACKAGE_FIXTURE = FIXTURES / "resume-package-valid.json"
SAMPLE_PDF = FIXTURES / "resumes" / "sample_resume.pdf"
TEST_TEMP_ROOT = ROOT / "reports" / "ai-resume-expert" / ".test-runtime"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pdf_pipeline  # noqa: E402
import render_resume  # noqa: E402
import validate_pdf as validate_pdf_cli  # noqa: E402


def local_pdf_stack_is_usable() -> bool:
    """Check that any discovered local renderer can really make a temporary PDF.

    macOS can expose a ``soffice`` launcher whose ``--version`` works while
    headless conversion aborts.  The default CLI falls back to WeasyPrint, so
    PDF integration tests need one functional renderer plus the full Poppler
    validation stack, not merely commands on PATH.  Deterministic fake-CLI
    unit tests remain runnable when this probe fails.
    """

    tools = {name: shutil.which(name) for name in ("pdftotext", "pdfinfo", "pdftoppm", "pdffonts")}
    if not all(tools.values()):
        return False

    renderers = (
        ("libreoffice", shutil.which("soffice") or shutil.which("libreoffice")),
        ("weasyprint", shutil.which("weasyprint")),
    )
    for renderer, executable in renderers:
        if not executable:
            continue
        try:
            with tempfile.TemporaryDirectory(prefix="ai-resume-pdf-stack-") as temporary_name:
                temporary = Path(temporary_name)
                source = temporary / "probe.html"
                generated = temporary / "probe.pdf"
                source.write_text("<!doctype html><html><body><p>PDF stack probe</p></body></html>", encoding="utf-8")
                if renderer == "libreoffice":
                    profile = temporary / "libreoffice-profile"
                    profile.mkdir()
                    result = pdf_pipeline.run_local_pty(
                        [
                            str(executable),
                            "-env:UserInstallation={0}".format(profile.as_uri()),
                            "-env:SingleAppInstance=false",
                            "--headless",
                            "--convert-to",
                            "pdf",
                            "--outdir",
                            str(temporary),
                            str(source),
                        ],
                        timeout=15,
                    )
                else:
                    result = pdf_pipeline.run_local([str(executable), str(source), str(generated)], timeout=15)
                if result.returncode == 0 and generated.is_file() and generated.stat().st_size > 0:
                    inspection = pdf_pipeline.run_local([str(tools["pdfinfo"]), str(generated)], timeout=15)
                    if inspection.returncode == 0:
                        return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


LOCAL_PDF_STACK = local_pdf_stack_is_usable()


class PdfPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TEST_TEMP_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            TEST_TEMP_ROOT.rmdir()
        except OSError:
            pass

    def run_json(
        self,
        command: list[str],
        env: Dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> Tuple[subprocess.CompletedProcess[str], Dict[str, Any]]:
        result = subprocess.run(command, cwd=cwd or ROOT, text=True, capture_output=True, check=False, env=env)
        self.assertTrue(result.stdout.strip(), result.stderr)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            self.fail("command did not emit one JSON document: {0}\n{1}\n{2}".format(exc, result.stdout, result.stderr))
        return result, payload

    def run_renderer(
        self,
        markdown: Path,
        output: Path,
        *extra: str,
        env: Dict[str, str] | None = None,
    ) -> Tuple[subprocess.CompletedProcess[str], Dict[str, Any]]:
        return self.run_json(
            [
                sys.executable,
                "-B",
                str(RENDERER),
                str(markdown),
                "--output-dir",
                str(output),
                *extra,
            ],
            env=env,
        )

    def run_validator(
        self,
        pdf: Path,
        output: Path,
        *extra: str,
        env: Dict[str, str] | None = None,
    ) -> Tuple[subprocess.CompletedProcess[str], Dict[str, Any]]:
        return self.run_json(
            [
                sys.executable,
                "-B",
                str(VALIDATOR),
                str(pdf),
                "--output-dir",
                str(output),
                *extra,
            ],
            env=env,
        )

    def run_signoff_recorder(
        self,
        validation_report: Path,
        output: Path,
        *extra: str,
    ) -> Tuple[subprocess.CompletedProcess[str], Dict[str, Any]]:
        return self.run_json(
            [
                sys.executable,
                "-B",
                str(SIGNOFF_RECORDER),
                "--validation-report",
                str(validation_report),
                "--output",
                str(output),
                *extra,
            ]
        )

    def isolated_tool_environment(self, directory: Path, excluded: set[str] | None = None) -> Dict[str, str]:
        excluded = excluded or set()
        bin_dir = directory / "isolated-bin"
        bin_dir.mkdir()
        # Keep every renderer that the integration-stack probe accepts.  A
        # GitHub runner may expose LibreOffice as ``libreoffice`` rather than
        # ``soffice``, or have only WeasyPrint available.  This helper is used
        # to remove a validation capability, not to remove rendering itself.
        for name in ("soffice", "libreoffice", "weasyprint", "pdftotext", "pdfinfo", "pdftoppm", "pdffonts"):
            if name in excluded:
                continue
            resolved = shutil.which(name)
            if resolved:
                (bin_dir / name).symlink_to(resolved)
        environment = os.environ.copy()
        environment["PATH"] = str(bin_dir)
        return environment

    def write_fake_executable(self, directory: Path, name: str, body: str) -> Path:
        """Create a deterministic renderer stub without installing any PDF package."""

        path = directory / name
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o700)
        return path

    def fake_renderer_environment(self, directory: Path) -> tuple[Path, Dict[str, str]]:
        bin_dir = directory / "fake-renderers"
        bin_dir.mkdir()
        environment = os.environ.copy()
        environment["PATH"] = str(bin_dir)
        return bin_dir, environment

    def make_pdf_ready_package(self, directory: Path, markdown: Path, hash_value: str | None = None) -> Path:
        package = json.loads(PACKAGE_FIXTURE.read_text(encoding="utf-8"))
        package["stage"] = "pdf_ready"
        package["markdown"].update(
            {
                "path": str(markdown.resolve()),
                "sha256": hash_value or hashlib.sha256(markdown.read_bytes()).hexdigest(),
                "confirmed_at": "2026-07-26T09:00:00+08:00",
                "confirmed_by_user": True,
            }
        )
        package["contact"] = {
            "name": "林晓（虚构）",
            "phone": "13800000000",
            "email": "linxiao@example.invalid",
            "city": "上海",
            "links": ["https://example.invalid/linxiao"],
            "confirmed_by_user": True,
        }
        path = directory / "pdf-ready-package.json"
        path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
        return path

    def successful_automatic_pdf_validation_at(
        self,
        root: Path,
        source_markdown: str | None,
        source_markdown_path: Path | None = None,
    ) -> Dict[str, Any]:
        """Exercise the automatic gate without relying on a local PDF stack."""

        body = "虚构候选人持续负责服务端系统设计、交付和稳定性改进，能够清楚说明个人贡献与可验证结果。" * 3
        extracted_text = "虚构候选人\n" + body + "\n"

        def fake_run_local(command: list[str], timeout: int = 90) -> subprocess.CompletedProcess[str]:
            executable = Path(command[0]).name
            if executable == "pdfinfo":
                if "-url" in command:
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="Pages: 1\nPage size: 595.28 x 841.89 pts (A4)\n",
                    stderr="",
                )
            if executable == "pdftotext":
                if "-bbox-layout" in command:
                    Path(command[-1]).write_text(
                        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                        "<doc><page width=\"595.28\" height=\"841.89\">"
                        "<word xMin=\"50\" yMin=\"50\" xMax=\"120\" yMax=\"64\">简历</word>"
                        "</page></doc>",
                        encoding="utf-8",
                    )
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                return subprocess.CompletedProcess(command, 0, stdout=extracted_text, stderr="")
            if executable == "pdffonts":
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=(
                        "name                                 type              encoding         emb sub uni object ID\n"
                        "------------------------------------ ----------------- ---------------- --- --- --- ---------\n"
                        "FixtureFont                          TrueType          Identity-H       yes yes yes      1  0\n"
                    ),
                    stderr="",
                )
            if executable == "pdftoppm":
                Path(str(command[-1]) + "-1.png").write_bytes(b"fixture png")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            raise AssertionError("unexpected fake command: {0}".format(command))

        pdf = root / "resume.pdf"
        pdf.write_bytes(b"%PDF-1.4\nfixture\n")
        output = root / "validation"
        output.mkdir()
        with (
            patch.object(pdf_pipeline, "resolve_command", side_effect=lambda _requested, candidates: candidates[0]),
            patch.object(pdf_pipeline, "run_local", side_effect=fake_run_local),
            patch.object(
                pdf_pipeline,
                "inspect_grayscale_png",
                return_value={
                    "width": 900,
                    "height": 1280,
                    "contrast_span": 200,
                    "dark_ratio": 0.01,
                    "ink_ratio": 0.1,
                    "edge_ink_pixels": 0,
                },
            ),
        ):
            return pdf_pipeline.validate_pdf_artifact(
                pdf,
                output,
                "resume",
                source_markdown=source_markdown,
                source_markdown_path=source_markdown_path,
            )

    def run_successful_automatic_pdf_validation(self, source_markdown: str | None) -> Dict[str, Any]:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            return self.successful_automatic_pdf_validation_at(Path(tmp), source_markdown)

    def make_signable_automatic_report(self, root: Path) -> tuple[Dict[str, Any], Path, Path]:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        body = "虚构候选人持续负责服务端系统设计、交付和稳定性改进，能够清楚说明个人贡献与可验证结果。" * 3
        source = root / "resume.md"
        source.write_text("# 虚构候选人\n\n" + body + "\n", encoding="utf-8")
        report = self.successful_automatic_pdf_validation_at(root, source.read_text(encoding="utf-8"), source)
        report_path = root / "resume.validation.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return report, report_path, source

    def test_unconfirmed_run_creates_only_versioned_markdown_and_standalone_html(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            output = Path(tmp)
            result, payload = self.run_renderer(ONE_PAGE, output, "--name", "resume")
            version = Path(payload["version_directory"])
            html_text = Path(payload["artifacts"]["html"]).read_text(encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(payload["status"], "awaiting_confirmation")
            self.assertFalse(payload["pdf_attempted"])
            self.assertIsNone(payload["artifacts"]["pdf"])
            self.assertEqual(version.parent, output.resolve())
            self.assertEqual(list(version.glob("*.pdf")), [])
            self.assertIn("@page", html_text)
            self.assertIn("size: A4 portrait", html_text)
            self.assertIn('<main class="resume"', html_text)
            self.assertIn('class="resume-name"', html_text)
            self.assertIn('class="resume-role"', html_text)
            self.assertIn('class="resume-contact"', html_text)
            self.assertIn('class="section-title"', html_text)
            self.assertIn('class="resume-entry ', html_text)
            self.assertIn('class="resume-entry resume-entry--keep"', html_text)
            self.assertIn('class="entry-heading"', html_text)
            self.assertIn('class="entry-date"', html_text)
            self.assertIn('class="project-meta"', html_text)
            self.assertNotIn("<h1", html_text)
            self.assertNotIn("<h2", html_text)
            self.assertNotIn("<h3", html_text)
            self.assertNotIn("<link rel=", html_text)
            self.assertEqual(
                payload["manifest"]["source_markdown_sha256"],
                hashlib.sha256(ONE_PAGE.read_bytes()).hexdigest(),
            )

    def test_source_markdown_automatic_gate_requires_visual_signoff_for_final_qualification(self) -> None:
        source = "# 虚构候选人\n\n" + "虚构候选人持续负责服务端系统设计、交付和稳定性改进，能够清楚说明个人贡献与可验证结果。" * 3
        without_source = self.run_successful_automatic_pdf_validation(None)
        unbound_source = self.run_successful_automatic_pdf_validation(source)

        self.assertFalse(without_source["qualified"])
        self.assertTrue(without_source["delivery_blocked"])
        self.assertEqual(without_source["status"], "automatic_checks_only")
        self.assertTrue(without_source["qualification_scope"]["automatic_checks_passed"])
        self.assertFalse(without_source["qualification_scope"]["source_markdown_supplied"])
        self.assertIn(
            "PDF_SOURCE_MARKDOWN_REQUIRED_FOR_QUALIFICATION",
            {item["code"] for item in without_source["warnings"]},
        )
        self.assertFalse(unbound_source["automatic_qualified"])
        self.assertFalse(unbound_source["qualified"])
        self.assertEqual(unbound_source["status"], "automatic_checks_only")
        self.assertFalse(unbound_source["qualification_scope"]["source_to_pdf_integrity_checked"])

        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            source_path = root / "resume.md"
            source_path.write_text(source, encoding="utf-8")
            with_source = self.successful_automatic_pdf_validation_at(root, source, source_path)
        self.assertTrue(with_source["automatic_qualified"])
        self.assertFalse(with_source["qualified"])
        self.assertTrue(with_source["delivery_blocked"])
        self.assertTrue(with_source["visual_signoff_pending"])
        self.assertEqual(with_source["status"], "visual_signoff_pending")
        self.assertTrue(with_source["qualification_scope"]["source_to_pdf_integrity_checked"])

    def test_recorded_visual_signoff_releases_only_the_bound_automatic_result(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            report, report_path, _source = self.make_signable_automatic_report(root)
            signoff_path = root / "resume.visual-signoff.json"
            missing_confirmation, missing_payload = self.run_signoff_recorder(report_path, signoff_path)
            self.assertEqual(missing_confirmation.returncode, 2)
            self.assertEqual(missing_payload["error"]["code"], "USER_VISUAL_CONFIRMATION_REQUIRED")
            self.assertFalse(signoff_path.exists())

            recorded, recorded_payload = self.run_signoff_recorder(
                report_path,
                signoff_path,
                "--confirmed-by-user",
            )
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
            self.assertEqual(recorded_payload["status"], "recorded")
            self.assertTrue(recorded_payload["signoff"]["confirmed_by_user"])
            self.assertEqual(recorded_payload["signoff"]["kind"], "pdf_visual_signoff")
            self.assertTrue(signoff_path.is_file())
            duplicate, duplicate_payload = self.run_signoff_recorder(report_path, signoff_path, "--confirmed-by-user")
            self.assertEqual(duplicate.returncode, 2)
            self.assertEqual(duplicate_payload["error"]["code"], "SIGNOFF_OUTPUT_EXISTS")

            qualified = pdf_pipeline.apply_pdf_visual_signoff(report, signoff_path)
            self.assertTrue(qualified["automatic_qualified"])
            self.assertTrue(qualified["qualified"])
            self.assertFalse(qualified["delivery_blocked"])
            self.assertEqual(qualified["status"], "qualified")
            self.assertTrue(qualified["visual_signoff"]["valid"])

    def test_source_file_snapshot_mismatch_blocks_automatic_qualification(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            checked = "# 虚构候选人\n\n" + "虚构候选人持续负责服务端系统设计、交付和稳定性改进，能够清楚说明个人贡献与可验证结果。" * 3
            source_path = root / "resume.md"
            source_path.write_text(checked + "\n\n验证期间被替换的内容。\n", encoding="utf-8")
            result = self.successful_automatic_pdf_validation_at(root, checked, source_path)
            self.assertFalse(result["automatic_qualified"])
            self.assertFalse(result["qualified"])
            self.assertTrue(result["delivery_blocked"])
            self.assertEqual(result["status"], "failed")
            self.assertIn("MARKDOWN_SOURCE_SNAPSHOT_MISMATCH", {item["code"] for item in result["errors"]})

    def test_validate_pdf_visual_signoff_option_releases_matching_current_report(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            report, report_path, source = self.make_signable_automatic_report(root)
            signoff_path = root / "resume.visual-signoff.json"
            recorded, _payload = self.run_signoff_recorder(report_path, signoff_path, "--confirmed-by-user")
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
            output = root / "revalidation"
            captured = io.StringIO()
            with (
                patch.object(validate_pdf_cli, "validate_pdf_artifact", return_value=json.loads(json.dumps(report))),
                redirect_stdout(captured),
            ):
                exit_code = validate_pdf_cli.main(
                    [
                        report["source"]["path"],
                        "--source-markdown",
                        str(source),
                        "--output-dir",
                        str(output),
                        "--visual-signoff",
                        str(signoff_path),
                    ]
                )
            payload = json.loads(captured.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "qualified")
            self.assertTrue(payload["qualified"])
            self.assertFalse(payload["delivery_blocked"])

    def test_crlf_markdown_without_final_newline_remains_byte_bound_to_validation_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            body = "虚构候选人持续负责服务端系统设计、交付和稳定性改进，能够清楚说明个人贡献与可验证结果。" * 3
            raw = ("# 虚构候选人\r\n\r\n" + body).encode("utf-8")
            source = root / "resume.md"
            source.write_bytes(raw)
            checked = render_resume._check_input(source)
            self.assertEqual(checked.encode("utf-8"), raw)
            snapshot = root / "snapshot.md"
            render_resume._atomic_write_text(snapshot, checked)
            self.assertEqual(snapshot.read_bytes(), raw)
            result = self.successful_automatic_pdf_validation_at(root, checked, snapshot)
            self.assertTrue(result["automatic_qualified"])
            self.assertEqual(result["status"], "visual_signoff_pending")
            self.assertEqual(result["source_markdown"]["sha256"], hashlib.sha256(raw).hexdigest())

    def test_forged_or_stale_visual_signoff_cannot_release_pdf(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            report, report_path, source = self.make_signable_automatic_report(root)
            forged = root / "forged.json"
            forged.write_text("{}", encoding="utf-8")
            forged_result = pdf_pipeline.apply_pdf_visual_signoff(report, forged)
            self.assertFalse(forged_result["qualified"])
            self.assertTrue(forged_result["delivery_blocked"])
            self.assertEqual(forged_result["status"], "visual_signoff_invalid")
            self.assertIn("PDF_VISUAL_SIGNOFF_INVALID", {item["code"] for item in forged_result["errors"]})

            # Recreate the pristine automatic report because applying the
            # forged record adds diagnostic errors to that in-memory object.
            report, report_path, source = self.make_signable_automatic_report(root / "fresh")
            signoff_path = root / "fresh" / "resume.visual-signoff.json"
            recorded, _payload = self.run_signoff_recorder(report_path, signoff_path, "--confirmed-by-user")
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
            source.write_text(source.read_text(encoding="utf-8") + "\n\n签收后新增内容。\n", encoding="utf-8")
            stale_result = pdf_pipeline.apply_pdf_visual_signoff(report, signoff_path)
            self.assertFalse(stale_result["qualified"])
            self.assertTrue(stale_result["delivery_blocked"])
            self.assertEqual(stale_result["status"], "visual_signoff_invalid")
            self.assertIn("SIGNOFF_RESOURCE_HASH_MISMATCH", {item["code"] for item in stale_result["errors"]})

    def test_preview_content_change_invalidates_visual_signoff_even_when_pdf_and_markdown_match(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            report, report_path, _source = self.make_signable_automatic_report(root)
            signoff_path = root / "resume.visual-signoff.json"
            recorded, _payload = self.run_signoff_recorder(report_path, signoff_path, "--confirmed-by-user")
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

            current = json.loads(json.dumps(report))
            for key in ("page_pngs", "grayscale_pngs"):
                replacement = root / ("changed-" + key + ".png")
                replacement.write_bytes(b"changed preview bytes")
                current["artifacts"][key] = [str(replacement.resolve())]
                current["artifact_hashes"][key] = [
                    {
                        "path": str(replacement.resolve()),
                        "sha256": hashlib.sha256(replacement.read_bytes()).hexdigest(),
                        "size_bytes": replacement.stat().st_size,
                    }
                ]
            changed_preview = pdf_pipeline.apply_pdf_visual_signoff(current, signoff_path)
            self.assertFalse(changed_preview["qualified"])
            self.assertEqual(changed_preview["status"], "visual_signoff_invalid")
            self.assertIn(
                "PDF_VISUAL_SIGNOFF_CURRENT_PREVIEW_MISMATCH",
                {item["code"] for item in changed_preview["errors"]},
            )

    def test_renderer_returns_success_for_automatic_pending_visual_signoff(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            source = root / "resume.md"
            source.write_bytes(ONE_PAGE.read_bytes())
            package = self.make_pdf_ready_package(root, source)
            output = root / "out"
            output.mkdir()

            def fake_render(_executable: str, _html_path: Path, output_dir: Path, stem: str) -> tuple[Path, Dict[str, Any]]:
                pdf = output_dir / (stem + ".pdf")
                pdf.write_bytes(b"%PDF-1.4\nfixture\n")
                return pdf, {"renderer": "libreoffice", "status": "succeeded", "returncode": 0, "output_produced": True}

            pending_validation = {
                "automatic_qualified": True,
                "qualified": False,
                "visual_signoff_pending": True,
                "status": "visual_signoff_pending",
                "delivery_blocked": True,
                "next_action": "Record explicit user visual signoff.",
                "artifacts": {"page_pngs": [], "grayscale_pngs": []},
            }
            captured = io.StringIO()
            with (
                patch.object(render_resume, "resolve_command", side_effect=lambda _requested, candidates: "/fake/soffice" if candidates[0] == "soffice" else None),
                patch.object(render_resume, "_render_with_libreoffice", side_effect=fake_render),
                patch.object(render_resume, "validate_pdf_artifact", return_value=pending_validation),
                redirect_stdout(captured),
            ):
                exit_code = render_resume.main(
                    [
                        str(source),
                        "--output-dir",
                        str(output),
                        "--confirmed",
                        "--package",
                        str(package),
                    ]
                )
            payload = json.loads(captured.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "visual_signoff_pending")
            self.assertTrue(payload["automatic_qualified"])
            self.assertFalse(payload["pdf_qualified"])
            self.assertTrue(payload["delivery_blocked"])

    def test_visual_page_break_override_matches_a_visible_block_without_changing_markdown(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            output = Path(tmp)
            result, payload = self.run_renderer(
                ONE_PAGE,
                output,
                "--name",
                "resume",
                "--page-break-before",
                "工作经历",
            )
            html_text = Path(payload["artifacts"]["html"]).read_text(encoding="utf-8")
            markdown_text = Path(payload["artifacts"]["markdown"]).read_bytes()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('class="section-title" style="page-break-before: always; break-before: page;"', html_text)
            self.assertEqual(payload["layout"]["page_break_before_matched"], ["工作经历"])
            self.assertEqual(payload["layout"]["page_break_before_unmatched"], [])
            self.assertEqual(markdown_text, ONE_PAGE.read_bytes())

    def test_default_output_root_is_namespaced_under_reports(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            workspace = Path(tmp)
            result, payload = self.run_json(
                [sys.executable, "-B", str(RENDERER), str(ONE_PAGE), "--name", "default-resume"],
                cwd=workspace,
            )
            expected_root = workspace / "reports" / "ai-resume-expert"
            version = Path(payload["version_directory"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(Path(payload["output_root"]), expected_root.resolve())
            self.assertEqual(version.parent, expected_root.resolve())
            self.assertTrue(Path(payload["artifacts"]["markdown"]).is_relative_to(version))
            self.assertTrue(Path(payload["artifacts"]["html"]).is_relative_to(version))
            self.assertFalse((workspace / "output").exists())

    def test_raw_html_and_unsafe_markdown_link_are_escaped(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            source = root / "unsafe.md"
            source.write_text("# 虚构候选人\n\n## Java 工程师\n\n<script>alert(1)</script> [危险链接](javascript:alert(1))\n\n## 个人简介\n\n真实内容。\n", encoding="utf-8")
            output = root / "out"
            output.mkdir()
            result, payload = self.run_renderer(source, output)
            html_text = Path(payload["artifacts"]["html"]).read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("<script>", html_text)
        self.assertIn("&lt;script&gt;", html_text)
        self.assertNotIn("javascript:", html_text)

    def test_multiple_bare_urls_separated_by_chinese_contact_bar_remain_distinct(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            source = root / "contact.md"
            source.write_text(
                "# 虚构候选人\n\n"
                "## AI 应用工程师\n\n"
                "GitHub：https://example.invalid/profile｜博客：https://example.invalid/notes\n\n"
                "## 个人简介\n\n真实内容。\n",
                encoding="utf-8",
            )
            output = root / "out"
            output.mkdir()
            result, payload = self.run_renderer(source, output)
            html_text = Path(payload["artifacts"]["html"]).read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(html_text.count('href="https://example.invalid/'), 2)
        self.assertIn('href="https://example.invalid/profile"', html_text)
        self.assertIn('href="https://example.invalid/notes"', html_text)
        self.assertNotIn(">https://", html_text)
        self.assertIn(">example.invalid/profile</a>", html_text)

    def test_confirmed_flag_alone_cannot_bypass_resume_package_gate(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            output = Path(tmp)
            result, payload = self.run_renderer(ONE_PAGE, output, "--confirmed")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["error"]["code"], "PDF_RESUME_PACKAGE_REQUIRED")
            self.assertEqual(list(output.iterdir()), [])

    def test_changed_markdown_is_blocked_by_confirmed_sha256(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            output = root / "out"
            output.mkdir()
            source = root / "resume.md"
            source.write_bytes(ONE_PAGE.read_bytes())
            package = self.make_pdf_ready_package(root, source, hash_value="0" * 64)
            result, payload = self.run_renderer(source, output, "--confirmed", "--package", str(package))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["error"]["code"], "CONFIRMED_MARKDOWN_HASH_MISMATCH")
            self.assertEqual(list(output.iterdir()), [])

    def test_arbitrary_executable_override_is_rejected_before_writes(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            output = Path(tmp)
            result, payload = self.run_renderer(ONE_PAGE, output, "--soffice", "/bin/echo")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["error"]["code"], "UNSAFE_EXECUTABLE_OVERRIDE")
            self.assertEqual(list(output.iterdir()), [])

    def test_arbitrary_weasyprint_override_is_rejected_before_writes(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            output = Path(tmp)
            result, payload = self.run_renderer(ONE_PAGE, output, "--weasyprint", "/bin/echo")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["error"]["code"], "UNSAFE_EXECUTABLE_OVERRIDE")
            self.assertEqual(list(output.iterdir()), [])

    def test_output_inside_skill_package_is_rejected(self) -> None:
        result, payload = self.run_renderer(ONE_PAGE, ROOT / "ai-resume-expert" / "assets")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["error"]["code"], "SKILL_PACKAGE_OUTPUT_REFUSED")

    def test_symbolic_link_output_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            real = root / "real"
            real.mkdir()
            linked = root / "linked"
            linked.symlink_to(real, target_is_directory=True)
            result, payload = self.run_renderer(ONE_PAGE, linked)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["error"]["code"], "SYMLINK_OUTPUT_REFUSED")

    def test_confirmed_missing_renderer_preserves_only_markdown_html_and_degradation_json(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            source = root / "resume.md"
            source.write_bytes(ONE_PAGE.read_bytes())
            package = self.make_pdf_ready_package(root, source)
            output = root / "out"
            output.mkdir()
            result, payload = self.run_renderer(
                source,
                output,
                "--confirmed",
                "--package",
                str(package),
                "--soffice",
                "soffice",
                env={**os.environ, "PATH": str(root / "empty-path")},
            )
            version = Path(payload["version_directory"])
            self.assertEqual(result.returncode, 3)
            self.assertEqual(payload["degradation"]["code"], "PDF_RENDERER_UNAVAILABLE")
            self.assertTrue(Path(payload["artifacts"]["markdown"]).is_file())
            self.assertTrue(Path(payload["artifacts"]["html"]).is_file())
            self.assertEqual(list(version.glob("*.pdf")), [])

    def test_weasyprint_renders_when_libreoffice_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            source = root / "resume.md"
            source.write_bytes(ONE_PAGE.read_bytes())
            package = self.make_pdf_ready_package(root, source)
            output = root / "out"
            output.mkdir()
            bin_dir, environment = self.fake_renderer_environment(root)
            self.write_fake_executable(
                bin_dir,
                "weasyprint",
                "/bin/cp {0} \"$2\"\n".format(shlex.quote(str(SAMPLE_PDF))),
            )
            result, payload = self.run_renderer(
                source,
                output,
                "--confirmed",
                "--package",
                str(package),
                "--soffice",
                "soffice",
                "--weasyprint",
                "weasyprint",
                env=environment,
            )
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertEqual(payload["status"], "degraded")
            self.assertEqual(payload["degradation"]["code"], "PDF_VALIDATION_CAPABILITY_UNAVAILABLE")
            self.assertEqual(payload["renderer"]["selected"], "weasyprint")
            self.assertTrue(payload["renderer"]["fallback_used"])
            self.assertEqual(payload["renderer"]["fallback_reason"], "libreoffice_unavailable")
            self.assertEqual([item["renderer"] for item in payload["renderer"]["attempts"]], ["weasyprint"])
            self.assertEqual(payload["renderer"]["attempts"][0]["status"], "succeeded")
            self.assertTrue(Path(payload["artifacts"]["pdf"]).is_file())

    def test_failed_libreoffice_falls_back_to_weasyprint(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            source = root / "resume.md"
            source.write_bytes(ONE_PAGE.read_bytes())
            package = self.make_pdf_ready_package(root, source)
            output = root / "out"
            output.mkdir()
            bin_dir, environment = self.fake_renderer_environment(root)
            self.write_fake_executable(
                bin_dir,
                "soffice",
                "/bin/echo 'simulated LibreOffice failure' >&2\nexit 17\n",
            )
            self.write_fake_executable(
                bin_dir,
                "weasyprint",
                "/bin/cp {0} \"$2\"\n".format(shlex.quote(str(SAMPLE_PDF))),
            )
            result, payload = self.run_renderer(
                source,
                output,
                "--confirmed",
                "--package",
                str(package),
                "--soffice",
                "soffice",
                "--weasyprint",
                "weasyprint",
                env=environment,
            )
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertEqual(payload["renderer"]["selected"], "weasyprint")
            self.assertTrue(payload["renderer"]["fallback_used"])
            self.assertEqual(payload["renderer"]["fallback_reason"], "libreoffice_failed")
            attempts = payload["renderer"]["attempts"]
            self.assertEqual([item["renderer"] for item in attempts], ["libreoffice", "weasyprint"])
            self.assertEqual([item["status"] for item in attempts], ["failed", "succeeded"])
            self.assertEqual(payload["renderer"]["details"], attempts[-1])
            self.assertTrue(Path(payload["artifacts"]["pdf"]).is_file())

    def test_failed_weasyprint_partial_output_is_not_promoted_to_a_formal_pdf(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            source = root / "resume.md"
            source.write_bytes(ONE_PAGE.read_bytes())
            package = self.make_pdf_ready_package(root, source)
            output = root / "out"
            output.mkdir()
            bin_dir, environment = self.fake_renderer_environment(root)
            self.write_fake_executable(
                bin_dir,
                "weasyprint",
                "/usr/bin/printf 'partial renderer output' > \"$2\"\nexit 19\n",
            )
            result, payload = self.run_renderer(
                source,
                output,
                "--confirmed",
                "--package",
                str(package),
                "--soffice",
                "soffice",
                "--weasyprint",
                "weasyprint",
                env=environment,
            )
            version = Path(payload["version_directory"])
            attempts = payload["renderer"]["attempts"]
            self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
            self.assertEqual(payload["degradation"]["code"], "PDF_RENDER_FAILED")
            self.assertIsNone(payload["renderer"]["selected"])
            self.assertFalse(payload["renderer"]["fallback_used"])
            self.assertEqual([item["renderer"] for item in attempts], ["weasyprint"])
            self.assertEqual(attempts[0]["status"], "failed")
            self.assertTrue(attempts[0]["output_produced"])
            self.assertIsNone(payload["artifacts"]["pdf"])
            self.assertEqual(list(version.glob("*.pdf")), [])

    @unittest.skipUnless(LOCAL_PDF_STACK, "local PDF renderer and Poppler stack is unavailable or unusable")
    def test_confirmed_one_page_pdf_passes_full_automatic_quality_gate(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            source = root / "one.md"
            source.write_bytes(ONE_PAGE.read_bytes())
            package = self.make_pdf_ready_package(root, source)
            output = root / "out"
            output.mkdir()
            result, payload = self.run_renderer(source, output, "--name", "one", "--confirmed", "--package", str(package))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            validation = payload["validation"]
            self.assertEqual(payload["status"], "visual_signoff_pending")
            self.assertTrue(payload["automatic_qualified"])
            self.assertFalse(payload["pdf_qualified"])
            self.assertTrue(payload["delivery_blocked"])
            self.assertTrue(validation["automatic_qualified"])
            self.assertFalse(validation["qualified"])
            self.assertTrue(validation["visual_signoff_pending"])
            self.assertEqual(validation["summary"]["pages"], 1)
            self.assertGreaterEqual(validation["summary"]["source_body_coverage"], 0.995)
            self.assertTrue(validation["summary"]["detected_link_annotations"])
            self.assertTrue(validation["summary"]["fonts"]["all_embedded"])
            self.assertEqual(len(validation["artifacts"]["page_pngs"]), 1)
            self.assertEqual(len(validation["artifacts"]["grayscale_pngs"]), 1)
            for artifact in validation["artifacts"]["page_pngs"] + validation["artifacts"]["grayscale_pngs"]:
                self.assertTrue(Path(artifact).is_file())

    @unittest.skipUnless(LOCAL_PDF_STACK, "local PDF renderer and Poppler stack is unavailable or unusable")
    def test_validator_default_output_root_is_namespaced_under_reports(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            workspace = Path(tmp)
            source = workspace / "one.md"
            source.write_bytes(ONE_PAGE.read_bytes())
            package = self.make_pdf_ready_package(workspace, source)
            render_root = workspace / "render"
            render_root.mkdir()
            rendered, render_payload = self.run_renderer(
                source,
                render_root,
                "--confirmed",
                "--package",
                str(package),
            )
            self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
            result, payload = self.run_json(
                [
                    sys.executable,
                    "-B",
                    str(VALIDATOR),
                    render_payload["artifacts"]["pdf"],
                    "--source-markdown",
                    str(source),
                ],
                cwd=workspace,
            )
            expected_root = workspace / "reports" / "ai-resume-expert"
            version = Path(payload["version_directory"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(Path(payload["output_root"]), expected_root.resolve())
            self.assertEqual(version.parent, expected_root.resolve())
            self.assertTrue(Path(payload["report_path"]).is_relative_to(version))
            self.assertEqual(payload["status"], "visual_signoff_pending")
            self.assertTrue(payload["automatic_qualified"])
            self.assertFalse(payload["qualified"])

    @unittest.skipUnless(LOCAL_PDF_STACK, "local PDF renderer and Poppler stack is unavailable or unusable")
    def test_compact_bare_contact_urls_keep_full_annotations_and_source_coverage(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            source = root / "contact.md"
            source.write_text(
                "# 虚构候选人\n\n"
                "## Java 后端工程师\n\n"
                "上海｜138-0000-0000｜candidate@example.invalid｜"
                "GitHub：https://example.invalid/profile｜博客：https://example.invalid/notes\n\n"
                "## 个人简介\n\n5 年 Java 后端经验，能够交付可维护的企业服务。\n\n"
                "## 工作经历\n\n### 虚构公司｜Java 工程师｜2021.01—至今\n\n"
                "**任务平台｜Java、Spring Boot、PostgreSQL**\n\n"
                "- 设计异步任务状态追踪，完善失败原因记录与定向恢复能力。\n",
                encoding="utf-8",
            )
            package = self.make_pdf_ready_package(root, source)
            output = root / "out"
            output.mkdir()
            result, payload = self.run_renderer(source, output, "--confirmed", "--package", str(package))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = payload["validation"]["summary"]
            self.assertGreaterEqual(summary["source_body_coverage"], 0.995)
            self.assertIn("https://example.invalid/profile", summary["detected_link_annotations"])
            self.assertIn("https://example.invalid/notes", summary["detected_link_annotations"])

    @unittest.skipUnless(LOCAL_PDF_STACK, "local PDF renderer and Poppler stack is unavailable or unusable")
    def test_representative_long_resume_is_exactly_two_pages(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            source = root / "two.md"
            source.write_bytes(TWO_PAGE.read_bytes())
            package = self.make_pdf_ready_package(root, source)
            output = root / "out"
            output.mkdir()
            result, payload = self.run_renderer(
                source,
                output,
                "--name",
                "two",
                "--confirmed",
                "--package",
                str(package),
                "--page-break-before",
                "转型证明项目",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(payload["validation"]["summary"]["pages"], 2)
            self.assertTrue(payload["validation"]["automatic_qualified"])
            self.assertFalse(payload["validation"]["qualified"])
            self.assertEqual(payload["status"], "visual_signoff_pending")

    @unittest.skipUnless(LOCAL_PDF_STACK, "local PDF renderer and Poppler stack is unavailable or unusable")
    def test_visibly_underfilled_second_page_is_not_qualified(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            source = root / "one.md"
            source.write_bytes(ONE_PAGE.read_bytes())
            package = self.make_pdf_ready_package(root, source)
            output = root / "out"
            output.mkdir()
            result, payload = self.run_renderer(
                source,
                output,
                "--name",
                "underfilled",
                "--confirmed",
                "--package",
                str(package),
                "--page-break-before",
                "教育经历",
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(payload["status"], "validation_failed")
            error_codes = {item["code"] for item in payload["validation"]["errors"]}
            self.assertIn("PDF_SECOND_PAGE_UNDERFILLED", error_codes)

    @unittest.skipUnless(LOCAL_PDF_STACK, "local PDF renderer and Poppler stack is unavailable or unusable")
    def test_missing_validation_capability_degrades_even_after_pdf_render(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            source = root / "one.md"
            source.write_bytes(ONE_PAGE.read_bytes())
            package = self.make_pdf_ready_package(root, source)
            output = root / "out"
            output.mkdir()
            environment = self.isolated_tool_environment(root, excluded={"pdftotext"})
            result, payload = self.run_renderer(
                source,
                output,
                "--confirmed",
                "--package",
                str(package),
                "--pdftotext",
                "pdftotext",
                env=environment,
            )
            self.assertEqual(result.returncode, 3)
            self.assertEqual(payload["status"], "degraded")
            self.assertFalse(payload["pdf_qualified"])
            self.assertEqual(payload["validation"]["status"], "capability_unavailable")
            self.assertTrue(Path(payload["artifacts"]["markdown"]).is_file())
            self.assertTrue(Path(payload["artifacts"]["html"]).is_file())

    @unittest.skipUnless(LOCAL_PDF_STACK, "local PDF renderer and Poppler stack is unavailable or unusable")
    def test_full_body_loss_is_blocking_not_hidden_by_heading_checks(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            source = root / "one.md"
            source.write_bytes(ONE_PAGE.read_bytes())
            package = self.make_pdf_ready_package(root, source)
            render_output = root / "render"
            validate_output = root / "validate"
            render_output.mkdir()
            validate_output.mkdir()
            rendered, render_payload = self.run_renderer(source, render_output, "--confirmed", "--package", str(package))
            self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
            mismatched = root / "expanded.md"
            mismatched.write_text(source.read_text(encoding="utf-8") + "\n\n这是一段必须出现但实际 PDF 完全缺失的唯一验证正文。\n", encoding="utf-8")
            result, payload = self.run_validator(
                Path(render_payload["artifacts"]["pdf"]),
                validate_output,
                "--source-markdown",
                str(mismatched),
            )
            self.assertEqual(result.returncode, 1)
            self.assertFalse(payload["qualified"])
            self.assertIn("PDF_SOURCE_BODY_INCOMPLETE", {item["code"] for item in payload["errors"]})

    @unittest.skipUnless(LOCAL_PDF_STACK, "local PDF renderer and Poppler stack is unavailable or unusable")
    def test_unembedded_font_report_blocks_pdf_qualification(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            source = root / "one.md"
            source.write_bytes(ONE_PAGE.read_bytes())
            package = self.make_pdf_ready_package(root, source)
            render_output = root / "render"
            validate_output = root / "validate"
            render_output.mkdir()
            validate_output.mkdir()
            rendered, render_payload = self.run_renderer(source, render_output, "--confirmed", "--package", str(package))
            self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
            environment = self.isolated_tool_environment(root)
            fake_dir = root / "isolated-bin"
            fake = fake_dir / "pdffonts"
            fake.unlink()
            fake.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' 'name                                 type              encoding         emb sub uni object ID'\n"
                "printf '%s\\n' '------------------------------------ ----------------- ---------------- --- --- --- ---------'\n"
                "printf '%s\\n' 'UnembeddedFont                       TrueType          WinAnsi          no  no  yes      1  0'\n",
                encoding="utf-8",
            )
            fake.chmod(0o700)
            result, payload = self.run_validator(
                Path(render_payload["artifacts"]["pdf"]),
                validate_output,
                "--source-markdown",
                str(source),
                env=environment,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("PDF_FONT_NOT_EMBEDDED", {item["code"] for item in payload["errors"]})

    @unittest.skipUnless(LOCAL_PDF_STACK, "local PDF renderer and Poppler stack is unavailable or unusable")
    def test_new_unconfirmed_source_cannot_reference_previous_success_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            root = Path(tmp)
            first = root / "first.md"
            first.write_bytes(ONE_PAGE.read_bytes())
            package = self.make_pdf_ready_package(root, first)
            output = root / "out"
            output.mkdir()
            succeeded, first_payload = self.run_renderer(first, output, "--name", "resume", "--confirmed", "--package", str(package))
            self.assertEqual(succeeded.returncode, 0, succeeded.stdout + succeeded.stderr)
            old_pdf = Path(first_payload["artifacts"]["pdf"])
            second = root / "second.md"
            second.write_text(first.read_text(encoding="utf-8") + "\n\n新增但尚未确认的真实内容。\n", encoding="utf-8")
            draft, second_payload = self.run_renderer(second, output, "--name", "resume")
            self.assertEqual(draft.returncode, 0, draft.stdout + draft.stderr)
            self.assertTrue(old_pdf.is_file())
            self.assertNotEqual(first_payload["version_directory"], second_payload["version_directory"])
            self.assertIsNone(second_payload["artifacts"]["pdf"])
            self.assertNotIn("pdf", second_payload["manifest"]["artifacts"])
            self.assertNotIn(str(old_pdf), json.dumps(second_payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
