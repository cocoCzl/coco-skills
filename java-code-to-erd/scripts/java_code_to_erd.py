#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.core import (  # noqa: E402
    SCHEMA_VERSION, SKILL, analyze_project, canonical_json, confirm_visual_verification, doctor, load_reviews,
    project_id, reject_symlink_components, stable_id, validate_model,
)


def envelope(command: str, started: float, data_status: str, data=None, artifacts=None, warnings=None, error_code=None, next_action=None):
    status = {"READY": "ready", "COMPLETE": "completed", "PARTIAL": "degraded", "FAILED": "error"}[data_status]
    return {
        "schema_version": SCHEMA_VERSION, "skill": SKILL, "command": command, "status": status,
        "data_status": data_status, "next_action": next_action, "artifacts": artifacts or [],
        "warnings": warnings or [], "error_code": error_code,
        "metrics": {"elapsed_ms": round((time.monotonic() - started) * 1000, 3)}, "data": data,
    }


def add_project(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Java project root (default: current directory)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evidence-first Java code-to-ERD analyzer")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("doctor", help="Inspect local capabilities without modifying the target project"); add_project(p)
    p = sub.add_parser("analyze", help="Analyze the Java project and generate stable artifacts"); add_project(p)
    p.add_argument("--scope", help="Module, package, or database object scope")
    p.add_argument("--application", help="Restrict output to one detected application id or name")
    p.add_argument("--data-source", help="Restrict output to one detected data source id or name")
    p.add_argument("--profile", help="Restrict output to one detected configuration profile")
    p.add_argument("--output", type=Path, help="Report directory; defaults to reports/java-code-to-erd")
    p.add_argument("--include-tests", action="store_true")
    p.add_argument("--language", choices=["zh", "en"], default="zh")
    p.add_argument("--full-rescan", action="store_true")
    p = sub.add_parser("query", help="Query one database object's relationships"); add_project(p)
    p.add_argument("--object", required=True); p.add_argument("--save", action="store_true"); p.add_argument("--language", choices=["zh", "en"], default="zh")
    p = sub.add_parser("validate-model", help="Validate an existing database model"); p.add_argument("model", type=Path)
    p = sub.add_parser("verify-visuals", help="Record explicit Agent visual inspection after every SVG passes review"); add_project(p)
    p.add_argument("--output", type=Path); p.add_argument("--language", choices=["zh", "en"], default="zh")
    p = sub.add_parser("review", help="Persist a human relation confirmation or exclusion"); add_project(p)
    p.add_argument("--action", required=True, choices=["confirm", "exclude", "correct"])
    p.add_argument("--from-table", required=True); p.add_argument("--from-column", action="append", required=True)
    p.add_argument("--to-table", required=True); p.add_argument("--to-column", action="append", required=True)
    p.add_argument("--reason")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv); started = time.monotonic()
    try:
        if args.command == "doctor":
            data = doctor(args.project)
            result = envelope("doctor", started, "READY", data=data, warnings=data["warnings"], next_action="Run analyze when ready.")
        elif args.command == "analyze":
            model, artifacts, warnings = analyze_project(args.project, args.output, args.scope, args.include_tests, args.language, True, args.full_rescan, application=args.application, data_source=args.data_source, profile=args.profile)
            result = envelope("analyze", started, model["analysisStatus"], data={"analysis_status": model["analysisStatus"], "visual_status": model["visualStatus"], "environment_diagnostics": model.get("environmentDiagnostics", []), "coverage": model["coverage"], "technologies": model["technologies"], "dialects": model["dialects"], "rule_references": model.get("ruleReferences", []), "objects": len(model["databaseObjects"]), "relationships": len(model["relationships"]), "conflicts": len(model["conflicts"]), "unresolved": len(model["unresolved"])}, artifacts=artifacts, warnings=warnings, next_action="Inspect conflicts and unresolved items." if model["analysisStatus"] == "PARTIAL" else None)
        elif args.command == "query":
            model, artifacts, warnings = analyze_project(args.project, scope=args.object, language=args.language, save=args.save)
            by_id = {o["id"]: o for o in model["databaseObjects"]}
            relations = []
            for rel in model["relationships"]:
                if rel["from"]["objectId"] in by_id and rel["to"]["objectId"] in by_id:
                    relations.append({"from": by_id[rel["from"]["objectId"]]["name"], "to": by_id[rel["to"]["objectId"]]["name"], "source_types": rel["sourceTypes"], "confidence": rel["confidence"], "status": rel["status"], "constraint_cardinality": rel["constraintCardinality"], "code_cardinality": rel["codeCardinality"], "evidence_ids": rel["evidenceIds"]})
            result = envelope("query", started, model["analysisStatus"], data={"object": args.object, "database_objects": model["databaseObjects"], "relationships": relations, "conflicts": model["conflicts"], "unresolved": model["unresolved"]}, artifacts=artifacts, warnings=warnings)
        elif args.command == "validate-model":
            model = json.loads(args.model.read_text(encoding="utf-8")); errors = validate_model(model)
            result = envelope("validate-model", started, "FAILED" if errors else "COMPLETE", data={"valid": not errors, "errors": errors}, error_code="INVALID_MODEL" if errors else None)
        elif args.command == "verify-visuals":
            model, svgs = confirm_visual_verification(args.project, args.output, args.language)
            result = envelope("verify-visuals", started, "COMPLETE", data={"visual_status": model["visualStatus"], "inspected_svgs": svgs}, artifacts=svgs)
        else:
            root = args.project.resolve(); data_root = root / "data" / SKILL / project_id(root)
            reject_symlink_components(root, data_root); data_root.mkdir(parents=True, exist_ok=True)
            path = data_root / "user-review.json"; payload = load_reviews(data_root)
            review = {"id": stable_id("review", args.action, args.from_table, *args.from_column, args.to_table, *args.to_column), "action": args.action.upper(), "fromTable": args.from_table, "fromColumns": args.from_column, "toTable": args.to_table, "toColumns": args.to_column, "reason": args.reason}
            payload["reviews"] = [r for r in payload["reviews"] if r["id"] != review["id"]] + [review]
            payload["reviews"].sort(key=lambda r: r["id"])
            from lib.core import atomic_write_text
            atomic_write_text(path, canonical_json(payload))
            result = envelope("review", started, "COMPLETE", data=review, artifacts=[path.as_posix()], next_action="Run analyze to apply the review.")
    except Exception as exc:
        result = envelope(args.command, started, "FAILED", data=None, error_code=type(exc).__name__.upper(), warnings=[str(exc)], next_action="Fix the reported input or capability issue; the previous valid report was preserved.")
    sys.stdout.write(canonical_json(result))
    return 0 if result["status"] not in {"error", "blocked"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
