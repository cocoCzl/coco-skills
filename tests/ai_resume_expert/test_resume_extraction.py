#!/usr/bin/env python3
"""Black-box tests for read-only original-resume extraction."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
EXTRACTOR = ROOT / "ai-resume-expert" / "scripts" / "extract_resume.py"
RESUMES = ROOT / "tests" / "fixtures" / "ai_resume_expert" / "resumes"


def make_pdf(path: Path, text: Optional[str]) -> None:
    content = b"q\nQ\n"
    if text is not None:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content = ("BT\n/F1 12 Tf\n72 720 Td\n({0}) Tj\nET\n".format(escaped)).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"endstream",
    ]
    payload = bytearray(b"%PDF-1.4\n%fixture\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend("{0} 0 obj\n".format(number).encode("ascii"))
        payload.extend(obj)
        payload.extend(b"\nendobj\n")
    xref = len(payload)
    payload.extend("xref\n0 {0}\n".format(len(objects) + 1).encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend("{0:010d} 00000 n \n".format(offset).encode("ascii"))
    payload.extend(
        ("trailer\n<< /Size {0} /Root 1 0 R >>\nstartxref\n{1}\n%%EOF\n".format(len(objects) + 1, xref)).encode("ascii")
    )
    path.write_bytes(bytes(payload))


class ResumeExtractionTests(unittest.TestCase):
    def run_extractor(
        self,
        path: Path,
        *extra: str,
        env: Optional[dict[str, str]] = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            [sys.executable, "-B", str(EXTRACTOR), str(path), *extra],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        self.assertTrue(result.stdout.strip(), result.stderr)
        return result, json.loads(result.stdout)

    def test_authorization_gate_precedes_resume_read(self) -> None:
        result, payload = self.run_extractor(RESUMES / "sample_resume.md")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["error"]["code"], "MATERIAL_AUTHORIZATION_REQUIRED")

    def test_markdown_extraction_keeps_sections_and_original_hash(self) -> None:
        source = RESUMES / "sample_resume.md"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        result, payload = self.run_extractor(source, "--authorized")
        after = hashlib.sha256(source.read_bytes()).hexdigest()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, after)
        self.assertEqual(payload["source"]["sha256"], before)
        self.assertTrue(payload["source"]["opened_read_only"])
        self.assertEqual(payload["diagnosis_scope"], "text_only")
        self.assertFalse(payload["visual_layout_reviewed"])
        self.assertIn("工作经历", payload["extraction"]["plain_text"])
        self.assertTrue(any(segment["section"] == "工作经历" for segment in payload["extraction"]["segments"]))
        self.assertTrue(all("locator" in segment for segment in payload["extraction"]["segments"]))

    def test_plain_text_extraction_recognizes_common_section_heading(self) -> None:
        result, payload = self.run_extractor(RESUMES / "sample_resume.txt", "--authorized")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        headings = [segment["text"] for segment in payload["extraction"]["segments"] if segment["kind"] == "section_heading"]
        self.assertIn("工作经历", headings)
        self.assertIn("教育经历", headings)

    def test_docx_extraction_uses_stdlib_zip_xml_and_paragraph_locations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample_resume.docx"
            xml = (RESUMES / "docx-document.xml").read_text(encoding="utf-8")
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("word/document.xml", xml)
            result, payload = self.run_extractor(path, "--authorized")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(payload["source"]["format"], "docx")
        self.assertIn("设计异步任务状态追踪机制", payload["extraction"]["plain_text"])
        self.assertTrue(any("paragraph" in segment["locator"] for segment in payload["extraction"]["segments"]))
        self.assertTrue(any(segment["section"] == "工作经历" for segment in payload["extraction"]["segments"]))
        body_segment = next(
            segment
            for segment in payload["extraction"]["segments"]
            if segment["text"] == "设计异步任务状态追踪机制，并补充异常记录。"
        )
        self.assertEqual(body_segment["locator"], "paragraph 4, page 1")
        self.assertEqual(body_segment["page"], 1)

    def test_docx_extraction_includes_header_and_footer_xml_with_clear_source_locations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resume_with_header_footer.docx"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("word/document.xml", (RESUMES / "docx-document.xml").read_text(encoding="utf-8"))
                archive.writestr("word/header1.xml", (RESUMES / "docx-header1.xml").read_text(encoding="utf-8"))
                archive.writestr("word/footer1.xml", (RESUMES / "docx-footer1.xml").read_text(encoding="utf-8"))
            result, payload = self.run_extractor(path, "--authorized")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        extraction = payload["extraction"]
        self.assertIn("设计异步任务状态追踪机制", extraction["plain_text"])
        self.assertIn("邮箱：lin@example.test", extraction["plain_text"])
        self.assertIn("作品集：https://portfolio.example.test/lin", extraction["plain_text"])
        self.assertEqual(
            [part["path"] for part in extraction["docx_text_coverage"]["parts_examined"]],
            ["word/document.xml", "word/header1.xml", "word/footer1.xml"],
        )
        header_segment = next(segment for segment in extraction["segments"] if segment["text"] == "邮箱：lin@example.test")
        footer_segment = next(segment for segment in extraction["segments"] if segment["text"] == "作品集：https://portfolio.example.test/lin")
        self.assertEqual(header_segment["source_part"], "word/header1.xml")
        self.assertEqual(footer_segment["source_part"], "word/footer1.xml")
        self.assertIn("word/header1.xml, paragraph", header_segment["locator"])
        self.assertIn("word/footer1.xml, paragraph", footer_segment["locator"])
        self.assertNotIn("page", header_segment)
        self.assertFalse(payload["visual_layout_reviewed"])
        self.assertIn("do not establish rendered page placement", extraction["docx_text_coverage"]["coverage_statement"])

    def test_corrupt_docx_stops_and_requests_reliable_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.docx"
            path.write_text("not a zip", encoding="utf-8")
            result, payload = self.run_extractor(path, "--authorized")
        self.assertEqual(result.returncode, 4)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "failed")
        self.assertIn("Do not draw a complete diagnosis", payload["next_action"])

    @unittest.skipUnless(shutil.which("pdftotext"), "local pdftotext is not installed")
    def test_text_pdf_extraction_preserves_page_locator(self) -> None:
        result, payload = self.run_extractor(RESUMES / "sample_resume.pdf", "--authorized")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(payload["source"]["format"], "pdf")
        self.assertIn("Candidate Resume", payload["extraction"]["plain_text"])
        self.assertEqual(payload["extraction"]["pages_detected"], 1)
        self.assertTrue(any("page 1" in segment["locator"] for segment in payload["extraction"]["segments"]))

    @unittest.skipUnless(shutil.which("pdftotext"), "local pdftotext is not installed")
    def test_image_only_pdf_degrades_to_ocr_confirmation_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scanned_resume.pdf"
            make_pdf(path, None)
            result, payload = self.run_extractor(path, "--authorized")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(payload["status"], "ocr_required")
        self.assertTrue(payload["user_confirmation_required"])
        self.assertFalse(payload["ocr_used"])

    def test_missing_pdf_capability_returns_explicit_degradation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample_resume.pdf"
            make_pdf(path, "Candidate Resume")
            environment = os.environ.copy()
            environment["PATH"] = str(Path(tmp) / "empty-path")
            result, payload = self.run_extractor(
                path,
                "--authorized",
                env=environment,
            )
        self.assertEqual(result.returncode, 3)
        self.assertEqual(payload["status"], "capability_unavailable")
        self.assertIn("paste", payload["next_action"].lower())

    def test_executable_override_is_not_a_supported_argument(self) -> None:
        result, payload = self.run_extractor(
            RESUMES / "sample_resume.pdf",
            "--authorized",
            "--pdftotext",
            str(RESUMES / "sample_resume.pdf"),
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENTS")


if __name__ == "__main__":
    unittest.main()
