#!/usr/bin/env python3
"""Measure real static analysis, cache I/O and fact equivalence; no network.

Run separately against a baseline snapshot and current source with --skill-dir.
Temporary fixtures and outputs are deleted. Optional JDK/SVG tools are disabled
in both runs to isolate the Python scanner, not to claim end-to-end render time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-dir", type=Path, default=Path(__file__).resolve().parents[1] / "java-code-to-erd")
    parser.add_argument("--files", type=int, default=600)
    args = parser.parse_args()
    if args.files < 2:
        parser.error("--files must be at least 2")
    sys.path.insert(0, str(args.skill_dir.resolve() / "scripts"))
    from lib import core

    with tempfile.TemporaryDirectory(prefix="erd-benchmark-") as tmp:
        root = Path(tmp).resolve()
        source = root / "src/main/java/example"
        source.mkdir(parents=True)
        # Linked JPA entities plus ordinary Java services exercise full discovery,
        # cross-file relations, inference and cache hits without giant diagrams.
        for index in range(args.files):
            text = (
                f'@Entity @Table(name="table_{index}") public class Entity{index} {{\n'
                '@Id private Long id;\n'
                + (f'@ManyToOne @JoinColumn(name="parent_id") private Entity{index-1} parent;\n' if index else '')
                + 'private String label;\n}'
            ) if index < 20 else f'public class Service{index} {{ public String label() {{ return "service{index}"; }} }}'
            (source / f"Source{index:05d}.java").write_text(text, encoding="utf-8")
        original_write, original_read, original_text, original_analyze = core.atomic_write_text, Path.read_bytes, Path.read_text, core.analyze_file
        measurements = []
        models = []
        for phase in ("cold", "repeat", "one_file_changed"):
            if phase == "one_file_changed":
                path = source / "Source00000.java"
                path.write_text(path.read_text().replace("private String label;", "private String label; private Long revision;"))
            counts = {"checkpoint_writes": 0, "checkpoint_bytes": 0, "source_reads": 0, "parsed_files": 0}

            def write(path, content):
                if path.name == "incremental-state.json":
                    counts["checkpoint_writes"] += 1
                    counts["checkpoint_bytes"] += len(content.encode("utf-8"))
                return original_write(path, content)

            def read(path, *a, **kw):
                if source in path.parents:
                    counts["source_reads"] += 1
                return original_read(path, *a, **kw)

            def read_text(path, *a, **kw):
                if source in path.parents:
                    counts["source_reads"] += 1
                return original_text(path, *a, **kw)

            def analyze(*a, **kw):
                counts["parsed_files"] += 1
                return original_analyze(*a, **kw)

            started = time.perf_counter()
            with patch.object(core, "atomic_write_text", write), patch.object(Path, "read_bytes", read), patch.object(Path, "read_text", read_text), patch.object(core, "analyze_file", analyze), patch.object(core.shutil, "which", return_value=None):
                model, _, _ = core.analyze_project(root)
            elapsed = time.perf_counter() - started
            models.append(model)
            # Project identity includes a temporary absolute root; compare facts.
            facts = {key: model[key] for key in ("databaseObjects", "relationships", "evidence", "unresolved", "conflicts")}
            measurements.append({"phase": phase, "seconds": round(elapsed, 4), **counts,
                                 "fact_sha256": hashlib.sha256(core.canonical_json(facts).encode()).hexdigest()})
        assert models[0] == models[1], "Repeat scan changed facts"
        assert measurements[1]["parsed_files"] == 0
        assert measurements[2]["parsed_files"] == 1
        assert measurements[0]["fact_sha256"] != measurements[2]["fact_sha256"]
        print(json.dumps({"files": args.files, "python": sys.version.split()[0], "optional_jdk_svg": "disabled for both versions", "measurements": measurements}, indent=2))


if __name__ == "__main__":
    main()
