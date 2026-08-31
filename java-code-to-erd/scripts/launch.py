#!/usr/bin/env python3
"""Dependency-free bootstrap that locates an already-installed Python 3.10+."""

from __future__ import print_function

import json
import os
import shutil
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRYPOINT = os.path.join(SCRIPT_DIR, "java_code_to_erd.py")


def fail():
    payload = {
        "schema_version": "1.0",
        "skill": "java-code-to-erd",
        "command": sys.argv[1] if len(sys.argv) > 1 else "bootstrap",
        "status": "error",
        "data_status": "FAILED",
        "next_action": "Use an already-installed Python 3.10 or newer; the Skill will not install it.",
        "artifacts": [],
        "warnings": ["No compatible Python 3.10+ interpreter was found on PATH."],
        "error_code": "PYTHON_VERSION_UNAVAILABLE",
        "metrics": {"elapsed_ms": 0},
        "data": None,
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return 1


def main():
    if sys.version_info[:2] >= (3, 10):
        os.execv(sys.executable, [sys.executable, ENTRYPOINT] + sys.argv[1:])
    for name in ("python3.13", "python3.12", "python3.11", "python3.10"):
        executable = shutil.which(name)
        if executable:
            os.execv(executable, [executable, ENTRYPOINT] + sys.argv[1:])
    return fail()


if __name__ == "__main__":
    sys.exit(main())
