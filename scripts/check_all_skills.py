#!/usr/bin/env python3
"""Run lightweight structural checks for every top-level skill in this repository."""

from __future__ import annotations

import ast
import json
import pathlib
import re
import subprocess
from typing import Optional


ROOT = pathlib.Path(__file__).resolve().parents[1]
IGNORED_DIRS = {
    ".agent",
    ".agents",
    ".claude",
    ".codex",
    ".git",
    ".idea",
    ".pi",
    ".pytest_cache",
    ".skill-workspaces",
    ".venv",
    "data",
    "docs",
    "evals",
    "examples",
    "output",
    "reports",
    "scripts",
    "tests",
}
FRONTMATTER_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(.*)$")
README_SKILL_LINK = re.compile(r"\]\(\s*(?:\./)?(?P<target>[^)\s]+/SKILL\.md)\s*\)")
MARKDOWN_LINK = re.compile(r"\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
LOCAL_ONLY_DIRECTORIES = {
    ".agent",
    ".agents",
    ".claude",
    ".codex",
    ".idea",
    ".pi",
    ".pytest_cache",
    ".skill-workspaces",
    "__pycache__",
    "data",
    "output",
    "reports",
}
LOCAL_ONLY_FILES = {".DS_Store", "skills-lock.json"}


def _yaml_scalar(value: str) -> str:
    """Return a simple YAML scalar without adding a PyYAML dependency.

    Skill frontmatter only needs top-level ``name`` and ``description``.  This
    deliberately supports plain and quoted scalars, plus the common block
    scalar form handled by ``read_frontmatter`` below.
    """

    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1].strip()
        if isinstance(parsed, str):
            return parsed.strip()
    return value


def read_frontmatter(path: pathlib.Path) -> dict[str, str]:
    """Read the shallow YAML frontmatter needed by the repository contract."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError("could not read file: {0}".format(exc)) from exc

    if not lines or lines[0].strip() != "---":
        raise ValueError("missing opening YAML frontmatter delimiter")
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("missing closing YAML frontmatter delimiter") from exc

    fields: dict[str, str] = {}
    index = 1
    while index < end:
        line = lines[index]
        index += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = FRONTMATTER_KEY.match(line)
        if not match:
            raise ValueError("unsupported frontmatter line {0}: {1}".format(index, line))
        key, value = match.groups()
        if key in fields:
            raise ValueError("duplicate frontmatter field: {0}".format(key))
        if value.strip() in {"|", ">", "|-", ">-", "|+", ">+"}:
            block: list[str] = []
            while index < end and lines[index][:1].isspace():
                block.append(lines[index].strip())
                index += 1
            fields[key] = " ".join(item for item in block if item).strip()
        else:
            fields[key] = _yaml_scalar(value)
    return fields


def tracked_paths() -> list[str]:
    """Return Git-tracked paths so ignored local state cannot enter a commit."""

    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise ValueError("could not execute git ls-files: {0}".format(exc)) from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError("git ls-files failed: {0}".format(detail or result.returncode))
    return [item for item in result.stdout.decode("utf-8", errors="surrogateescape").split("\0") if item]


def local_only_reason(git_path: str) -> Optional[str]:
    """Identify tracked paths that are machine-local state or generated output."""

    parts = pathlib.PurePosixPath(git_path).parts
    for part in parts:
        if part in LOCAL_ONLY_DIRECTORIES:
            return "local-only directory '{0}'".format(part)
        if part == ".venv" or part.startswith(".venv-"):
            return "local virtual environment '{0}'".format(part)
    filename = parts[-1] if parts else ""
    if filename in LOCAL_ONLY_FILES:
        return "local-only file '{0}'".format(filename)
    if filename.endswith((".pyc", ".pyo")):
        return "compiled Python artifact '{0}'".format(filename)
    return None


def discover_skills() -> list[pathlib.Path]:
    skills: list[pathlib.Path] = []
    for child in sorted(ROOT.iterdir()):
        if (
            not child.is_dir()
            or child.name in IGNORED_DIRS
            or child.name == ".venv"
            or child.name.startswith(".venv-")
        ):
            continue
        if (child / "SKILL.md").is_file():
            skills.append(child)
    return skills


def readme_registers_skill(readme: str, skill: pathlib.Path) -> bool:
    """Require a root README Markdown link for every distributable skill."""

    expected = "{0}/SKILL.md".format(skill.name)
    return any(match.group("target") == expected for match in README_SKILL_LINK.finditer(readme))


def eval_directory_name(skill: pathlib.Path) -> str:
    """Map a distributable skill directory to its repository eval directory."""

    return skill.name.replace("-", "_")


def check_markdown_links(skill: pathlib.Path) -> list[str]:
    """Return missing local links from SKILL.md without policing web links."""

    errors: list[str] = []
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    for match in MARKDOWN_LINK.finditer(text):
        raw_target = match.group("target")
        target = raw_target.split("#", 1)[0]
        if not target or "://" in target or target.startswith(("mailto:", "#")):
            continue
        candidate = (skill / target).resolve()
        try:
            candidate.relative_to(skill.resolve())
        except ValueError:
            errors.append("link escapes skill directory: {0}".format(raw_target))
            continue
        if not candidate.exists():
            errors.append("missing local link target: {0}".format(raw_target))
    return errors


def check_evals(skill: pathlib.Path) -> list[str]:
    """Validate the repository-level behavior and trigger regression sets."""

    directory = ROOT / "evals" / eval_directory_name(skill)
    behavior_path = directory / "evals.json"
    trigger_path = directory / "trigger-evals.json"
    errors: list[str] = []
    if not behavior_path.is_file() or not trigger_path.is_file():
        return ["missing repository evals/evals.json or trigger-evals.json"]
    try:
        behavior = json.loads(behavior_path.read_text(encoding="utf-8"))
        trigger = json.loads(trigger_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return ["invalid evaluation JSON: {0}".format(exc)]

    cases = behavior.get("evals") if isinstance(behavior, dict) else None
    if not isinstance(cases, list) or len(cases) < 10:
        errors.append("behavior evals must contain at least 10 cases")
    else:
        ids = [str(item.get("id", "")) for item in cases if isinstance(item, dict)]
        if len(ids) != len(cases) or not all(ids) or len(set(ids)) != len(ids):
            errors.append("behavior eval IDs must be present and unique")
        for item in cases:
            if not isinstance(item, dict) or not all(
                isinstance(item.get(key), str) and item[key].strip()
                for key in ("prompt", "expected_output")
            ):
                errors.append("each behavior eval needs non-empty prompt and expected_output")
                break
            expectations = item.get("expectations")
            if not isinstance(expectations, list) or len(expectations) < 3:
                errors.append("each behavior eval needs at least 3 expectations")
                break

    queries = trigger.get("queries") if isinstance(trigger, dict) else None
    if not isinstance(queries, list) or len(queries) < 20:
        errors.append("trigger evals must contain at least 20 near-neighbor queries")
    else:
        positive = negative = 0
        ids: list[str] = []
        for item in queries:
            if not isinstance(item, dict):
                errors.append("each trigger eval must be an object")
                break
            ids.append(str(item.get("id", "")))
            query = item.get("query")
            reason = item.get("reason")
            decision = item.get("should_trigger")
            if not isinstance(query, str) or len(query.strip()) < 15 or not isinstance(reason, str) or not reason.strip():
                errors.append("each trigger eval needs a realistic query and reason")
                break
            if decision is True:
                positive += 1
            elif decision is False:
                negative += 1
            else:
                errors.append("each trigger eval needs boolean should_trigger")
                break
        if not all(ids) or len(ids) != len(set(ids)):
            errors.append("trigger eval IDs must be present and unique")
        if positive < 8 or negative < 8 or positive != negative:
            errors.append("trigger evals must be balanced with at least 8 positive and 8 negative cases")
    return errors


def main() -> int:
    skills = discover_skills()
    if not skills:
        print("No top-level skills found.")
        return 1

    failed = False
    try:
        root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    except OSError as exc:
        root_readme = ""
        failed = True
        print("Could not read root README.md: {0}".format(exc))

    for skill in skills:
        print(f"\n== {skill.name} ==")
        required = [skill / "SKILL.md", skill / "README.md"]
        missing = [path.name for path in required if not path.is_file()]
        if missing:
            failed = True
            print(f"Missing required files: {', '.join(missing)}")
        else:
            print("Required files present.")
            try:
                frontmatter = read_frontmatter(skill / "SKILL.md")
            except ValueError as exc:
                failed = True
                print("Invalid SKILL.md frontmatter: {0}".format(exc))
            else:
                if frontmatter.get("name") != skill.name:
                    failed = True
                    print(
                        "Frontmatter name must match directory: expected '{0}', found '{1}'.".format(
                            skill.name, frontmatter.get("name", "<missing>")
                        )
                    )
                else:
                    print("Frontmatter name matches directory.")
                if not frontmatter.get("description", "").strip():
                    failed = True
                    print("Frontmatter description must be non-empty.")
                else:
                    print("Frontmatter description present.")
            line_count = len((skill / "SKILL.md").read_text(encoding="utf-8").splitlines())
            if line_count > 500:
                failed = True
                print("SKILL.md exceeds 500 lines; move detailed material into references/.")
            else:
                print("SKILL.md stays within the progressive-disclosure budget.")
            link_errors = check_markdown_links(skill)
            if link_errors:
                failed = True
                print("Broken SKILL.md links:")
                for error in link_errors:
                    print("- {0}".format(error))
            else:
                print("SKILL.md local links resolve.")

        interface_schema = skill / "schemas" / "agent-result.schema.json"
        if not interface_schema.is_file():
            failed = True
            print("Missing schemas/agent-result.schema.json.")
        else:
            try:
                import json

                contract = json.loads(interface_schema.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                failed = True
                print("Invalid agent result schema: {0}".format(exc))
            else:
                required_result_fields = {
                    "schema_version", "skill", "command", "status", "data_status",
                    "next_action", "artifacts", "warnings", "error_code", "metrics",
                }
                if not required_result_fields.issubset(set(contract.get("required", []))):
                    failed = True
                    print("Agent result schema is missing required envelope fields.")
                else:
                    print("Agent result schema present.")

        eval_errors = check_evals(skill)
        if eval_errors:
            failed = True
            print("Evaluation contract failures:")
            for error in eval_errors:
                print("- {0}".format(error))
        else:
            print("Behavior and trigger evaluation sets are release-ready.")

        if not readme_registers_skill(root_readme, skill):
            failed = True
            print("Root README.md does not register this skill.")
        else:
            print("Root README.md registers this skill.")

    try:
        forbidden = [(path, local_only_reason(path)) for path in tracked_paths()]
    except ValueError as exc:
        failed = True
        print("\nCould not inspect tracked local state: {0}".format(exc))
    else:
        forbidden = [(path, reason) for path, reason in forbidden if reason]
        if forbidden:
            failed = True
            print("\nTracked local/runtime or generated paths are not allowed:")
            for path, reason in forbidden:
                print("- {0}: {1}".format(path, reason))
        else:
            print("\nNo tracked local/runtime or generated paths found.")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
