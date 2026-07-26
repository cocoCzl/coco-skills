#!/usr/bin/env python3
"""Run lightweight structural checks for every top-level skill in this repository."""

from __future__ import annotations

import ast
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
