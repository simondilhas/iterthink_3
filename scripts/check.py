"""One command for agents and humans: uv run python scripts/check.py [--full]

Fast (default): ruff + format check + mypy on STRICT_PATHS, then
architecture tests and all tests not marked slow / e2e / jj.
--full: everything, with coverage on STRICT_PATHS and the legacy suite.

Only strict paths are linted and type-checked: the base list below plus one
file per slice in scripts/strict_paths.d/<slice>.txt (one path per line,
# comments allowed). Separate files keep parallel agents from conflicting.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BASE_STRICT_PATHS: list[str] = ["tests/v2", "scripts/check.py"]
STRICT_DIR = ROOT / "scripts" / "strict_paths.d"

COVERAGE_FAIL_UNDER = 85


KNOWN_FAILURES = ROOT / "tests" / "legacy_known_failures.txt"


def known_failures() -> list[str]:
    """1.x test node ids failing at baseline (S00). Shrink-only."""
    if not KNOWN_FAILURES.exists():
        return []
    ids = []
    for line in KNOWN_FAILURES.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            ids.append(entry)
    return ids


def module_name(path: str) -> str:
    """pytest-cov wants modules or packages, not file paths."""
    return path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")


def strict_paths() -> list[str]:
    paths = list(BASE_STRICT_PATHS)
    for file in sorted(STRICT_DIR.glob("*.txt")):
        for line in file.read_text(encoding="utf-8").splitlines():
            entry = line.split("#", 1)[0].strip()
            if entry and entry not in paths:
                paths.append(entry)
    return paths


def existing(paths: list[str]) -> list[str]:
    return [p for p in paths if (ROOT / p).exists()]


def run(name: str, cmd: list[str], env: dict[str, str] | None = None) -> bool:
    print(f"\n── {name}: {' '.join(cmd)}", flush=True)
    start = time.monotonic()
    result = subprocess.run(cmd, cwd=ROOT, env={**os.environ, **(env or {})}, check=False)
    ok = result.returncode == 0
    print(f"── {name}: {'ok' if ok else 'FAILED'} ({time.monotonic() - start:.1f}s)", flush=True)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="all tests, coverage, legacy suite")
    parser.add_argument(
        "--keep-going", action="store_true", help="run all steps even after a failure"
    )
    args = parser.parse_args()

    py = sys.executable
    strict = existing(strict_paths())
    strict_src = [p for p in strict if p.startswith("iterthink")]
    env = {"HYPOTHESIS_PROFILE": "ci"} if args.full else {}

    steps: list[tuple[str, list[str]]] = [
        ("ruff", [py, "-m", "ruff", "check", *strict]),
        ("format", [py, "-m", "ruff", "format", "--check", *strict]),
        ("mypy", [py, "-m", "mypy", *strict]),
        ("architecture", [py, "-m", "pytest", "tests/v2/architecture", "-q"]),
    ]
    if args.full:
        cov = [f"--cov={module_name(p)}" for p in strict_src]
        cov_opts = (
            [
                *cov,
                "--cov-branch",
                "--cov-report=term-missing",
                f"--cov-fail-under={COVERAGE_FAIL_UNDER}",
            ]
            if cov
            else []
        )
        steps += [
            ("tests v2", [py, "-m", "pytest", "tests/v2", "-q", *cov_opts]),
        ]
        legacy = [
            p
            for p in (ROOT / "tests").rglob("test_*.py")
            if "v2" not in p.relative_to(ROOT / "tests").parts
        ]
        if legacy:
            steps.append(
                (
                    "tests 1.x",
                    [
                        py,
                        "-m",
                        "pytest",
                        "tests",
                        "-q",
                        "--ignore=tests/v2",
                        *(f"--deselect={node}" for node in known_failures()),
                    ],
                )
            )
    else:
        fast = "not slow and not e2e and not jj"
        steps.append(("tests v2 (fast)", [py, "-m", "pytest", "tests/v2", "-q", "-m", fast]))

    failed = []
    for name, cmd in steps:
        if not run(name, cmd, env):
            failed.append(name)
            if not args.keep_going:
                break

    print("\n" + ("ALL GREEN" if not failed else f"FAILED: {', '.join(failed)}"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
