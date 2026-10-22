#!/usr/bin/env python3
"""Single orchestration entry point for AI Resume Expert agents.

The wrapper deliberately delegates domain work to the existing CLIs. It adds
request routing, capability diagnosis, a stable result envelope, and one
place for an agent to discover the next safe action.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SKILL = "ai-resume-expert"
SCRIPT_DIR = Path(__file__).resolve().parent
SCHEMA_VERSION = "1.0"


def envelope(command: str, started: float, *, status: str, data_status: str, next_action: str | None,
             data: Any = None, artifacts: list[str] | None = None, warnings: list[str] | None = None,
             error_code: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL,
        "command": command,
        "status": status,
        "data_status": data_status,
        "next_action": next_action,
        "artifacts": artifacts or [],
        "warnings": warnings or [],
        "error_code": error_code,
        "metrics": {"elapsed_ms": round((time.perf_counter() - started) * 1000, 3)},
    }
    if data is not None:
        result["data"] = data
    return result


def route_request(text: str, *, intent: str | None = None, target_role: str | None = None) -> dict[str, Any]:
    """Offer a bounded hint, not a semantic parser or an authorization decision.

    The agent resolves negation, mixed requests and prior conversation. Explicit
    parameters carry that decision without asking this heuristic to rediscover it.
    """
    lowered = text.lower()
    clauses = re.split(r"[，。；,;\n]", lowered)
    export_requested = any(
        any(word in clause for word in ("导出", "渲染", "生成pdf", "生成 pdf"))
        and not re.search(r"不|别|无需|禁止", clause)
        for clause in clauses
    )
    if any(word in lowered for word in ("诊断", "问题", "审查")):
        mode = "diagnosis"
    elif any(word in lowered for word in ("优化", "润色", "改写")):
        mode = "optimization"
    elif any(word in lowered for word in ("代码库", "仓库", "repository", "repo")):
        mode = "repository_evidence"
    elif export_requested:
        mode = "pdf_delivery"
    else:
        mode = "generation"
    mode = intent or mode
    target_markers = ("后端", "前端", "全栈", "客户端", "移动端", "测试开发", "android", "ios", "sre", "devops", "数据工程", "算法", "机器学习", "大模型", "架构师", "技术负责人")
    target_present = bool(target_role) or any(marker in lowered for marker in target_markers) or bool(re.search(r"\bai\b", lowered))
    actions = {
        "diagnosis": "对已授权简历按需 extract 并诊断；输入 PDF 不表示要求导出。岗位缺失时可先诊断通用问题。",
        "optimization": "复用已有目标岗位、事实和授权；必要时 extract，仅补齐事实缺口后改写。",
        "repository_evidence": "复用已有范围授权；尚未授权时说明边界，再运行 scan。",
        "pdf_delivery": "复用已确认的 Markdown 和 resume-package，运行 render；未确认内容时先补齐确认。",
        "generation": "复用已有事实，达到最低证据门槛后生成。",
    }
    next_action = actions[mode]
    if not target_present and mode in {"generation", "optimization"}:
        next_action = "先检查会话中已有的目标岗位；确实缺失时询问目标岗位。"
    return {
        "mode": mode,
        "advisory_only": True,
        "input_format_hint": "pdf" if "pdf" in lowered else None,
        "export_requested_hint": export_requested,
        "target_role_present": target_present,
        "reference_index": "references/index.md",
        "next_action": next_action,
    }


def run_child(script: str, arguments: list[str]) -> tuple[int, Any, str]:
    process = subprocess.run([sys.executable, str(SCRIPT_DIR / script), *arguments], text=True, capture_output=True, check=False)
    stream = process.stdout.strip() or process.stderr.strip()
    try:
        payload: Any = json.loads(stream)
    except json.JSONDecodeError:
        payload = {"raw_output": stream}
    return process.returncode, payload, process.stderr.strip()


def artifacts_from(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    found: list[str] = []
    for key, value in payload.items():
        if isinstance(value, str) and (key.endswith("_path") or key.endswith("_file") or key in {"output_dir", "version_dir"}):
            found.append(value)
    return found


def doctor() -> dict[str, Any]:
    required = ["extract_resume.py", "scan_repository.py", "validate_resume_package.py", "render_resume.py"]
    optional = {name: bool(shutil.which(name)) for name in ("soffice", "libreoffice", "weasyprint", "pdfinfo", "pdftotext", "pdftoppm", "pdffonts")}
    missing = [name for name in required if not (SCRIPT_DIR / name).is_file()]
    return {
        "python": sys.version.split()[0],
        "required_scripts": {name: (SCRIPT_DIR / name).is_file() for name in required},
        "optional_pdf_tools": optional,
        "pdf_render_available": any(optional[name] for name in ("soffice", "libreoffice", "weasyprint")),
        "pdf_full_validation_available": all(optional[name] for name in ("pdfinfo", "pdftotext", "pdftoppm", "pdffonts")),
        "missing_required": missing,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Inspect bundled and optional capabilities without reading user material.")
    route = commands.add_parser("route", help="Classify a natural-language request and return the safest next action.")
    route.add_argument("text")
    route.add_argument("--intent", choices=("diagnosis", "optimization", "repository_evidence", "pdf_delivery", "generation"))
    route.add_argument("--target-role", help="Target already known from conversation; do not re-ask it.")
    extract = commands.add_parser("extract", help="Delegate authorized resume extraction.")
    extract.add_argument("input")
    extract.add_argument("--authorized", action="store_true")
    extract.add_argument("--format", choices=("auto", "txt", "md", "docx", "pdf", "image"), default="auto")
    scan = commands.add_parser("scan", help="Delegate authorized static repository evidence scanning.")
    scan.add_argument("target")
    scan.add_argument("--authorized", action="store_true")
    scan.add_argument("--include-git-hints", action="store_true")
    scan.add_argument("--git-authorized", action="store_true")
    validate = commands.add_parser("validate", help="Validate a resume package or evidence trace.")
    validate.add_argument("input")
    validate.add_argument("--stage", choices=("markdown", "pdf"))
    render = commands.add_parser("render", help="Create HTML or a confirmed PDF through the existing renderer.")
    render.add_argument("input")
    render.add_argument("--output-dir")
    render.add_argument("--package")
    render.add_argument("--confirmed", action="store_true")
    return parser


def main() -> int:
    started = time.perf_counter()
    args = build_parser().parse_args()
    if args.command == "doctor":
        data = doctor()
        status = "ready" if not data["missing_required"] else "blocked"
        output = envelope("doctor", started, status=status, data_status="capabilities_checked", next_action=None if status == "ready" else "Restore missing bundled scripts.", data=data, error_code=None if status == "ready" else "DEPENDENCY_MISSING")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if status == "ready" else 2
    if args.command == "route":
        data = route_request(args.text, intent=args.intent, target_role=args.target_role)
        output = envelope("route", started, status="ready", data_status="request_classified", next_action=data["next_action"], data=data)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    child_args: list[str]
    if args.command == "extract":
        child_args = [args.input, "--format", args.format] + (["--authorized"] if args.authorized else [])
        script = "extract_resume.py"
    elif args.command == "scan":
        child_args = [args.target]
        child_args += ["--authorized"] if args.authorized else []
        child_args += ["--include-git-hints"] if args.include_git_hints else []
        child_args += ["--git-authorized"] if args.git_authorized else []
        script = "scan_repository.py"
    elif args.command == "validate":
        child_args = [args.input] + (["--stage", args.stage] if args.stage else [])
        script = "validate_resume_package.py"
    else:
        child_args = [args.input]
        child_args += ["--output-dir", args.output_dir] if args.output_dir else []
        child_args += ["--package", args.package] if args.package else []
        child_args += ["--confirmed"] if args.confirmed else []
        script = "render_resume.py"

    code, payload, stderr = run_child(script, child_args)
    child_error = payload.get("error", {}) if isinstance(payload, dict) else {}
    error_code = child_error.get("code") if isinstance(child_error, dict) else None
    if code == 0:
        status, data_status, next_action = "completed", "validated_output", payload.get("next_action") if isinstance(payload, dict) else None
    elif code == 3:
        status, data_status, next_action = "degraded", "capability_unavailable", payload.get("next_action") if isinstance(payload, dict) else "Supply the missing local capability or confirm extracted material."
    else:
        status, data_status, next_action = "blocked", "child_command_failed", child_error.get("message") if isinstance(child_error, dict) else "Inspect the child command output."
    warnings = [stderr] if stderr and not isinstance(payload, dict) else []
    output = envelope(args.command, started, status=status, data_status=data_status, next_action=next_action, data=payload, artifacts=artifacts_from(payload), warnings=warnings, error_code=error_code or ("CHILD_COMMAND_FAILED" if code else None))
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
