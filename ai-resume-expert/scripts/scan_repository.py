#!/usr/bin/env python3
"""Safely extract project-fact candidates from an authorized local repository.

The scanner is static and read-only.  It never imports project modules, starts
processes, invokes build/test tools, opens network connections, or modifies the
target.  Git metadata is excluded unless *both* Git-specific flags are passed;
even then only a redacted reflog summary is returned as an unconfirmed clue.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from _json_cli import CliFailure, JsonArgumentParser, emit, emit_failure, parse_json_cli


DEFAULT_MAX_FILE_BYTES = 512 * 1024
DEFAULT_MAX_FILES = 500

SKIPPED_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".gradle",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "bin",
    "bower_components",
    "build",
    "coverage",
    "data",
    "dataset",
    "datasets",
    "deriveddata",
    "dist",
    "dump",
    "dumps",
    "node_modules",
    "obj",
    "out",
    "pods",
    "target",
    "vendor",
    "venv",
}

SENSITIVE_SUFFIXES = {
    ".cer",
    ".crt",
    ".der",
    ".jks",
    ".key",
    ".keystore",
    ".kdbx",
    ".p12",
    ".pem",
    ".pfx",
}

BINARY_OR_DATA_SUFFIXES = {
    ".7z",
    ".a",
    ".avi",
    ".bin",
    ".class",
    ".csv",
    ".db",
    ".dmg",
    ".dll",
    ".doc",
    ".docx",
    ".dump",
    ".dylib",
    ".exe",
    ".feather",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".lockb",
    ".mov",
    ".mp3",
    ".mp4",
    ".o",
    ".parquet",
    ".pdf",
    ".png",
    ".pyc",
    ".rar",
    ".so",
    ".sqlite",
    ".sqlite3",
    ".tsv",
    ".tar",
    ".tiff",
    ".wav",
    ".webp",
    ".xls",
    ".xlsx",
    ".xz",
    ".zip",
    ".jsonl",
    ".ndjson",
}

TEXT_SUFFIXES = {
    ".adoc",
    ".c",
    ".cc",
    ".cfg",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".dart",
    ".ex",
    ".exs",
    ".go",
    ".gradle",
    ".graphql",
    ".groovy",
    ".h",
    ".hpp",
    ".htm",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".kts",
    ".less",
    ".lua",
    ".md",
    ".m",
    ".mjs",
    ".mm",
    ".php",
    ".plist",
    ".properties",
    ".proto",
    ".ps1",
    ".py",
    ".rb",
    ".rs",
    ".rst",
    ".sass",
    ".scala",
    ".scss",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}

KNOWN_TEXT_NAMES = {
    "build.gradle",
    "build.gradle.kts",
    "cargo.toml",
    "cmakelists.txt",
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
    "dockerfile",
    "gemfile",
    "go.mod",
    "makefile",
    "package.json",
    "podfile",
    "pom.xml",
    "pyproject.toml",
    "requirements.txt",
}

LANGUAGES = {
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cs": "C#",
    ".dart": "Dart",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".go": "Go",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".m": "Objective-C",
    ".mm": "Objective-C++",
    ".php": "PHP",
    ".py": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".scala": "Scala",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
}

TECHNOLOGY_PATTERNS = {
    "Docker": re.compile(r"(?:\bFROM\s+[A-Za-z0-9._/-]+|docker[- ]compose|\bdockerfile\b)", re.IGNORECASE),
    "Kubernetes": re.compile(r"(?:apiVersion\s*:\s*(?:apps|batch|v1)|\bkind\s*:\s*(?:Deployment|Service|StatefulSet|Job))", re.IGNORECASE),
    "Spring Boot": re.compile(r"(?:spring-boot|org\.springframework\.boot)", re.IGNORECASE),
    "React": re.compile(r"(?:\bfrom\s+['\"]react['\"]|['\"]react['\"]\s*:)", re.IGNORECASE),
    "Vue.js": re.compile(r"(?:\bvue\b|createApp\s*\()", re.IGNORECASE),
    "PostgreSQL": re.compile(r"(?:postgresql|\bpostgres\b|org\.postgresql)", re.IGNORECASE),
    "Redis": re.compile(r"(?:\bredis\b|lettuce-core|jedis)", re.IGNORECASE),
    "Kafka": re.compile(r"(?:apache\.kafka|spring-kafka|\bkafka\b)", re.IGNORECASE),
    "OpenAI-compatible API": re.compile(r"(?:openai|chat/completions|responses\.create)", re.IGNORECASE),
    "pytest": re.compile(r"(?:\bpytest\b|@pytest\.)", re.IGNORECASE),
    "JUnit": re.compile(r"(?:org\.junit|junit-jupiter|@Test\b)", re.IGNORECASE),
}

SENSITIVE_NAME_RE = re.compile(
    r"(?:^|[._-])(?:credential|credentials|password|passwd|secret|secrets|token|private[-_]?key)(?:$|[._-])",
    re.IGNORECASE,
)
PRIVATE_KEY_CONTENT_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE)
CREDENTIAL_CONTENT_RE = re.compile(
    r"(?:\b(?:api[_-]?key|access[_-]?key|client[_-]?secret|credential|password|passwd|private[_-]?key|secret|token)\b"
    r"\s*[:=]\s*['\"]?[^\s'\"${}]{6,}|\bAuthorization\s*:\s*(?:Bearer|Basic)\s+\S{6,})",
    re.IGNORECASE,
)
EMAIL_CONTENT_RE = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])")
PHONE_CONTENT_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
IDENTITY_CONTENT_RE = re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")


def relative_display(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix() or "."
    except ValueError:
        return "<outside-root>"


def is_sensitive_file(path: Path) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name == ".env" or name.startswith(".env."):
        return True
    if suffix in SENSITIVE_SUFFIXES:
        return True
    if name in {"id_rsa", "id_dsa", "id_ed25519", "authorized_keys", "known_hosts"}:
        return True
    if name in {".npmrc", ".pypirc", "settings.xml", "application-prod.yml", "application-prod.yaml", "application-prod.properties"}:
        return True
    if re.search(r"(?:^|[._-])(?:prod|production)(?:$|[._-])", name) and suffix in {".json", ".properties", ".toml", ".yaml", ".yml"}:
        return True
    return bool(SENSITIVE_NAME_RE.search(name))


def classify_scope(path: Path) -> str:
    rel_lower = path.as_posix().lower()
    name = path.name.lower()
    if any(part in {"test", "tests", "spec", "specs", "__tests__"} for part in path.parts):
        return "tests"
    if name.startswith("dockerfile") or "compose" in name:
        return "container_configuration"
    if ".github/workflows" in rel_lower or name in {".gitlab-ci.yml", "jenkinsfile"}:
        return "ci_configuration"
    if name in KNOWN_TEXT_NAMES or name.endswith((".gradle", ".gradle.kts")):
        return "dependencies_or_build_manifest"
    if "architecture" in rel_lower or "design" in rel_lower or "adr" in path.parts:
        return "architecture_documentation"
    if name.startswith("readme") or path.suffix.lower() in {".md", ".rst", ".adoc"}:
        return "documentation"
    if path.suffix.lower() in LANGUAGES:
        return "source"
    return "ordinary_configuration"


def safe_path_hint(relative: str) -> str:
    """Return a useful but confidentiality-safe locator.

    Source/class/document basenames often contain internal project or customer
    identifiers. Only standardized public filenames remain visible; all other
    paths are replaced by a scoped, one-way locator and file suffix.
    """

    path = Path(relative)
    name = path.name
    lower_name = name.lower()
    digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:12]
    if lower_name in KNOWN_TEXT_NAMES or lower_name.startswith("readme"):
        return "{0}#{1}".format(name, digest)
    scope = classify_scope(path).replace("_", "-")
    suffix = path.suffix.lower()
    safe_suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ""
    return "<{0}:{1}{2}>".format(scope, digest, safe_suffix)


def content_sensitive_reason(text: str) -> Optional[str]:
    """Classify sensitive content without returning or retaining its value."""

    if PRIVATE_KEY_CONTENT_RE.search(text):
        return "private_key_content"
    if CREDENTIAL_CONTENT_RE.search(text):
        return "credential_content"
    if EMAIL_CONTENT_RE.search(text):
        return "personal_email_content"
    if PHONE_CONTENT_RE.search(text) or IDENTITY_CONTENT_RE.search(text):
        return "personal_identity_content"
    return None


def append_example(examples: DefaultDict[str, List[str]], reason: str, value: str) -> None:
    bucket = examples[reason]
    if value not in bucket and len(bucket) < 8:
        bucket.append(value)


def safe_read_text(path: Path, maximum: int) -> Tuple[Optional[str], Optional[str], int]:
    """Return decoded text, skip reason, and bytes read without following links."""

    try:
        if path.is_symlink():
            return None, "symlink", 0
        stat = path.stat()
        if not path.is_file():
            return None, "not_regular_file", 0
        if stat.st_size > maximum:
            return None, "large_file", 0
        if path.suffix.lower() in BINARY_OR_DATA_SUFFIXES:
            return None, "binary_or_data", 0
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name.lower() not in KNOWN_TEXT_NAMES:
            return None, "unsupported_type", 0
        with path.open("rb") as handle:
            payload = handle.read(maximum + 1)
        if len(payload) > maximum:
            return None, "large_file", 0
        if b"\x00" in payload[:8192]:
            return None, "binary_or_data", 0
        try:
            return payload.decode("utf-8-sig"), None, len(payload)
        except UnicodeDecodeError:
            try:
                return payload.decode("gb18030"), None, len(payload)
            except UnicodeDecodeError:
                return payload.decode("utf-8", errors="replace"), "decoded_with_replacement", len(payload)
    except PermissionError:
        return None, "permission_denied", 0
    except OSError:
        return None, "read_error", 0


def iter_repository_files(root: Path) -> Iterable[Tuple[Path, int]]:
    """Yield files and directory count increments in a deterministic order."""

    if root.is_file() or root.is_symlink():
        yield root, 0
        return
    for current, directories, files in os.walk(str(root), topdown=True, followlinks=False):
        current_path = Path(current)
        directories.sort()
        files.sort()
        kept: List[str] = []
        for directory in directories:
            if directory.lower() not in SKIPPED_DIRECTORY_NAMES:
                kept.append(directory)
        directories[:] = kept
        for name in files:
            yield current_path / name, 1


def make_fact(fact_id: str, category: str, statement: str, sources: List[str]) -> Dict[str, Any]:
    return {
        "id": fact_id,
        "category": category,
        "statement": statement,
        "confidence": "observed",
        "source_hints": sources[:8],
        "evidence_status": "observed_project_fact",
        "ownership_status": "pending_confirmation",
        "disclosure_status": "review_required",
        "resume_eligible": False,
    }


def evidence_record_from_fact(fact: Dict[str, Any]) -> Dict[str, Any]:
    """Map a human scan finding to the canonical evidence-record schema."""

    source_type = "project_document" if fact.get("category") in {"documentation", "engineering"} else "code"
    sources = [
        {
            "source_id": "{0}-source-{1}".format(fact["id"], index),
            "type": source_type,
            "locator": locator,
        }
        for index, locator in enumerate(fact.get("source_hints", []), start=1)
    ]
    return {
        "id": fact["id"],
        "fact_type": "project_fact",
        "statement": fact["statement"],
        "status": "observed_project_fact",
        "resume_eligible": False,
        "sources": sources,
        "ownership": {"status": "pending", "confirmed_by_user": False},
        "disclosure": {"status": "unknown", "confirmed_by_user": False},
        "conflict": {"status": "none"},
        "tags": [str(fact.get("category") or "project")],
    }


def read_git_hints(root: Path, maximum_bytes: int) -> Dict[str, Any]:
    if not root.is_dir():
        return {"status": "unavailable", "reason": "target_is_not_a_repository_directory", "clue_only": True}
    git_entry = root / ".git"
    if git_entry.is_file():
        return {
            "status": "unavailable",
            "reason": "git_worktree_pointer_not_followed",
            "clue_only": True,
        }
    log_path = git_entry / "logs" / "HEAD"
    try:
        resolved = log_path.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return {"status": "unavailable", "reason": "git_log_outside_target_or_unreadable", "clue_only": True}
    if log_path.is_symlink() or not log_path.is_file():
        return {"status": "unavailable", "reason": "git_head_log_not_found", "clue_only": True}
    try:
        size = log_path.stat().st_size
        if size > maximum_bytes:
            return {"status": "sampled", "reason": "git_head_log_too_large", "clue_only": True}
        data = log_path.read_bytes()
    except (OSError, PermissionError):
        return {"status": "unavailable", "reason": "git_head_log_unreadable", "clue_only": True}
    text = data.decode("utf-8", errors="replace")
    lines = [line for line in text.splitlines() if line.strip()]
    categories: Counter[str] = Counter()
    allowed_categories = {"build", "chore", "ci", "docs", "feat", "fix", "perf", "refactor", "test"}
    for line in lines:
        message = line.split("\t", 1)[1] if "\t" in line else ""
        prefix_match = re.match(r"([a-z]+)(?:\([^)]*\))?!?:", message.strip(), re.IGNORECASE)
        if prefix_match:
            category = prefix_match.group(1).lower()
            if category in allowed_categories:
                categories[category] += 1
    return {
        "status": "available",
        "source_hint": ".git/logs/HEAD",
        "local_reflog_entries": len(lines),
        "conventional_change_categories": dict(sorted(categories.items())),
        "redactions": ["commit hashes", "authors", "emails", "commit messages"],
        "clue_only": True,
        "ownership_status": "pending_confirmation",
        "note": "Git metadata can suggest follow-up questions but does not prove personal contribution.",
    }


def scan(root: Path, max_file_bytes: int, max_files: int, include_git: bool) -> Dict[str, Any]:
    if not root.exists():
        raise CliFailure("TARGET_NOT_FOUND", "Target path does not exist: {0}".format(root), 2)
    if root.is_symlink():
        raise CliFailure("SYMLINK_TARGET_REFUSED", "Repository root cannot be a symbolic link.", 2)
    try:
        resolved_root = root.resolve()
    except OSError as exc:
        raise CliFailure("TARGET_UNREADABLE", "Could not resolve target path: {0}".format(exc), 2)
    skip_counts: Counter[str] = Counter()
    skip_examples: DefaultDict[str, List[str]] = defaultdict(list)
    scope_counts: Counter[str] = Counter()
    language_counts: Counter[str] = Counter()
    language_sources: DefaultDict[str, List[str]] = defaultdict(list)
    technology_sources: DefaultDict[str, List[str]] = defaultdict(list)
    documentation_sources: List[str] = []
    test_sources: List[str] = []
    manifest_sources: List[str] = []
    container_sources: List[str] = []
    ci_sources: List[str] = []
    viewed_paths: List[str] = []
    fingerprint_rows: List[str] = []
    files_seen = 0
    files_opened = 0
    files_read = 0
    bytes_read = 0
    directories_seen: Set[str] = set()

    # Record excluded directories without entering them. This second pass only
    # looks at directory entry names and never reads their contents.
    if resolved_root.is_dir():
        for current, directories, _files in os.walk(str(resolved_root), topdown=True, followlinks=False):
            directories.sort()
            current_path = Path(current)
            directories_seen.add(relative_display(current_path, resolved_root))
            kept: List[str] = []
            for directory in directories:
                candidate = current_path / directory
                if directory.lower() in SKIPPED_DIRECTORY_NAMES:
                    skip_counts["excluded_directory"] += 1
                    append_example(skip_examples, "excluded_directory", "<excluded-directory:{0}>".format(directory.lower()))
                elif candidate.is_symlink():
                    skip_counts["symlink_directory"] += 1
                    append_example(skip_examples, "symlink_directory", "<symlink-directory>")
                else:
                    kept.append(directory)
            directories[:] = kept

    for path, _directory_increment in iter_repository_files(resolved_root):
        files_seen += 1
        relative = relative_display(path, resolved_root if resolved_root.is_dir() else resolved_root.parent)
        if is_sensitive_file(path):
            skip_counts["sensitive_file"] += 1
            append_example(skip_examples, "sensitive_file", "<redacted-sensitive-path>")
            continue
        if files_opened >= max_files:
            skip_counts["scan_file_limit"] += 1
            append_example(skip_examples, "scan_file_limit", safe_path_hint(relative))
            continue
        text, skip_reason, size = safe_read_text(path, max_file_bytes)
        if text is None:
            reason = skip_reason or "read_error"
            skip_counts[reason] += 1
            shown = "<redacted-sensitive-path>" if reason == "sensitive_file" else safe_path_hint(relative)
            append_example(skip_examples, reason, shown)
            continue
        files_opened += 1
        bytes_read += size
        if skip_reason == "decoded_with_replacement":
            skip_counts[skip_reason] += 1
            append_example(skip_examples, skip_reason, safe_path_hint(relative))
        sensitive_reason = content_sensitive_reason(text)
        if sensitive_reason:
            skip_counts["content_sensitive"] += 1
            skip_counts[sensitive_reason] += 1
            append_example(skip_examples, "content_sensitive", "<redacted-content-sensitive-path>")
            continue
        files_read += 1
        scope = classify_scope(Path(relative))
        scope_counts[scope] += 1
        source_hint = safe_path_hint(relative)
        if len(viewed_paths) < 120:
            viewed_paths.append(source_hint)
        fingerprint_rows.append("{0}:{1}".format(relative, size))
        suffix = path.suffix.lower()
        if suffix in LANGUAGES:
            language = LANGUAGES[suffix]
            language_counts[language] += 1
            if len(language_sources[language]) < 8:
                language_sources[language].append(source_hint)
        if scope in {"documentation", "architecture_documentation"} and len(documentation_sources) < 8:
            documentation_sources.append(source_hint)
        if scope == "tests" and len(test_sources) < 8:
            test_sources.append(source_hint)
        if scope == "dependencies_or_build_manifest" and len(manifest_sources) < 8:
            manifest_sources.append(source_hint)
        if scope == "container_configuration" and len(container_sources) < 8:
            container_sources.append(source_hint)
        if scope == "ci_configuration" and len(ci_sources) < 8:
            ci_sources.append(source_hint)
        for technology, pattern in TECHNOLOGY_PATTERNS.items():
            if pattern.search(text) and len(technology_sources[technology]) < 8 and source_hint not in technology_sources[technology]:
                technology_sources[technology].append(source_hint)

    facts: List[Dict[str, Any]] = []
    for index, (language, count) in enumerate(language_counts.most_common(), start=1):
        facts.append(
            make_fact(
                "pf-language-{0}".format(index),
                "technology",
                "仓库包含 {0} 源文件；这只说明项目技术构成，不证明个人贡献。".format(language),
                language_sources[language],
            )
        )
    for index, technology in enumerate(sorted(technology_sources), start=1):
        facts.append(
            make_fact(
                "pf-technology-{0}".format(index),
                "technology",
                "静态材料中检测到 {0} 使用线索；需结合文档并由使用者确认参与边界。".format(technology),
                technology_sources[technology],
            )
        )
    if documentation_sources:
        facts.append(make_fact("pf-documentation", "documentation", "仓库包含可用于了解项目边界的项目文档。", documentation_sources))
    if test_sources:
        facts.append(make_fact("pf-tests", "quality", "仓库包含测试相关文件；测试存在不证明使用者设计或实现了这些测试。", test_sources))
    if manifest_sources:
        facts.append(make_fact("pf-manifests", "engineering", "仓库包含依赖或构建清单，可用于核对项目技术选型。", manifest_sources))
    if container_sources:
        facts.append(make_fact("pf-containers", "delivery", "仓库包含容器化配置线索；需确认使用者是否参与相关交付工作。", container_sources))
    if ci_sources:
        facts.append(make_fact("pf-ci", "delivery", "仓库包含持续集成配置线索；需确认使用者是否参与流水线建设。", ci_sources))

    candidates = [
        {
            "project_fact_id": fact["id"],
            "status": "pending_confirmation",
            "ownership_confirmed": False,
            "candidate_only": True,
            "question": "请确认你在该项目事实中的个人角色、具体行动和真实结果；若没有直接贡献，可以全部否定。",
        }
        for fact in facts
    ]

    git_hints = read_git_hints(resolved_root, max_file_bytes) if include_git else {
        "status": "not_read",
        "reason": "git_authorization_not_requested",
        "clue_only": True,
    }
    if include_git and git_hints.get("status") == "available":
        candidates.append(
            {
                "project_fact_id": "git-history-clue",
                "status": "pending_confirmation",
                "ownership_confirmed": False,
                "candidate_only": True,
                "question": "Git 线索不能证明个人贡献。请由你确认实际参与的变更、角色和结果。",
            }
        )

    digest = hashlib.sha256("\n".join(sorted(fingerprint_rows)).encode("utf-8")).hexdigest()
    evidence_records = [evidence_record_from_fact(fact) for fact in facts]
    return {
        "ok": True,
        "kind": "repository_static_scan",
        "schema_version": "1.0",
        "authorization": {
            "material_processing_confirmed": True,
            "platform_boundary_notice": "本地路径不等于仅在本机处理；材料处理仍受当前 Agent 平台的数据政策约束。",
        },
        "safety": {
            "mode": "static_read_only",
            "executed_code": False,
            "ran_builds": False,
            "ran_tests": False,
            "ran_scripts": False,
            "ran_containers": False,
            "used_network": False,
            "modified_target": False,
            "copied_source_text_to_output": False,
            "git_history_read": bool(include_git),
        },
        "project_facts": facts,
        "evidence_records": evidence_records,
        "contribution_candidates": candidates,
        "git_hints": git_hints,
        "scan_coverage": {
            "target_type": "directory" if resolved_root.is_dir() else "file",
            "scan_strategy": "bounded_static_scan",
            "complete_full_repository_claim": False,
            "files_seen_in_included_directories": files_seen,
            "files_opened_for_static_inspection": files_opened,
            "files_read": files_read,
            "bytes_read": bytes_read,
            "directories_seen": len(directories_seen),
            "max_files": max_files,
            "max_file_bytes": max_file_bytes,
            "file_limit_reached": skip_counts.get("scan_file_limit", 0) > 0,
            "read_scope_counts": dict(sorted(scope_counts.items())),
            "viewed_paths": viewed_paths,
            "viewed_paths_truncated": files_read > len(viewed_paths),
            "skipped_counts": dict(sorted(skip_counts.items())),
            "skipped_examples": dict(sorted(skip_examples.items())),
            "unreadable_count": sum(skip_counts.get(key, 0) for key in ("permission_denied", "read_error")),
            "coverage_statement": "仅对上述已查看文件做静态分析；跳过项和未读区域不属于已审查范围。",
            "scan_fingerprint": digest,
        },
        "required_next_step": "在任何项目事实进入简历前，由使用者确认个人角色、行动、结果与可披露边界。",
    }


def build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(description="Statically scan an authorized repository without executing it.")
    parser.add_argument("target", help="Repository directory or single project document to inspect.")
    parser.add_argument(
        "--authorized",
        action="store_true",
        help="Confirm the user is authorized to let the current AI environment process this material.",
    )
    parser.add_argument(
        "--include-git-hints",
        action="store_true",
        help="Request a redacted local Git reflog summary. This does not prove contribution.",
    )
    parser.add_argument(
        "--git-authorized",
        action="store_true",
        help="Separate confirmation that Git metadata may be read.",
    )
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES, help="Maximum number of eligible files to read.")
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=DEFAULT_MAX_FILE_BYTES,
        help="Maximum bytes read from any one file.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    command = "scan_repository"
    try:
        args = parse_json_cli(build_parser(), argv)
        # Authorization is checked before resolving, listing, or opening target.
        if not args.authorized:
            raise CliFailure(
                "MATERIAL_AUTHORIZATION_REQUIRED",
                "No files were read. Confirm authorization with --authorized after explaining the current platform data boundary.",
                2,
            )
        if args.include_git_hints and not args.git_authorized:
            raise CliFailure(
                "GIT_AUTHORIZATION_REQUIRED",
                "No files were read. --include-git-hints also requires the independent --git-authorized flag.",
                2,
            )
        if args.git_authorized and not args.include_git_hints:
            raise CliFailure(
                "INVALID_GIT_FLAGS",
                "--git-authorized has no effect without --include-git-hints; pass both or neither.",
                2,
            )
        if args.max_files < 1 or args.max_files > 10000:
            raise CliFailure("INVALID_LIMIT", "--max-files must be between 1 and 10000.", 2)
        if args.max_file_bytes < 1024 or args.max_file_bytes > 10 * 1024 * 1024:
            raise CliFailure("INVALID_LIMIT", "--max-file-bytes must be between 1024 and 10485760.", 2)
        result = scan(Path(args.target), args.max_file_bytes, args.max_files, args.include_git_hints)
        emit(result)
        return 0
    except CliFailure as failure:
        return emit_failure(failure, command)


if __name__ == "__main__":
    sys.exit(main())
