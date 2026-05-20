"""Run the repository's credential-free validation checks."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Sequence
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONSOLE_SCRIPT = "fintech-ingest-corporate-actions"


def format_command(command: Sequence[str | Path]) -> str:
    return " ".join(str(part) for part in command)


def run_step(name: str, command: Sequence[str | Path]) -> None:
    print(f"\n==> {name}", flush=True)
    print(format_command(command), flush=True)
    subprocess.run([str(part) for part in command], cwd=REPO_ROOT, check=True)


def console_script_command() -> list[str | Path]:
    executable = shutil.which(CONSOLE_SCRIPT)
    if executable:
        return [executable, "--help"]

    scripts_path = Path(sysconfig.get_path("scripts"))
    candidates = [scripts_path / CONSOLE_SCRIPT]
    if os.name == "nt":
        candidates.append(scripts_path / f"{CONSOLE_SCRIPT}.exe")

    for candidate in candidates:
        if candidate.exists():
            # Editable installs can put console-script shims in Python's scripts
            # directory even when that directory is not on PATH, especially on
            # Windows user installs. Resolve it from sysconfig instead of using
            # any platform-specific or machine-local path.
            return [candidate, "--help"]

    raise FileNotFoundError(
        f"Could not find {CONSOLE_SCRIPT!r}. Run `python -m pip install -e \".[dev]\"` "
        "with the same Python interpreter used for validation."
    )


def main() -> int:
    python = sys.executable
    try:
        steps: list[tuple[str, list[str | Path]]] = [
            ("Run repository hygiene checks", [python, "scripts/check_repo_hygiene.py"]),
            ("Run full test suite", [python, "-m", "pytest", "tests", "-q"]),
            (
                "Run M3 corporate-actions regression validation",
                [python, "-m", "pytest", "tests/test_m3_corporate_actions_validation.py", "-q"],
            ),
            ("Run Ruff lint check", [python, "-m", "ruff", "check", "src", "tests", "examples"]),
            (
                "Run Ruff format check",
                [python, "-m", "ruff", "format", "--check", "src", "tests", "examples"],
            ),
            (
                "Run py_compile smoke check",
                [python, "-m", "py_compile", "src/cli/ingest_corporate_actions.py"],
            ),
            (
                "Run module CLI help smoke check",
                [python, "-m", "src.cli.ingest_corporate_actions", "--help"],
            ),
            ("Run installed console script help smoke check", console_script_command()),
        ]

        for name, command in steps:
            run_step(name, command)
    except FileNotFoundError as exc:
        print(f"\nValidation failed: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"\nValidation failed in step: {format_command(exc.cmd)}", file=sys.stderr)
        return exc.returncode

    print("\nValidation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
