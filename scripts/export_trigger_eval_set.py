#!/usr/bin/env python3
"""Export a repository trigger-evals object as skill-creator's JSON array."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    document = json.loads(args.input.read_text(encoding="utf-8"))
    queries = document.get("queries") if isinstance(document, dict) else document
    if not isinstance(queries, list) or not queries:
        parser.error("input must be a query array or an object containing non-empty queries")
    normalized = [{"query": item["query"], "should_trigger": bool(item["should_trigger"])} for item in queries]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
