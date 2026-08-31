from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator


SKILL = "java-code-to-erd"
SCHEMA_VERSION = "1.0"
RULE_VERSION = "1.2.0"
RELATION_SOURCES = {
    "DDL_FOREIGN_KEY", "ORM_RELATION", "RESULT_MAPPING", "SQL_JOIN",
    "SQL_COLUMN_COMPARISON", "CODE_INFERRED", "NAMING_CANDIDATE",
    "USER_CONFIRMED", "OBJECT_DEPENDENCY",
}
EXCLUDED_DIRS = {
    ".git", ".idea", ".vscode", ".gradle", ".mvn", "node_modules", "vendor",
    "target", "build", "out", "dist", "generated", "reports", "data", ".codex",
    ".agents", ".agent", ".claude", ".pi", "examples", "samples",
}
SILENT_GENERATED_DIRS = {"reports", "data"}
SUPPORTED_SUFFIXES = {".java", ".xml", ".sql", ".ddl", ".yml", ".yaml", ".json", ".properties"}
SQL_WORDS = re.compile(r"\b(select|insert\s+into|update|delete\s+from|merge\s+into|call|create\s+(?:or\s+replace\s+)?(?:table|view|materialized\s+view)|alter\s+table|drop\s+table)\b", re.I)
IDENT = r'(?:(?:"[^"]+")|(?:`[^`]+`)|(?:\[[^\]]+\])|(?:[A-Za-z_][\w$#]*))'
QUALIFIED = rf'{IDENT}(?:\s*\.\s*{IDENT}){{0,2}}'


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "\x1f".join("" if p is None else str(p) for p in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def reject_symlink_components(root: Path, target: Path) -> None:
    root = root.resolve()
    absolute = target.absolute()
    try:
        relative = absolute.relative_to(root)
    except ValueError:
        if target.is_symlink():
            raise ValueError(f"Refusing symbolic-link output path: {target}")
        return
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Refusing symbolic-link output component: {current}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strip_identifier(value: str) -> str:
    value = re.sub(r"\s+", "", value.strip())
    parts = []
    for part in value.split("."):
        if len(part) >= 2 and ((part[0] == part[-1] == '"') or (part[0] == '`' and part[-1] == '`') or (part[0] == '[' and part[-1] == ']')):
            part = part[1:-1]
        parts.append(part)
    return ".".join(parts)


def split_name(value: str) -> tuple[str | None, str]:
    clean = strip_identifier(value)
    parts = clean.split(".")
    return (parts[-2], parts[-1]) if len(parts) >= 2 else (None, parts[-1])


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def line_range(text: str, start: int, end: int) -> tuple[int, int]:
    return line_number(text, start), line_number(text, end)


def evidence(path: str, start: int, end: int, source: str) -> dict[str, Any]:
    ev_id = stable_id("ev", path, start, end, source)
    return {"id": ev_id, "file": path, "startLine": max(1, start), "endLine": max(start, end), "sourceType": source}


def default_column(name: str, ev_id: str | None = None, **updates: Any) -> dict[str, Any]:
    result = {
        "id": "", "name": name, "javaName": None, "javaType": None, "databaseType": None,
        "primaryKey": False, "unique": False, "nullable": None, "default": None,
        "generated": None, "usages": [], "evidenceIds": [ev_id] if ev_id else [],
    }
    result.update(updates)
    return result


@dataclass
class Fragment:
    file: str
    content_hash: str
    observations: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)

    def json(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION, "file": self.file, "contentHash": self.content_hash,
            "ruleVersion": RULE_VERSION, "observations": self.observations, "unresolved": self.unresolved,
        }


class Facts:
    def __init__(self) -> None:
        self.evidence: dict[str, dict[str, Any]] = {}
        self.objects: dict[tuple[str | None, str], dict[str, Any]] = {}
        self.code_objects: dict[str, dict[str, Any]] = {}
        self.mappings: list[dict[str, Any]] = []
        self.operations: list[dict[str, Any]] = []
        self.relation_observations: list[dict[str, Any]] = []
        self.ddl_events: list[dict[str, Any]] = []
        self.deleted_objects: dict[tuple[str | None, str], str] = {}
        self.deleted_columns: set[tuple[str | None, str, str]] = set()
        self.unresolved: list[dict[str, Any]] = []

    def add_evidence(self, ev: dict[str, Any]) -> str:
        self.evidence[ev["id"]] = ev
        return ev["id"]

    def object_key(self, schema: str | None, name: str) -> tuple[str | None, str]:
        return (schema.lower() if schema else None, name.lower())

    def add_object(self, name: str, schema: str | None, ev_id: str, source: str, object_type: str = "TABLE", dynamic: str | None = None) -> dict[str, Any]:
        key = self.object_key(schema, name)
        obj = self.objects.get(key)
        if obj is None:
            obj = {
                "name": name, "schema": schema, "objectType": object_type, "sources": set(),
                "evidenceIds": set(), "columns": {}, "primaryKeys": [], "uniqueConstraints": [],
                "indexes": [], "historicalNames": [], "possibleNames": [], "synonyms": [],
                "dynamicPattern": dynamic,
            }
            self.objects[key] = obj
        obj["sources"].add(source)
        obj["evidenceIds"].add(ev_id)
        if obj["objectType"] == "UNKNOWN" and object_type != "UNKNOWN":
            obj["objectType"] = object_type
        return obj

    def add_column(self, obj: dict[str, Any], column: dict[str, Any]) -> dict[str, Any]:
        key = column["name"].lower()
        current = obj["columns"].get(key)
        if current is None:
            current = default_column(column["name"])
            obj["columns"][key] = current
        for field_name in ("javaName", "javaType", "databaseType", "default", "generated"):
            if column.get(field_name) is not None:
                current[field_name] = column[field_name]
        for field_name in ("primaryKey", "unique"):
            current[field_name] = bool(current[field_name] or column.get(field_name))
        if column.get("nullable") is not None:
            current["nullable"] = column["nullable"]
        current["usages"] = sorted(set(current["usages"]) | set(column.get("usages", [])))
        current["evidenceIds"] = sorted(set(current["evidenceIds"]) | set(column.get("evidenceIds", [])))
        return current


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def project_id(root: Path) -> str:
    return stable_id("project", root.resolve().as_posix())


def is_test_path(rel: Path) -> bool:
    parts = [p.lower() for p in rel.parts]
    return "test" in parts or "tests" in parts or any(p.startswith("src-test") for p in parts)


def discover_files(root: Path, include_tests: bool = False) -> tuple[list[Path], list[dict[str, str]]]:
    found: list[Path] = []
    skipped: list[dict[str, str]] = []
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        rel_dir = current_path.relative_to(root)
        kept_dirs = []
        for dirname in sorted(dirs):
            child_rel = rel_dir / dirname
            child_path = current_path / dirname
            external_link = False
            if child_path.is_symlink():
                try:
                    child_path.resolve().relative_to(root.resolve())
                except ValueError:
                    external_link = True
            if external_link:
                skipped.append({"file": child_rel.as_posix(), "reason": "external symlink"})
            elif dirname.lower() in EXCLUDED_DIRS or (not include_tests and is_test_path(child_rel)):
                if dirname.lower() not in SILENT_GENERATED_DIRS:
                    skipped.append({"file": child_rel.as_posix(), "reason": "excluded directory"})
            else:
                kept_dirs.append(dirname)
        dirs[:] = kept_dirs
        for filename in sorted(files):
            path = current_path / filename
            rel = path.relative_to(root)
            if path.is_symlink():
                try:
                    path.resolve().relative_to(root.resolve())
                except ValueError:
                    skipped.append({"file": rel.as_posix(), "reason": "external symlink"})
                    continue
            if not include_tests and is_test_path(rel):
                skipped.append({"file": rel.as_posix(), "reason": "test source excluded"})
                continue
            lower = filename.lower()
            if path.suffix.lower() in SUPPORTED_SUFFIXES or lower in {"pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"}:
                found.append(path)
    return sorted(found, key=lambda p: p.relative_to(root).as_posix()), skipped


TECH_MARKERS = {
    "JPA_HIBERNATE": ("jakarta.persistence", "javax.persistence", "spring-boot-starter-data-jpa", "hibernate-core", "@Entity"),
    "MYBATIS": ("org.mybatis", "mybatis-spring", "<mapper", "@Select", "@Mapper"),
    "MYBATIS_PLUS": ("mybatis-plus", "@TableName", "QueryWrapper", "LambdaQueryWrapper"),
    "JDBC_TEMPLATE": ("JdbcTemplate", "NamedParameterJdbcTemplate", "spring-jdbc"),
    "JDBC": ("java.sql.Connection", "PreparedStatement", "ResultSet"),
    "FLYWAY": ("flyway-core", "db/migration",),
    "LIQUIBASE": ("liquibase-core", "databaseChangeLog",),
    "JOOQ_UNSUPPORTED": ("org.jooq", "jooq-codegen"),
    "JDBI_UNSUPPORTED": ("org.jdbi",),
    "EBEAN_UNSUPPORTED": ("io.ebean",),
    "SPRING_DATA_JDBC_UNSUPPORTED": ("spring-data-jdbc",),
    "R2DBC_UNSUPPORTED": ("io.r2dbc", "spring-data-r2dbc"),
    "REFLECTION_DATA_ACCESS_UNSUPPORTED": ("Class.forName(", "getDeclaredMethod(", "java.lang.reflect"),
    "BYTECODE_GENERATION_UNSUPPORTED": ("net.bytebuddy", "byte-buddy", "javassist", "cglib"),
    "EXTERNAL_CONFIG_UNSUPPORTED": ("spring.cloud.config", "spring-cloud-config", "nacos", "apollo.meta"),
}


def detect_technologies(files: list[Path]) -> list[str]:
    hits: set[str] = set()
    for path in files:
        if path.stat().st_size > 2_000_000:
            continue
        text = read_text(path)
        rel = path.as_posix().lower()
        for tech, markers in TECH_MARKERS.items():
            if any(marker.lower() in text.lower() or marker.lower() in rel for marker in markers):
                hits.add(tech)
    return sorted(hits)


def detect_dialects(files: list[Path]) -> list[str]:
    joined = "\n".join(read_text(p) for p in files if p.suffix.lower() in {".xml", ".properties", ".yml", ".yaml"} and p.stat().st_size < 500_000).lower()
    result = []
    for dialect, markers in {
        "MYSQL": ("mysql", "com.mysql"), "POSTGRESQL": ("postgresql", "org.postgresql"),
        "ORACLE": ("oracle.jdbc", "oracle"), "SQL_SERVER": ("sqlserver", "microsoft.sqlserver"),
    }.items():
        if any(m in joined for m in markers):
            result.append(dialect)
    return result or ["UNKNOWN"]


def detect_profiles(files: list[Path]) -> list[str]:
    profiles = set()
    for path in files:
        name = path.name
        match = re.match(r"application-([^.]+)\.(?:yml|yaml|properties)$", name)
        if match and match.group(1).lower() not in {"test", "tests"}:
            profiles.add(match.group(1))
    return sorted(profiles)


def detect_data_sources(files: list[Path]) -> list[dict[str, Any]]:
    observations: dict[str, dict[str, Any]] = {}
    for path in files:
        if path.suffix.lower() not in {".properties", ".yml", ".yaml", ".xml"} or path.stat().st_size > 1_000_000:
            continue
        text = read_text(path)
        for match in re.finditer(r"jdbc:(mysql|postgresql|oracle|sqlserver)(?::|://|@)", text, re.I):
            dialect = {"mysql": "MYSQL", "postgresql": "POSTGRESQL", "oracle": "ORACLE", "sqlserver": "SQL_SERVER"}[match.group(1).lower()]
            line_start = text.rfind("\n", 0, match.start()) + 1
            prefix = text[line_start:match.start()]
            key_match = re.search(r"([A-Za-z0-9_.-]*(?:datasource|jdbc)[A-Za-z0-9_.-]*(?:url)?)\s*[:=]\s*$", prefix, re.I)
            raw_key = key_match.group(1) if key_match else "default"
            parts = [part for part in re.split(r"[._-]", raw_key) if part.lower() not in {"spring", "datasource", "jdbc", "url"}]
            label = parts[-1] if parts else "default"
            identity = stable_id("datasource", label.lower(), dialect)
            observations[identity] = {"id": identity, "name": label, "dialect": dialect, "configurationFiles": sorted(set(observations.get(identity, {}).get("configurationFiles", []) + [path.name]))}
    return sorted(observations.values(), key=lambda item: item["id"])


def detect_applications(root: Path, files: list[Path]) -> list[dict[str, Any]]:
    boot_sources = []
    for path in files:
        if path.suffix.lower() == ".java" and re.search(r"@(?:[A-Za-z_]\w*\.)*SpringBootApplication\b", read_text(path)):
            boot_sources.append(path)
    roots: set[Path] = set()
    for source in boot_sources:
        current = source.parent
        while current != root and not any((current / marker).exists() for marker in ("pom.xml", "build.gradle", "build.gradle.kts")):
            current = current.parent
        roots.add(current if current != root or any((root / marker).exists() for marker in ("pom.xml", "build.gradle", "build.gradle.kts")) else root)
    if not roots:
        roots = {root}
    apps = []
    for app_root in sorted(roots, key=lambda p: p.as_posix()):
        rel = app_root.relative_to(root).as_posix() or "."
        modules = []
        for marker in files:
            if marker.name in {"pom.xml", "build.gradle", "build.gradle.kts"}:
                try:
                    module_rel = marker.parent.relative_to(app_root).as_posix() or "."
                except ValueError:
                    continue
                modules.append(module_rel)
        apps.append({"id": stable_id("app", rel), "name": app_root.name if rel != "." else root.name, "root": rel, "modules": sorted(set(modules))})
    return apps


def detect_java_language_level(files: list[Path]) -> str | None:
    patterns = [
        r"<maven\.compiler\.release>\s*([^<]+)", r"<maven\.compiler\.source>\s*([^<]+)",
        r"<java\.version>\s*([^<]+)", r"sourceCompatibility\s*=\s*['\"]?([0-9.]+)",
        r"JavaLanguageVersion\.of\((\d+)\)",
    ]
    levels = []
    for path in files:
        if path.name not in {"pom.xml", "build.gradle", "build.gradle.kts"}: continue
        text = read_text(path)
        for pattern in patterns:
            levels.extend(match.group(1).strip() for match in re.finditer(pattern, text, re.I))
    return sorted(set(levels))[-1] if levels else None


def evidence_for_match(rel: str, text: str, match: re.Match[str], source: str, facts: Facts) -> str:
    start, end = line_range(text, match.start(), match.end())
    return facts.add_evidence(evidence(rel, start, end, source))


def split_sql_statements(text: str) -> Iterator[tuple[str, int]]:
    start = 0
    quote: str | None = None
    depth = 0
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            if char == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 1
                else:
                    quote = None
        elif char in {"'", '"', '`'}:
            quote = char
        elif char == "(": depth += 1
        elif char == ")": depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            chunk = text[start:i + 1]
            if chunk.strip(): yield chunk, start
            start = i + 1
        i += 1
    tail = text[start:]
    if tail.strip(): yield tail, start


def balanced_parenthesized(text: str, open_at: int) -> tuple[str, int] | None:
    """Return a balanced parenthesized block without executing dialect-specific SQL."""
    if open_at >= len(text) or text[open_at] != "(":
        return None
    depth = 0
    quote: str | None = None
    index = open_at
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif char in {"'", '"', "`"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_at:index + 1], index + 1
        index += 1
    return None


def split_top_level_csv(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = None
        elif char in {"'", '"', "`"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


def alias_map(statement: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    pattern = re.compile(rf"\b(?:from|join|update|into|using)\s+({QUALIFIED})(?:\s+(?:as\s+)?([A-Za-z_][\w$]*))?", re.I)
    reserved = {"left", "right", "inner", "outer", "full", "cross", "where", "join", "on", "set", "values", "group", "order", "having", "limit"}
    for match in pattern.finditer(statement):
        table = strip_identifier(match.group(1))
        alias = match.group(2)
        aliases[table.split(".")[-1].lower()] = table
        if alias and alias.lower() not in reserved:
            aliases[alias.lower()] = table
    return aliases


def resolve_field(token: str, aliases: dict[str, str]) -> tuple[str | None, str | None]:
    clean = strip_identifier(token)
    parts = clean.split(".")
    if len(parts) < 2:
        return None, parts[-1]
    owner = ".".join(parts[:-1])
    table = aliases.get(owner.lower(), owner)
    return table, parts[-1]


def parse_ddl(text: str, rel: str, facts: Facts, conditional: bool = False, base_line: int = 0) -> None:
    create_re = re.compile(rf"\bcreate\s+(?P<temp>temporary\s+)?(?P<kind>table|view|materialized\s+view)\s+(?:if\s+not\s+exists\s+)?(?P<name>{QUALIFIED})", re.I | re.S)
    for match in create_re.finditer(text):
        kind = match.group("kind").upper().replace(" ", "_")
        if match.group("temp"): kind = "TEMPORARY"
        schema, name = split_name(match.group("name"))
        body_info = None
        body_start = match.end()
        while body_start < len(text) and text[body_start].isspace():
            body_start += 1
        if body_start < len(text) and text[body_start] == "(":
            body_info = balanced_parenthesized(text, body_start)
        ev_start, ev_end = line_range(text, match.start(), body_info[1] if body_info else match.end())
        ev_id = facts.add_evidence(evidence(rel, ev_start + base_line, ev_end + base_line, "DDL"))
        obj = facts.add_object(name, schema, ev_id, "DDL", kind)
        body = body_info[0] if body_info else ""
        if kind not in {"TABLE", "TEMPORARY"}:
            tail = text[match.end():]
            as_match = re.match(r"\s+as\s+(.*?)(?:;|$)", tail, re.I | re.S)
            if as_match:
                for dependency in re.finditer(rf"\b(?:from|join)\s+({QUALIFIED})", as_match.group(1), re.I):
                    dep_schema, dep_name = split_name(dependency.group(1)); facts.add_object(dep_name, dep_schema, ev_id, "DDL")
                    facts.relation_observations.append({"fromTable": name, "fromSchema": schema, "fromColumns": [], "toTable": dep_name, "toSchema": dep_schema, "toColumns": [], "sourceType": "OBJECT_DEPENDENCY", "confidence": "HIGH", "status": "NORMAL", "directionKnown": True, "evidenceIds": [ev_id]})
            continue
        inner = body[1:-1] if body.startswith("(") else body
        parts = split_top_level_csv(inner)
        for part in parts:
            item = part.strip()
            if not item: continue
            pk = re.match(r"(?:constraint\s+\S+\s+)?primary\s+key\s*\(([^)]+)\)", item, re.I)
            uq = re.match(r"(?:constraint\s+\S+\s+)?unique\s*\(([^)]+)\)", item, re.I)
            idx = re.match(r"(?:key|index)\s+(\S+)\s*\(([^)]+)\)", item, re.I)
            fk = re.match(r"(?:constraint\s+(\S+)\s+)?foreign\s+key\s*\(([^)]+)\)\s+references\s+([\w.`\"\[\]$#]+)\s*\(([^)]+)\)", item, re.I)
            if pk:
                cols = [strip_identifier(x) for x in pk.group(1).split(",")]
                obj["primaryKeys"].append(cols)
                for col in cols: facts.add_column(obj, default_column(col, ev_id, primaryKey=True, nullable=False))
                continue
            if uq:
                cols = [strip_identifier(x) for x in uq.group(1).split(",")]
                obj["uniqueConstraints"].append(cols)
                for col in cols: facts.add_column(obj, default_column(col, ev_id, unique=True))
                continue
            if idx:
                obj["indexes"].append({"name": strip_identifier(idx.group(1)), "columns": [strip_identifier(x) for x in idx.group(2).split(",")], "unique": False, "evidenceIds": [ev_id]})
                continue
            if fk:
                from_cols = [strip_identifier(x) for x in fk.group(2).split(",")]
                to_schema, to_name = split_name(fk.group(3))
                to_cols = [strip_identifier(x) for x in fk.group(4).split(",")]
                facts.relation_observations.append({"fromTable": name, "fromSchema": schema, "fromColumns": from_cols, "toTable": to_name, "toSchema": to_schema, "toColumns": to_cols, "constraintName": strip_identifier(fk.group(1)) if fk.group(1) else None, "sourceType": "DDL_FOREIGN_KEY", "confidence": "HIGH", "status": "CONDITIONAL" if conditional else "NORMAL", "directionKnown": True, "evidenceIds": [ev_id]})
                continue
            column = re.match(rf"({IDENT})\s+([A-Za-z][\w]*(?:\s*\([^)]*\))?(?:\s+with(?:out)?\s+time\s+zone)?)\s*(.*)$", item, re.I | re.S)
            if column:
                col_name = strip_identifier(column.group(1))
                tail = column.group(3)
                is_pk = bool(re.search(r"\bprimary\s+key\b", tail, re.I))
                is_unique = bool(re.search(r"\bunique\b", tail, re.I))
                nullable = False if re.search(r"\bnot\s+null\b", tail, re.I) or is_pk else True
                default_match = re.search(r"\bdefault\s+([^\s,]+)", tail, re.I)
                generated = "AUTO_INCREMENT" if re.search(r"auto_increment|identity|serial", item, re.I) else None
                facts.add_column(obj, default_column(col_name, ev_id, databaseType=column.group(2).strip(), primaryKey=is_pk, unique=is_unique, nullable=nullable, default=default_match.group(1) if default_match else None, generated=generated))
                if is_pk: obj["primaryKeys"].append([col_name])
                if is_unique: obj["uniqueConstraints"].append([col_name])
                inline_fk = re.search(r"\breferences\s+([\w.`\"\[\]$#]+)\s*\(([^)]+)\)", tail, re.I)
                if inline_fk:
                    ts, tn = split_name(inline_fk.group(1))
                    facts.relation_observations.append({"fromTable": name, "fromSchema": schema, "fromColumns": [col_name], "toTable": tn, "toSchema": ts, "toColumns": [strip_identifier(x) for x in inline_fk.group(2).split(",")], "sourceType": "DDL_FOREIGN_KEY", "confidence": "HIGH", "status": "NORMAL", "directionKnown": True, "evidenceIds": [ev_id]})
    for match in re.finditer(rf"\bcreate\s+(?:or\s+replace\s+)?(procedure|function|trigger)\s+({QUALIFIED})(.*?)(?=\bend\s*;|\Z)", text, re.I | re.S):
        object_type = match.group(1).upper(); schema, name = split_name(match.group(2)); start, end = line_range(text, match.start(), match.end()); ev_id = facts.add_evidence(evidence(rel, start + base_line, end + base_line, "DDL")); facts.add_object(name, schema, ev_id, "DDL", object_type)
        for dependency in re.finditer(rf"\b(?:from|join|update|insert\s+into|delete\s+from)\s+({QUALIFIED})", match.group(3), re.I):
            dep_schema, dep_name = split_name(dependency.group(1)); facts.add_object(dep_name, dep_schema, ev_id, "DDL")
            facts.relation_observations.append({"fromTable": name, "fromSchema": schema, "fromColumns": [], "toTable": dep_name, "toSchema": dep_schema, "toColumns": [], "sourceType": "OBJECT_DEPENDENCY", "confidence": "HIGH", "status": "NORMAL", "directionKnown": True, "evidenceIds": [ev_id]})
    alter_fk = re.compile(rf"\balter\s+table\s+({QUALIFIED})\s+add\s+(?:constraint\s+({IDENT})\s+)?foreign\s+key\s*\(([^)]+)\)\s+references\s+({QUALIFIED})\s*\(([^)]+)\)", re.I | re.S)
    for match in alter_fk.finditer(text):
        fs, fn = split_name(match.group(1)); ts, tn = split_name(match.group(4))
        ev_start, ev_end = line_range(text, match.start(), match.end())
        ev_id = facts.add_evidence(evidence(rel, ev_start + base_line, ev_end + base_line, "DDL"))
        facts.add_object(fn, fs, ev_id, "DDL"); facts.add_object(tn, ts, ev_id, "DDL")
        facts.relation_observations.append({"fromTable": fn, "fromSchema": fs, "fromColumns": [strip_identifier(x) for x in match.group(3).split(",")], "toTable": tn, "toSchema": ts, "toColumns": [strip_identifier(x) for x in match.group(5).split(",")], "constraintName": strip_identifier(match.group(2)) if match.group(2) else None, "sourceType": "DDL_FOREIGN_KEY", "confidence": "HIGH", "status": "NORMAL", "directionKnown": True, "evidenceIds": [ev_id]})
    for match in re.finditer(rf"\bcreate\s+(unique\s+)?index\s+({IDENT})\s+on\s+({QUALIFIED})\s*\(([^)]+)\)", text, re.I):
        schema, name = split_name(match.group(3)); start, end = line_range(text, match.start(), match.end()); ev_id = facts.add_evidence(evidence(rel, start + base_line, end + base_line, "DDL")); obj = facts.add_object(name, schema, ev_id, "DDL")
        columns = [strip_identifier(value) for value in split_top_level_csv(match.group(4))]
        obj["indexes"].append({"name": strip_identifier(match.group(2)), "columns": columns, "unique": bool(match.group(1)), "evidenceIds": [ev_id]})
        if match.group(1): obj["uniqueConstraints"].append(columns)
    for match in re.finditer(rf"\balter\s+table\s+({QUALIFIED})\s+add\s+(?:constraint\s+\S+\s+)?(primary\s+key|unique)\s*\(([^)]+)\)", text, re.I):
        schema, name = split_name(match.group(1)); start, end = line_range(text, match.start(), match.end()); ev_id = facts.add_evidence(evidence(rel, start + base_line, end + base_line, "DDL")); obj = facts.add_object(name, schema, ev_id, "DDL"); columns = [strip_identifier(value) for value in split_top_level_csv(match.group(3))]
        if match.group(2).lower().startswith("primary"):
            obj["primaryKeys"].append(columns)
            for column in columns: facts.add_column(obj, default_column(column, ev_id, primaryKey=True, nullable=False))
        else:
            obj["uniqueConstraints"].append(columns)
            for column in columns: facts.add_column(obj, default_column(column, ev_id, unique=True))
    event_patterns = [
        ("DROP_TABLE", re.compile(rf"\bdrop\s+table\s+(?:if\s+exists\s+)?({QUALIFIED})", re.I)),
        ("RENAME_TABLE", re.compile(rf"\balter\s+table\s+({QUALIFIED})\s+rename\s+to\s+({QUALIFIED})", re.I)),
        ("ADD_COLUMN", re.compile(rf"\balter\s+table\s+({QUALIFIED})\s+add\s+(?:column\s+)?(?!constraint\b)({IDENT})\s+([A-Za-z][\w]*(?:\s*\([^)]*\))?)", re.I)),
        ("DROP_COLUMN", re.compile(rf"\balter\s+table\s+({QUALIFIED})\s+drop\s+(?:column\s+)?(?!constraint\b)({IDENT})", re.I)),
        ("RENAME_COLUMN", re.compile(rf"\balter\s+table\s+({QUALIFIED})\s+rename\s+column\s+({IDENT})\s+to\s+({IDENT})", re.I)),
        ("DROP_FOREIGN_KEY", re.compile(rf"\balter\s+table\s+({QUALIFIED})\s+drop\s+(?:constraint|foreign\s+key)\s+({IDENT})", re.I)),
    ]
    for event_kind, pattern in event_patterns:
        for match in pattern.finditer(text):
            start, end = line_range(text, match.start(), match.end())
            ev_id = facts.add_evidence(evidence(rel, start + base_line, end + base_line, "DDL"))
            schema, table = split_name(match.group(1))
            event: dict[str, Any] = {"event": event_kind, "schema": schema, "table": table, "evidenceId": ev_id}
            if event_kind == "RENAME_TABLE":
                new_schema, new_table = split_name(match.group(2)); event.update({"newSchema": new_schema or schema, "newTable": new_table})
            elif event_kind == "ADD_COLUMN":
                event.update({"column": strip_identifier(match.group(2)), "databaseType": match.group(3).strip()})
            elif event_kind == "DROP_COLUMN":
                event.update({"column": strip_identifier(match.group(2))})
            elif event_kind == "RENAME_COLUMN":
                event.update({"column": strip_identifier(match.group(2)), "newColumn": strip_identifier(match.group(3))})
            elif event_kind == "DROP_FOREIGN_KEY":
                event.update({"constraintName": strip_identifier(match.group(2))})
            facts.ddl_events.append(event)


def parse_sql(text: str, rel: str, facts: Facts, conditional: bool = False, source: str = "SQL", base_line: int = 0) -> None:
    parse_ddl(text, rel, facts, conditional, base_line)
    for dynamic in re.finditer(r"([A-Za-z_][\w$#-]*)(?:_\$\{[^}]+\}|_#\{[^}]+\}|\$\{[^}]+\}|#\{[^}]+\})", text):
        start, end = line_range(text, dynamic.start(), dynamic.end())
        ev_id = facts.add_evidence(evidence(rel, start + base_line, end + base_line, source))
        pattern = dynamic.group(0)
        facts.add_object(pattern, None, ev_id, "CODE", "UNKNOWN", dynamic=pattern)
        facts.unresolved.append({"kind": "DYNAMIC_TABLE", "message": f"Runtime database object pattern retained without inventing concrete tables: {pattern}", "evidenceIds": [ev_id]})
    for statement, offset in split_sql_statements(text):
        aliases = alias_map(statement)
        cte_names = {strip_identifier(match.group(1)).lower() for match in re.finditer(rf"(?:\bwith\b|,)\s*({IDENT})\s+as\s*\(", statement, re.I)}
        # Resolve the common, statically provable CTE lineage case. This keeps
        # the CTE itself out of the physical object list while allowing a
        # comparison such as cte_alias.x > table.x to retain its real upstream
        # dependency. Ambiguous/multi-source CTEs deliberately remain unresolved.
        for cte in cte_names:
            cte_match = re.search(rf"\b{re.escape(cte)}\s+as\s*\((.*?)\)\s*(?:,|select\b)", statement, re.I | re.S)
            if not cte_match:
                continue
            sources = [strip_identifier(item.group(1)) for item in re.finditer(rf"\b(?:from|join)\s+({QUALIFIED})", cte_match.group(1), re.I)]
            if len(set(sources)) == 1:
                source_table = sources[0]
                for alias, target in list(aliases.items()):
                    if target.lower() == cte:
                        aliases[alias] = source_table
                aliases[cte] = source_table
        table_matches = list(re.finditer(rf"\b(from|join|update|insert\s+into|delete\s+from|merge\s+into)\s+({QUALIFIED})", statement, re.I))
        for call in re.finditer(rf"(?:\bcall\s+|\{{\s*\??\s*=*\s*call\s+)({QUALIFIED})", statement, re.I):
            schema, name = split_name(call.group(1)); start, end = line_range(text, offset + call.start(), offset + call.end()); ev_id = facts.add_evidence(evidence(rel, start + base_line, end + base_line, source))
            facts.add_object(name, schema, ev_id, "CODE", "PROCEDURE")
            facts.operations.append({"kind": "CALL", "table": name, "schema": schema, "columns": [], "evidenceIds": [ev_id]})
            if source in {"JAVA_SQL", "MYBATIS_XML", "XML_SQL"}:
                facts.unresolved.append({"kind": "EXTERNAL_ROUTINE_BODY", "message": f"Routine {name} is called from Java/project SQL but its body may be external", "evidenceIds": [ev_id]})
        for match in table_matches:
            keyword = match.group(1).lower()
            schema, name = split_name(match.group(2))
            if schema is None and name.lower() in cte_names:
                continue
            start, end = line_range(text, offset + match.start(), offset + match.end())
            ev_id = facts.add_evidence(evidence(rel, start + base_line, end + base_line, source))
            obj = facts.add_object(name, schema, ev_id, "CODE", "TABLE")
            kind = "READ" if keyword in {"from", "join"} else ("INSERT" if "insert" in keyword else "UPDATE" if keyword in {"update", "merge into"} else "DELETE")
            facts.operations.append({"kind": kind, "table": name, "schema": schema, "columns": [], "evidenceIds": [ev_id]})
        # Record explicit write columns without treating parameters or values as identifiers.
        insert = re.search(rf"\binsert\s+into\s+({QUALIFIED})\s*\(([^)]+)\)", statement, re.I | re.S)
        if insert:
            schema, name = split_name(insert.group(1)); columns = [strip_identifier(value) for value in split_top_level_csv(insert.group(2))]
            for operation in facts.operations:
                if operation["kind"] == "INSERT" and operation["table"].lower() == name.lower(): operation["columns"] = columns
            obj = facts.objects.get(facts.object_key(schema, name))
            if obj:
                for column in columns: facts.add_column(obj, default_column(column, usages=["INSERT_FIELD"]))
        update = re.search(rf"\bupdate\s+({QUALIFIED})(?:\s+\w+)?\s+set\s+(.*?)(?:\bwhere\b|$)", statement, re.I | re.S)
        if update:
            schema, name = split_name(update.group(1)); columns = [strip_identifier(match.group(1).split(".")[-1]) for match in re.finditer(rf"({QUALIFIED})\s*=", update.group(2))]
            for operation in facts.operations:
                if operation["kind"] == "UPDATE" and operation["table"].lower() == name.lower(): operation["columns"] = columns
            obj = facts.objects.get(facts.object_key(schema, name))
            if obj:
                for column in columns: facts.add_column(obj, default_column(column, usages=["UPDATE_FIELD"]))
        merge = re.search(rf"\bmerge\s+into\s+({QUALIFIED})(?:\s+\w+)?\s+using\b.*?\bupdate\s+set\s+(.*?)(?:\bwhen\b|$)", statement, re.I | re.S)
        if merge:
            schema, name = split_name(merge.group(1)); columns = [strip_identifier(item.group(1).split(".")[-1]) for item in re.finditer(rf"({QUALIFIED})\s*=", merge.group(2))]
            for operation in facts.operations:
                if operation["kind"] == "UPDATE" and operation["table"].lower() == name.lower(): operation["columns"] = sorted(set(operation.get("columns", []) + columns))
            obj = facts.objects.get(facts.object_key(schema, name))
            if obj:
                for column in columns: facts.add_column(obj, default_column(column, usages=["UPDATE_FIELD"]))
        compare = re.compile(rf"({QUALIFIED})\s*=\s*({QUALIFIED})", re.I)
        for match in compare.finditer(statement):
            left_table, left_col = resolve_field(match.group(1), aliases)
            right_table, right_col = resolve_field(match.group(2), aliases)
            if not left_table or not right_table or left_table.lower() == right_table.lower(): continue
            ls, ln = split_name(left_table); rs, rn = split_name(right_table)
            if (ls is None and ln.lower() in cte_names) or (rs is None and rn.lower() in cte_names): continue
            prefix = statement[:match.start()].lower()
            clause_positions = {
                "ON": max((item.start() for item in re.finditer(r"\bon\b", prefix)), default=-1),
                "WHERE": max((item.start() for item in re.finditer(r"\bwhere\b", prefix)), default=-1),
                "HAVING": max((item.start() for item in re.finditer(r"\bhaving\b", prefix)), default=-1),
            }
            source_type = "SQL_JOIN" if clause_positions["ON"] == max(clause_positions.values()) and clause_positions["ON"] >= 0 else "SQL_COLUMN_COMPARISON"
            start, end = line_range(text, offset + match.start(), offset + match.end())
            ev_id = facts.add_evidence(evidence(rel, start + base_line, end + base_line, source))
            facts.add_object(ln, ls, ev_id, "CODE"); facts.add_object(rn, rs, ev_id, "CODE")
            # JOIN order never defines direction; key evidence may resolve it later.
            facts.relation_observations.append({"fromTable": ln, "fromSchema": ls, "fromColumns": [left_col], "toTable": rn, "toSchema": rs, "toColumns": [right_col], "sourceType": source_type, "confidence": "HIGH", "status": "CONDITIONAL" if conditional else "NORMAL", "directionKnown": False, "evidenceIds": [ev_id]})
        # JOIN ... USING(col) is a relation with known endpoints but unknown reference direction.
        first_from = next((match for match in table_matches if match.group(1).lower() == "from"), None)
        if first_from:
            base_schema, base_name = split_name(first_from.group(2))
            for match in re.finditer(rf"\bjoin\s+({QUALIFIED})(?:\s+(?:as\s+)?\w+)?\s+using\s*\(([^)]+)\)", statement, re.I | re.S):
                join_schema, join_name = split_name(match.group(1)); columns = [strip_identifier(value) for value in split_top_level_csv(match.group(2))]
                start, end = line_range(text, offset + match.start(), offset + match.end()); ev_id = facts.add_evidence(evidence(rel, start + base_line, end + base_line, source))
                facts.add_object(base_name, base_schema, ev_id, "CODE"); facts.add_object(join_name, join_schema, ev_id, "CODE")
                facts.relation_observations.append({"fromTable": base_name, "fromSchema": base_schema, "fromColumns": columns, "toTable": join_name, "toSchema": join_schema, "toColumns": columns, "sourceType": "SQL_JOIN", "confidence": "HIGH", "status": "CONDITIONAL" if conditional else "NORMAL", "directionKnown": False, "evidenceIds": [ev_id]})
        # Non-equality cross-object comparisons establish query dependency only.
        for match in re.finditer(rf"({QUALIFIED})\s*(<>|!=|<=|>=|<|>)\s*({QUALIFIED})", statement, re.I):
            left_table, left_col = resolve_field(match.group(1), aliases); right_table, right_col = resolve_field(match.group(3), aliases)
            if not left_table or not right_table or left_table.lower() == right_table.lower(): continue
            ls, ln = split_name(left_table); rs, rn = split_name(right_table); start, end = line_range(text, offset + match.start(), offset + match.end()); ev_id = facts.add_evidence(evidence(rel, start + base_line, end + base_line, source))
            if (ls is None and ln.lower() in cte_names) or (rs is None and rn.lower() in cte_names): continue
            facts.add_object(ln, ls, ev_id, "CODE"); facts.add_object(rn, rs, ev_id, "CODE")
            facts.relation_observations.append({"fromTable": ln, "fromSchema": ls, "fromColumns": [left_col], "toTable": rn, "toSchema": rs, "toColumns": [right_col], "sourceType": "OBJECT_DEPENDENCY", "confidence": "MEDIUM", "status": "CONDITIONAL" if conditional else "NORMAL", "directionKnown": False, "evidenceIds": [ev_id]})
        # Capture selected and written fields when owner is unambiguous.
        for token_match in re.finditer(rf"({QUALIFIED})", statement):
            token = token_match.group(1)
            if "." not in token: continue
            table, col = resolve_field(token, aliases)
            if not table or not col: continue
            schema, name = split_name(table)
            obj = facts.objects.get(facts.object_key(schema, name))
            if obj:
                facts.add_column(obj, default_column(col, usages=["QUERY_FIELD"]))


JAVA_STRING = re.compile(r'"""(.*?)"""|"((?:\\.|[^"\\])*)"', re.S)


def java_strings(text: str) -> list[tuple[str, int, int]]:
    result = []
    for match in JAVA_STRING.finditer(text):
        raw = match.group(1) if match.group(1) is not None else match.group(2)
        try:
            value = bytes(raw, "utf-8").decode("unicode_escape") if match.group(1) is None else raw
        except UnicodeDecodeError:
            value = raw
        result.append((value, match.start(), match.end()))
    return result


def java_static_sql_values(text: str) -> list[tuple[str, int, int]]:
    """Resolve literals and unambiguous String constant/local concatenations."""
    assignments = list(re.finditer(r"\b(?:String|var)\s+([A-Za-z_]\w*)\s*=\s*(.*?);", text, re.S))
    values: dict[str, str] = {}
    resolved: list[tuple[str, int, int]] = []
    pending = assignments[:]
    for _ in range(len(assignments) + 1):
        changed = False
        remaining = []
        for match in pending:
            expression = match.group(2).strip()
            pieces = re.split(r"\s*\+\s*", expression)
            output: list[str] = []
            valid = True
            for piece in pieces:
                piece = piece.strip().strip("()")
                literal = java_strings(piece)
                if len(literal) == 1 and literal[0][1] == 0 and literal[0][2] == len(piece):
                    output.append(literal[0][0])
                elif re.fullmatch(r"[A-Za-z_]\w*", piece) and piece in values:
                    output.append(values[piece])
                else:
                    valid = False
                    break
            if valid:
                value = "".join(output)
                values[match.group(1)] = value
                if SQL_WORDS.search(value):
                    resolved.append((value, match.start(2), match.end(2)))
                changed = True
            else:
                remaining.append(match)
        pending = remaining
        if not changed:
            break
    return resolved


def annotation_value(block: str, name: str, key: str | None = None) -> str | None:
    match = re.search(rf"@{re.escape(name)}\s*(?:\((.*?)\))?", block, re.S)
    if not match: return None
    body = match.group(1) or ""
    if key:
        keyed = re.search(rf"\b{re.escape(key)}\s*=\s*\"([^\"]+)\"", body)
        return keyed.group(1) if keyed else None
    quoted = re.search(r'"([^\"]+)"', body)
    return quoted.group(1) if quoted else None


def mapped_java_fields(body: str, full_text: str, body_start: int, rel: str, facts: Facts) -> list[dict[str, Any]]:
    result = []
    field_re = re.compile(r"((?:\s*@[^\r\n]+(?:\r?\n))*)\s*(?:private|protected|public)\s+(?:final\s+)?([\w.<>, ?\[\]]+)\s+(\w+)\s*(?:=[^;]*)?;", re.M)
    for match in field_re.finditer(body):
        annotations, java_type, java_name = match.group(1), match.group(2).strip(), match.group(3)
        if re.search(r"@(Transient|TableField\s*\([^)]*exist\s*=\s*false)", annotations, re.I): continue
        if re.search(r"@(OneToOne|OneToMany|ManyToOne|ManyToMany)\b", annotations): continue
        start, end = line_range(full_text, body_start + match.start(), body_start + match.end()); ev_id = facts.add_evidence(evidence(rel, start, end, "JAVA"))
        overrides = {m.group(1): m.group(2) for m in re.finditer(r"@AttributeOverride\s*\(\s*name\s*=\s*\"([^\"]+)\"\s*,\s*column\s*=\s*@Column\s*\([^)]*name\s*=\s*\"([^\"]+)\"", annotations, re.S)}
        result.append({"javaName": java_name, "javaType": java_type, "column": annotation_value(annotations, "Column", "name") or java_name, "primaryKey": bool(re.search(r"@(Id|EmbeddedId)\b", annotations)), "embedded": bool(re.search(r"@(Embedded|EmbeddedId)\b", annotations)), "overrides": overrides, "evidenceIds": [ev_id]})
    return result


def simple_java_annotations(text: str) -> str:
    """Remove annotation package qualifiers without changing line structure."""
    return re.sub(r"@(?:[A-Za-z_]\w*\.)+([A-Za-z_]\w*)", r"@\1", text)


def parse_java(text: str, rel: str, facts: Facts) -> None:
    # Java projects commonly use fully-qualified annotations in generated or
    # dependency-light source. The analyzer needs annotation semantics, not a
    # compilable rewrite; line numbers remain stable because no newlines move.
    text = simple_java_annotations(text)
    for dynamic_mapping in re.finditer(r"@(Formula|Subselect|ColumnTransformer|Any)\b", text):
        start, end = line_range(text, dynamic_mapping.start(), dynamic_mapping.end()); ev_id = facts.add_evidence(evidence(rel, start, end, "JAVA"))
        facts.unresolved.append({"kind": "HIBERNATE_DYNAMIC_MAPPING", "message": f"Hibernate {dynamic_mapping.group(1)} mapping cannot always be reduced to a physical column relation", "evidenceIds": [ev_id]})
    for interceptor in re.finditer(r"\b(?:implements|extends)\s+(?:\w+\.)*(?:InnerInterceptor|Interceptor)\b", text):
        start, end = line_range(text, interceptor.start(), interceptor.end()); ev_id = facts.add_evidence(evidence(rel, start, end, "JAVA"))
        facts.unresolved.append({"kind": "RUNTIME_SQL_INTERCEPTOR", "message": "A custom SQL interceptor may rewrite tables, fields, or conditions at runtime", "evidenceIds": [ev_id]})
    package_match = re.search(r"\bpackage\s+([\w.]+)\s*;", text)
    package = package_match.group(1) if package_match else ""
    class_re = re.compile(r"((?:\s*@\w+(?:\s*\([^)]*\))?\s*)*)\s*(?:public\s+|protected\s+|private\s+|abstract\s+|final\s+)*(?:class|interface|record)\s+(\w+)(?:[^\{]*)\{", re.M)
    classes = list(class_re.finditer(text))
    for class_index, class_match in enumerate(classes):
        ann = class_match.group(1); class_name = class_match.group(2)
        qualified = f"{package}.{class_name}" if package else class_name
        role = "JAVA_CLASS"
        if re.search(r"@MappedSuperclass\b", ann): role = "MAPPED_SUPERCLASS"
        elif re.search(r"@Embeddable\b", ann): role = "EMBEDDABLE"
        elif re.search(r"@(Entity|TableName)\b", ann): role = "ENTITY"
        elif re.search(r"@(Mapper|Repository)\b", ann) or class_name.endswith("Mapper"): role = "MAPPER"
        elif class_name.endswith("Repository"): role = "REPOSITORY"
        elif class_name.endswith(("Dao", "DAO")): role = "DAO"
        elif class_name.endswith(("Dto", "DTO", "Vo", "VO")): role = "QUERY_RESULT"
        start, end = line_range(text, class_match.start(), class_match.end())
        ev_id = facts.add_evidence(evidence(rel, start, end, "JAVA"))
        code_id = stable_id("code", qualified, role)
        super_match = re.search(r"\bextends\s+([\w.]+)", class_match.group(0))
        body_start = class_match.end()
        body_end = classes[class_index + 1].start() if class_index + 1 < len(classes) else len(text)
        body = text[body_start:body_end]
        inheritance = annotation_value(ann, "Inheritance", "strategy") or ("JOINED" if "InheritanceType.JOINED" in ann else "SINGLE_TABLE" if "InheritanceType.SINGLE_TABLE" in ann else "TABLE_PER_CLASS" if "InheritanceType.TABLE_PER_CLASS" in ann else None)
        facts.code_objects[code_id] = {"id": code_id, "qualifiedName": qualified, "role": role, "superClass": super_match.group(1) if super_match else None, "inheritanceStrategy": inheritance, "mappedFields": mapped_java_fields(body, text, body_start, rel, facts), "evidenceIds": [ev_id]}
        table_name = annotation_value(ann, "Table", "name") or annotation_value(ann, "TableName")
        schema = annotation_value(ann, "Table", "schema")
        if role == "ENTITY" and not table_name:
            table_name = class_name
            facts.unresolved.append({"kind": "IMPLICIT_TABLE_NAMING", "message": f"Entity {qualified} has no explicit physical table name; logical JPA default was retained", "evidenceIds": [ev_id]})
        if table_name:
            obj = facts.add_object(table_name, schema, ev_id, "CODE")
            facts.mappings.append({"codeObjectId": code_id, "table": table_name, "schema": schema, "role": role, "evidenceIds": [ev_id]})
            for secondary in re.finditer(r"@SecondaryTable\s*\((.*?)\)", ann, re.S):
                secondary_name = annotation_value("@SecondaryTable(" + secondary.group(1) + ")", "SecondaryTable", "name")
                if secondary_name:
                    secondary_obj = facts.add_object(secondary_name, schema, ev_id, "CODE")
                    facts.add_column(secondary_obj, default_column("id", ev_id, primaryKey=True, nullable=False)); secondary_obj["primaryKeys"].append(["id"])
                    facts.relation_observations.append({"fromTable": secondary_name, "fromSchema": schema, "fromColumns": ["id"], "toTable": table_name, "toSchema": schema, "toColumns": ["id"], "sourceType": "ORM_RELATION", "confidence": "HIGH", "status": "NORMAL", "directionKnown": True, "codeCardinality": "ONE_TO_ONE", "optionality": "REQUIRED", "evidenceIds": [ev_id]})
            field_re = re.compile(r"((?:\s*@[^\n]+\n)*)\s*(?:private|protected|public)\s+(?:final\s+)?([\w.<>, ?\[\]]+)\s+(\w+)\s*(?:=[^;]*)?;", re.M)
            for fm in field_re.finditer(body):
                fann, java_type, java_name = fm.group(1), fm.group(2).strip(), fm.group(3)
                if re.search(r"@(Transient|TableField\s*\([^)]*exist\s*=\s*false)", fann, re.I): continue
                col_name = annotation_value(fann, "Column", "name") or annotation_value(fann, "TableField") or annotation_value(fann, "TableId")
                join_col = annotation_value(fann, "JoinColumn", "name")
                referenced = annotation_value(fann, "JoinColumn", "referencedColumnName") or "id"
                if not col_name and not join_col:
                    col_name = java_name
                is_pk = bool(re.search(r"@(Id|EmbeddedId|TableId)\b", fann))
                unique = bool(re.search(r"\bunique\s*=\s*true", fann))
                nullable = False if re.search(r"\bnullable\s*=\s*false|\boptional\s*=\s*false", fann) or is_pk else True
                fstart, fend = line_range(text, body_start + fm.start(), body_start + fm.end())
                fev = facts.add_evidence(evidence(rel, fstart, fend, "JAVA"))
                db_col = join_col or col_name
                relation_match = re.search(r"@(OneToOne|OneToMany|ManyToOne|ManyToMany)\b", fann)
                collection_table = annotation_value(fann, "CollectionTable", "name")
                if collection_table:
                    collection_join = annotation_value(fann, "JoinColumn", "name")
                    collection_obj = facts.add_object(collection_table, schema, fev, "CODE")
                    if collection_join:
                        facts.add_column(collection_obj, default_column(collection_join, fev))
                        facts.relation_observations.append({"fromTable": collection_table, "fromSchema": schema, "fromColumns": [collection_join], "toTable": table_name, "toSchema": schema, "toColumns": ["id"], "sourceType": "ORM_RELATION", "confidence": "HIGH", "status": "NORMAL", "directionKnown": True, "codeCardinality": "MANY_TO_ONE", "optionality": "REQUIRED", "evidenceIds": [fev]})
                    else:
                        facts.unresolved.append({"kind": "IMPLICIT_COLLECTION_TABLE_JOIN", "message": f"CollectionTable {collection_table} has no statically explicit join column", "evidenceIds": [fev]})
                usages = []
                if re.search(r"@TableLogic\b", fann): usages.append("LOGIC_DELETE")
                if re.search(r"@Version\b", fann): usages.append("OPTIMISTIC_LOCK")
                # Relationship properties are not physical columns unless a
                # join column is explicit. Scalar/entity-id fields are columns.
                if not relation_match or join_col:
                    facts.add_column(obj, default_column(db_col, fev, javaName=java_name, javaType=java_type, primaryKey=is_pk, unique=unique, nullable=nullable, usages=usages))
                    if is_pk: obj["primaryKeys"].append([db_col])
                if relation_match:
                    target_type = re.sub(r"^(?:List|Set|Collection|Iterable)<|>$", "", java_type).split("<")[-1].rstrip(">?")
                    target_table = target_type
                    card_map = {"OneToOne": "ONE_TO_ONE", "OneToMany": "ONE_TO_MANY", "ManyToOne": "MANY_TO_ONE", "ManyToMany": "MANY_TO_MANY"}
                    cardinality = card_map[relation_match.group(1)]
                    join_table = annotation_value(fann, "JoinTable", "name")
                    join_pairs = []
                    for join_match in re.finditer(r"@JoinColumn\s*\(([^)]*)\)", fann, re.S):
                        block = "@JoinColumn(" + join_match.group(1) + ")"
                        local_name = annotation_value(block, "JoinColumn", "name")
                        if local_name: join_pairs.append((local_name, annotation_value(block, "JoinColumn", "referencedColumnName") or "id"))
                    if join_pairs:
                        facts.relation_observations.append({"fromTable": table_name, "fromSchema": schema, "fromColumns": [pair[0] for pair in join_pairs], "toTable": target_table, "toSchema": None, "toColumns": [pair[1] for pair in join_pairs], "sourceType": "ORM_RELATION", "confidence": "HIGH", "status": "NORMAL", "directionKnown": relation_match.group(1) in {"ManyToOne", "OneToOne"}, "codeCardinality": cardinality, "optionality": "REQUIRED" if nullable is False or re.search(r"@MapsId\b", fann) else "UNKNOWN", "evidenceIds": [fev]})
                    elif join_table:
                        owner_match = re.search(r"\bjoinColumns\s*=\s*(?:\{\s*)?@JoinColumn\s*\((.*?)\)", fann, re.S)
                        inverse_match = re.search(r"\binverseJoinColumns\s*=\s*(?:\{\s*)?@JoinColumn\s*\((.*?)\)", fann, re.S)
                        owner_column = annotation_value("@JoinColumn(" + owner_match.group(1) + ")", "JoinColumn", "name") if owner_match else None
                        inverse_column = annotation_value("@JoinColumn(" + inverse_match.group(1) + ")", "JoinColumn", "name") if inverse_match else None
                        if owner_column and inverse_column:
                            join_obj = facts.add_object(join_table, schema, fev, "CODE")
                            facts.add_column(join_obj, default_column(owner_column, fev))
                            facts.add_column(join_obj, default_column(inverse_column, fev))
                            facts.relation_observations.append({"fromTable": join_table, "fromSchema": schema, "fromColumns": [owner_column], "toTable": table_name, "toSchema": schema, "toColumns": ["id"], "sourceType": "ORM_RELATION", "confidence": "HIGH", "status": "NORMAL", "directionKnown": True, "codeCardinality": "MANY_TO_ONE", "optionality": "UNKNOWN", "evidenceIds": [fev]})
                            facts.relation_observations.append({"fromTable": join_table, "fromSchema": schema, "fromColumns": [inverse_column], "toTable": target_table, "toSchema": None, "toColumns": ["id"], "sourceType": "ORM_RELATION", "confidence": "HIGH", "status": "NORMAL", "directionKnown": True, "codeCardinality": "MANY_TO_ONE", "optionality": "UNKNOWN", "evidenceIds": [fev]})
                        else:
                            facts.unresolved.append({"kind": "COMPLEX_JOIN_TABLE", "message": f"JoinTable on {qualified}.{java_name} could not be resolved as complete column pairs", "evidenceIds": [fev]})
                    else:
                        facts.unresolved.append({"kind": "IMPLICIT_ORM_JOIN", "message": f"ORM relation {qualified}.{java_name} has no explicit join column/table; physical names were not guessed", "evidenceIds": [fev]})
            getter_re = re.compile(r"((?:\s*@\w+(?:\([^;{}]*?\))?\s*)+)\s*(?:public|protected)\s+([\w.<>, ?\[\]]+)\s+(?:get|is)([A-Z]\w*)\s*\(\s*\)", re.M)
            for getter in getter_re.finditer(body):
                getter_ann, java_type, suffix = getter.group(1), getter.group(2).strip(), getter.group(3)
                if re.search(r"@Transient\b", getter_ann): continue
                java_name = suffix[0].lower() + suffix[1:]
                col_name = annotation_value(getter_ann, "Column", "name") or java_name
                is_pk = bool(re.search(r"@(Id|EmbeddedId)\b", getter_ann))
                gs, ge = line_range(text, body_start + getter.start(), body_start + getter.end())
                gev = facts.add_evidence(evidence(rel, gs, ge, "JAVA"))
                embedded = bool(re.search(r"@(Embedded|EmbeddedId)\b", getter_ann))
                overrides = {m.group(1): m.group(2) for m in re.finditer(r"@AttributeOverride\s*\(\s*name\s*=\s*\"([^\"]+)\"\s*,\s*column\s*=\s*@Column\s*\([^)]*name\s*=\s*\"([^\"]+)\"", getter_ann, re.S)}
                facts.code_objects[code_id]["mappedFields"].append({"javaName": java_name, "javaType": java_type, "column": col_name, "primaryKey": is_pk, "embedded": embedded, "overrides": overrides, "evidenceIds": [gev]})
                if not embedded:
                    facts.add_column(obj, default_column(col_name, gev, javaName=java_name, javaType=java_type, primaryKey=is_pk, nullable=False if is_pk else None))
                    if is_pk: obj["primaryKeys"].append([col_name])
            # Compact/generated entities often place annotations and fields on
            # one line or use package-private access. Capture explicit mapping
            # annotations without treating arbitrary local variables as fields.
            compact_field_re = re.compile(r"((?:@\w+(?:\([^;{}]*?\))?\s*)+)\s*(?:(?:private|protected|public)\s+)?([\w.<>, ?\[\]]+)\s+(\w+)\s*(?:=[^;]*)?;", re.M)
            for compact in compact_field_re.finditer(body):
                compact_ann, java_type, java_name = compact.group(1), compact.group(2).strip(), compact.group(3)
                if not re.search(r"@(TableId|TableField|TableLogic|Version|Id|Column)\b", compact_ann): continue
                column = annotation_value(compact_ann, "Column", "name") or annotation_value(compact_ann, "TableField") or annotation_value(compact_ann, "TableId") or java_name
                primary = bool(re.search(r"@(TableId|Id)\b", compact_ann)); usages = []
                if re.search(r"@TableLogic\b", compact_ann): usages.append("LOGIC_DELETE")
                if re.search(r"@Version\b", compact_ann): usages.append("OPTIMISTIC_LOCK")
                cs, ce = line_range(text, body_start + compact.start(), body_start + compact.end()); cev = facts.add_evidence(evidence(rel, cs, ce, "JAVA"))
                facts.add_column(obj, default_column(column, cev, javaName=java_name, javaType=java_type, primaryKey=primary, nullable=False if primary else None, usages=usages))
                if primary and [column] not in obj["primaryKeys"]: obj["primaryKeys"].append([column])
        # Repository/Mapper association using generic entity.
        generic = re.search(r"(?:JpaRepository|CrudRepository|BaseMapper)\s*<\s*(\w+)", text)
        if generic and role in {"MAPPER", "REPOSITORY"}:
            facts.mappings.append({"codeObjectId": code_id, "table": generic.group(1), "schema": None, "role": role, "evidenceIds": [ev_id], "possible": True})
    # JPQL/HQL uses entity/property names; retain query observations without
    # pretending these identifiers are physical table names.
    jpql_spans = []
    for query in re.finditer(r"@Query\s*\((.*?)\)", text, re.S):
        body = query.group(1)
        if re.search(r"nativeQuery\s*=\s*true", body, re.I): continue
        literal = java_strings(body)
        if not literal: continue
        value = literal[0][0]; jpql_spans.append((query.start(1) + literal[0][1], query.start(1) + literal[0][2]))
        entity = re.search(r"\bfrom\s+(\w+)\s+(\w+)", value, re.I)
        if entity:
            start, end = line_range(text, query.start(), query.end()); ev_id = facts.add_evidence(evidence(rel, start, end, "JPQL"))
            fields = [match.group(1) for match in re.finditer(rf"\b{re.escape(entity.group(2))}\.(\w+)", value)]
            facts.operations.append({"kind": "READ", "table": entity.group(1), "schema": None, "columns": fields, "evidenceIds": [ev_id], "possible": True})
    # Annotation SQL, JdbcTemplate SQL, and unambiguous String concatenations.
    finite_values: dict[str, list[str]] = {}
    for choice in re.finditer(r"\b(?:String|var)\s+(\w+)\s*=\s*[^;?]+\?\s*\"([^\"]+)\"\s*:\s*\"([^\"]+)\"\s*;", text):
        finite_values[choice.group(1)] = sorted({choice.group(2), choice.group(3)})
    for assignment in re.finditer(r"\b(?:String|var)\s+\w+\s*=\s*\"([^\"]*)\"\s*\+\s*(\w+)\s*;", text):
        if assignment.group(2) in finite_values and SQL_WORDS.search(assignment.group(1)):
            for value in finite_values[assignment.group(2)]:
                parse_sql(assignment.group(1) + value, rel, facts, conditional=True, source="JAVA_SQL", base_line=line_number(text, assignment.start()) - 1)
    composed = java_static_sql_values(text)
    composed_spans = [(start, end) for _, start, end in composed]
    for value, start, end in composed:
        parse_sql(value, rel, facts, source="JAVA_SQL", base_line=line_number(text, start) - 1)
    for value, start, end in java_strings(text):
        if SQL_WORDS.search(value) and not any(a <= start and end <= b for a, b in composed_spans) and not any(a <= start and end <= b for a, b in jpql_spans):
            parse_sql(value, rel, facts, source="JAVA_SQL", base_line=line_number(text, start) - 1)
    # Derived Spring Data methods supplement field usage only.
    repository_entity = re.search(r"(?:JpaRepository|CrudRepository)\s*<\s*(\w+)", text)
    if repository_entity:
        for method in re.finditer(r"\b(?:find|read|get|count|exists|delete)By([A-Z]\w*)\s*\(", text):
            names = [part for part in re.split(r"And|Or|OrderBy", method.group(1)) if part]
            columns = [name[0].lower() + name[1:] for name in names if name]
            start, end = line_range(text, method.start(), method.end()); ev_id = facts.add_evidence(evidence(rel, start, end, "SPRING_DATA"))
            facts.operations.append({"kind": "READ", "table": repository_entity.group(1), "schema": None, "columns": columns, "evidenceIds": [ev_id], "possible": True})
    # Static Criteria/Specification/QueryDSL paths supplement field use when an
    # entity owner is explicit. Runtime composition remains unresolved.
    query_context = repository_entity.group(1) if repository_entity else None
    # A bare `.get("key")` is common JSON/Map access and has no database
    # meaning.  Accept Criteria API fields only when their owner is explicit;
    # this preserves `root.get("field")` while refusing `payload.get("key")`.
    for match in re.finditer(r"(?:\broot(?:\.get)?|\bpath)\s*\(\s*\"([^\"]+)\"\s*\)|\bQ(\w+)\.\w+\.(\w+)", text):
        column = match.group(1) or match.group(3); owner = match.group(2) or query_context
        start, end = line_range(text, match.start(), match.end()); ev_id = facts.add_evidence(evidence(rel, start, end, "JAVA_QUERY_API"))
        if owner:
            facts.operations.append({"kind": "READ", "table": owner, "schema": None, "columns": [column], "evidenceIds": [ev_id], "possible": True})
        else:
            facts.unresolved.append({"kind": "QUERY_API_CONTEXT", "message": f"Static query field {column} was found but its entity context is ambiguous", "evidenceIds": [ev_id]})
    if re.search(r"\b(?:Specification|CriteriaQuery|BooleanBuilder|QueryWrapper)\b", text) and re.search(r"\b(?:for|while|stream|reflect|Class\.forName)\b", text):
        ev_id = facts.add_evidence(evidence(rel, 1, max(1, text.count("\n") + 1), "JAVA_QUERY_API"))
        facts.unresolved.append({"kind": "DYNAMIC_QUERY_API", "message": "Runtime-composed query expressions cannot be exhaustively resolved statically", "evidenceIds": [ev_id]})
    # Provider references are safe only when their project method contains
    # statically reconstructable SQL (already parsed above).
    for match in re.finditer(r"@(Select|Insert|Update|Delete)Provider\s*\((.*?)\)", text, re.S):
        method = re.search(r"method\s*=\s*\"([^\"]+)\"", match.group(2)); start, end = line_range(text, match.start(), match.end()); ev_id = facts.add_evidence(evidence(rel, start, end, "MYBATIS_PROVIDER"))
        if not method or method.group(1) not in text:
            method_name = method.group(1) if method else "<unknown>"
            facts.unresolved.append({"kind": "MYBATIS_PROVIDER", "message": f"MyBatis Provider target method cannot yet be resolved: {method_name}", "providerMethod": method_name, "evidenceIds": [ev_id]})
    # Native JDBC ResultSet columns are tied to a table only when the file has
    # exactly one statically known SQL table.
    result_columns = []
    for match in re.finditer(r"\.get(?:String|Long|Int|Boolean|Object|BigDecimal|Timestamp)\s*\(\s*\"([^\"]+)\"\s*\)", text):
        result_columns.append((match.group(1), match))
    literal_bindings: dict[str, str] = {}
    for binding in re.finditer(r"\b(?:String|var)\s+(\w+)\s*=\s*(\"(?:\\.|[^\"\\])*\")\s*;", text, re.S):
        values = java_strings(binding.group(2))
        if values: literal_bindings[binding.group(1)] = values[0][0]
    statement_bindings = {match.group(1): match.group(2) for match in re.finditer(r"\b(?:PreparedStatement|var)\s+(\w+)\s*=\s*\w+\.prepareStatement\s*\(\s*(\w+)\s*\)", text)}
    result_bindings = {match.group(1): match.group(2) for match in re.finditer(r"\b(?:ResultSet|var)\s+(\w+)\s*=\s*(\w+)\.executeQuery\s*\(", text)}
    targeted_result_ids: set[int] = set()
    for column, match in result_columns:
        receiver = re.search(r"(\w+)\s*$", text[max(0, match.start() - 80):match.start()])
        result_var = receiver.group(1) if receiver else None; statement_var = result_bindings.get(result_var or ""); sql = literal_bindings.get(statement_bindings.get(statement_var or "", ""))
        tables = [item.group(1) for item in re.finditer(rf"\bfrom\s+({QUALIFIED})", sql or "", re.I)]
        if len(tables) == 1:
            schema, table = split_name(tables[0]); start, end = line_range(text, match.start(), match.end()); ev_id = facts.add_evidence(evidence(rel, start, end, "JDBC_RESULTSET")); obj = facts.add_object(table, schema, ev_id, "CODE"); facts.add_column(obj, default_column(column, ev_id, usages=["RESULT_FIELD"])); targeted_result_ids.add(id(match))
    file_tables = []
    for value, _, _ in java_static_sql_values(text) + [(v, s, e) for v, s, e in java_strings(text) if SQL_WORDS.search(v)]:
        file_tables.extend(strip_identifier(match.group(2)) for match in re.finditer(rf"\b(from|join)\s+({QUALIFIED})", value, re.I))
    if result_columns and len(set(file_tables)) == 1:
        schema, table = split_name(file_tables[0])
        for column, match in result_columns:
            if id(match) in targeted_result_ids: continue
            start, end = line_range(text, match.start(), match.end()); ev_id = facts.add_evidence(evidence(rel, start, end, "JDBC_RESULTSET")); obj = facts.add_object(table, schema, ev_id, "CODE"); facts.add_column(obj, default_column(column, ev_id, usages=["RESULT_FIELD"]))
    # MyBatis-Plus wrapper field references.
    for match in re.finditer(r"(\w+)::get(\w+)", text):
        start, end = line_range(text, match.start(), match.end())
        ev_id = facts.add_evidence(evidence(rel, start, end, "JAVA"))
        facts.operations.append({"kind": "READ", "table": match.group(1), "schema": None, "columns": [match.group(2)[0].lower()+match.group(2)[1:]], "evidenceIds": [ev_id], "possible": True})
    wrapper_types = {m.group(2): m.group(1) for m in re.finditer(r"(?:Lambda)?QueryWrapper\s*<\s*(\w+)\s*>\s+(\w+)", text)}
    for match in re.finditer(r"\b(\w+)\.(eq|ne|gt|ge|lt|le|in|like|orderByAsc|orderByDesc|select|set)\s*\(\s*\"([^\"]+)\"", text):
        owner = wrapper_types.get(match.group(1))
        start, end = line_range(text, match.start(), match.end()); ev_id = facts.add_evidence(evidence(rel, start, end, "MYBATIS_PLUS_WRAPPER"))
        if owner:
            facts.operations.append({"kind": "UPDATE" if match.group(2) == "set" else "READ", "table": owner, "schema": None, "columns": [match.group(3)], "evidenceIds": [ev_id], "possible": True})
        else:
            facts.unresolved.append({"kind": "DYNAMIC_WRAPPER", "message": f"Wrapper field {match.group(3)} has no unambiguous generic entity owner", "evidenceIds": [ev_id]})
    # Dynamic table patterns are unresolved database object patterns.
    for match in re.finditer(r'([A-Za-z_][\w]*)[_-]?["\s]*\+\s*(\w+)', text):
        context = text[max(0, match.start()-80):match.end()+80]
        if SQL_WORDS.search(context):
            start, end = line_range(text, match.start(), match.end())
            ev_id = facts.add_evidence(evidence(rel, start, end, "JAVA_SQL"))
            facts.unresolved.append({"kind": "DYNAMIC_TABLE", "message": f"Runtime database identifier pattern near {match.group(1)}_${{{match.group(2)}}}", "evidenceIds": [ev_id]})


def parse_mapper_xml(text: str, rel: str, facts: Facts) -> None:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        ev_id = facts.add_evidence(evidence(rel, 1, max(1, text.count("\n") + 1), "MYBATIS_XML"))
        facts.unresolved.append({"kind": "XML_PARSE", "message": str(exc), "evidenceIds": [ev_id]})
        return
    tag = root.tag.split("}")[-1]
    if tag != "mapper": return
    namespace = root.attrib.get("namespace", rel)
    ev_id = facts.add_evidence(evidence(rel, 1, 1, "MYBATIS_XML"))
    code_id = stable_id("code", namespace, "MAPPER")
    facts.code_objects[code_id] = {"id": code_id, "qualifiedName": namespace, "role": "MAPPER", "evidenceIds": [ev_id]}
    fragments: dict[str, str] = {}
    result_maps: dict[str, list[dict[str, str]]] = defaultdict(list)
    for child in root:
        if child.tag.split("}")[-1] == "sql" and child.attrib.get("id"):
            fragments[child.attrib["id"]] = " ".join(child.itertext())
        if child.tag.split("}")[-1] == "resultMap" and child.attrib.get("id"):
            for node in child.iter():
                node_tag = node.tag.split("}")[-1]
                target = node.attrib.get("javaType") or node.attrib.get("ofType") or node.attrib.get("resultMap")
                column = node.attrib.get("column")
                if node_tag in {"association", "collection"} and target and column:
                    result_maps[child.attrib["id"]].append({"target": target.split(".")[-1], "column": column, "cardinality": "ONE_TO_MANY" if node_tag == "collection" else "ONE_TO_ONE"})
    for child in root:
        child_tag = child.tag.split("}")[-1]
        if child_tag in {"select", "insert", "update", "delete"}:
            relation_start = len(facts.relation_observations)
            sql = " ".join(child.itertext())
            include_evidence = []
            for include in child.iter():
                if include.tag.split("}")[-1] == "include":
                    sql += " " + fragments.get(include.attrib.get("refid", ""), "")
                    refid = include.attrib.get("refid", ""); include_match = re.search(rf"<sql\b[^>]*\bid\s*=\s*['\"]{re.escape(refid)}['\"]", text, re.I)
                    if include_match:
                        line = line_number(text, include_match.start()); include_evidence.append(facts.add_evidence(evidence(rel, line, line, "MYBATIS_INCLUDE")))
            conditional = bool(child.attrib.get("databaseId")) or any(node.tag.split("}")[-1] in {"if", "choose", "when", "otherwise", "foreach"} for node in child.iter())
            statement_id = child.attrib.get("id")
            opening = re.search(rf"<{child_tag}\b[^>]*\bid\s*=\s*['\"]{re.escape(statement_id or '')}['\"]", text, re.I)
            base_line = line_number(text, opening.start()) - 1 if opening else 0
            parse_sql(sql, rel, facts, conditional=conditional, source="MYBATIS_XML", base_line=base_line)
            if include_evidence:
                for observation in facts.relation_observations[relation_start:]:
                    if observation.get("sourceType") == "SQL_JOIN" and observation.get("evidenceIds"):
                        observation["evidenceIds"] = sorted(set(observation["evidenceIds"] + include_evidence))
            base_table = re.search(rf"\bfrom\s+({QUALIFIED})", sql, re.I)
            for mapping in result_maps.get(child.attrib.get("resultMap", ""), []):
                if base_table:
                    base_schema, base_name = split_name(base_table.group(1)); line = line_number(text, opening.start()) if opening else 1; mapping_ev = facts.add_evidence(evidence(rel, line, line, "MYBATIS_RESULT_MAP"))
                    facts.relation_observations.append({"fromTable": base_name, "fromSchema": base_schema, "fromColumns": [mapping["column"]], "toTable": mapping["target"], "toSchema": None, "toColumns": ["id"], "sourceType": "RESULT_MAPPING", "confidence": "HIGH", "status": "CONDITIONAL" if conditional else "NORMAL", "directionKnown": False, "codeCardinality": mapping["cardinality"], "evidenceIds": [mapping_ev]})
        elif child_tag == "resultMap":
            target_type = child.attrib.get("type", "QUERY_RESULT")
            result_code_id = stable_id("code", target_type, "QUERY_RESULT")
            facts.code_objects[result_code_id] = {"id": result_code_id, "qualifiedName": target_type, "role": "QUERY_RESULT", "evidenceIds": [ev_id]}


def parse_jpa_xml(text: str, rel: str, facts: Facts) -> None:
    if "entity-mappings" not in text and "hibernate-mapping" not in text: return
    try: root = ET.fromstring(text)
    except ET.ParseError: return
    for dynamic in root.iter():
        if dynamic.tag.split("}")[-1] in {"formula", "subselect", "any", "many-to-any"} or dynamic.attrib.get("formula"):
            ev_id = facts.add_evidence(evidence(rel, 1, max(1, text.count("\n") + 1), "ORM_XML")); facts.unresolved.append({"kind": "HIBERNATE_DYNAMIC_MAPPING", "message": "Hibernate XML formula/dynamic mapping was retained as unresolved", "evidenceIds": [ev_id]}); break
    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag in {"entity", "class", "subclass", "joined-subclass"}:
            class_name = node.attrib.get("class") or node.attrib.get("name")
            table = node.attrib.get("table") or (class_name.split(".")[-1] if class_name else None)
            if not class_name or not table: continue
            ev_id = facts.add_evidence(evidence(rel, 1, max(1, text.count("\n")+1), "ORM_XML"))
            code_id = stable_id("code", class_name, "ENTITY")
            facts.code_objects[code_id] = {"id": code_id, "qualifiedName": class_name, "role": "ENTITY", "evidenceIds": [ev_id]}
            obj = facts.add_object(table, node.attrib.get("schema"), ev_id, "CODE")
            facts.mappings.append({"codeObjectId": code_id, "table": table, "schema": node.attrib.get("schema"), "role": "ENTITY", "evidenceIds": [ev_id], "xmlOverride": True})
            for child in node.iter():
                ctag = child.tag.split("}")[-1]
                if ctag in {"id", "basic", "property", "key-property"}:
                    col = child.attrib.get("column") or child.attrib.get("name")
                    if col:
                        pk = ctag in {"id", "key-property"}
                        facts.add_column(obj, default_column(col, ev_id, javaName=child.attrib.get("name"), primaryKey=pk))
                        if pk: obj["primaryKeys"].append([col])
                elif ctag in {"many-to-one", "one-to-one", "many-to-many", "one-to-many"}:
                    target = child.attrib.get("target-entity") or child.attrib.get("class") or child.attrib.get("entity-name")
                    column = child.attrib.get("column")
                    if not column:
                        join = next((item for item in child.iter() if item.tag.split("}")[-1] in {"join-column", "column"}), None)
                        column = join.attrib.get("name") if join is not None else None
                    if target and column:
                        cards = {"many-to-one": "MANY_TO_ONE", "one-to-one": "ONE_TO_ONE", "many-to-many": "MANY_TO_MANY", "one-to-many": "ONE_TO_MANY"}
                        facts.relation_observations.append({"fromTable": table, "fromSchema": node.attrib.get("schema"), "fromColumns": [column], "toTable": target.split(".")[-1], "toSchema": None, "toColumns": [child.attrib.get("referenced-column-name", "id")], "sourceType": "ORM_RELATION", "confidence": "HIGH", "status": "NORMAL", "directionKnown": ctag in {"many-to-one", "one-to-one"}, "codeCardinality": cards[ctag], "optionality": "UNKNOWN", "evidenceIds": [ev_id]})
                elif ctag in {"secondary-table", "join"} and child.attrib.get("table"):
                    secondary = child.attrib["table"]; secondary_obj = facts.add_object(secondary, node.attrib.get("schema"), ev_id, "CODE")
                    key = next((item for item in child.iter() if item.tag.split("}")[-1] in {"primary-key-join-column", "key"}), None)
                    key_name = key.attrib.get("name") or key.attrib.get("column") if key is not None else "id"
                    facts.add_column(secondary_obj, default_column(key_name, ev_id, primaryKey=True, nullable=False)); secondary_obj["primaryKeys"].append([key_name])
                    facts.relation_observations.append({"fromTable": secondary, "fromSchema": node.attrib.get("schema"), "fromColumns": [key_name], "toTable": table, "toSchema": node.attrib.get("schema"), "toColumns": ["id"], "sourceType": "ORM_RELATION", "confidence": "HIGH", "status": "NORMAL", "directionKnown": True, "codeCardinality": "ONE_TO_ONE", "optionality": "REQUIRED", "evidenceIds": [ev_id]})


def parse_liquibase(text: str, rel: str, facts: Facts, suffix: str) -> bool:
    if "databaseChangeLog" not in text and "databasechangelog" not in text.lower(): return False
    if suffix == ".xml":
        try: root = ET.fromstring(text)
        except ET.ParseError as exc:
            ev_id = facts.add_evidence(evidence(rel, 1, max(1, text.count("\n")+1), "LIQUIBASE"))
            facts.unresolved.append({"kind": "LIQUIBASE_PARSE", "message": str(exc), "evidenceIds": [ev_id]}); return True
        for parent in root.iter():
            for child in list(parent):
                if child.tag.split("}")[-1] == "rollback": parent.remove(child)
        conditional_nodes: set[Any] = set()
        for change_set in root.iter():
            if change_set.tag.split("}")[-1] == "changeSet" and (change_set.attrib.get("context") or change_set.attrib.get("contextFilter") or change_set.attrib.get("dbms")):
                conditional_nodes.update(change_set.iter())
        for node in root.iter():
            tag = node.tag.split("}")[-1]
            ev_id = facts.add_evidence(evidence(rel, 1, max(1, text.count("\n")+1), "LIQUIBASE"))
            conditional = node in conditional_nodes
            if tag == "createTable" and node.attrib.get("tableName"):
                table = node.attrib["tableName"]; obj = facts.add_object(table, node.attrib.get("schemaName"), ev_id, "DDL")
                for col in node:
                    if col.tag.split("}")[-1] != "column": continue
                    constraints = next((c for c in col if c.tag.split("}")[-1] == "constraints"), None)
                    pk = constraints is not None and constraints.attrib.get("primaryKey") == "true"
                    unique = constraints is not None and constraints.attrib.get("unique") == "true"
                    nullable = None if constraints is None or "nullable" not in constraints.attrib else constraints.attrib["nullable"] == "true"
                    facts.add_column(obj, default_column(col.attrib.get("name", "unknown"), ev_id, databaseType=col.attrib.get("type"), primaryKey=pk, unique=unique, nullable=nullable))
                    if pk: obj["primaryKeys"].append([col.attrib.get("name", "unknown")])
            elif tag == "addForeignKeyConstraint":
                facts.relation_observations.append({"fromTable": node.attrib.get("baseTableName", "unknown"), "fromSchema": node.attrib.get("baseTableSchemaName"), "fromColumns": [x.strip() for x in node.attrib.get("baseColumnNames", "").split(",") if x.strip()], "toTable": node.attrib.get("referencedTableName", "unknown"), "toSchema": node.attrib.get("referencedTableSchemaName"), "toColumns": [x.strip() for x in node.attrib.get("referencedColumnNames", "").split(",") if x.strip()], "constraintName": node.attrib.get("constraintName"), "sourceType": "DDL_FOREIGN_KEY", "confidence": "HIGH", "status": "CONDITIONAL" if conditional else "NORMAL", "directionKnown": True, "evidenceIds": [ev_id]})
            elif tag in {"customChange", "customPrecondition"}:
                facts.unresolved.append({"kind": "LIQUIBASE_CUSTOM_CHANGE", "message": "Custom Liquibase Java change cannot be evaluated statically", "evidenceIds": [ev_id]})
            elif tag == "sql":
                parse_sql(" ".join(node.itertext()), rel, facts, conditional=conditional, source="LIQUIBASE")
            elif tag in {"dropTable", "addColumn", "dropColumn", "renameColumn", "renameTable"} and node.attrib.get("tableName"):
                event = {"event": {"dropTable": "DROP_TABLE", "addColumn": "ADD_COLUMN", "dropColumn": "DROP_COLUMN", "renameColumn": "RENAME_COLUMN", "renameTable": "RENAME_TABLE"}[tag], "schema": node.attrib.get("schemaName"), "table": node.attrib["tableName"], "evidenceId": ev_id}
                if tag == "addColumn":
                    columns = [child for child in node if child.tag.split("}")[-1] == "column"]
                    if not columns: continue
                    for column in columns:
                        facts.ddl_events.append(event | {"column": column.attrib.get("name", "unknown"), "databaseType": column.attrib.get("type")})
                    continue
                elif tag == "dropColumn": event["column"] = node.attrib.get("columnName", "unknown")
                elif tag == "renameColumn": event.update({"column": node.attrib.get("oldColumnName", "unknown"), "newColumn": node.attrib.get("newColumnName", "unknown")})
                elif tag == "renameTable": event.update({"newSchema": node.attrib.get("schemaName"), "newTable": node.attrib.get("newTableName", "unknown")})
                facts.ddl_events.append(event)
            elif tag == "dropForeignKeyConstraint" and node.attrib.get("baseTableName"):
                facts.ddl_events.append({"event": "DROP_FOREIGN_KEY", "schema": node.attrib.get("baseTableSchemaName"), "table": node.attrib["baseTableName"], "constraintName": node.attrib.get("constraintName", ""), "evidenceId": ev_id})
            elif tag in {"addPrimaryKey", "addUniqueConstraint"} and node.attrib.get("tableName"):
                obj = facts.add_object(node.attrib["tableName"], node.attrib.get("schemaName"), ev_id, "DDL"); columns = [value.strip() for value in node.attrib.get("columnNames", "").split(",") if value.strip()]
                if tag == "addPrimaryKey":
                    obj["primaryKeys"].append(columns)
                    for column in columns: facts.add_column(obj, default_column(column, ev_id, primaryKey=True, nullable=False))
                else:
                    obj["uniqueConstraints"].append(columns)
                    for column in columns: facts.add_column(obj, default_column(column, ev_id, unique=True))
        return True
    if suffix == ".json":
        try:
            payload = json.loads(text)
        except ValueError as exc:
            ev_id = facts.add_evidence(evidence(rel, 1, max(1, text.count("\n") + 1), "LIQUIBASE")); facts.unresolved.append({"kind": "LIQUIBASE_PARSE", "message": str(exc), "evidenceIds": [ev_id]}); return True
        def walk(value: Any) -> Iterator[dict[str, Any]]:
            if isinstance(value, dict):
                yield value
                for nested in value.values(): yield from walk(nested)
            elif isinstance(value, list):
                for nested in value: yield from walk(nested)
        for node in walk(payload):
            create = node.get("createTable")
            if isinstance(create, dict) and create.get("tableName"):
                ev_id = facts.add_evidence(evidence(rel, 1, max(1, text.count("\n") + 1), "LIQUIBASE")); obj = facts.add_object(create["tableName"], create.get("schemaName"), ev_id, "DDL")
                for item in create.get("columns", []):
                    column = item.get("column", item) if isinstance(item, dict) else {}
                    if isinstance(column, dict) and column.get("name"):
                        constraints = column.get("constraints", {}) if isinstance(column.get("constraints", {}), dict) else {}
                        pk = constraints.get("primaryKey") is True; unique = constraints.get("unique") is True
                        facts.add_column(obj, default_column(column["name"], ev_id, databaseType=column.get("type"), primaryKey=pk, unique=unique, nullable=constraints.get("nullable")))
                        if pk: obj["primaryKeys"].append([column["name"]])
            foreign = node.get("addForeignKeyConstraint")
            if isinstance(foreign, dict) and foreign.get("baseTableName") and foreign.get("referencedTableName"):
                ev_id = facts.add_evidence(evidence(rel, 1, max(1, text.count("\n") + 1), "LIQUIBASE"))
                facts.relation_observations.append({"fromTable": foreign["baseTableName"], "fromSchema": foreign.get("baseTableSchemaName"), "fromColumns": [x.strip() for x in foreign.get("baseColumnNames", "").split(",") if x.strip()], "toTable": foreign["referencedTableName"], "toSchema": foreign.get("referencedTableSchemaName"), "toColumns": [x.strip() for x in foreign.get("referencedColumnNames", "").split(",") if x.strip()], "constraintName": foreign.get("constraintName"), "sourceType": "DDL_FOREIGN_KEY", "confidence": "HIGH", "status": "NORMAL", "directionKnown": True, "evidenceIds": [ev_id]})
            for key, event_name in (("dropTable", "DROP_TABLE"), ("dropColumn", "DROP_COLUMN"), ("renameColumn", "RENAME_COLUMN"), ("renameTable", "RENAME_TABLE")):
                change = node.get(key)
                if not isinstance(change, dict) or not change.get("tableName"): continue
                ev_id = facts.add_evidence(evidence(rel, 1, max(1, text.count("\n") + 1), "LIQUIBASE")); event = {"event": event_name, "schema": change.get("schemaName"), "table": change["tableName"], "evidenceId": ev_id}
                if key == "dropColumn": event["column"] = change.get("columnName", "unknown")
                if key == "renameColumn": event.update({"column": change.get("oldColumnName", "unknown"), "newColumn": change.get("newColumnName", "unknown")})
                if key == "renameTable": event.update({"newSchema": change.get("schemaName"), "newTable": change.get("newTableName", "unknown")})
                facts.ddl_events.append(event)
        return True
    # Safe indentation-aware subset for ordinary Liquibase YAML. Unknown YAML
    # features remain explicit instead of requiring or installing PyYAML.
    blocks = list(re.finditer(r"(?m)^\s*-?\s*(createTable|addForeignKeyConstraint|addColumn|dropColumn|dropTable|renameColumn|renameTable|addPrimaryKey|addUniqueConstraint)\s*:\s*$", text))
    for index, block in enumerate(blocks):
        chunk = text[block.end():blocks[index + 1].start() if index + 1 < len(blocks) else len(text)]
        attrs = {m.group(1): m.group(2).strip().strip("'\"") for m in re.finditer(r"(?m)^\s+([A-Za-z]\w*)\s*:\s*([^\n#]+)", chunk)}
        tag = block.group(1); ev_id = facts.add_evidence(evidence(rel, line_number(text, block.start()), line_number(text, block.end()), "LIQUIBASE"))
        table = attrs.get("tableName") or attrs.get("baseTableName")
        if tag == "createTable" and table:
            obj = facts.add_object(table, attrs.get("schemaName"), ev_id, "DDL")
            for col_block in re.finditer(r"(?ms)^\s*-\s*column\s*:\s*(.*?)(?=^\s*-\s*column\s*:|\Z)", chunk):
                col_attrs = {m.group(1): m.group(2).strip().strip("'\"") for m in re.finditer(r"(?m)^\s+([A-Za-z]\w*)\s*:\s*([^\n#]+)", col_block.group(1))}
                if col_attrs.get("name"): facts.add_column(obj, default_column(col_attrs["name"], ev_id, databaseType=col_attrs.get("type")))
        elif tag == "addForeignKeyConstraint" and table and attrs.get("referencedTableName"):
            facts.relation_observations.append({"fromTable": table, "fromSchema": attrs.get("baseTableSchemaName"), "fromColumns": [x.strip() for x in attrs.get("baseColumnNames", "").split(",") if x.strip()], "toTable": attrs["referencedTableName"], "toSchema": attrs.get("referencedTableSchemaName"), "toColumns": [x.strip() for x in attrs.get("referencedColumnNames", "").split(",") if x.strip()], "constraintName": attrs.get("constraintName"), "sourceType": "DDL_FOREIGN_KEY", "confidence": "HIGH", "status": "NORMAL", "directionKnown": True, "evidenceIds": [ev_id]})
        elif table and tag in {"dropColumn", "dropTable", "renameColumn", "renameTable", "addColumn"}:
            event = {"event": {"dropColumn": "DROP_COLUMN", "dropTable": "DROP_TABLE", "renameColumn": "RENAME_COLUMN", "renameTable": "RENAME_TABLE", "addColumn": "ADD_COLUMN"}[tag], "schema": attrs.get("schemaName"), "table": table, "evidenceId": ev_id}
            if tag in {"dropColumn", "addColumn"}: event["column"] = attrs.get("columnName") or attrs.get("name", "unknown")
            if tag == "addColumn": event["databaseType"] = attrs.get("type")
            if tag == "renameColumn": event.update({"column": attrs.get("oldColumnName", "unknown"), "newColumn": attrs.get("newColumnName", "unknown")})
            if tag == "renameTable": event.update({"newSchema": attrs.get("schemaName"), "newTable": attrs.get("newTableName", "unknown")})
            facts.ddl_events.append(event)
    if "customChange" in text:
        ev_id = facts.add_evidence(evidence(rel, 1, max(1, text.count("\n")+1), "LIQUIBASE"))
        facts.unresolved.append({"kind": "LIQUIBASE_CUSTOM_CHANGE", "message": "Custom Liquibase change cannot be evaluated statically", "evidenceIds": [ev_id]})
    return True


def analyze_file(path: Path, root: Path) -> Fragment:
    data = path.read_bytes(); text = data.decode("utf-8", errors="replace"); rel = path.relative_to(root).as_posix()
    local = Facts(); suffix = path.suffix.lower(); lower_name = path.name.lower()
    try:
        if suffix == ".java": parse_java(text, rel, local)
        elif suffix == ".xml":
            if not parse_liquibase(text, rel, local, suffix):
                parse_mapper_xml(text, rel, local); parse_jpa_xml(text, rel, local)
            if "<mapper" not in text.lower() and SQL_WORDS.search(text):
                parse_sql(text, rel, local, source="XML_SQL")
        elif suffix in {".sql", ".ddl"}: parse_sql(text, rel, local, source="MIGRATION" if "migration" in rel.lower() or re.match(r"[vr]\d+.*__", lower_name) else "SQL")
        elif suffix in {".yml", ".yaml", ".json"}: parse_liquibase(text, rel, local, suffix)
    except Exception as exc:  # A parser failure must be explicit and file-local.
        ev_id = local.add_evidence(evidence(rel, 1, max(1, text.count("\n")+1), "PARSER"))
        local.unresolved.append({"kind": "PARSER_FAILURE", "message": f"{type(exc).__name__}: {exc}", "evidenceIds": [ev_id]})
    observations: list[dict[str, Any]] = []
    observations += [{"kind": "evidence", "value": ev} for ev in local.evidence.values()]
    for (schema, _), obj in local.objects.items():
        serial = dict(obj); serial["sources"] = sorted(obj["sources"]); serial["evidenceIds"] = sorted(obj["evidenceIds"]); serial["columns"] = list(obj["columns"].values())
        observations.append({"kind": "databaseObject", "schema": schema, "value": serial})
    observations += [{"kind": "codeObject", "value": v} for v in local.code_objects.values()]
    observations += [{"kind": "mapping", "value": v} for v in local.mappings]
    observations += [{"kind": "operation", "value": v} for v in local.operations]
    observations += [{"kind": "relationship", "value": v} for v in local.relation_observations]
    observations += [{"kind": "ddlEvent", "value": v} for v in local.ddl_events]
    return Fragment(rel, sha256_bytes(data), observations, local.unresolved)


def verify_java_syntax_with_jdk(files: list[Path]) -> str | None:
    """Parse Java syntax with the local JDK helper without compiling the project."""
    java = shutil.which("java")
    javac = shutil.which("javac")
    java_files = [path for path in files if path.suffix.lower() == ".java"]
    if not java_files:
        return None
    if not java or not javac:
        return "Local JDK is unavailable; Java syntax verification was skipped."
    helper = Path(__file__).resolve().parents[1] / "java" / "SourceFactExtractor.java"
    if not helper.is_file():
        return "Bundled JDK source parser is missing."
    try:
        with tempfile.TemporaryDirectory(prefix="java-code-to-erd-jdk-") as directory:
            compile_result = subprocess.run(
                [javac, "-d", directory, str(helper)],
                capture_output=True, text=True, check=False, timeout=60,
            )
            if compile_result.returncode != 0:
                return "Bundled JDK source parser could not be compiled by the local JDK."
            # Batching avoids command-line length limits without imposing a scan cap.
            for start in range(0, len(java_files), 100):
                result = subprocess.run(
                    [java, "-cp", directory, "SourceFactExtractor", *[str(p) for p in java_files[start:start + 100]]],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                    check=False, timeout=120,
                )
                if result.returncode != 0 or " error:" in result.stderr.lower():
                    return "The local JDK could not parse one or more Java source files; regex-based reliable facts were retained."
    except (OSError, subprocess.SubprocessError):
        return "The local JDK source verification failed; regex-based reliable facts were retained."
    return None


def migration_inventory_issues(root: Path, files: list[Path]) -> list[dict[str, Any]]:
    issues = []
    flyway_versions: dict[tuple[str, str], list[str]] = defaultdict(list)
    has_flyway = False; has_liquibase = False
    rel_paths = {path.relative_to(root).as_posix() for path in files}
    include_graph: dict[str, set[str]] = defaultdict(set)
    for path in files:
        rel = path.relative_to(root).as_posix(); name = path.name
        version = re.match(r"V([0-9][0-9._-]*)__", name, re.I)
        if version:
            has_flyway = True; flyway_versions[(path.parent.relative_to(root).as_posix(), version.group(1))].append(rel)
        text = read_text(path) if path.stat().st_size < 2_000_000 else ""
        if re.match(r"R__", name, re.I):
            has_flyway = True
            if re.search(r"\b(?:alter|drop|rename|truncate)\b", text, re.I):
                issues.append({"kind": "FLYWAY_REPEATABLE_ORDER", "message": f"Repeatable migration has stateful DDL whose repeated application cannot be proven safe: {rel}", "evidence": evidence(rel, 1, max(1, text.count("\n") + 1), "MIGRATION")})
        if "databaseChangeLog" in text or "databasechangelog" in text.lower():
            has_liquibase = True
            for match in re.finditer(r"(?:file|path)\s*=\s*['\"]([^'\"]+)['\"]|(?:file|path)\s*:\s*([^\s]+)", text, re.I):
                reference = (match.group(1) or match.group(2)).strip().strip("'\"")
                target = (path.parent / reference).resolve()
                try: target_rel = target.relative_to(root).as_posix()
                except ValueError: target_rel = ""
                if not target_rel or target_rel not in rel_paths:
                    ev_id = stable_id("ev", rel, line_number(text, match.start()), "LIQUIBASE_INCLUDE")
                    issues.append({"kind": "LIQUIBASE_INCLUDE_MISSING", "message": f"Liquibase include cannot be resolved: {reference}", "evidence": evidence(rel, line_number(text, match.start()), line_number(text, match.end()), "LIQUIBASE_INCLUDE") | {"id": ev_id}})
                else:
                    include_graph[rel].add(target_rel)
            for match in re.finditer(r"includeAll\b[^>]*\bpath\s*=\s*['\"]([^'\"]+)['\"]|includeAll\s*:\s*\n?\s*path\s*:\s*([^\s]+)", text, re.I):
                reference = (match.group(1) or match.group(2)).strip().strip("'\"")
                directory = (path.parent / reference).resolve()
                try: directory.relative_to(root)
                except ValueError: directory = Path("/__outside_project__")
                children = sorted(candidate for candidate in files if candidate.parent == directory and candidate.suffix.lower() in {".xml", ".yml", ".yaml", ".json", ".sql"})
                if not children:
                    issues.append({"kind": "LIQUIBASE_INCLUDE_ALL_MISSING", "message": f"Liquibase includeAll directory cannot be resolved or is empty: {reference}", "evidence": evidence(rel, line_number(text, match.start()), line_number(text, match.end()), "LIQUIBASE_INCLUDE")})
                for child in children: include_graph[rel].add(child.relative_to(root).as_posix())
    for (_, version), paths in sorted(flyway_versions.items()):
        if len(paths) > 1:
            issues.append({"kind": "FLYWAY_VERSION_CONFLICT", "message": f"Flyway version {version} is declared more than once: {', '.join(sorted(paths))}", "evidence": None})
    if has_flyway and has_liquibase:
        issues.append({"kind": "MIGRATION_TOOL_ORDER", "message": "Flyway and Liquibase are both present; their cross-tool execution order cannot be proven statically", "evidence": None})
    visiting: set[str] = set(); visited: set[str] = set()
    def visit(node: str, chain: list[str]) -> None:
        if node in visiting:
            cycle = chain[chain.index(node):] + [node] if node in chain else chain + [node]
            issues.append({"kind": "LIQUIBASE_INCLUDE_CYCLE", "message": "Liquibase include cycle: " + " -> ".join(cycle), "evidence": None}); return
        if node in visited: return
        visiting.add(node)
        for child in sorted(include_graph.get(node, set())): visit(child, chain + [child])
        visiting.remove(node); visited.add(node)
    for node in sorted(include_graph): visit(node, [node])
    return issues


def infer_project_value_flows(root: Path, files: list[Path], facts: Facts) -> None:
    entity_tables: dict[str, str] = {}
    for mapping in facts.mappings:
        code = facts.code_objects.get(mapping["codeObjectId"], {})
        if code.get("role") == "ENTITY": entity_tables[code.get("qualifiedName", "").split(".")[-1].lower()] = mapping["table"]
    for path in files:
        if path.suffix.lower() != ".java": continue
        text = read_text(path); rel = path.relative_to(root).as_posix()
        declarations = {match.group(2): re.sub(r"<.*>", "", match.group(1)).split(".")[-1] for match in re.finditer(r"\b([A-Z]\w*(?:<[^;=]+>)?)\s+([a-zA-Z_]\w*)\s*(?:[;=,)])", text)}
        pattern = re.compile(r"\b(\w+)\.(?:find|read|get|select|count|exists)\w*By([A-Z]\w*)\s*\(\s*(\w+)\.get([A-Z]\w*)\s*\(\s*\)\s*\)")
        for match in pattern.finditer(text):
            receiver, query_suffix, source_var, getter = match.groups()
            target_type = declarations.get(receiver) or receiver[:1].upper() + receiver[1:]
            target_type = re.sub(r"(?:Mapper|Repository|Dao|DAO)$", "", target_type)
            source_type = declarations.get(source_var) or source_var[:1].upper() + source_var[1:]
            target_table = entity_tables.get(target_type.lower()); source_table = entity_tables.get(source_type.lower())
            if not target_table or not source_table: continue
            query_field = re.split(r"And|Or|OrderBy", query_suffix)[0]
            target_column = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", query_field).lower()
            source_column = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", getter).lower()
            start, end = line_range(text, match.start(), match.end()); ev_id = facts.add_evidence(evidence(rel, start, end, "JAVA_VALUE_FLOW"))
            facts.relation_observations.append({"fromTable": target_table, "fromSchema": None, "fromColumns": [target_column], "toTable": source_table, "toSchema": None, "toColumns": [source_column], "sourceType": "CODE_INFERRED", "confidence": "MEDIUM", "status": "NORMAL", "directionKnown": True, "evidenceIds": [ev_id]})

    # Bounded interprocedural propagation for the common getter -> service
    # parameter -> repository/mapper query chain. Labels are propagated only
    # through project methods with a unique name/arity target. Multiple source
    # labels deliberately stop confirmation rather than being voted on.
    methods = []
    for path in files:
        if path.suffix.lower() != ".java": continue
        text = simple_java_annotations(read_text(path)); rel = path.relative_to(root).as_posix()
        class_match = re.search(r"\bclass\s+(\w+)", text); class_name = class_match.group(1) if class_match else path.stem
        class_fields = {match.group(2): re.sub(r"<.*>", "", match.group(1)).split(".")[-1] for match in re.finditer(r"\b([A-Z]\w*(?:<[^;=]+>)?)\s+(\w+)\s*;", text)}
        method_re = re.compile(r"(?:public|protected|private|static|final|synchronized|\s)+[\w.<>, ?\[\]]+\s+(\w+)\s*\(([^)]*)\)\s*(?:throws[^\{]+)?\{", re.M)
        for match in method_re.finditer(text):
            depth = 1; cursor = match.end()
            while cursor < len(text) and depth:
                if text[cursor] == "{": depth += 1
                elif text[cursor] == "}": depth -= 1
                cursor += 1
            if depth: continue
            params = []
            for raw in split_top_level_csv(match.group(2)):
                parsed = re.search(r"([\w.<>, ?\[\]]+)\s+(\w+)\s*$", re.sub(r"@\w+(?:\([^)]*\))?", "", raw).strip())
                if parsed: params.append((re.sub(r"<.*>", "", parsed.group(1)).split(".")[-1].strip(), parsed.group(2)))
            methods.append({"key": (class_name, match.group(1), len(params)), "name": match.group(1), "params": params, "body": text[match.end():cursor-1], "bodyOffset": match.end(), "text": text, "file": rel, "fields": class_fields})
    by_signature: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for method in methods: by_signature[(method["name"], len(method["params"]))].append(method)
    labels: dict[tuple[tuple[str, str, int], int], set[tuple[str, str, tuple[str, ...]]]] = defaultdict(set)

    def value_label(method: dict[str, Any], value: str, locals_map: dict[str, set[tuple[str, str, tuple[str, ...]]]], call_start: int) -> set[tuple[str, str, tuple[str, ...]]]:
        value = value.strip()
        if value in locals_map: return locals_map[value]
        getter = re.fullmatch(r"(\w+)\.get([A-Z]\w*)\s*\(\s*\)", value)
        if getter:
            variable, suffix = getter.groups(); declared = {name: kind for kind, name in method["params"]} | method["fields"]
            source_table = entity_tables.get(declared.get(variable, "").lower())
            if source_table:
                column = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", suffix).lower(); line = line_number(method["text"], method["bodyOffset"] + call_start)
                ev_id = facts.add_evidence(evidence(method["file"], line, line, "JAVA_VALUE_FLOW")); return {(source_table, column, (ev_id,))}
        return set()

    emitted: set[tuple[Any, ...]] = set()
    for _ in range(max(1, min(50, len(methods) * 2))):
        changed = False
        for method in methods:
            local_labels = {name: set(labels.get((method["key"], index), set())) for index, (_, name) in enumerate(method["params"])}
            for assignment in re.finditer(r"\b(?:[\w.<>, ?\[\]]+\s+)?(\w+)\s*=\s*([^;]+);", method["body"]):
                found = value_label(method, assignment.group(2), local_labels, assignment.start())
                if found: local_labels[assignment.group(1)] = set(found)
            for call in re.finditer(r"\b(\w+)\.(\w+)\s*\(([^;{}]*)\)", method["body"]):
                receiver, called, raw_args = call.groups(); args = split_top_level_csv(raw_args) if raw_args.strip() else []
                arg_labels = [value_label(method, arg, local_labels, call.start()) for arg in args]
                query = re.match(r"(?:find|read|get|select|count|exists)\w*By([A-Z]\w*)", called)
                if query and arg_labels:
                    receiver_type = method["fields"].get(receiver) or receiver[:1].upper() + receiver[1:]
                    target_type = re.sub(r"(?:Mapper|Repository|Dao|DAO)$", "", receiver_type); target_table = entity_tables.get(target_type.lower())
                    if target_table and len(arg_labels[0]) == 1:
                        source_table, source_column, source_evidence = next(iter(arg_labels[0])); target_column = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", re.split(r"And|Or|OrderBy", query.group(1))[0]).lower(); line = line_number(method["text"], method["bodyOffset"] + call.start()); sink_ev = facts.add_evidence(evidence(method["file"], line, line, "JAVA_VALUE_FLOW")); identity = (target_table, target_column, source_table, source_column)
                        if identity not in emitted:
                            facts.relation_observations.append({"fromTable": target_table, "fromSchema": None, "fromColumns": [target_column], "toTable": source_table, "toSchema": None, "toColumns": [source_column], "sourceType": "CODE_INFERRED", "confidence": "MEDIUM", "status": "NORMAL", "directionKnown": True, "evidenceIds": sorted(set(source_evidence + (sink_ev,))) }); emitted.add(identity)
                    continue
                targets = by_signature.get((called, len(args)), [])
                if len(targets) != 1: continue
                target = targets[0]
                for index, found in enumerate(arg_labels):
                    if not found: continue
                    node = (target["key"], index); before = len(labels[node]); labels[node].update(found)
                    if len(labels[node]) != before: changed = True
        if not changed: break


def resolve_project_provider_targets(files: list[Path], facts: Facts) -> None:
    java_text = "\n".join(read_text(path) for path in files if path.suffix.lower() == ".java")
    retained = []
    for item in facts.unresolved:
        if item.get("kind") != "MYBATIS_PROVIDER":
            retained.append(item); continue
        method = item.get("providerMethod")
        if not method or method == "<unknown>" or not re.search(rf"\b{re.escape(method)}\s*\(", java_text):
            retained.append(item)
    facts.unresolved = retained


def fragment_order(fragment: dict[str, Any]) -> tuple[Any, ...]:
    path = Path(fragment["file"])
    match = re.match(r"V([0-9][0-9._-]*)__", path.name, re.I)
    if match:
        version = tuple(int(value) for value in re.split(r"[._-]", match.group(1)) if value)
        return (path.parent.as_posix(), 0, version, path.name.lower())
    if re.match(r"R__", path.name, re.I):
        return (path.parent.as_posix(), 2, (), path.name.lower())
    return (path.parent.as_posix(), 1, (), path.name.lower())


def apply_ddl_event(facts: Facts, event: dict[str, Any]) -> None:
    key = facts.object_key(event.get("schema"), event["table"])
    obj = facts.objects.get(key)
    kind = event["event"]
    if kind == "DROP_TABLE":
        facts.deleted_objects[key] = event["evidenceId"]
        facts.objects.pop(key, None)
        facts.relation_observations = [
            relation for relation in facts.relation_observations
            if not ((relation["fromTable"].lower() == event["table"].lower() and relation.get("fromSchema") == event.get("schema")) or (relation["toTable"].lower() == event["table"].lower() and relation.get("toSchema") == event.get("schema")))
        ]
        return
    if obj is None:
        obj = facts.add_object(event["table"], event.get("schema"), event["evidenceId"], "DDL")
    facts.deleted_objects.pop(key, None)
    obj["evidenceIds"].add(event["evidenceId"])
    if kind == "RENAME_TABLE":
        old_name = obj["name"]
        old_schema = obj.get("schema")
        facts.objects.pop(key, None)
        obj["historicalNames"].append(obj["name"])
        obj["name"] = event["newTable"]
        obj["schema"] = event.get("newSchema")
        facts.objects[facts.object_key(obj.get("schema"), obj["name"])] = obj
        for relation in facts.relation_observations:
            if relation["fromTable"].lower() == old_name.lower() and relation.get("fromSchema") == old_schema:
                relation["fromTable"] = obj["name"]; relation["fromSchema"] = obj.get("schema")
            if relation["toTable"].lower() == old_name.lower() and relation.get("toSchema") == old_schema:
                relation["toTable"] = obj["name"]; relation["toSchema"] = obj.get("schema")
    elif kind == "ADD_COLUMN":
        facts.deleted_columns.discard((event.get("schema"), event["table"].lower(), event["column"].lower()))
        facts.add_column(obj, default_column(event["column"], event["evidenceId"], databaseType=event.get("databaseType")))
    elif kind == "DROP_COLUMN":
        facts.deleted_columns.add((event.get("schema"), event["table"].lower(), event["column"].lower()))
        obj["columns"].pop(event["column"].lower(), None)
        obj["primaryKeys"] = [key_cols for key_cols in obj["primaryKeys"] if event["column"] not in key_cols]
        obj["uniqueConstraints"] = [key_cols for key_cols in obj["uniqueConstraints"] if event["column"] not in key_cols]
        facts.relation_observations = [relation for relation in facts.relation_observations if not (relation["fromTable"].lower() == obj["name"].lower() and event["column"].lower() in {c.lower() for c in relation.get("fromColumns", [])})]
    elif kind == "RENAME_COLUMN":
        facts.deleted_columns.add((event.get("schema"), event["table"].lower(), event["column"].lower()))
        facts.deleted_columns.discard((event.get("schema"), event["table"].lower(), event["newColumn"].lower()))
        column = obj["columns"].pop(event["column"].lower(), None)
        if column:
            column["name"] = event["newColumn"]
            column["evidenceIds"] = sorted(set(column["evidenceIds"] + [event["evidenceId"]]))
            obj["columns"][event["newColumn"].lower()] = column
        for collection in (obj["primaryKeys"], obj["uniqueConstraints"]):
            for columns in collection:
                for index, name in enumerate(columns):
                    if name.lower() == event["column"].lower(): columns[index] = event["newColumn"]
        for relation in facts.relation_observations:
            if relation["fromTable"].lower() == obj["name"].lower():
                relation["fromColumns"] = [event["newColumn"] if name.lower() == event["column"].lower() else name for name in relation.get("fromColumns", [])]
            if relation["toTable"].lower() == obj["name"].lower():
                relation["toColumns"] = [event["newColumn"] if name.lower() == event["column"].lower() else name for name in relation.get("toColumns", [])]
    elif kind == "DROP_FOREIGN_KEY":
        constraint = event.get("constraintName", "").lower()
        facts.relation_observations = [
            relation for relation in facts.relation_observations
            if not (
                relation.get("sourceType") == "DDL_FOREIGN_KEY"
                and relation["fromTable"].lower() == obj["name"].lower()
                and (relation.get("constraintName") or "").lower() == constraint
            )
        ]


def merge_fragments(fragments: list[dict[str, Any]]) -> Facts:
    facts = Facts()
    for fragment in sorted(fragments, key=fragment_order):
        for obs in fragment.get("observations", []):
            kind, value = obs.get("kind"), obs.get("value", {})
            if kind == "evidence": facts.evidence[value["id"]] = value
            elif kind == "databaseObject":
                obj = facts.add_object(value["name"], value.get("schema"), next(iter(value.get("evidenceIds", [])), stable_id("ev", fragment["file"])), next(iter(value.get("sources", ["CODE"]))), value.get("objectType", "TABLE"), value.get("dynamicPattern"))
                obj["sources"].update(value.get("sources", [])); obj["evidenceIds"].update(value.get("evidenceIds", []))
                for col in value.get("columns", []): facts.add_column(obj, col)
                for key in ("primaryKeys", "uniqueConstraints", "indexes", "historicalNames", "possibleNames", "synonyms"):
                    for item in value.get(key, []):
                        if item not in obj[key]: obj[key].append(item)
            elif kind == "codeObject":
                current = facts.code_objects.get(value["id"])
                if current:
                    current["evidenceIds"] = sorted(set(current.get("evidenceIds", []) + value.get("evidenceIds", [])))
                    existing_fields = {(field.get("javaName"), field.get("column")): field for field in current.get("mappedFields", [])}
                    for mapped in value.get("mappedFields", []): existing_fields[(mapped.get("javaName"), mapped.get("column"))] = mapped
                    if existing_fields: current["mappedFields"] = list(existing_fields.values())
                    for key in ("superClass", "inheritanceStrategy"):
                        if value.get(key): current[key] = value[key]
                else:
                    facts.code_objects[value["id"]] = value
            elif kind == "mapping": facts.mappings.append(value)
            elif kind == "operation": facts.operations.append(value)
            elif kind == "relationship": facts.relation_observations.append(value)
            elif kind == "ddlEvent": apply_ddl_event(facts, value)
        facts.unresolved.extend(fragment.get("unresolved", []))
    return facts


def apply_jpa_xml_overrides(facts: Facts) -> None:
    override_codes = {mapping["codeObjectId"] for mapping in facts.mappings if mapping.get("xmlOverride")}
    if not override_codes: return
    superseded = [mapping for mapping in facts.mappings if mapping["codeObjectId"] in override_codes and not mapping.get("xmlOverride")]
    facts.mappings = [mapping for mapping in facts.mappings if mapping["codeObjectId"] not in override_codes or mapping.get("xmlOverride")]
    active_keys = {facts.object_key(mapping.get("schema"), mapping["table"]) for mapping in facts.mappings}
    for mapping in superseded:
        key = facts.object_key(mapping.get("schema"), mapping["table"]); obj = facts.objects.get(key)
        if obj and key not in active_keys and obj.get("sources") == {"CODE"}:
            facts.objects.pop(key, None)


def apply_jpa_structural_fields(facts: Facts) -> None:
    by_simple: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for code in facts.code_objects.values():
        by_simple[code["qualifiedName"].split(".")[-1]].append(code)

    def expanded_fields(code: dict[str, Any], seen: set[str]) -> list[dict[str, Any]]:
        if code["id"] in seen: return []
        seen = set(seen) | {code["id"]}; fields = list(code.get("mappedFields", []))
        parent_name = (code.get("superClass") or "").split(".")[-1]
        parents = by_simple.get(parent_name, [])
        if len(parents) == 1 and parents[0].get("role") == "MAPPED_SUPERCLASS": fields = expanded_fields(parents[0], seen) + fields
        output = []
        for field in fields:
            if field.get("embedded"):
                embedded = by_simple.get(re.sub(r"<.*>", "", field["javaType"]).split(".")[-1], [])
                if len(embedded) == 1 and embedded[0].get("role") == "EMBEDDABLE":
                    for nested in expanded_fields(embedded[0], seen):
                        nested = dict(nested)
                        override = field.get("overrides", {}).get(nested.get("javaName"))
                        if override: nested["column"] = override
                        if field.get("primaryKey"): nested["primaryKey"] = True
                        output.append(nested)
                    continue
            output.append(field)
        return output

    for mapping in facts.mappings:
        code = facts.code_objects.get(mapping["codeObjectId"])
        if not code or code.get("role") != "ENTITY": continue
        obj = facts.objects.get(facts.object_key(mapping.get("schema"), mapping["table"]))
        if not obj: continue
        for field in expanded_fields(code, set()):
            if (mapping.get("schema"), mapping["table"].lower(), field["column"].lower()) in facts.deleted_columns: continue
            column = default_column(field["column"], next(iter(field.get("evidenceIds", [])), None), javaName=field["javaName"], javaType=field["javaType"], primaryKey=field.get("primaryKey", False), nullable=False if field.get("primaryKey") else None)
            facts.add_column(obj, column)
            if field.get("primaryKey") and [field["column"]] not in obj["primaryKeys"]: obj["primaryKeys"].append([field["column"]])

    # JOINED inheritance uses the subclass primary key as a one-to-one ORM link
    # to its mapped parent. Other strategies share/duplicate storage and do not
    # imply a separate physical relation.
    mappings_by_code = {mapping["codeObjectId"]: mapping for mapping in facts.mappings}
    inherited_strategy: dict[str, str | None] = {}
    for code in facts.code_objects.values():
        inherited_strategy[code["qualifiedName"].split(".")[-1]] = code.get("inheritanceStrategy")
    for code in facts.code_objects.values():
        parent_name = (code.get("superClass") or "").split(".")[-1]
        parents = by_simple.get(parent_name, [])
        child_mapping = mappings_by_code.get(code["id"])
        if len(parents) != 1 or not child_mapping: continue
        parent_mapping = mappings_by_code.get(parents[0]["id"])
        strategy = parents[0].get("inheritanceStrategy") or inherited_strategy.get(parent_name)
        if not parent_mapping or strategy != "JOINED" or child_mapping["table"].lower() == parent_mapping["table"].lower(): continue
        child_obj = facts.objects.get(facts.object_key(child_mapping.get("schema"), child_mapping["table"])); parent_obj = facts.objects.get(facts.object_key(parent_mapping.get("schema"), parent_mapping["table"]))
        child_pk = child_obj["primaryKeys"][0] if child_obj and child_obj["primaryKeys"] else ["id"]
        parent_pk = parent_obj["primaryKeys"][0] if parent_obj and parent_obj["primaryKeys"] else ["id"]
        ev_ids = sorted(set(code.get("evidenceIds", []) + parents[0].get("evidenceIds", [])))
        facts.relation_observations.append({"fromTable": child_mapping["table"], "fromSchema": child_mapping.get("schema"), "fromColumns": child_pk, "toTable": parent_mapping["table"], "toSchema": parent_mapping.get("schema"), "toColumns": parent_pk, "sourceType": "ORM_RELATION", "confidence": "HIGH", "status": "NORMAL", "directionKnown": True, "codeCardinality": "ONE_TO_ONE", "optionality": "REQUIRED", "evidenceIds": ev_ids})


def resolve_table_name(facts: Facts, schema: str | None, name: str, evidence_id: str) -> dict[str, Any]:
    exact = facts.objects.get(facts.object_key(schema, name))
    if exact: return exact
    candidates = [obj for (sch, nm), obj in facts.objects.items() if nm == name.lower()]
    if len(candidates) == 1: return candidates[0]
    # Entity target often names a Java class; resolve by case-insensitive/simple naming.
    normalized = re.sub(r"[_-]", "", name).lower()
    fuzzy = [obj for obj in facts.objects.values() if re.sub(r"[_-]", "", obj["name"]).lower() == normalized]
    if len(fuzzy) == 1: return fuzzy[0]
    return facts.add_object(name, schema, evidence_id, "CODE", "UNKNOWN")


def finalize_model(root: Path, facts: Facts, files: list[Path], skipped: list[dict[str, str]], technologies: list[str], dialects: list[str], profiles: list[str], applications: list[dict[str, Any]], data_sources: list[dict[str, Any]], scope: str | None, reviews: dict[str, Any] | None = None) -> dict[str, Any]:
    xml_overrides = {mapping["codeObjectId"] for mapping in facts.mappings if mapping.get("xmlOverride")}
    if xml_overrides:
        facts.mappings = [mapping for mapping in facts.mappings if mapping.get("xmlOverride") or mapping["codeObjectId"] not in xml_overrides]
    app_id = applications[0]["id"] if len(applications) == 1 else None
    data_source_id = data_sources[0]["id"] if len(data_sources) == 1 else None
    profile_id = profiles[0] if len(profiles) == 1 else None
    code_id_map = {old_id: stable_id("code", app_id, data_source_id, code.get("qualifiedName"), code.get("role")) for old_id, code in facts.code_objects.items()}
    final_code_objects = []
    for old_id, code in facts.code_objects.items():
        copied = dict(code); copied["id"] = code_id_map[old_id]; copied["applicationId"] = app_id; copied["dataSourceId"] = data_source_id; final_code_objects.append(copied)
    object_ids: dict[int, str] = {}
    db_objects = []
    for obj in sorted(facts.objects.values(), key=lambda o: ((o.get("schema") or ""), o["name"].lower())):
        obj_id = stable_id("db", app_id, profile_id, data_source_id, obj.get("schema"), obj["name"].lower())
        object_ids[id(obj)] = obj_id
        columns = []
        for col in sorted(obj["columns"].values(), key=lambda c: c["name"].lower()):
            col = dict(col); col["id"] = stable_id("col", obj_id, col["name"].lower()); columns.append(col)
        sources = obj["sources"]
        status = "DDL_AND_CODE" if "DDL" in sources and "CODE" in sources else "DDL_ONLY" if "DDL" in sources else "CODE_ONLY"
        db_objects.append({
            "id": obj_id, "applicationId": app_id, "dataSourceId": data_source_id, "profile": profile_id, "catalog": None,
            "schema": obj.get("schema"), "name": obj["name"], "normalizedName": obj["name"].lower(),
            "objectType": obj.get("objectType", "TABLE"), "discoveryStatus": status,
            "historicalNames": sorted(set(obj.get("historicalNames", []))), "possibleNames": sorted(set(obj.get("possibleNames", []))),
            "synonyms": sorted(set(obj.get("synonyms", []))), "dynamicPattern": obj.get("dynamicPattern"),
            "columns": columns, "primaryKeys": sorted({tuple(x) for x in obj.get("primaryKeys", [])}),
            "uniqueConstraints": sorted({tuple(x) for x in obj.get("uniqueConstraints", [])}), "indexes": obj.get("indexes", []),
            "evidenceIds": sorted(obj["evidenceIds"]),
        })
    by_id = {o["id"]: o for o in db_objects}
    by_name = defaultdict(list)
    for o in db_objects: by_name[(o.get("schema"), o["name"].lower())].append(o); by_name[(None, o["name"].lower())].append(o)

    def endpoint(schema: str | None, table: str, columns: list[str], evidence_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        obj = resolve_table_name(facts, schema, table, evidence_id)
        oid = object_ids.get(id(obj))
        if not oid:
            oid = stable_id("db", app_id, profile_id, data_source_id, obj.get("schema"), obj["name"].lower())
            object_ids[id(obj)] = oid
            col_list = []
            for c in columns:
                col_list.append(default_column(c, primaryKey=False) | {"id": stable_id("col", oid, c.lower())})
            new_obj = {"id": oid, "applicationId": app_id, "dataSourceId": data_source_id, "profile": profile_id, "catalog": None, "schema": obj.get("schema"), "name": obj["name"], "normalizedName": obj["name"].lower(), "objectType": obj.get("objectType", "UNKNOWN"), "discoveryStatus": "CODE_ONLY", "historicalNames": [], "possibleNames": [], "synonyms": [], "dynamicPattern": obj.get("dynamicPattern"), "columns": col_list, "primaryKeys": [], "uniqueConstraints": [], "indexes": [], "evidenceIds": sorted(obj["evidenceIds"])}
            db_objects.append(new_obj); by_id[oid] = new_obj
        target_obj = by_id[oid]
        col_ids = []
        for name in columns:
            existing = next((c for c in target_obj["columns"] if c["name"].lower() == name.lower()), None)
            if not existing:
                existing = default_column(name) | {"id": stable_id("col", oid, name.lower())}
                target_obj["columns"].append(existing); target_obj["columns"].sort(key=lambda c: c["name"].lower())
            col_ids.append(existing["id"])
        return {"objectId": oid, "columnIds": col_ids}, target_obj

    # Apply manual review observations before aggregation.
    excluded_keys = set()
    for review in (reviews or {}).get("reviews", []):
        key = (review["fromTable"].lower(), tuple(x.lower() for x in review["fromColumns"]), review["toTable"].lower(), tuple(x.lower() for x in review["toColumns"]))
        if review["action"] == "EXCLUDE": excluded_keys.add(key)
        else:
            ev_id = stable_id("ev", "user-review", review["id"])
            facts.evidence[ev_id] = {"id": ev_id, "file": f"data/java-code-to-erd/{project_id(root)}/user-review.json", "startLine": 1, "endLine": 1, "sourceType": "USER_REVIEW"}
            facts.relation_observations.append({"fromTable": review["fromTable"], "fromSchema": None, "fromColumns": review["fromColumns"], "toTable": review["toTable"], "toSchema": None, "toColumns": review["toColumns"], "sourceType": "USER_CONFIRMED", "confidence": "HIGH", "status": "NORMAL", "directionKnown": True, "evidenceIds": [ev_id]})

    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for obs in facts.relation_observations:
        raw_key = (obs["fromTable"].lower(), tuple(x.lower() for x in obs.get("fromColumns", [])), obs["toTable"].lower(), tuple(x.lower() for x in obs.get("toColumns", [])))
        if raw_key in excluded_keys: continue
        observation_evidence = next(iter(obs.get("evidenceIds", [])))
        left, _ = endpoint(obs.get("fromSchema"), obs["fromTable"], obs.get("fromColumns", []), observation_evidence)
        right, _ = endpoint(obs.get("toSchema"), obs["toTable"], obs.get("toColumns", []), observation_evidence)
        left_key = (left["objectId"], tuple(left["columnIds"]))
        right_key = (right["objectId"], tuple(right["columnIds"]))
        # Group by the same two endpoints regardless of SQL spelling. A directed
        # DDL/ORM observation later supplies the reference direction.
        key = tuple(sorted((left_key, right_key)))
        grouped[key].append(obs | {"_from": left, "_to": right})
    relationships = []; conflicts = []
    for key, observations in sorted(grouped.items(), key=lambda kv: kv[0]):
        sources = sorted({o["sourceType"] for o in observations if o["sourceType"] in RELATION_SOURCES})
        statuses = {o.get("status", "NORMAL") for o in observations}
        code_cards = {o.get("codeCardinality", "UNKNOWN") for o in observations if o.get("codeCardinality", "UNKNOWN") != "UNKNOWN"}
        optionals = {o.get("optionality", "UNKNOWN") for o in observations if o.get("optionality", "UNKNOWN") != "UNKNOWN"}
        directed = {
            ((o["_from"]["objectId"], tuple(o["_from"]["columnIds"])), (o["_to"]["objectId"], tuple(o["_to"]["columnIds"])))
            for o in observations if o.get("directionKnown", False)
        }
        conflicted = len(code_cards) > 1 or len(directed) > 1 or "CONFLICTED" in statuses
        ev_ids = sorted({e for o in observations for e in o.get("evidenceIds", [])})
        if len(directed) == 1:
            directed_from, directed_to = next(iter(directed))
            oriented = next(o for o in observations if (o["_from"]["objectId"], tuple(o["_from"]["columnIds"])) == directed_from and (o["_to"]["objectId"], tuple(o["_to"]["columnIds"])) == directed_to)
            from_ep, to_ep = oriented["_from"], oriented["_to"]
        else:
            ordered = sorted(((o["_from"], o["_to"]) for o in observations), key=lambda pair: (pair[0]["objectId"], pair[0]["columnIds"], pair[1]["objectId"], pair[1]["columnIds"]))
            from_ep, to_ep = ordered[0]
        from_obj, to_obj = by_id[from_ep["objectId"]], by_id[to_ep["objectId"]]
        to_names = {c["id"]: c for c in to_obj["columns"]}
        from_names = {c["id"]: c for c in from_obj["columns"]}
        to_cols = [to_names[c]["name"] for c in to_ep["columnIds"] if c in to_names]
        from_cols = [from_names[c]["name"] for c in from_ep["columnIds"] if c in from_names]
        from_nullable = [from_names[c].get("nullable") for c in from_ep["columnIds"] if c in from_names]
        to_unique = any(set(to_cols) == set(pk) for pk in to_obj["primaryKeys"]) or any(set(to_cols) == set(uq) for uq in to_obj["uniqueConstraints"])
        from_unique = any(set(from_cols) == set(pk) for pk in from_obj["primaryKeys"]) or any(set(from_cols) == set(uq) for uq in from_obj["uniqueConstraints"])
        constraint_card = "ONE_TO_ONE" if to_unique and from_unique else "MANY_TO_ONE" if to_unique else "UNKNOWN"
        conclusion = "USER_CONFIRMED" if "USER_CONFIRMED" in sources else "DECLARED" if any(s in sources for s in {"DDL_FOREIGN_KEY", "ORM_RELATION", "RESULT_MAPPING"}) else "INFERRED"
        confidence_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        confidence = max((o.get("confidence", "LOW") for o in observations), key=lambda x: confidence_order[x])
        derived_optional = "REQUIRED" if from_nullable and all(value is False for value in from_nullable) else "OPTIONAL" if any(value is True for value in from_nullable) else "UNKNOWN"
        incomplete_composite = any(set(to_cols) < set(pk) for pk in to_obj["primaryKeys"] + to_obj["uniqueConstraints"]) or any(set(from_cols) < set(pk) for pk in from_obj["primaryKeys"] + from_obj["uniqueConstraints"])
        endpoint_completeness = "PARTIAL" if incomplete_composite else "COMPLETE" if from_cols and to_cols and len(from_cols) == len(to_cols) else "UNKNOWN"
        relation = {"id": stable_id("rel", *key), "from": from_ep, "to": to_ep, "sourceTypes": sources, "conclusionKind": conclusion, "confidence": confidence, "status": "CONFLICTED" if conflicted else "CONDITIONAL" if "CONDITIONAL" in statuses else "NORMAL", "directionKnown": len(directed) == 1, "endpointCompleteness": endpoint_completeness, "constraintCardinality": constraint_card, "codeCardinality": next(iter(code_cards)) if len(code_cards) == 1 else "UNKNOWN", "optionality": next(iter(optionals)) if len(optionals) == 1 else derived_optional, "evidenceIds": ev_ids}
        relationships.append(relation)
        if conflicted:
            conflicts.append({"id": stable_id("conflict", relation["id"]), "kind": "RELATIONSHIP_CONFLICT", "message": f"Conflicting evidence for {from_obj['name']} -> {to_obj['name']}", "evidenceIds": ev_ids})

    # A single referencing field cannot point at two different declared targets
    # without an explicit condition. Preserve both conclusions and expose the conflict.
    by_reference: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = defaultdict(list)
    for relation in relationships:
        if relation["directionKnown"] and any(source in relation["sourceTypes"] for source in {"DDL_FOREIGN_KEY", "ORM_RELATION", "USER_CONFIRMED"}):
            by_reference[(relation["from"]["objectId"], tuple(relation["from"]["columnIds"]))].append(relation)
    for reference, related in sorted(by_reference.items()):
        targets = {(relation["to"]["objectId"], tuple(relation["to"]["columnIds"])) for relation in related}
        if len(targets) <= 1:
            continue
        ev_ids = sorted({ev for relation in related for ev in relation["evidenceIds"]})
        for relation in related:
            relation["status"] = "CONFLICTED"
        source_object = by_id[reference[0]]["name"]
        conflicts.append({"id": stable_id("conflict", "MULTIPLE_TARGETS", *reference), "kind": "RELATIONSHIP_TARGET_CONFLICT", "message": f"The same referencing field on {source_object} points to multiple declared targets", "evidenceIds": ev_ids})

    # Convert mappings/operations to IDs.
    mappings = []
    for m in facts.mappings:
        matches = [o for o in db_objects if o["name"].lower() == m["table"].lower() and (not m.get("schema") or o.get("schema") == m.get("schema"))]
        mappings.append({"codeObjectId": code_id_map.get(m["codeObjectId"], m["codeObjectId"]), "databaseObjectIds": sorted({o["id"] for o in matches}), "role": m["role"], "evidenceIds": sorted(set(m.get("evidenceIds", []))), "possible": m.get("possible", False)})
    operations = []
    mapped_names: dict[str, set[str]] = defaultdict(set)
    for mapping in facts.mappings:
        code = facts.code_objects.get(mapping["codeObjectId"], {})
        mapped_names[code.get("qualifiedName", "").split(".")[-1].lower()].add(mapping["table"].lower())
    for op in facts.operations:
        requested = op["table"].lower(); possible_names = {requested} | mapped_names.get(requested, set())
        normalized = {re.sub(r"[_-]", "", name) for name in possible_names}
        matches = [o for o in db_objects if o["name"].lower() in possible_names or re.sub(r"[_-]", "", o["name"].lower()) in normalized]
        for obj in matches[:1]:
            operations.append({"id": stable_id("op", op["kind"], obj["id"], *op.get("evidenceIds", [])), "kind": op["kind"], "databaseObjectId": obj["id"], "columnNames": sorted(set(op.get("columns", []))), "evidenceIds": sorted(set(op.get("evidenceIds", [])))})
    merged_operations: dict[str, dict[str, Any]] = {}
    for operation in operations:
        current = merged_operations.get(operation["id"])
        if current:
            current["columnNames"] = sorted(set(current["columnNames"] + operation["columnNames"])); current["evidenceIds"] = sorted(set(current["evidenceIds"] + operation["evidenceIds"]))
        else:
            merged_operations[operation["id"]] = operation
    operations = list(merged_operations.values())
    unresolved = []
    for item in facts.unresolved:
        unresolved.append({"id": stable_id("unresolved", item.get("kind"), item.get("message"), *item.get("evidenceIds", [])), "kind": item.get("kind", "UNKNOWN"), "message": item.get("message", "Unresolved construct"), "evidenceIds": sorted(set(item.get("evidenceIds", [])))})
    for (deleted_schema, deleted_name), deleted_evidence in sorted(facts.deleted_objects.items(), key=lambda item: ((item[0][0] or ""), item[0][1])):
        current = facts.objects.get((deleted_schema, deleted_name))
        if current and "CODE" in current["sources"]:
            ev_ids = sorted(set(current["evidenceIds"]) | {deleted_evidence})
            unresolved.append({"id": stable_id("unresolved", "CODE_USES_DROPPED_OBJECT", deleted_schema, deleted_name), "kind": "DDL_CODE_CONFLICT", "message": f"Code still references database object {deleted_name} after a project migration drops it", "evidenceIds": ev_ids})
    unsupported = [t for t in technologies if t.endswith("_UNSUPPORTED")]
    for tech in unsupported:
        unresolved.append({"id": stable_id("unresolved", tech), "kind": "UNSUPPORTED_FRAMEWORK", "message": f"Detected but not deeply supported: {tech.replace('_UNSUPPORTED','')}", "evidenceIds": []})
    if len(applications) > 1:
        unresolved.append({"id": stable_id("unresolved", "MULTIPLE_APPLICATIONS"), "kind": "APPLICATION_IDENTITY", "message": "Multiple Java applications were detected; facts without an unambiguous owning application were not force-assigned", "evidenceIds": []})
    if len(data_sources) > 1:
        unresolved.append({"id": stable_id("unresolved", "MULTIPLE_DATASOURCES"), "kind": "DATA_SOURCE_IDENTITY", "message": "Multiple data sources were detected; facts without explicit binding were not merged into a selected data source", "evidenceIds": []})
    if len(profiles) > 1:
        unresolved.append({"id": stable_id("unresolved", "MULTIPLE_PROFILES"), "kind": "PROFILE_IDENTITY", "message": "Multiple formal configuration profiles were detected; no production profile was selected or silently merged", "evidenceIds": []})
    status = "PARTIAL" if unresolved or conflicts else "COMPLETE"
    rule_refs = ["references/rules/project-discovery.md", "references/rules/sql-semantics.md"]
    if "JPA_HIBERNATE" in technologies: rule_refs.append("references/rules/jpa-hibernate.md")
    if "MYBATIS" in technologies or "MYBATIS_PLUS" in technologies: rule_refs.append("references/rules/mybatis.md")
    if "JDBC_TEMPLATE" in technologies or "JDBC" in technologies: rule_refs.append("references/rules/jdbc-and-java-sql.md")
    if "FLYWAY" in technologies or "LIQUIBASE" in technologies: rule_refs.append("references/rules/ddl-flyway-liquibase.md")
    # Naming alone never becomes a normal relationship. It may become a low
    # confidence candidate only when the target object and a matching key exist.
    candidates = []
    existing_pairs = {
        frozenset((r["from"]["objectId"], r["to"]["objectId"])) for r in relationships
    }
    for source_obj in db_objects:
        for source_col in source_obj["columns"]:
            if not source_col["name"].lower().endswith("_id"):
                continue
            base = source_col["name"][:-3].lower()
            targets = [
                obj for obj in db_objects
                if obj["id"] != source_obj["id"]
                and re.sub(r"[_-]", "", obj["name"]).lower() in {re.sub(r"[_-]", "", base), re.sub(r"[_-]", "", base + "s")}
            ]
            if len(targets) != 1:
                continue
            target = targets[0]
            key_columns = [c for c in target["columns"] if c["primaryKey"] and c["name"].lower() == "id"]
            if len(key_columns) != 1 or frozenset((source_obj["id"], target["id"])) in existing_pairs:
                continue
            target_col = key_columns[0]
            ev_ids = sorted(set(source_col["evidenceIds"] + target_col["evidenceIds"]))
            candidate_key = (source_obj["id"], source_col["id"], target["id"], target_col["id"])
            candidates.append({
                "id": stable_id("candidate", *candidate_key),
                "from": {"objectId": source_obj["id"], "columnIds": [source_col["id"]]},
                "to": {"objectId": target["id"], "columnIds": [target_col["id"]]},
                "sourceTypes": ["NAMING_CANDIDATE"], "conclusionKind": "CANDIDATE",
                "confidence": "LOW", "status": "NORMAL", "directionKnown": True,
                "constraintCardinality": "UNKNOWN", "codeCardinality": "UNKNOWN",
                "optionality": "UNKNOWN", "evidenceIds": ev_ids,
                "message": f"Possible relation inferred only from naming: {source_obj['name']}.{source_col['name']} -> {target['name']}.{target_col['name']}",
            })
    model = {
        "schemaVersion": SCHEMA_VERSION, "analysisStatus": status,
        "scope": {"mode": "SCOPED" if scope else "FULL_PROJECT", "value": scope, "project": root.name},
        "applications": applications, "profiles": profiles, "dataSources": data_sources, "dialects": dialects,
        "technologies": technologies, "ruleReferences": sorted(rule_refs), "environmentDiagnostics": [],
        "visualStatus": "RENDERER_AVAILABLE_NOT_VERIFIED" if shutil.which("mmdc") else "SOURCE_ONLY",
        "coverage": {"discovered": len(files), "analyzed": len(files), "skipped": len(skipped), "unresolved": len(unresolved), "skippedFiles": skipped},
        "databaseObjects": sorted(db_objects, key=lambda o: o["id"]), "codeObjects": sorted(final_code_objects, key=lambda o: o["id"]),
        "objectMappings": sorted(mappings, key=lambda m: (m["codeObjectId"], m["role"])), "operations": sorted(operations, key=lambda o: o["id"]),
        "relationships": sorted(relationships, key=lambda r: r["id"]), "evidence": sorted(facts.evidence.values(), key=lambda e: e["id"]),
        "conflicts": sorted(conflicts, key=lambda c: c["id"]), "candidates": sorted(candidates, key=lambda c: c["id"]), "unresolved": sorted(unresolved, key=lambda u: u["id"]),
    }
    if scope:
        target = scope.lower()
        evidence_by_id = {item["id"]: item for item in model["evidence"]}
        selected_ids = {
            o["id"] for o in model["databaseObjects"]
            if target in o["name"].lower()
            or target in (o.get("schema") or "").lower()
            or any(target in evidence_by_id.get(ev, {}).get("file", "").lower() for ev in o["evidenceIds"])
        }
        scoped_code_ids = {code["id"] for code in model["codeObjects"] if target in code["qualifiedName"].lower()}
        for mapping in model["objectMappings"]:
            if mapping["codeObjectId"] in scoped_code_ids:
                selected_ids.update(mapping["databaseObjectIds"])
        for rel in model["relationships"]:
            if rel["from"]["objectId"] in selected_ids or rel["to"]["objectId"] in selected_ids:
                selected_ids.update({rel["from"]["objectId"], rel["to"]["objectId"]})
        model["databaseObjects"] = [o for o in model["databaseObjects"] if o["id"] in selected_ids]
        model["relationships"] = [r for r in model["relationships"] if r["from"]["objectId"] in selected_ids and r["to"]["objectId"] in selected_ids]
        model["candidates"] = [r for r in model["candidates"] if r["from"]["objectId"] in selected_ids and r["to"]["objectId"] in selected_ids]
        model["operations"] = [o for o in model["operations"] if o["databaseObjectId"] in selected_ids]
        model["objectMappings"] = [m for m in model["objectMappings"] if set(m["databaseObjectIds"]) & selected_ids]
        if not selected_ids:
            item = {"id": stable_id("unresolved", "SCOPE_NOT_FOUND", scope), "kind": "SCOPE_NOT_FOUND", "message": f"No database object, module path, package, or Java mapping matched scope: {scope}", "evidenceIds": []}
            model["unresolved"] = sorted(model["unresolved"] + [item], key=lambda value: value["id"])
            model["coverage"]["unresolved"] = len(model["unresolved"])
            model["analysisStatus"] = "PARTIAL"
    return model


def combine_application_models(models: list[dict[str, Any]], applications: list[dict[str, Any]], files: list[Path], skipped: list[dict[str, str]], technologies: list[str], dialects: list[str], profiles: list[str], data_sources: list[dict[str, Any]], scope: str | None, root: Path) -> dict[str, Any]:
    combined = {
        "schemaVersion": SCHEMA_VERSION, "analysisStatus": "COMPLETE",
        "scope": {"mode": "SCOPED" if scope else "FULL_PROJECT", "value": scope, "project": root.name},
        "applications": applications, "profiles": profiles, "dataSources": data_sources,
        "dialects": dialects, "technologies": technologies,
        "ruleReferences": sorted({ref for model in models for ref in model.get("ruleReferences", [])}), "environmentDiagnostics": [],
        "visualStatus": "RENDERER_AVAILABLE_NOT_VERIFIED" if shutil.which("mmdc") else "SOURCE_ONLY",
        "coverage": {"discovered": len(files), "analyzed": len(files), "skipped": len(skipped), "unresolved": 0, "skippedFiles": skipped},
    }
    for section in ("databaseObjects", "codeObjects", "objectMappings", "operations", "relationships", "evidence", "conflicts", "candidates", "unresolved"):
        values = []
        for model in models: values.extend(model.get(section, []))
        unique = {item["id"]: item for item in values if item.get("id")}
        combined[section] = sorted(unique.values(), key=lambda item: item["id"])
    combined["coverage"]["unresolved"] = len(combined["unresolved"])
    if combined["unresolved"] or combined["conflicts"]: combined["analysisStatus"] = "PARTIAL"
    return combined


def validate_model(model: dict[str, Any]) -> list[str]:
    errors = []
    required = {"schemaVersion", "analysisStatus", "scope", "applications", "profiles", "dataSources", "dialects", "technologies", "coverage", "databaseObjects", "codeObjects", "objectMappings", "operations", "relationships", "evidence", "conflicts", "candidates", "unresolved"}
    missing = required - set(model)
    if missing: errors.append("missing top-level fields: " + ", ".join(sorted(missing)))
    if model.get("analysisStatus") not in {"COMPLETE", "PARTIAL", "FAILED"}: errors.append("invalid analysisStatus")
    if model.get("visualStatus", "SOURCE_ONLY") not in {"SOURCE_ONLY", "RENDERER_AVAILABLE_NOT_VERIFIED", "VERIFIED"}: errors.append("invalid visualStatus")
    for item in model.get("environmentDiagnostics", []):
        if not isinstance(item, dict) or item.get("kind") != "JDK_SOURCE_VERIFICATION" or not isinstance(item.get("message"), str):
            errors.append("invalid environment diagnostic")
    ids: dict[str, str] = {}
    for section in ("databaseObjects", "codeObjects", "operations", "relationships", "evidence", "conflicts", "candidates", "unresolved"):
        for item in model.get(section, []):
            item_id = item.get("id")
            if not item_id: errors.append(f"{section} item missing id"); continue
            if item_id in ids: errors.append(f"duplicate id {item_id} in {section} and {ids[item_id]}")
            ids[item_id] = section
    for obj in model.get("databaseObjects", []):
        for column in obj.get("columns", []):
            column_id = column.get("id")
            if not column_id:
                errors.append(f"database object {obj.get('id')} has column without id")
            elif column_id in ids:
                errors.append(f"duplicate id {column_id} in column and {ids[column_id]}")
            else:
                ids[column_id] = "column"
    object_ids = {o["id"] for o in model.get("databaseObjects", [])}
    column_ids = {c["id"] for o in model.get("databaseObjects", []) for c in o.get("columns", [])}
    evidence_ids = {e["id"] for e in model.get("evidence", [])}
    for ev in model.get("evidence", []):
        if set(ev) != {"id", "file", "startLine", "endLine", "sourceType"}: errors.append(f"evidence {ev.get('id')} contains unsupported fields")
        if Path(ev.get("file", "")).is_absolute() or ".." in Path(ev.get("file", "")).parts: errors.append(f"evidence {ev.get('id')} path is not project-relative")
        if not isinstance(ev.get("startLine"), int) or not isinstance(ev.get("endLine"), int) or ev.get("startLine", 0) < 1 or ev.get("endLine", 0) < ev.get("startLine", 1): errors.append(f"evidence {ev.get('id')} has invalid line range")
    for rel in model.get("relationships", []) + model.get("candidates", []):
        if rel.get("from", {}).get("objectId") not in object_ids: errors.append(f"relationship {rel.get('id')} has missing from object")
        if rel.get("to", {}).get("objectId") not in object_ids: errors.append(f"relationship {rel.get('id')} has missing to object")
        for cid in rel.get("from", {}).get("columnIds", []) + rel.get("to", {}).get("columnIds", []):
            if cid not in column_ids: errors.append(f"relationship {rel.get('id')} has missing column {cid}")
        if not set(rel.get("sourceTypes", [])).issubset(RELATION_SOURCES): errors.append(f"relationship {rel.get('id')} has invalid source type")
        if rel.get("confidence") not in {"HIGH", "MEDIUM", "LOW"}: errors.append(f"relationship {rel.get('id')} has invalid confidence")
        if rel.get("status") not in {"NORMAL", "CONDITIONAL", "CONFLICTED"}: errors.append(f"relationship {rel.get('id')} has invalid status")
        for key in ("constraintCardinality", "codeCardinality"):
            if rel.get(key) not in {"ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_ONE", "MANY_TO_MANY", "UNKNOWN"}: errors.append(f"relationship {rel.get('id')} has invalid {key}")
        from_columns = set(rel.get("from", {}).get("columnIds", []))
        to_columns = set(rel.get("to", {}).get("columnIds", []))
        from_obj = next((o for o in model.get("databaseObjects", []) if o["id"] == rel.get("from", {}).get("objectId")), None)
        to_obj = next((o for o in model.get("databaseObjects", []) if o["id"] == rel.get("to", {}).get("objectId")), None)
        if from_obj and not from_columns.issubset({c["id"] for c in from_obj.get("columns", [])}): errors.append(f"relationship {rel.get('id')} has from-column on another object")
        if to_obj and not to_columns.issubset({c["id"] for c in to_obj.get("columns", [])}): errors.append(f"relationship {rel.get('id')} has to-column on another object")
    code_ids = {c["id"] for c in model.get("codeObjects", [])}
    for mapping in model.get("objectMappings", []):
        if mapping.get("codeObjectId") not in code_ids: errors.append("object mapping references missing code object")
        if not set(mapping.get("databaseObjectIds", [])).issubset(object_ids): errors.append("object mapping references missing database object")
    for operation in model.get("operations", []):
        if operation.get("databaseObjectId") not in object_ids: errors.append(f"operation {operation.get('id')} references missing database object")
    for section in ("databaseObjects", "codeObjects", "objectMappings", "operations", "relationships", "conflicts", "candidates", "unresolved"):
        for item in model.get(section, []):
            for ev_id in item.get("evidenceIds", []):
                if ev_id not in evidence_ids: errors.append(f"{section} references missing evidence {ev_id}")
    return sorted(set(errors))


def mermaid_entity_name(obj: dict[str, Any]) -> str:
    raw = ((obj.get("schema") + "_") if obj.get("schema") else "") + obj["name"]
    return re.sub(r"[^A-Za-z0-9_]", "_", raw).upper()


def mermaid_names(objects: Iterable[dict[str, Any]]) -> dict[str, str]:
    objects = list(objects); counts: dict[str, int] = defaultdict(int)
    for obj in objects: counts[mermaid_entity_name(obj)] += 1
    return {obj["id"]: (mermaid_entity_name(obj) if counts[mermaid_entity_name(obj)] == 1 else f"{mermaid_entity_name(obj)}_{obj['id'][-6:].upper()}") for obj in objects}


def relation_label(rel: dict[str, Any]) -> str:
    short = {"DDL_FOREIGN_KEY": "DDL", "ORM_RELATION": "ORM", "RESULT_MAPPING": "MAP", "SQL_JOIN": "JOIN", "SQL_COLUMN_COMPARISON": "SQL", "CODE_INFERRED": "CODE", "NAMING_CANDIDATE": "NAME?", "USER_CONFIRMED": "USER", "OBJECT_DEPENDENCY": "DEP"}
    label = "|".join(short[s] for s in rel["sourceTypes"])
    if rel["status"] == "CONDITIONAL": label += "|CONDITIONAL"
    return f"[{label}]"


def crow_foot(rel: dict[str, Any]) -> str | None:
    if not rel.get("directionKnown") or rel.get("optionality") == "UNKNOWN" or rel.get("endpointCompleteness") == "PARTIAL":
        return None
    card = rel["constraintCardinality"] if rel["constraintCardinality"] != "UNKNOWN" else rel["codeCardinality"]
    optional = rel["optionality"]
    mapping = {
        "ONE_TO_ONE": "||--||" if optional == "REQUIRED" else "||--o|",
        "MANY_TO_ONE": "||--o{" if optional == "REQUIRED" else "o|--o{",
        "ONE_TO_MANY": "||--o{" if optional == "REQUIRED" else "o|--o{",
        "MANY_TO_MANY": "}o--o{",
    }
    return mapping.get(card)


def generate_mermaid(model: dict[str, Any], object_ids: set[str] | None = None, overview: bool = False) -> str:
    objects = [o for o in model["databaseObjects"] if object_ids is None or o["id"] in object_ids]
    by_id = {o["id"]: o for o in objects}
    names = mermaid_names(objects)
    lines = ["%% Generated by java-code-to-erd. Re-running updates this file.", "%% Labels: DDL=project FK, ORM=JPA/Hibernate, MAP=result mapping, JOIN/SQL=query relation, CODE=Java inference, USER=human review.", "erDiagram"]
    if not overview:
        for obj in sorted(objects, key=lambda o: names[o["id"]]):
            name = names[obj["id"]]; lines.append(f"    {name} {{")
            cols = obj["columns"]
            display = cols if len(cols) <= 20 else [c for c in cols if c["primaryKey"] or c["unique"] or any(c["id"] in r["from"]["columnIds"] + r["to"]["columnIds"] for r in model["relationships"])]
            for col in display:
                db_type = re.sub(r"[^A-Za-z0-9_]", "_", col.get("databaseType") or col.get("javaType") or "unknown")
                flags = []
                if col["primaryKey"]: flags.append("PK")
                if col["unique"]: flags.append("UK")
                suffix = " " + ",".join(flags) if flags else ""
                col_name = re.sub(r"[^A-Za-z0-9_]", "_", col["name"])
                lines.append(f"        {db_type} {col_name}{suffix}")
            if len(cols) > len(display): lines.append(f"        string omitted_{len(cols)-len(display)}_fields")
            lines.append("    }")
    else:
        for obj in sorted(objects, key=lambda o: names[o["id"]]):
            lines.extend([f"    {names[obj['id']]} {{", "    }"])
    for rel in model["relationships"]:
        if rel["status"] == "CONFLICTED": continue
        if rel["from"]["objectId"] not in by_id or rel["to"]["objectId"] not in by_id: continue
        connector = crow_foot(rel)
        if not connector: continue
        left = names[rel["to"]["objectId"]]; right = names[rel["from"]["objectId"]]
        lines.append(f"    {left} {connector} {right} : \"{relation_label(rel)}\"")
    return "\n".join(lines) + "\n"


def generate_logic_mermaid(model: dict[str, Any]) -> str | None:
    unknown = [r for r in model["relationships"] if r["status"] != "CONFLICTED" and crow_foot(r) is None]
    if not unknown: return None
    by_id = {o["id"]: o for o in model["databaseObjects"]}
    names = mermaid_names(by_id.values())
    lines = ["%% Reliable relations with unknown cardinality.", "flowchart LR", "    classDef table fill:#EFF6FF,stroke:#3B82F6,color:#172033,stroke-width:1.5px;"]
    used = {r["from"]["objectId"] for r in unknown} | {r["to"]["objectId"] for r in unknown}
    for oid in sorted(used):
        if oid in by_id:
            lines.append(f"    {names[oid]}[\"{by_id[oid]['name']}\"]:::table")
    for index, rel in enumerate(unknown, 1):
        if rel["from"]["objectId"] in by_id and rel["to"]["objectId"] in by_id:
            lines.append(f"    {names[rel['from']['objectId']]} -- \"UNKNOWN {relation_label(rel)}\" --> {names[rel['to']['objectId']]}")
    return "\n".join(lines) + "\n"


def generate_overview_mermaid(model: dict[str, Any]) -> str:
    """Object-only overview that does not invent Crow's Foot cardinality."""
    by_id = {o["id"]: o for o in model["databaseObjects"]}
    names = mermaid_names(by_id.values())
    lines = ["%% Object-only overview; arrows mean evidence-backed dependency, not a foreign key.", "flowchart LR", "    classDef table fill:#F8FAFC,stroke:#334155,color:#0F172A,stroke-width:1.5px;"]
    for obj in sorted(model["databaseObjects"], key=lambda item: item["id"]):
        lines.append(f"    {names[obj['id']]}[\"{obj['name']}\"]:::table")
    for rel in model["relationships"]:
        if rel["status"] == "CONFLICTED" or rel["from"]["objectId"] not in by_id or rel["to"]["objectId"] not in by_id: continue
        lines.append(f"    {names[rel['from']['objectId']]} -- \"{relation_label(rel)}\" --> {names[rel['to']['objectId']]}")
    return "\n".join(lines) + "\n"


def generate_dbml(model: dict[str, Any]) -> str:
    lines = ["// Generated by java-code-to-erd. Only DDL_FOREIGN_KEY creates Ref.", ""]
    by_id = {o["id"]: o for o in model["databaseObjects"]}
    app_names = {app["id"]: app["name"] for app in model.get("applications", [])}
    base_names = {obj["id"]: f"{obj['schema']}.{obj['name']}" if obj.get("schema") else obj["name"] for obj in model["databaseObjects"]}
    name_counts: dict[str, int] = defaultdict(int)
    for value in base_names.values(): name_counts[value.lower()] += 1
    dbml_names = {obj["id"]: (base_names[obj["id"]] if name_counts[base_names[obj["id"]].lower()] == 1 else f"{app_names.get(obj.get('applicationId'), obj['id'][-6:])}.{base_names[obj['id']]}") for obj in model["databaseObjects"]}
    col_by_id = {c["id"]: c for o in model["databaseObjects"] for c in o["columns"]}
    for obj in sorted(model["databaseObjects"], key=lambda o: ((o.get("schema") or ""), o["name"])):
        qualified = dbml_names[obj["id"]]
        lines.append(f'Table "{qualified}" {{')
        for col in obj["columns"]:
            flags = []
            if col["primaryKey"]: flags.append("pk")
            if col["unique"]: flags.append("unique")
            if col["nullable"] is False: flags.append("not null")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f'  "{col["name"]}" {col.get("databaseType") or "unknown"}{suffix}')
        lines.append("}"); lines.append("")
    for rel in model["relationships"]:
        from_obj, to_obj = by_id.get(rel["from"]["objectId"]), by_id.get(rel["to"]["objectId"])
        if not from_obj or not to_obj: continue
        fcols = [col_by_id[c]["name"] for c in rel["from"]["columnIds"] if c in col_by_id]
        tcols = [col_by_id[c]["name"] for c in rel["to"]["columnIds"] if c in col_by_id]
        if rel["status"] == "NORMAL" and "DDL_FOREIGN_KEY" in rel["sourceTypes"] and fcols and tcols:
            fobj = dbml_names[from_obj["id"]]; tobj = dbml_names[to_obj["id"]]
            if len(fcols) == 1:
                lines.append(f'Ref: "{fobj}"."{fcols[0]}" > "{tobj}"."{tcols[0]}"')
            else:
                left_cols = ", ".join(f'"{name}"' for name in fcols); right_cols = ", ".join(f'"{name}"' for name in tcols)
                lines.append(f'Ref: "{fobj}".({left_cols}) > "{tobj}".({right_cols})')
        else:
            lines.append(f"// Logical relation {from_obj['name']} -> {to_obj['name']} {relation_label(rel)} confidence={rel['confidence']}")
    for candidate in model["candidates"]:
        from_obj, to_obj = by_id.get(candidate["from"]["objectId"]), by_id.get(candidate["to"]["objectId"])
        if from_obj and to_obj:
            lines.append(f"// Candidate only; no Ref: {from_obj['name']} -> {to_obj['name']} confidence=LOW")
    return "\n".join(lines) + "\n"


def ev_locations(model: dict[str, Any], ids: list[str]) -> str:
    by_id = {e["id"]: e for e in model["evidence"]}
    return ", ".join(f"{by_id[i]['file']}:{by_id[i]['startLine']}" for i in ids if i in by_id) or "(no location)"


def generate_report(model: dict[str, Any], language: str = "zh") -> str:
    zh = language.lower().startswith("zh")
    objects = model["databaseObjects"]; rels = model["relationships"]
    title = "Java 项目数据库模型分析" if zh else "Java Project Database Model Analysis"
    lines = [f"# {title}", "", "> 此报告由 `java-code-to-erd` 生成；再次运行会更新。" if zh else "> Generated by `java-code-to-erd`; re-running updates it.", ""]
    lines += ["## 分析摘要" if zh else "## Summary", "", f"- Database analysis: **{model['analysisStatus']}**", f"- Diagram visual check: **{model.get('visualStatus', 'SOURCE_ONLY')}**", f"- Database objects: **{len(objects)}**", f"- Relationships: **{len(rels)}**", f"- Conflicts: **{len(model['conflicts'])}**", f"- Unresolved: **{len(model['unresolved'])}**", ""]
    diagnostics = model.get("environmentDiagnostics", [])
    if diagnostics:
        lines += ["## 环境诊断" if zh else "## Environment diagnostics", ""]
        for item in diagnostics:
            lines.append(f"- {item['message']}" + ("；已确认的数据库事实不受此项影响。" if zh else "; verified database facts are unaffected."))
        lines.append("")
    lines += ["## 扫描覆盖" if zh else "## Coverage", "", f"- Discovered: {model['coverage']['discovered']}", f"- Analyzed: {model['coverage']['analyzed']}", f"- Skipped: {model['coverage']['skipped']}", f"- Unresolved: {model['coverage']['unresolved']}", ""]
    lines += ["## 检测结果" if zh else "## Detection", "", f"- Technologies: {', '.join(model['technologies']) or 'None'}", f"- Dialects: {', '.join(model['dialects'])}", f"- Profiles: {', '.join(model['profiles']) or 'default/unknown'}", ""]
    lines += ["## ERD", "", "![Database ERD](database-erd.svg)" if model.get("visualStatus") == "VERIFIED" else "```mermaid\n" + generate_mermaid(model).rstrip() + "\n```", ""]
    if model.get("visualStatus") != "VERIFIED":
        lines += ["> 本机未完成 SVG 视觉验收；Mermaid 源已生成，未安装任何额外工具。" if zh else "> SVG visual QA was not completed locally; Mermaid source is available and no tool was installed.", ""]
    if generate_logic_mermaid(model):
        lines += ["- [未知数量关系图](database-relations.mmd)" if zh else "- [Unknown-cardinality relationship graph](database-relations.mmd)", ""]
    if len(model["databaseObjects"]) > 25 or len(model["relationships"]) > 50:
        lines += ["- [大型项目总览](database-erd-overview.mmd)" if zh else "- [Large-project overview](database-erd-overview.mmd)", "- `erd/cluster-*.mmd`：按稳定关系簇拆分的详细图" if zh else "- `erd/cluster-*.mmd`: detailed diagrams split by stable relationship clusters", ""]
    lines += ["### 关系标记" if zh else "### Relationship labels", "", "| Label | Meaning |", "|---|---|", "| DDL | Project DDL foreign-key declaration |", "| ORM | JPA/Hibernate mapping |", "| MAP | Query result mapping |", "| JOIN / SQL | SQL join or cross-table comparison |", "| CODE | Java code inference |", "| USER | Human confirmation |", ""]
    lines += ["## 数据库对象" if zh else "## Database objects", ""]
    mappings_by_db = defaultdict(list)
    code_by_id = {c["id"]: c for c in model["codeObjects"]}
    for m in model["objectMappings"]:
        for oid in m["databaseObjectIds"]: mappings_by_db[oid].append(code_by_id.get(m["codeObjectId"], {}).get("qualifiedName", m["codeObjectId"]))
    ops_by_db = defaultdict(set)
    for op in model["operations"]: ops_by_db[op["databaseObjectId"]].add(op["kind"])
    for obj in sorted(objects, key=lambda o: ((o.get("schema") or ""), o["name"])):
        qname = f"{obj['schema']}.{obj['name']}" if obj.get("schema") else obj["name"]
        lines += [f"### `{qname}`", "", f"- Type: {obj['objectType']}", f"- Discovery: {obj['discoveryStatus']}", f"- Java: {', '.join(sorted(mappings_by_db[obj['id']])) or '—'}", f"- Operations: {', '.join(sorted(ops_by_db[obj['id']])) or '—'}", ""]
        if obj["columns"]:
            lines += ["| Column | DB type | Java type | Keys | Nullable |", "|---|---|---|---|---|"]
            for c in obj["columns"]:
                keys = ", ".join(x for x, yes in (("PK", c["primaryKey"]), ("UK", c["unique"])) if yes) or "—"
                lines.append(f"| `{c['name']}` | {c.get('databaseType') or 'unknown'} | {c.get('javaType') or '—'} | {keys} | {c.get('nullable') if c.get('nullable') is not None else 'unknown'} |")
            lines.append("")
    lines += ["## 关系" if zh else "## Relationships", ""]
    by_id = {o["id"]: o for o in objects}
    cols = {c["id"]: c for o in objects for c in o["columns"]}
    for rel in rels:
        if rel["from"]["objectId"] not in by_id or rel["to"]["objectId"] not in by_id: continue
        f = by_id[rel["from"]["objectId"]]; t = by_id[rel["to"]["objectId"]]
        fc = ",".join(cols[i]["name"] for i in rel["from"]["columnIds"] if i in cols) or "?"
        tc = ",".join(cols[i]["name"] for i in rel["to"]["columnIds"] if i in cols) or "?"
        lines.append(f"- `{f['name']}.{fc} -> {t['name']}.{tc}` — {relation_label(rel)}, confidence={rel['confidence']}, constraint={rel['constraintCardinality']}, code={rel['codeCardinality']}, status={rel['status']}")
    lines.append("")
    for heading, items in (("关系冲突" if zh else "Conflicts", model["conflicts"]), ("未解析项" if zh else "Unresolved", model["unresolved"]), ("候选关系" if zh else "Candidates", model["candidates"])):
        lines += [f"## {heading}", ""]
        if not items: lines += ["- None", ""]; continue
        for item in items:
            lines.append(f"- {item.get('message', item.get('id'))} — {ev_locations(model, item.get('evidenceIds', []))}")
        lines.append("")
    lines += ["## 生成物" if zh else "## Artifacts", "", "- `database-model.json`", "- `database-analysis.md`", "- `database-erd.mmd`"]
    if generate_logic_mermaid(model): lines.append("- `database-relations.mmd`")
    if len(objects) > 25 or len(rels) > 50: lines.append("- `database-erd-overview.mmd`")
    lines += ["- `database.dbml`", "- `artifact-manifest.json`", ""]
    return "\n".join(lines)


def render_mermaid(mmd: Path, svg: Path, config: Path) -> tuple[bool, str | None]:
    executable = shutil.which("mmdc")
    if not executable: return False, "Mermaid CLI not installed; SVG visual QA not performed."
    result = subprocess.run([executable, "-i", str(mmd), "-o", str(svg), "-c", str(config), "-b", "transparent"], capture_output=True, text=True, check=False, timeout=60)
    if result.returncode != 0: return False, result.stderr.strip() or "Mermaid rendering failed"
    text = svg.read_text(encoding="utf-8", errors="replace")
    if "<svg" not in text or "viewBox" not in text: return False, "Rendered SVG lacks a valid viewBox"
    return True, None


def atomic_publish(output: Path, artifacts: dict[str, str], config: Path) -> tuple[list[str], list[str], str]:
    output.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []; written: list[str] = []
    with tempfile.TemporaryDirectory(prefix="java-code-to-erd-", dir=output.parent) as temp_dir:
        staging = Path(temp_dir)
        for name, content in artifacts.items():
            path = staging / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")
        visual = "NOT_AVAILABLE"
        for mmd in sorted(staging.rglob("*.mmd")):
            ok, warning = render_mermaid(mmd, mmd.with_suffix(".svg"), config)
            if ok: visual = "RENDERED"
            elif warning and warning not in warnings: warnings.append(warning)
        manifest_paths = sorted(p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file())
        manifest = {"schemaVersion": SCHEMA_VERSION, "skill": SKILL, "artifacts": manifest_paths}
        (staging / "artifact-manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
        manifest_paths.append("artifact-manifest.json")
        previous_manifest = output / "artifact-manifest.json"
        owned = []
        if previous_manifest.exists():
            try: owned = json.loads(previous_manifest.read_text(encoding="utf-8"))["artifacts"]
            except (ValueError, KeyError): owned = []
        for name in sorted(set(owned) - set(manifest_paths)):
            target = output / name
            if target.is_file(): target.unlink()
        for source in sorted(staging.rglob("*")):
            if not source.is_file(): continue
            rel = source.relative_to(staging); target = output / rel; target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target); written.append(target.as_posix())
    return sorted(written), warnings, visual


def confirm_visual_verification(root: Path, output: Path | None = None, language: str = "zh") -> tuple[dict[str, Any], list[str]]:
    """Persist an Agent's explicit post-inspection decision; never auto-approve."""
    root = root.resolve(); output = output or root / "reports" / SKILL
    reject_symlink_components(root, output)
    model_path = output / "database-model.json"
    if not model_path.is_file(): raise ValueError("No generated database-model.json is available for visual verification")
    model = json.loads(model_path.read_text(encoding="utf-8")); errors = validate_model(model)
    if errors: raise ValueError("Cannot verify visuals for an invalid model: " + "; ".join(errors))
    diagrams = sorted(output.rglob("*.mmd"))
    if not diagrams: raise ValueError("No Mermaid diagrams are available")
    missing = [path.relative_to(output).as_posix() for path in diagrams if not path.with_suffix(".svg").is_file()]
    if missing: raise ValueError("SVG rendering is incomplete: " + ", ".join(missing))
    for diagram in diagrams:
        svg = diagram.with_suffix(".svg").read_text(encoding="utf-8", errors="replace")
        if "<svg" not in svg or "viewBox" not in svg: raise ValueError(f"Invalid SVG for {diagram.relative_to(output).as_posix()}")
    model["visualStatus"] = "VERIFIED"
    atomic_write_text(model_path, canonical_json(model)); atomic_write_text(output / "database-analysis.md", generate_report(model, language))
    return model, [path.with_suffix(".svg").as_posix() for path in diagrams]


def load_reviews(data_root: Path) -> dict[str, Any]:
    path = data_root / "user-review.json"
    if not path.exists(): return {"schemaVersion": SCHEMA_VERSION, "reviews": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data.get("reviews"), list) else {"schemaVersion": SCHEMA_VERSION, "reviews": []}
    except (ValueError, OSError): return {"schemaVersion": SCHEMA_VERSION, "reviews": []}


def load_incremental(state_path: Path, context_hash: str) -> dict[str, Any]:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("ruleVersion") == RULE_VERSION and state.get("contextHash") == context_hash: return state
    except (OSError, ValueError): pass
    return {"schemaVersion": SCHEMA_VERSION, "ruleVersion": RULE_VERSION, "contextHash": context_hash, "files": {}}


def analyze_project(root: Path, output: Path | None = None, scope: str | None = None, include_tests: bool = False, language: str = "zh", save: bool = True, full_rescan: bool = False, config_path: Path | None = None, application: str | None = None, data_source: str | None = None, profile: str | None = None) -> tuple[dict[str, Any], list[str], list[str]]:
    root = root.resolve()
    if not root.is_dir(): raise ValueError(f"Project directory does not exist: {root}")
    output = output or root / "reports" / SKILL
    data_root = root / "data" / SKILL / project_id(root)
    reject_symlink_components(root, output)
    reject_symlink_components(root, data_root)
    files, skipped = discover_files(root, include_tests)
    config_paths = [path for path in files if path.name in {"pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"} or path.name.startswith("application")]
    context_hash = sha256_bytes("".join(path.relative_to(root).as_posix() + ":" + sha256_bytes(path.read_bytes()) for path in config_paths).encode("utf-8"))
    state_path = data_root / "incremental-state.json"
    state = {"schemaVersion": SCHEMA_VERSION, "ruleVersion": RULE_VERSION, "contextHash": context_hash, "files": {}} if full_rescan or not save else load_incremental(state_path, context_hash)
    new_state = {"schemaVersion": SCHEMA_VERSION, "ruleVersion": RULE_VERSION, "contextHash": context_hash, "files": {}}
    fragments = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            digest = sha256_bytes(path.read_bytes())
        except OSError as exc:
            ev = evidence(rel, 1, 1, "DISCOVERY")
            fragment = Fragment(rel, stable_id("unreadable", rel), [{"kind": "evidence", "value": ev}], [{"kind": "UNREADABLE_FILE", "message": str(exc), "evidenceIds": [ev["id"]]}]).json()
            new_state["files"][rel] = {"contentHash": fragment["contentHash"], "fragment": fragment}
            fragments.append(fragment)
            if save: atomic_write_text(state_path, canonical_json(new_state))
            continue
        cached = state["files"].get(rel)
        if cached and cached.get("contentHash") == digest:
            fragment = cached["fragment"]
        else:
            fragment = analyze_file(path, root).json()
        new_state["files"][rel] = {"contentHash": digest, "fragment": fragment}
        fragments.append(fragment)
        if save:
            # Each fragment is independently valid and content-addressed. Save
            # progress so an interrupted large scan can resume without treating
            # incomplete facts as a published model.
            atomic_write_text(state_path, canonical_json(new_state))
    tech = detect_technologies(files); dialects = detect_dialects(files); profiles = detect_profiles(files); effective_profiles = [profile] if profile else profiles; apps = detect_applications(root, files); data_sources = detect_data_sources(files)
    reviews = load_reviews(data_root) if data_root.exists() else {"schemaVersion": SCHEMA_VERSION, "reviews": []}
    if len(apps) == 1 and len(data_sources) > 1:
        data_source_models = []
        assigned_files: set[str] = set()
        for detected_source in data_sources:
            tokens = [token.lower() for token in re.split(r"[._-]", detected_source.get("name", "")) if token.lower() not in {"spring", "datasource", "jdbc", "url", "default"}]
            selected = [fragment for fragment in fragments if any(token in fragment["file"].lower().split("/") for token in tokens)]
            if not selected: continue
            selected_names = {fragment["file"] for fragment in selected}; assigned_files.update(selected_names)
            selected_files = [path for path in files if path.relative_to(root).as_posix() in selected_names]
            facts = merge_fragments(selected); apply_jpa_xml_overrides(facts); apply_jpa_structural_fields(facts); infer_project_value_flows(root, selected_files, facts); resolve_project_provider_targets(selected_files, facts)
            data_source_models.append(finalize_model(root, facts, selected_files, [], tech, [detected_source["dialect"]], effective_profiles, apps, [detected_source], scope, reviews))
        if data_source_models:
            model = combine_application_models(data_source_models, apps, files, skipped, tech, dialects, effective_profiles, data_sources, scope, root)
            if len(assigned_files) < len(fragments):
                item = {"id": stable_id("unresolved", "UNBOUND_DATASOURCE_FILES"), "kind": "DATA_SOURCE_IDENTITY", "message": "Some project files could not be bound unambiguously to one of the detected data sources", "evidenceIds": []}
                model["unresolved"].append(item); model["unresolved"].sort(key=lambda value: value["id"]); model["analysisStatus"] = "PARTIAL"; model["coverage"]["unresolved"] = len(model["unresolved"])
        else:
            facts = merge_fragments(fragments); apply_jpa_xml_overrides(facts); apply_jpa_structural_fields(facts); infer_project_value_flows(root, files, facts); resolve_project_provider_targets(files, facts)
            facts.unresolved.append({"kind": "DATA_SOURCE_IDENTITY", "message": "Multiple data sources were detected but source files could not be bound to them", "evidenceIds": []})
            model = finalize_model(root, facts, files, skipped, tech, dialects, effective_profiles, apps, data_sources, scope, reviews)
    elif len(apps) > 1:
        app_models = []
        for app in apps:
            prefix = "" if app["root"] == "." else app["root"].rstrip("/") + "/"
            app_fragments = [fragment for fragment in fragments if not prefix or fragment["file"].startswith(prefix)]
            app_files = [path for path in files if not prefix or path.relative_to(root).as_posix().startswith(prefix)]
            app_sources = detect_data_sources(app_files)
            if len(app_sources) > 1:
                bound_any = False
                for detected_source in app_sources:
                    tokens = [token.lower() for token in re.split(r"[._-]", detected_source.get("name", "")) if token.lower() not in {"spring", "datasource", "jdbc", "url", "default"}]
                    selected = [fragment for fragment in app_fragments if any(token in fragment["file"].lower().split("/") for token in tokens)]
                    if not selected: continue
                    bound_any = True; selected_names = {fragment["file"] for fragment in selected}; selected_files = [path for path in app_files if path.relative_to(root).as_posix() in selected_names]
                    facts = merge_fragments(selected); apply_jpa_xml_overrides(facts); apply_jpa_structural_fields(facts); infer_project_value_flows(root, selected_files, facts); resolve_project_provider_targets(selected_files, facts)
                    app_models.append(finalize_model(root, facts, selected_files, [], tech, [detected_source["dialect"]], effective_profiles, [app], [detected_source], scope, reviews))
                if bound_any: continue
            facts = merge_fragments(app_fragments); apply_jpa_xml_overrides(facts); apply_jpa_structural_fields(facts); infer_project_value_flows(root, app_files, facts); resolve_project_provider_targets(app_files, facts)
            app_models.append(finalize_model(root, facts, app_files, [], tech, dialects, effective_profiles, [app], app_sources, scope, reviews))
        model = combine_application_models(app_models, apps, files, skipped, tech, dialects, effective_profiles, data_sources, scope, root)
    else:
        facts = merge_fragments(fragments); apply_jpa_xml_overrides(facts); apply_jpa_structural_fields(facts); infer_project_value_flows(root, files, facts); resolve_project_provider_targets(files, facts)
        model = finalize_model(root, facts, files, skipped, tech, dialects, effective_profiles, apps, data_sources, scope, reviews)
    # Migration inventory is repository-wide, including multi-application and
    # multi-data-source layouts. Attach it after model isolation so cross-file
    # include/order problems are never silently lost.
    for issue in migration_inventory_issues(root, files):
        ev = issue.get("evidence"); ev_ids = []
        if ev:
            model["evidence"] = [item for item in model["evidence"] if item["id"] != ev["id"]] + [ev]
            model["evidence"].sort(key=lambda item: item["id"]); ev_ids = [ev["id"]]
        item = {"id": stable_id("unresolved", issue["kind"], issue["message"], *ev_ids), "kind": issue["kind"], "message": issue["message"], "evidenceIds": ev_ids}
        if not any(existing["id"] == item["id"] for existing in model["unresolved"]): model["unresolved"].append(item)
    model["unresolved"].sort(key=lambda item: item["id"]); model["coverage"]["unresolved"] = len(model["unresolved"])
    if model["unresolved"] or model["conflicts"]: model["analysisStatus"] = "PARTIAL"
    jdk_issue = verify_java_syntax_with_jdk(files)
    if jdk_issue:
        # This parser is an optional source-syntax cross-check.  The evidence
        # model comes from deterministic project-file analysis, so a local JDK
        # capability gap is reported separately rather than degrading it.
        model["environmentDiagnostics"] = [{"kind": "JDK_SOURCE_VERIFICATION", "message": jdk_issue}]
    if application or data_source or profile:
        app_ids = {item["id"] for item in model["applications"] if not application or application.lower() in {item["id"].lower(), item["name"].lower()}}
        ds_ids = {item["id"] for item in model["dataSources"] if not data_source or data_source.lower() in {item["id"].lower(), item.get("name", "").lower()}}
        object_ids = {obj["id"] for obj in model["databaseObjects"] if (not application or obj.get("applicationId") in app_ids) and (not data_source or obj.get("dataSourceId") in ds_ids) and (not profile or obj.get("profile") in {None, profile})}
        model["databaseObjects"] = [obj for obj in model["databaseObjects"] if obj["id"] in object_ids]
        model["relationships"] = [rel for rel in model["relationships"] if rel["from"]["objectId"] in object_ids and rel["to"]["objectId"] in object_ids]
        model["candidates"] = [rel for rel in model["candidates"] if rel["from"]["objectId"] in object_ids and rel["to"]["objectId"] in object_ids]
        model["operations"] = [op for op in model["operations"] if op["databaseObjectId"] in object_ids]
        model["objectMappings"] = [mapping for mapping in model["objectMappings"] if set(mapping["databaseObjectIds"]) & object_ids]
    errors = validate_model(model)
    if errors:
        model["analysisStatus"] = "FAILED"
        raise ValueError("Model validation failed: " + "; ".join(errors))
    if save:
        atomic_write_text(state_path, canonical_json(new_state))
    artifacts = {
        "database-model.json": canonical_json(model), "database-erd.mmd": generate_mermaid(model),
        "database.dbml": generate_dbml(model), "database-analysis.md": generate_report(model, language),
    }
    logic = generate_logic_mermaid(model)
    if logic: artifacts["database-relations.mmd"] = logic
    if len(model["databaseObjects"]) > 25 or len(model["relationships"]) > 50:
        artifacts["database-erd-overview.mmd"] = generate_overview_mermaid(model)
        # Stable connected components capped at 25 objects.
        adjacency = defaultdict(set)
        for rel in model["relationships"]:
            a, b = rel["from"]["objectId"], rel["to"]["objectId"]; adjacency[a].add(b); adjacency[b].add(a)
        remaining = {o["id"] for o in model["databaseObjects"]}; clusters = []
        while remaining:
            seed = min(remaining); queue = deque([seed]); component = []
            while queue and len(component) < 25:
                node = queue.popleft()
                if node not in remaining: continue
                remaining.remove(node); component.append(node)
                queue.extend(sorted(adjacency[node] & remaining))
            clusters.append(set(component))
        for i, ids in enumerate(clusters, 1): artifacts[f"erd/cluster-{i:02d}.mmd"] = generate_mermaid(model, ids)
    written: list[str] = []; warnings: list[str] = []
    if save:
        config = config_path or Path(__file__).resolve().parents[2] / "assets" / "mermaid-config.json"
        written, warnings, visual = atomic_publish(output, artifacts, config)
        # Rendering is not the same as visual verification. Keep the schema-valid
        # pre-render status until an Agent has actually inspected every SVG.
        # The SVG files are still returned in the artifact manifest when present.
    return model, written, warnings


def doctor(project: Path) -> dict[str, Any]:
    python_ok = tuple(__import__("sys").version_info[:2]) >= (3, 10)
    java = shutil.which("java"); javac = shutil.which("javac"); mmdc = shutil.which("mmdc")
    root = project.resolve(); writable = os.access(root, os.W_OK)
    files, _ = discover_files(root) if root.is_dir() else ([], [])
    language_level = detect_java_language_level(files)
    def tool_version(command: list[str]) -> str | None:
        if not command[0]: return None
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
            output = (result.stdout + "\n" + result.stderr).strip().splitlines()
            return output[0].strip() if output else None
        except (OSError, subprocess.SubprocessError): return None
    java_version = tool_version([java, "-version"]) if java else None
    javac_version = tool_version([javac, "-version"]) if javac else None
    mermaid_version = tool_version([mmdc, "--version"]) if mmdc else None
    warnings = []
    if not python_ok: warnings.append("Python 3.10+ is required for complete deterministic analysis.")
    if not java or not javac: warnings.append("A local JDK is unavailable; the optional Java syntax cross-check will be skipped, but database analysis can still complete.")
    if not mmdc: warnings.append("Mermaid CLI is unavailable; SVG rendering and local visual QA will be skipped, but Mermaid source will still be delivered.")
    if not writable: warnings.append("Project directory is not writable; reports and incremental state cannot be saved.")
    return {"python": {"available": python_ok, "version": __import__("platform").python_version()}, "jdk": {"java": java, "javac": javac, "javaVersion": java_version, "javacVersion": javac_version, "projectLanguageLevel": language_level}, "mermaid": {"mmdc": mmdc, "version": mermaid_version}, "paths": {"project": root.as_posix(), "reportWritable": writable and os.access(root, os.W_OK), "dataWritable": writable and os.access(root, os.W_OK)}, "projectWritable": writable, "warnings": warnings, "safety": {"connectsDatabase": False, "runsProject": False, "buildsProject": False, "usesNetwork": False, "installsSoftware": False}}
