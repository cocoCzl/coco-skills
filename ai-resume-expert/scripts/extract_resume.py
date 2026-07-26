#!/usr/bin/env python3
"""Extract reviewable text from an authorized original resume, read-only.

Supported inputs are TXT, Markdown, DOCX (Office Open XML parsed with stdlib
ZIP/XML), and text-based PDF (through a locally installed ``pdftotext``).
This helper does not perform OCR or visual-layout diagnosis.  A scanned PDF or
missing capability returns a machine-readable degradation and a non-zero exit
status instead of pretending that extraction succeeded.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.etree import ElementTree

from _json_cli import CliFailure, JsonArgumentParser, emit, emit_failure, parse_json_cli


MAX_INPUT_BYTES = 30 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED_BYTES = 80 * 1024 * 1024
MAX_DOCX_ENTRIES = 3000
MAX_XML_BYTES = 20 * 1024 * 1024

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NAMESPACES = {"w": W_NS}
DOCX_DOCUMENT_PART = "word/document.xml"

SECTION_NAMES = {
    "个人信息",
    "基本信息",
    "个人简介",
    "职业概述",
    "专业技能",
    "技术能力",
    "技能",
    "工作经历",
    "工作经验",
    "项目经历",
    "项目经验",
    "教育经历",
    "教育背景",
    "实习经历",
    "开源经历",
    "竞赛经历",
    "证书",
    "奖项",
    "profile",
    "summary",
    "skills",
    "experience",
    "work experience",
    "projects",
    "project experience",
    "education",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def normalized_heading(text: str) -> str:
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", text.strip())
    cleaned = cleaned.rstrip(":：").strip()
    return cleaned.lower()


def is_section_heading(text: str, markdown_heading: bool = False, style_heading: bool = False) -> bool:
    cleaned = normalized_heading(text)
    if not cleaned:
        return False
    if markdown_heading or style_heading:
        return len(cleaned) <= 80
    return cleaned in SECTION_NAMES


def segments_from_lines(lines: List[str], page: Optional[int] = None) -> List[Dict[str, Any]]:
    segments: List[Dict[str, Any]] = []
    section = "未分类"
    paragraph: List[str] = []
    paragraph_start = 1

    def flush(end_line: int) -> None:
        nonlocal paragraph
        text = "\n".join(paragraph).strip()
        if text:
            locator = "lines {0}-{1}".format(paragraph_start, end_line) if paragraph_start != end_line else "line {0}".format(paragraph_start)
            segment: Dict[str, Any] = {
                "kind": "paragraph",
                "locator": locator,
                "section": section,
                "text": text,
            }
            if page is not None:
                segment["page"] = page
            segments.append(segment)
        paragraph = []

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip()
        markdown_heading = bool(re.match(r"^\s{0,3}#{1,6}\s+", line))
        if line.strip() and is_section_heading(line, markdown_heading=markdown_heading):
            flush(line_number - 1)
            section = re.sub(r"^\s{0,3}#{1,6}\s*", "", line.strip()).rstrip(":：").strip()
            segment = {
                "kind": "section_heading",
                "locator": "line {0}".format(line_number),
                "section": section,
                "text": section,
            }
            if page is not None:
                segment["page"] = page
            segments.append(segment)
            paragraph_start = line_number + 1
            continue
        if not line.strip():
            flush(line_number - 1)
            paragraph_start = line_number + 1
            continue
        if not paragraph:
            paragraph_start = line_number
        paragraph.append(line)
    flush(len(lines))
    return segments


def decode_text(payload: bytes) -> Tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return payload.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace"), "utf-8-with-replacement"


def extract_plain(path: Path, source_format: str) -> Dict[str, Any]:
    try:
        payload = path.read_bytes()
    except PermissionError:
        raise CliFailure("INPUT_NOT_READABLE", "Resume file is not readable.", 2)
    except OSError as exc:
        raise CliFailure("INPUT_READ_FAILED", "Could not read resume: {0}".format(exc), 2)
    text, encoding = decode_text(payload)
    if not text.strip():
        return {
            "status": "failed",
            "reason": "empty_text_file",
            "plain_text": "",
            "segments": [],
            "pages_detected": 0,
            "encoding": encoding,
        }
    return {
        "status": "success",
        "reason": None,
        "plain_text": text.replace("\r\n", "\n").replace("\r", "\n"),
        "segments": segments_from_lines(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), page=1),
        "pages_detected": 1,
        "encoding": encoding,
    }


def paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: List[str] = []
    for element in paragraph.iter():
        local = element.tag.rsplit("}", 1)[-1]
        if local == "t" and element.text:
            parts.append(element.text)
        elif local == "tab":
            parts.append("\t")
        elif local in {"br", "cr"}:
            parts.append("\n")
    return "".join(parts).strip()


def docx_style(paragraph: ElementTree.Element) -> str:
    style = paragraph.find("./w:pPr/w:pStyle", NAMESPACES)
    if style is None:
        return ""
    return style.attrib.get("{{{0}}}val".format(W_NS), "")


def docx_header_footer_part_kind(part_name: str) -> Optional[str]:
    """Return the role for a direct Word header/footer XML part, if any."""

    match = re.fullmatch(r"word/(header|footer)[^/]*\.xml", part_name)
    return match.group(1) if match else None


def extract_docx_part(
    root: ElementTree.Element,
    source_part: str,
    source_part_role: str,
    include_page_locators: bool,
) -> Tuple[List[Dict[str, Any]], List[str], int]:
    """Extract paragraph text from one WordprocessingML part.

    ``word/document.xml`` retains its historical paragraph/page locators. Header
    and footer XML has no reliable rendered-page association without layout
    processing, so those segments identify their ZIP part and paragraph only.
    """

    segments: List[Dict[str, Any]] = []
    plain_paragraphs: List[str] = []
    current_section = "未分类"
    current_page = 1
    paragraph_number = 0
    for paragraph in root.findall(".//w:p", NAMESPACES):
        paragraph_number += 1
        rendered_breaks = 0
        explicit_breaks: List[ElementTree.Element] = []
        if include_page_locators:
            rendered_breaks = len(paragraph.findall(".//w:lastRenderedPageBreak", NAMESPACES))
            explicit_breaks = [
                item
                for item in paragraph.findall(".//w:br", NAMESPACES)
                if item.attrib.get("{{{0}}}type".format(W_NS)) == "page"
            ]
            if rendered_breaks:
                current_page += rendered_breaks
        text = paragraph_text(paragraph)
        if not text:
            if include_page_locators:
                current_page += len(explicit_breaks)
            continue
        style = docx_style(paragraph)
        style_heading = style.lower().startswith("heading") or style.startswith("标题")
        heading = is_section_heading(text, style_heading=style_heading)
        if heading:
            current_section = text.rstrip(":：").strip()
        segment: Dict[str, Any] = {
            "kind": "section_heading" if heading else "paragraph",
            "section": current_section,
            "style": style or None,
            "text": text,
        }
        if include_page_locators:
            segment["locator"] = "paragraph {0}, page {1}".format(paragraph_number, current_page)
            segment["page"] = current_page
        else:
            segment["locator"] = "{0}, paragraph {1}".format(source_part, paragraph_number)
            segment["source_part"] = source_part
            segment["source_part_role"] = source_part_role
        segments.append(segment)
        plain_paragraphs.append(text)
        if include_page_locators:
            current_page += len(explicit_breaks)
    pages_detected = max((segment.get("page", 0) for segment in segments), default=0)
    return segments, plain_paragraphs, pages_detected


def extract_docx(path: Path) -> Dict[str, Any]:
    try:
        with zipfile.ZipFile(str(path), "r") as archive:
            infos = archive.infolist()
            if len(infos) > MAX_DOCX_ENTRIES:
                return failure_extraction("docx_entry_limit_exceeded")
            if sum(info.file_size for info in infos) > MAX_DOCX_UNCOMPRESSED_BYTES:
                return failure_extraction("docx_uncompressed_size_limit_exceeded")
            if any(info.flag_bits & 0x1 for info in infos):
                return failure_extraction("encrypted_docx_not_supported")
            try:
                document_info = archive.getinfo(DOCX_DOCUMENT_PART)
            except KeyError:
                return failure_extraction("docx_document_xml_missing")
            optional_parts: Dict[str, Tuple[str, zipfile.ZipInfo]] = {}
            for info in infos:
                part_kind = docx_header_footer_part_kind(info.filename)
                if part_kind is not None:
                    optional_parts[info.filename] = (part_kind, info)
            part_infos: List[Tuple[str, str, zipfile.ZipInfo]] = [
                (DOCX_DOCUMENT_PART, "document_body", document_info)
            ]
            for part_kind in ("header", "footer"):
                for part_name in sorted(optional_parts):
                    discovered_kind, info = optional_parts[part_name]
                    if discovered_kind == part_kind:
                        part_infos.append((part_name, part_kind, info))

            xml_parts: List[Tuple[str, str, bytes]] = []
            for part_name, part_role, info in part_infos:
                if info.file_size > MAX_XML_BYTES:
                    if part_name == DOCX_DOCUMENT_PART:
                        return failure_extraction("docx_document_xml_too_large")
                    return failure_extraction("docx_header_or_footer_xml_too_large")
                xml_parts.append((part_name, part_role, archive.read(info)))
    except zipfile.BadZipFile:
        return failure_extraction("invalid_or_corrupt_docx")
    except PermissionError:
        raise CliFailure("INPUT_NOT_READABLE", "Resume file is not readable.", 2)
    except OSError as exc:
        raise CliFailure("INPUT_READ_FAILED", "Could not read DOCX: {0}".format(exc), 2)

    segments: List[Dict[str, Any]] = []
    plain_paragraphs: List[str] = []
    body_pages_detected = 0
    coverage_parts: List[Dict[str, Any]] = []
    for part_name, part_role, xml_payload in xml_parts:
        lowered = xml_payload[:4096].lower()
        if b"<!doctype" in lowered or b"<!entity" in lowered:
            if part_name == DOCX_DOCUMENT_PART:
                return failure_extraction("unsafe_xml_declaration")
            return failure_extraction("unsafe_docx_header_or_footer_xml_declaration")
        try:
            root = ElementTree.fromstring(xml_payload)
        except ElementTree.ParseError:
            if part_name == DOCX_DOCUMENT_PART:
                return failure_extraction("invalid_docx_xml")
            return failure_extraction("invalid_docx_header_or_footer_xml")
        part_segments, part_paragraphs, part_pages_detected = extract_docx_part(
            root,
            source_part=part_name,
            source_part_role=part_role,
            include_page_locators=part_name == DOCX_DOCUMENT_PART,
        )
        segments.extend(part_segments)
        plain_paragraphs.extend(part_paragraphs)
        if part_name == DOCX_DOCUMENT_PART:
            body_pages_detected = part_pages_detected
        coverage_parts.append(
            {
                "path": part_name,
                "role": part_role,
                "text_paragraphs": len(part_paragraphs),
                "has_extractable_text": bool(part_paragraphs),
            }
        )
    plain_text = "\n\n".join(plain_paragraphs)
    if not plain_text.strip():
        return {
            "status": "ocr_required",
            "reason": "docx_contains_no_extractable_text",
            "plain_text": "",
            "segments": [],
            "pages_detected": 0,
            "encoding": "xml-utf8",
            "docx_text_coverage": {
                "parts_examined": coverage_parts,
                "coverage_statement": "Text was read from the listed WordprocessingML XML parts only. Header and footer part paths do not establish rendered page placement, visibility, repetition, reading order, or visual layout.",
            },
        }
    return {
        "status": "success",
        "reason": None,
        "plain_text": plain_text,
        "segments": segments,
        "pages_detected": body_pages_detected,
        "encoding": "office-open-xml",
        "docx_text_coverage": {
            "parts_examined": coverage_parts,
            "coverage_statement": "Text was read from the listed WordprocessingML XML parts only. Header and footer part paths do not establish rendered page placement, visibility, repetition, reading order, or visual layout.",
        },
    }


def failure_extraction(reason: str) -> Dict[str, Any]:
    return {
        "status": "failed",
        "reason": reason,
        "plain_text": "",
        "segments": [],
        "pages_detected": 0,
        "encoding": None,
    }


def resolve_pdftotext() -> Optional[str]:
    """Probe only the known local command; never accept an executable override."""

    return shutil.which("pdftotext")


def extract_pdf(path: Path) -> Dict[str, Any]:
    executable = resolve_pdftotext()
    if executable is None:
        return {
            "status": "capability_unavailable",
            "reason": "pdftotext_not_available",
            "plain_text": "",
            "segments": [],
            "pages_detected": 0,
            "encoding": None,
        }
    try:
        result = subprocess.run(
            [executable, "-layout", str(path), "-"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return failure_extraction("pdftotext_timeout")
    except OSError:
        return failure_extraction("pdftotext_execution_failed")
    if result.returncode != 0:
        return failure_extraction("pdf_parse_failed")
    text, encoding = decode_text(result.stdout)
    raw_pages = text.replace("\r\n", "\n").replace("\r", "\n").split("\f")
    while raw_pages and not raw_pages[-1].strip():
        raw_pages.pop()
    if not any(page.strip() for page in raw_pages):
        return {
            "status": "ocr_required",
            "reason": "pdf_has_no_extractable_text",
            "plain_text": "",
            "segments": [],
            "pages_detected": max(1, len(raw_pages)),
            "encoding": encoding,
        }
    segments: List[Dict[str, Any]] = []
    for page_number, page_text in enumerate(raw_pages, start=1):
        page_segments = segments_from_lines(page_text.split("\n"), page=page_number)
        for segment in page_segments:
            segment["locator"] = "page {0}, {1}".format(page_number, segment["locator"])
        segments.extend(page_segments)
    return {
        "status": "success",
        "reason": None,
        "plain_text": "\n\f\n".join(raw_pages),
        "segments": segments,
        "pages_detected": len(raw_pages),
        "encoding": encoding,
    }


def detect_format(path: Path, requested: str) -> str:
    if requested != "auto":
        return requested
    suffix = path.suffix.lower()
    if suffix in {".txt"}:
        return "txt"
    if suffix in {".md", ".markdown"}:
        return "md"
    if suffix == ".docx":
        return "docx"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".webp"}:
        return "image"
    try:
        with path.open("rb") as handle:
            prefix = handle.read(8)
    except OSError:
        prefix = b""
    if prefix.startswith(b"%PDF-"):
        return "pdf"
    if prefix.startswith(b"PK"):
        return "docx"
    return "unsupported"


def extract(path: Path, requested_format: str) -> Dict[str, Any]:
    if not path.exists():
        raise CliFailure("INPUT_NOT_FOUND", "Resume file does not exist: {0}".format(path), 2)
    if path.is_symlink():
        raise CliFailure("SYMLINK_INPUT_REFUSED", "Resume input cannot be a symbolic link.", 2)
    if not path.is_file():
        raise CliFailure("INPUT_NOT_FILE", "Resume input must be a regular file.", 2)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise CliFailure("INPUT_NOT_READABLE", "Could not inspect resume: {0}".format(exc), 2)
    if size > MAX_INPUT_BYTES:
        raise CliFailure("INPUT_TOO_LARGE", "Resume exceeds the 30 MiB extraction limit.", 2)
    checksum_before = sha256_file(path)
    source_format = detect_format(path, requested_format)
    if source_format in {"txt", "md"}:
        extraction = extract_plain(path, source_format)
    elif source_format == "docx":
        extraction = extract_docx(path)
    elif source_format == "pdf":
        extraction = extract_pdf(path)
    elif source_format == "image":
        extraction = {
            "status": "ocr_required",
            "reason": "image_requires_ocr_or_vision",
            "plain_text": "",
            "segments": [],
            "pages_detected": 1,
            "encoding": None,
        }
    else:
        extraction = failure_extraction("unsupported_resume_format")
    checksum_after = sha256_file(path)
    if checksum_after != checksum_before:
        raise CliFailure(
            "SOURCE_CHANGED_DURING_EXTRACTION",
            "The original resume changed while it was being read; discard this extraction and retry.",
            2,
        )

    status = extraction["status"]
    success = status == "success"
    ocr_required = status == "ocr_required"
    capability_unavailable = status == "capability_unavailable"
    if success:
        next_action = "Use the extracted text for a text-only diagnosis; render the original separately for visual diagnosis when available."
    elif ocr_required:
        next_action = "Use an authorized OCR/vision capability and ask the user to confirm the recognized text, or ask the user to paste reliable text."
    elif capability_unavailable:
        next_action = "Install/use a local pdftotext capability or ask the user to paste the resume text."
    else:
        next_action = "Do not draw a complete diagnosis from missing text; ask the user for a readable copy or pasted text."

    return {
        "ok": success,
        "kind": "resume_text_extraction",
        "schema_version": "1.0",
        "status": status,
        "source": {
            "path": str(path.resolve()),
            "format": source_format,
            "size_bytes": size,
            "sha256": checksum_before,
            "opened_read_only": True,
            "unchanged": True,
        },
        "authorization": {
            "material_processing_confirmed": True,
            "platform_boundary_notice": "本地文件不等于仅在本机处理；材料处理仍受当前 Agent 平台的数据政策约束。",
        },
        "extraction": extraction,
        "diagnosis_scope": "text_only" if success else "unavailable",
        "visual_layout_reviewed": False,
        "ocr_used": False,
        "user_confirmation_required": ocr_required,
        "limitations": [
            "This helper extracts text only and does not validate fonts, spacing, alignment, links, clipping, or reading order.",
            "Original resume statements remain candidate material, not automatically confirmed career facts.",
        ],
        "next_action": next_action,
    }


def build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(description="Read-only text extraction for an authorized original resume.")
    parser.add_argument("input", help="Path to TXT, Markdown, DOCX, or text-based PDF resume.")
    parser.add_argument(
        "--authorized",
        action="store_true",
        help="Confirm the user is authorized to let the current AI environment process this resume.",
    )
    parser.add_argument("--format", choices=("auto", "txt", "md", "docx", "pdf", "image"), default="auto")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    command = "extract_resume"
    try:
        args = parse_json_cli(build_parser(), argv)
        # Do not resolve, stat, or open the resume until authorization is explicit.
        if not args.authorized:
            raise CliFailure(
                "MATERIAL_AUTHORIZATION_REQUIRED",
                "No resume was read. Confirm authorization with --authorized after explaining the platform data boundary.",
                2,
            )
        result = extract(Path(args.input), args.format)
        emit(result)
        if result["ok"]:
            return 0
        if result["status"] in {"ocr_required", "capability_unavailable"}:
            return 3
        return 4
    except CliFailure as failure:
        return emit_failure(failure, command)


if __name__ == "__main__":
    sys.exit(main())
