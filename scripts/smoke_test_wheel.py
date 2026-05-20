"""Install the built wheel and run credential-free CLI smoke checks."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Sequence
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = REPO_ROOT / "dist"
CONSOLE_SCRIPT = "fintech-ingest-corporate-actions"


def format_command(command: Sequence[str | Path]) -> str:
    return " ".join(str(part) for part in command)


def run_step(name: str, command: Sequence[str | Path]) -> None:
    print(f"\n==> {name}", flush=True)
    print(format_command(command), flush=True)
    subprocess.run([str(part) for part in command], cwd=REPO_ROOT, check=True)


def locate_wheel() -> Path:
    wheels = sorted(DIST_DIR.glob("*.whl"))
    if len(wheels) != 1:
        wheel_list = ", ".join(str(wheel.relative_to(REPO_ROOT)) for wheel in wheels) or "none"
        raise FileNotFoundError(
            f"Expected exactly one wheel in {DIST_DIR.relative_to(REPO_ROOT)}, found: {wheel_list}"
        )
    return wheels[0]


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
            # Wheel installs can place console-script shims in Python's scripts
            # directory even when that directory is not on PATH, especially on
            # Windows user installs. Resolve it from sysconfig so this stays
            # cross-platform and avoids hardcoded machine paths.
            return [candidate, "--help"]

    raise FileNotFoundError(
        f"Could not find {CONSOLE_SCRIPT!r} after wheel install. "
        "Check the wheel install step and Python scripts path."
    )


def main() -> int:
    python = sys.executable

    try:
        wheel = locate_wheel()
        steps: list[tuple[str, list[str | Path]]] = [
            ("Install built wheel", [python, "-m", "pip", "install", wheel]),
            (
                "Run module CLI help smoke check",
                [python, "-m", "src.cli.ingest_corporate_actions", "--help"],
            ),
        ]

        for name, command in steps:
            run_step(name, command)
        run_step("Run installed console script help smoke check", console_script_command())
    except FileNotFoundError as exc:
        print(f"\nWheel smoke test failed: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"\nWheel smoke test failed in step: {format_command(exc.cmd)}", file=sys.stderr)
        return exc.returncode

    print("\nWheel smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
