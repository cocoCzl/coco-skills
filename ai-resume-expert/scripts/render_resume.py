#!/usr/bin/env python3
"""Render confirmed resume Markdown to standalone HTML and a validated PDF.

The command always writes a Markdown copy and printable HTML into an explicit
user output directory.  It only invokes a local PDF renderer when
``--confirmed`` is present.  Network renderers are intentionally unsupported.
"""

from __future__ import annotations

import html
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from _json_cli import CliFailure, JsonArgumentParser, atomic_write_json, emit, emit_failure, load_json, parse_json_cli
from pdf_pipeline import resolve_command, run_local, run_local_pty, sha256_file, validate_pdf_artifact
from validate_resume_package import validate_resume_package


SKILL_ROOT = Path(__file__).resolve().parents[1]
STYLE_PATH = SKILL_ROOT / "assets" / "resume.css"
DEFAULT_OUTPUT_DIR = Path("reports") / "ai-resume-expert"
MAX_MARKDOWN_BYTES = 2 * 1024 * 1024
SECTION_HEADINGS = {
    "个人简介",
    "职业概述",
    "专业技能",
    "技术能力",
    "工作经历",
    "工作经验",
    "项目经历",
    "项目经验",
    "转型证明项目",
    "其他项目证据",
    "教育经历",
    "教育背景",
    "实习经历",
    "开源经历",
    "开源与技术表达",
    "论文与专利",
    "竞赛经历",
    "证书与奖项",
}
SAFE_SCHEMES = {"http", "https", "mailto", "tel"}
BARE_URL = re.compile(r"(?<![\"'=])(https?://[^\s<>()\[\]|｜,，;；。]+)", re.IGNORECASE)
EMAIL = re.compile(r"(?<![\w@./+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![\w@.-])")


def _atomic_write_text(path: Path, content: str) -> None:
    if path.is_symlink():
        raise CliFailure("SYMLINK_OUTPUT_REFUSED", "Refusing to write through a symbolic link: {0}".format(path), 2)
    temporary = path.parent / (".{0}.{1}.tmp".format(path.name, os.getpid()))
    if temporary.exists():
        raise CliFailure("TEMPORARY_PATH_EXISTS", "Temporary output path already exists: {0}".format(temporary), 2)
    try:
        with temporary.open("xb") as handle:
            handle.write(content.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    except CliFailure:
        raise
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise CliFailure("OUTPUT_WRITE_FAILED", "Could not write output artifact: {0}".format(exc), 2)


def _valid_link(target: str) -> bool:
    try:
        parsed = urlsplit(target)
    except ValueError:
        return False
    return parsed.scheme.lower() in SAFE_SCHEMES and bool(parsed.path or parsed.netloc)


def _protect_inline(text: str) -> Tuple[str, Dict[str, str]]:
    tokens: Dict[str, str] = {}

    def store(fragment: str) -> str:
        key = "@@AIRESINLINE{0}@@".format(len(tokens))
        tokens[key] = fragment
        return key

    def code_replacement(match: re.Match[str]) -> str:
        return store("<code>{0}</code>".format(html.escape(match.group(1), quote=False)))

    text = re.sub(r"`([^`\n]+)`", code_replacement, text)

    def link_replacement(match: re.Match[str]) -> str:
        label = html.escape(match.group(1), quote=False)
        target = match.group(2).strip()
        if not _valid_link(target):
            return store(label)
        return store(
            '<a href="{0}" rel="noopener noreferrer" style="color:#315b6d;text-decoration:none">{1}</a>'.format(
                html.escape(target, quote=True),
                label,
            )
        )

    text = re.sub(r"\[([^\]\n]+)\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)", link_replacement, text)
    return text, tokens


def render_inline(source: str) -> str:
    protected, tokens = _protect_inline(source)
    rendered = html.escape(protected, quote=False)
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"__(.+?)__", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", rendered)
    rendered = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"<em>\1</em>", rendered)

    def url_replacement(match: re.Match[str]) -> str:
        target = html.unescape(match.group(1)).rstrip(".,;:，。；：")
        suffix = html.unescape(match.group(1))[len(target) :]
        parsed = urlsplit(target)
        display = (parsed.netloc + parsed.path).rstrip("/") or target
        if parsed.query:
            display += "?" + parsed.query
        if parsed.fragment:
            display += "#" + parsed.fragment
        anchor = '<a href="{0}" rel="noopener noreferrer" style="color:#315b6d;text-decoration:none">{1}</a>'.format(
            html.escape(target, quote=True),
            html.escape(display, quote=False),
        )
        return anchor + html.escape(suffix, quote=False)

    rendered = BARE_URL.sub(url_replacement, rendered)

    def email_replacement(match: re.Match[str]) -> str:
        address = match.group(1)
        return '<a href="mailto:{0}" style="color:#315b6d;text-decoration:none">{0}</a>'.format(html.escape(address, quote=True))

    rendered = EMAIL.sub(email_replacement, rendered)
    for key, fragment in tokens.items():
        rendered = rendered.replace(html.escape(key, quote=False), fragment)
    return rendered


def _render_contact(source: str) -> str:
    """Render a masthead contact row as compact, independently wrapping items."""

    items: List[str] = []
    for raw_item in re.split(r"\s*[｜|]\s*", source.strip()):
        item = raw_item.strip()
        if not item:
            continue
        rendered = render_inline(item)
        items.append('<span class="contact-item">{0}</span>'.format(rendered))
    separator = '<span class="contact-separator" aria-hidden="true">·</span>'
    return '<p class="resume-contact">{0}</p>'.format(separator.join(items))


def _render_entry_heading(source: str, level: int) -> str:
    """Move a trailing date range to a dedicated visual column without changing order."""

    if level != 3:
        return "<h{0}>{1}</h{0}>".format(level, render_inline(source))
    parts = [part.strip() for part in source.split("｜")]
    if len(parts) < 2 or not re.search(r"(?:19|20)\d{2}|至今|present", parts[-1], re.IGNORECASE):
        return '<p class="entry-heading">{0}</p>'.format(render_inline(source))
    main = "｜".join(parts[:-1])
    return (
        '<p class="entry-heading"><span class="entry-main">{0}</span>'
        '<span class="entry-date">{1}</span></p>'
    ).format(render_inline(main), render_inline(parts[-1]))


def _render_project_meta(source: str) -> str:
    cleaned = source.strip()
    if cleaned.startswith("**") and cleaned.endswith("**"):
        cleaned = cleaned[2:-2].strip()
    parts = [part.strip() for part in cleaned.split("｜", 1)]
    if len(parts) == 2:
        return (
            '<p class="project-meta"><strong class="project-name">{0}</strong>'
        '<span class="project-separator" aria-hidden="true">｜</span>'
            '<span class="project-stack">{1}</span></p>'
        ).format(render_inline(parts[0]), render_inline(parts[1]))
    return '<p class="project-meta">{0}</p>'.format(render_inline(cleaned))


def _blocks(markdown: str) -> List[Dict[str, Any]]:
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: List[Dict[str, Any]] = []
    paragraph: List[str] = []
    list_kind: Optional[str] = None
    list_items: List[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            parts: List[str] = []
            for value in paragraph:
                hard_break = value.endswith("  ") or value.endswith("\\")
                cleaned = value[:-1] if value.endswith("\\") else value.rstrip()
                parts.append(render_inline(cleaned))
                if hard_break:
                    parts.append("<br>")
                else:
                    parts.append(" ")
            body = "".join(parts).rstrip()
            blocks.append(
                {
                    "kind": "paragraph",
                    "source": " ".join(value.strip().rstrip("\\") for value in paragraph),
                    "html": "<p>{0}</p>".format(body),
                }
            )
        paragraph = []

    def flush_list() -> None:
        nonlocal list_kind, list_items
        if list_kind:
            items = "\n".join("<li>{0}</li>".format(render_inline(item)) for item in list_items)
            blocks.append({"kind": "list", "html": "<{0}>\n{1}\n</{0}>".format(list_kind, items)})
        list_kind = None
        list_items = []

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush_paragraph()
            flush_list()
            continue
        heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            value = heading.group(2).strip()
            blocks.append(
                {
                    "kind": "heading",
                    "level": level,
                    "text": re.sub(r"[*_`]", "", value).strip(),
                    "source": value,
                    "html": _render_entry_heading(value, level),
                }
            )
            continue
        if re.match(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$", line):
            flush_paragraph()
            flush_list()
            blocks.append({"kind": "rule", "html": "<hr>"})
            continue
        bullet = re.match(r"^\s{0,3}[-+*]\s+(.+)$", line)
        ordered = re.match(r"^\s{0,3}\d+[.)]\s+(.+)$", line)
        if bullet or ordered:
            flush_paragraph()
            current_kind = "ul" if bullet else "ol"
            if list_kind and list_kind != current_kind:
                flush_list()
            list_kind = current_kind
            list_items.append((bullet or ordered).group(1).strip())
            continue
        if list_kind and re.match(r"^\s{2,}\S", raw):
            list_items[-1] += " " + line.strip()
            continue
        flush_list()
        paragraph.append(line.strip())
    flush_paragraph()
    flush_list()
    return blocks


def markdown_to_html(
    markdown: str,
    css: str,
    page_break_before: Optional[Sequence[str]] = None,
) -> Tuple[str, str, List[str]]:
    blocks = _blocks(markdown)
    requested_breaks = [re.sub(r"\s+", " ", item.strip()) for item in (page_break_before or []) if item.strip()]
    matched_breaks: List[str] = []
    title = "程序员简历"
    for block in blocks:
        if block.get("kind") == "heading" and block.get("level") == 1:
            title = block.get("text") or title
            break

    first_section = len(blocks)
    seen_header_h2 = False
    for index, block in enumerate(blocks):
        if block.get("kind") != "heading" or block.get("level") != 2:
            continue
        normalized = str(block.get("text", "")).rstrip(":：").strip()
        if normalized in SECTION_HEADINGS or seen_header_h2:
            first_section = index
            break
        seen_header_h2 = True

    header_blocks = blocks[:first_section]
    body_blocks = blocks[first_section:]
    rendered_header: List[str] = []
    for block in header_blocks:
        value = block["html"]
        if block.get("kind") == "heading" and block.get("level") == 1:
            value = '<p class="resume-name">{0}</p>'.format(
                render_inline(str(block.get("source", "")))
            )
        elif block.get("kind") == "heading" and block.get("level") == 2:
            value = '<p class="resume-role">{0}</p>'.format(
                render_inline(str(block.get("source", "")))
            )
        elif block.get("kind") == "paragraph":
            value = _render_contact(str(block.get("source", "")))
        rendered_header.append(value)
    header_html = "\n".join(rendered_header)
    sections: List[str] = []
    current: List[Tuple[Dict[str, Any], str]] = []

    def render_section(items: List[Tuple[Dict[str, Any], str]]) -> str:
        """Keep each company or project entry together when it fits on a page.

        A level-three heading starts a resume entry. Grouping that heading with
        its metadata and bullets gives the print renderer a meaningful unit for
        page-break avoidance, instead of letting a new page begin with orphaned
        continuation bullets.
        """

        def wrap_entry(values: List[str]) -> str:
            joined = "\n".join(values)
            visible = html.unescape(re.sub(r"<[^>]+>", "", joined))
            character_count = len(re.sub(r"\s+", "", visible))
            bullet_count = joined.count("<li>")
            classes = "resume-entry"
            if bullet_count <= 5 and character_count <= 400:
                classes += " resume-entry--keep"
            return '<div class="{0}">\n{1}\n</div>'.format(classes, joined)

        rendered: List[str] = []
        entry: List[str] = []
        for item_block, item_html in items:
            starts_entry = item_block.get("kind") == "heading" and item_block.get("level") == 3
            if starts_entry:
                if entry:
                    rendered.append(wrap_entry(entry))
                entry = [item_html]
            elif entry:
                entry.append(item_html)
            else:
                rendered.append(item_html)
        if entry:
            rendered.append(wrap_entry(entry))
        return "<section>\n{0}\n</section>".format("\n".join(rendered))

    for block in body_blocks:
        value = block["html"]
        if block.get("kind") == "heading" and block.get("level") == 2:
            value = '<p class="section-title">{0}</p>'.format(
                render_inline(str(block.get("source", "")))
            )
        elif block.get("kind") == "paragraph" and re.fullmatch(r"<p><strong>.+</strong></p>", value, re.DOTALL):
            value = _render_project_meta(str(block.get("source", "")))
        visible_label = re.sub(r"[*_`]", "", str(block.get("source", block.get("text", ""))))
        visible_label = re.sub(r"\s+", " ", visible_label).strip().rstrip(":：")
        for requested in requested_breaks:
            if requested in matched_breaks:
                continue
            if visible_label == requested or visible_label.startswith(requested + "｜"):
                if value.startswith('<p class="'):
                    class_end = value.find('">')
                    value = value[:class_end] + '" style="page-break-before: always; break-before: page;"' + value[class_end + 1 :]
                elif value.startswith("<p>"):
                    value = value.replace("<p>", '<p style="page-break-before: always; break-before: page;">', 1)
                else:
                    value = '<div style="page-break-before: always; break-before: page;">{0}</div>'.format(value)
                matched_breaks.append(requested)
                break
        if block.get("kind") == "heading" and block.get("level") == 2:
            if current:
                sections.append(render_section(current))
            current = [(block, value)]
        else:
            current.append((block, value))
    if current:
        sections.append(render_section(current))
    if not header_blocks and sections:
        header_html = '<p class="resume-name">{0}</p>'.format(html.escape(title))

    document = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{title}</title>
  <style>
{css}
  </style>
</head>
<body>
  <main class="resume" aria-label="{aria_title}">
    <header class="resume-masthead">
{header}
    </header>
{sections}
  </main>
</body>
</html>
""".format(
        title=html.escape(title),
        aria_title=html.escape(title + "的简历", quote=True),
        css=css.rstrip(),
        header="\n".join("      " + line for line in header_html.splitlines()),
        sections="\n".join("    " + line for section in sections for line in section.splitlines()),
    )
    return document, title, matched_breaks


def _check_input(path: Path) -> str:
    if not path.exists():
        raise CliFailure("INPUT_NOT_FOUND", "Markdown input does not exist: {0}".format(path), 2)
    if path.is_symlink():
        raise CliFailure("SYMLINK_INPUT_REFUSED", "Markdown input cannot be a symbolic link.", 2)
    if not path.is_file():
        raise CliFailure("INPUT_NOT_FILE", "Markdown input must be a regular file.", 2)
    if path.suffix.lower() not in {".md", ".markdown"}:
        raise CliFailure("UNSUPPORTED_INPUT_FORMAT", "Input must be a Markdown file.", 2)
    try:
        if path.stat().st_size > MAX_MARKDOWN_BYTES:
            raise CliFailure("INPUT_TOO_LARGE", "Markdown input exceeds the 2 MiB rendering limit.", 2)
        raw = path.read_bytes()
        if len(raw) > MAX_MARKDOWN_BYTES:
            raise CliFailure("INPUT_TOO_LARGE", "Markdown input exceeds the 2 MiB rendering limit.", 2)
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise CliFailure("INPUT_NOT_UTF8", "Markdown input must use UTF-8.", 2)
    except PermissionError:
        raise CliFailure("INPUT_NOT_READABLE", "Markdown input is not readable.", 2)
    except OSError as exc:
        raise CliFailure("INPUT_READ_FAILED", "Could not read Markdown input: {0}".format(exc), 2)


def _check_output_dir(path: Path) -> Path:
    if path.is_symlink():
        raise CliFailure("SYMLINK_OUTPUT_REFUSED", "Output directory cannot be a symbolic link.", 2)
    resolved = path.resolve()
    try:
        resolved.relative_to(SKILL_ROOT.resolve())
        raise CliFailure("SKILL_PACKAGE_OUTPUT_REFUSED", "Resume artifacts must not be written into the Skill package; choose a user output directory.", 2)
    except ValueError:
        pass
    if path.exists() and not path.is_dir():
        raise CliFailure("OUTPUT_DIRECTORY_NOT_FOUND", "Output path must be a directory: {0}".format(path), 2)
    if not path.exists():
        try:
            path.mkdir(mode=0o700, parents=True)
        except OSError as exc:
            raise CliFailure("OUTPUT_DIRECTORY_CREATE_FAILED", "Could not create output directory: {0}".format(exc), 2)
    if path.is_symlink():
        raise CliFailure("SYMLINK_OUTPUT_REFUSED", "Output directory cannot be a symbolic link.", 2)
    return path.resolve()


def _artifact_name(requested: Optional[str], input_path: Path) -> str:
    name = requested or input_path.stem
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", name):
        raise CliFailure("INVALID_ARTIFACT_NAME", "Artifact name must use 1-80 ASCII letters, digits, dot, underscore, or hyphen.", 2)
    return name


def _create_version_directory(
    output_root: Path,
    stem: str,
    source_hash: str,
    confirmed: bool,
    package_hash: Optional[str],
) -> Path:
    phase = "confirmed-{0}".format((package_hash or "missing")[:12]) if confirmed else "draft"
    prefix = "{0}-{1}-{2}".format(stem, source_hash[:12], phase)
    for number in range(1, 1000):
        candidate = output_root / (prefix + "-{0:03d}".format(number))
        try:
            candidate.mkdir(mode=0o700)
            return candidate
        except FileExistsError:
            continue
        except OSError as exc:
            raise CliFailure("OUTPUT_DIRECTORY_CREATE_FAILED", "Could not create a versioned artifact directory: {0}".format(exc), 2)
    raise CliFailure("OUTPUT_VERSION_LIMIT", "Could not allocate a unique versioned artifact directory.", 2)


def _manifest_for_paths(source_hash: str, paths: Dict[str, Any]) -> Dict[str, Any]:
    artifacts: Dict[str, Any] = {}
    for name, raw in paths.items():
        if not raw or name == "render_report":
            continue
        values = raw if isinstance(raw, list) else [raw]
        records: List[Dict[str, Any]] = []
        for value in values:
            path = Path(str(value))
            if path.is_file():
                records.append({"path": str(path.resolve()), "sha256": sha256_file(path), "size_bytes": path.stat().st_size})
        if records:
            artifacts[name] = records if isinstance(raw, list) else records[0]
    return {
        "source_markdown_sha256": source_hash,
        "artifacts": artifacts,
        "note": "The render report is the manifest itself and therefore does not self-hash.",
    }


def _validate_executable_override(value: Optional[str], allowed: Sequence[str], option: str) -> None:
    if value and (value not in set(allowed) or os.path.sep in value or (os.path.altsep and os.path.altsep in value)):
        raise CliFailure(
            "UNSAFE_EXECUTABLE_OVERRIDE",
            "{0} only accepts a PATH-resolved command name (no directory) from: {1}.".format(option, ", ".join(allowed)),
            2,
        )


def _validate_pdf_gate(package_value: Optional[str], input_path: Path, checked_markdown_sha256: Optional[str] = None) -> Dict[str, Any]:
    if not package_value:
        raise CliFailure(
            "PDF_RESUME_PACKAGE_REQUIRED",
            "--confirmed cannot authorize PDF generation by itself; provide --package with a valid pdf_ready resume package.",
            2,
        )
    package_path = Path(package_value)
    if package_path.is_symlink():
        raise CliFailure("SYMLINK_INPUT_REFUSED", "Resume package input cannot be a symbolic link.", 2)
    document = load_json(package_path)
    if not isinstance(document, dict):
        raise CliFailure("INVALID_RESUME_PACKAGE", "Resume package must be a JSON object.", 2)
    validation = validate_resume_package(document, "pdf")
    if not validation.get("valid") or validation.get("delivery_blocked"):
        raise CliFailure(
            "PDF_RESUME_PACKAGE_GATE_FAILED",
            "The resume package did not pass the deterministic PDF delivery gate.",
            2,
            {"errors": validation.get("errors", [])},
        )
    markdown_record = document.get("markdown") if isinstance(document.get("markdown"), dict) else {}
    confirmed_path_value = markdown_record.get("path")
    if not isinstance(confirmed_path_value, str) or not confirmed_path_value.strip():
        raise CliFailure("CONFIRMED_MARKDOWN_PATH_MISSING", "The resume package does not bind confirmation to a Markdown path.", 2)
    confirmed_path = Path(confirmed_path_value)
    if not confirmed_path.is_absolute():
        confirmed_path = package_path.resolve().parent / confirmed_path
    if confirmed_path.resolve() != input_path.resolve():
        raise CliFailure(
            "CONFIRMED_MARKDOWN_PATH_MISMATCH",
            "The Markdown input is not the file confirmed by the resume package.",
            2,
            {"confirmed_path": str(confirmed_path.resolve()), "input_path": str(input_path.resolve())},
        )
    actual_hash = sha256_file(input_path)
    if checked_markdown_sha256 and actual_hash != checked_markdown_sha256:
        raise CliFailure(
            "MARKDOWN_INPUT_CHANGED_DURING_READ",
            "The Markdown file changed after its checked content was read; PDF generation is blocked.",
            2,
            {"checked_sha256": checked_markdown_sha256, "actual_sha256": actual_hash},
        )
    confirmed_hash = str(markdown_record.get("sha256", "")).lower()
    if actual_hash != confirmed_hash:
        raise CliFailure(
            "CONFIRMED_MARKDOWN_HASH_MISMATCH",
            "The Markdown content changed after user confirmation; PDF generation is blocked.",
            2,
            {"confirmed_sha256": confirmed_hash, "actual_sha256": actual_hash},
        )
    return {
        "package_path": str(package_path.resolve()),
        "package_sha256": sha256_file(package_path),
        "markdown_path": str(input_path.resolve()),
        "markdown_sha256": actual_hash,
        "confirmed_at": markdown_record.get("confirmed_at"),
        "validator": validation,
    }


def _renderer_failure_details(renderer: str, command: Sequence[str], error: BaseException) -> Dict[str, Any]:
    return {
        "renderer": renderer,
        "attempted": True,
        "status": "failed",
        "command": list(command),
        "returncode": None,
        "stdout": "",
        "stderr": str(error),
        "output_produced": False,
    }


def _renderer_result_details(
    renderer: str,
    command: Sequence[str],
    result: subprocess.CompletedProcess[str],
    generated: Path,
) -> Dict[str, Any]:
    return {
        "renderer": renderer,
        "attempted": True,
        "status": "failed",
        "command": list(command),
        "returncode": result.returncode,
        "stdout": result.stdout[-1000:],
        "stderr": result.stderr[-1000:],
        "output_produced": generated.is_file() and generated.stat().st_size > 0,
    }


def _commit_rendered_pdf(generated: Path, output_dir: Path, stem: str, details: Dict[str, Any]) -> Optional[Path]:
    """Atomically promote a non-empty temporary PDF, never a partial renderer output."""

    if not details["output_produced"] or details["returncode"] != 0:
        return None
    destination = output_dir / (stem + ".pdf")
    try:
        os.replace(str(generated), str(destination))
    except OSError as exc:
        details["stderr"] = "{0}\nCould not preserve rendered PDF: {1}".format(details["stderr"], exc).strip()
        return None
    details["status"] = "succeeded"
    details["output_path"] = str(destination.resolve())
    details["output_size_bytes"] = destination.stat().st_size
    return destination


def _render_with_libreoffice(soffice: str, html_path: Path, output_dir: Path, stem: str) -> Tuple[Optional[Path], Dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix=".pdf-render-", dir=str(output_dir)) as temporary_name:
        temporary = Path(temporary_name)
        profile = temporary / "libreoffice-profile"
        command = [
            soffice,
            "-env:UserInstallation={0}".format(profile.resolve().as_uri()),
            "-env:SingleAppInstance=false",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(temporary),
            str(html_path),
        ]
        try:
            result = run_local_pty(command)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, _renderer_failure_details("libreoffice", command, exc)
        generated = temporary / (html_path.stem + ".pdf")
        details = _renderer_result_details("libreoffice", command, result, generated)
        return _commit_rendered_pdf(generated, output_dir, stem, details), details


def _render_with_weasyprint(weasyprint: str, html_path: Path, output_dir: Path, stem: str) -> Tuple[Optional[Path], Dict[str, Any]]:
    """Render the already standalone HTML through the local WeasyPrint CLI."""

    with tempfile.TemporaryDirectory(prefix=".pdf-render-", dir=str(output_dir)) as temporary_name:
        temporary = Path(temporary_name)
        generated = temporary / (stem + ".pdf")
        command = [weasyprint, str(html_path), str(generated)]
        try:
            result = run_local(command)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, _renderer_failure_details("weasyprint", command, exc)
        details = _renderer_result_details("weasyprint", command, result, generated)
        return _commit_rendered_pdf(generated, output_dir, stem, details), details


def build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(description="Create standalone resume HTML and, after explicit confirmation, a locally rendered PDF.")
    parser.add_argument("input", help="Path to the final UTF-8 Markdown resume.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Artifact root; defaults to reports/ai-resume-expert in the current working directory.",
    )
    parser.add_argument("--name", help="Stable artifact basename; defaults to the Markdown filename.")
    parser.add_argument(
        "--page-break-before",
        action="append",
        default=[],
        metavar="BLOCK_LABEL",
        help="Repeatable visual-only override that starts a matching section, entry, or project label on a new page.",
    )
    parser.add_argument("--confirmed", action="store_true", help="Confirm the user approved this Markdown for final PDF generation.")
    parser.add_argument("--package", help="Required pdf_ready resume-package JSON that binds confirmation to this Markdown path and SHA-256.")
    parser.add_argument("--soffice", help="Optional PATH-resolved command name: soffice or libreoffice.")
    parser.add_argument("--weasyprint", help="Optional PATH-resolved WeasyPrint command name: weasyprint.")
    parser.add_argument("--pdftotext", help="Optional PATH-resolved pdftotext command name for validation.")
    parser.add_argument("--pdfinfo", help="Optional PATH-resolved pdfinfo command name for validation.")
    parser.add_argument("--pdftoppm", help="Optional PATH-resolved pdftoppm command name for validation.")
    parser.add_argument("--pdffonts", help="Optional PATH-resolved pdffonts command name for validation.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    command = "render_resume"
    try:
        args = parse_json_cli(build_parser(), argv)
        _validate_executable_override(args.soffice, ("soffice", "libreoffice"), "--soffice")
        _validate_executable_override(args.weasyprint, ("weasyprint",), "--weasyprint")
        _validate_executable_override(args.pdftotext, ("pdftotext",), "--pdftotext")
        _validate_executable_override(args.pdfinfo, ("pdfinfo",), "--pdfinfo")
        _validate_executable_override(args.pdftoppm, ("pdftoppm",), "--pdftoppm")
        _validate_executable_override(args.pdffonts, ("pdffonts",), "--pdffonts")
        input_path = Path(args.input)
        markdown = _check_input(input_path)
        checked_source_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        stem = _artifact_name(args.name, input_path)
        gate = _validate_pdf_gate(args.package, input_path, checked_source_hash) if args.confirmed else None
        output_root = _check_output_dir(Path(args.output_dir))
        source_hash = checked_source_hash
        output_dir = _create_version_directory(
            output_root,
            stem,
            source_hash,
            bool(args.confirmed),
            gate.get("package_sha256") if gate else None,
        )
        try:
            css = STYLE_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            raise CliFailure("TEMPLATE_ASSET_UNAVAILABLE", "Could not read the bundled resume stylesheet: {0}".format(exc), 2)
        rendered_html, title, matched_page_breaks = markdown_to_html(markdown, css, args.page_break_before)
        markdown_path = output_dir / (stem + ".md")
        html_path = output_dir / (stem + ".html")
        report_path = output_dir / (stem + ".render.json")
        _atomic_write_text(markdown_path, markdown)
        _atomic_write_text(html_path, rendered_html)

        soffice = resolve_command(args.soffice, ("soffice", "libreoffice"))
        weasyprint = resolve_command(args.weasyprint, ("weasyprint",))
        base: Dict[str, Any] = {
            "ok": True,
            "kind": "resume_render",
            "schema_version": "1.0",
            "confirmed": bool(args.confirmed),
            "pdf_gate": gate,
            "title": title,
            "source_markdown_sha256": source_hash,
            "output_root": str(output_root),
            "version_directory": str(output_dir.resolve()),
            "layout": {
                "page_break_before_requested": list(args.page_break_before),
                "page_break_before_matched": matched_page_breaks,
                "page_break_before_unmatched": [
                    item for item in args.page_break_before if item not in matched_page_breaks
                ],
            },
            "renderer": {
                "network_service_used": False,
                "preference_order": ["libreoffice", "weasyprint"],
                "selected": None,
                "fallback_used": False,
                "fallback_reason": None,
                "soffice": soffice,
                "weasyprint": weasyprint,
                "availability": {"libreoffice": bool(soffice), "weasyprint": bool(weasyprint)},
                "attempts": [],
                "details": None,
            },
            "artifacts": {
                "markdown": str(markdown_path.resolve()),
                "html": str(html_path.resolve()),
                "pdf": None,
                "validation_report": None,
                "visual_signoff": None,
                "render_report": str(report_path.resolve()),
            },
        }
        if not args.confirmed:
            base.update(
                {
                    "status": "awaiting_confirmation",
                    "pdf_attempted": False,
                    "pdf_qualified": False,
                    "delivery_blocked": True,
                    "degradation": None,
                    "next_action": "Ask the user to review this Markdown/HTML. Rerun with --confirmed only after explicit approval.",
                }
            )
            base["manifest"] = _manifest_for_paths(source_hash, base["artifacts"])
            atomic_write_json(report_path, base)
            emit(base)
            return 0

        if not soffice and not weasyprint:
            base["renderer"]["fallback_reason"] = "no_renderer_available"
            base.update(
                {
                    "ok": False,
                    "status": "degraded",
                    "pdf_attempted": False,
                    "pdf_qualified": False,
                    "delivery_blocked": True,
                    "degradation": {
                        "code": "PDF_RENDERER_UNAVAILABLE",
                        "message": "No local LibreOffice/soffice or WeasyPrint renderer is available; no PDF was generated.",
                        "preserved_artifacts": [str(markdown_path.resolve()), str(html_path.resolve())],
                    },
                    "next_action": "Deliver the confirmed Markdown and printable HTML explicitly as a degradation, or install a local LibreOffice/soffice or WeasyPrint renderer and retry.",
                }
            )
            base["manifest"] = _manifest_for_paths(source_hash, base["artifacts"])
            atomic_write_json(report_path, base)
            emit(base)
            return 3

        renderer_attempts: List[Dict[str, Any]] = base["renderer"]["attempts"]
        pdf_path: Optional[Path] = None
        if soffice:
            pdf_path, renderer_details = _render_with_libreoffice(soffice, html_path, output_dir, stem)
            renderer_attempts.append(renderer_details)
            if pdf_path:
                base["renderer"]["selected"] = "libreoffice"
            else:
                base["renderer"]["fallback_reason"] = "libreoffice_failed"
        else:
            base["renderer"]["fallback_reason"] = "libreoffice_unavailable"

        if not pdf_path and weasyprint:
            pdf_path, renderer_details = _render_with_weasyprint(weasyprint, html_path, output_dir, stem)
            renderer_attempts.append(renderer_details)
            if pdf_path:
                base["renderer"]["selected"] = "weasyprint"
                base["renderer"]["fallback_used"] = True

        base["pdf_attempted"] = bool(renderer_attempts)
        if renderer_attempts:
            base["renderer"]["details"] = renderer_attempts[-1]
        if not pdf_path:
            base.update(
                {
                    "ok": False,
                    "status": "degraded",
                    "pdf_qualified": False,
                    "delivery_blocked": True,
                    "degradation": {
                        "code": "PDF_RENDER_FAILED",
                        "message": "No available local renderer produced a PDF; Markdown and printable HTML remain available.",
                        "preserved_artifacts": [str(markdown_path.resolve()), str(html_path.resolve())],
                    },
                    "next_action": "Inspect renderer attempts and local diagnostics, then retry; do not claim that a PDF was delivered.",
                }
            )
            base["manifest"] = _manifest_for_paths(source_hash, base["artifacts"])
            atomic_write_json(report_path, base)
            emit(base)
            return 4

        base["artifacts"]["pdf"] = str(pdf_path.resolve())
        validation = validate_pdf_artifact(
            pdf_path,
            output_dir,
            stem,
            source_markdown=markdown,
            pdftotext_request=args.pdftotext,
            pdfinfo_request=args.pdfinfo,
            pdftoppm_request=args.pdftoppm,
            pdffonts_request=args.pdffonts,
            source_markdown_path=markdown_path,
        )
        validation_path = output_dir / (stem + ".validation.json")
        atomic_write_json(validation_path, validation)
        base["artifacts"]["validation_report"] = str(validation_path.resolve())
        base["artifacts"]["page_pngs"] = validation.get("artifacts", {}).get("page_pngs", [])
        base["artifacts"]["grayscale_pngs"] = validation.get("artifacts", {}).get("grayscale_pngs", [])
        base["validation"] = validation
        base["pdf_qualified"] = bool(validation["qualified"])
        base["automatic_qualified"] = bool(validation.get("automatic_qualified"))
        base["visual_signoff_pending"] = bool(validation.get("visual_signoff_pending"))
        base["delivery_blocked"] = not bool(validation["qualified"])
        base["degradation"] = None
        if validation["qualified"]:
            base["status"] = "qualified"
            base["next_action"] = "The current PDF is fully qualified and may be delivered."
            exit_code = 0
        elif validation["status"] == "visual_signoff_pending":
            base["status"] = "visual_signoff_pending"
            base["next_action"] = validation["next_action"]
            exit_code = 0
        elif validation["status"] == "capability_unavailable":
            base["ok"] = False
            base["status"] = "degraded"
            base["degradation"] = {
                "code": "PDF_VALIDATION_CAPABILITY_UNAVAILABLE",
                "message": "A PDF was rendered but cannot be called qualified because required local validation capabilities are missing.",
                "preserved_artifacts": [str(markdown_path.resolve()), str(html_path.resolve())],
            }
            base["next_action"] = "Deliver Markdown and printable HTML as the qualified fallback; do not call the unvalidated PDF delivery-ready."
            exit_code = 3
        else:
            base["ok"] = False
            base["status"] = "validation_failed"
            base["next_action"] = "Correct every PDF validation error and rerun; until then, only Markdown and printable HTML are valid fallback artifacts."
            exit_code = 1
        base["manifest"] = _manifest_for_paths(source_hash, base["artifacts"])
        atomic_write_json(report_path, base)
        emit(base)
        return exit_code
    except CliFailure as failure:
        return emit_failure(failure, command)


if __name__ == "__main__":
    sys.exit(main())
