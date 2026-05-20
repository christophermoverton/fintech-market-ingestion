"""Validate repository hygiene expectations for tracked files."""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

TEXT_EXTENSIONS = {".md", ".py", ".toml", ".txt", ".yml", ".yaml"}
PATH_SCAN_EXTENSIONS = TEXT_EXTENSIONS

FORBIDDEN_EXACT_PATHS = {
    ".env",
    ".env.local",
    ".envrc",
}
FORBIDDEN_PREFIXES = (
    ".venv/",
    "venv/",
    "data/",
    "artifacts/",
    "reports/",
    "dist/",
    "build/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".ipynb_checkpoints/",
)
FORBIDDEN_PARTS = (
    "/__pycache__/",
    "/.pytest_cache/",
    "/.ruff_cache/",
    "/.ipynb_checkpoints/",
)
FORBIDDEN_SUFFIXES = (
    ".egg-info/PKG-INFO",
    ".egg-info/SOURCES.txt",
    ".egg-info/dependency_links.txt",
    ".egg-info/entry_points.txt",
    ".egg-info/requires.txt",
    ".egg-info/top_level.txt",
)

LOCAL_PATH_PATTERNS = (
    re.compile(r"\b[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/][^ \t\r\n`'\"<>]+"),
    re.compile(r"(?<!\w)/(?:Users|home)/[A-Za-z0-9._-]+/[^ \t\r\n`'\"<>]+"),
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    failures: list[str]
    hint: str

    @property
    def passed(self) -> bool:
        return not self.failures


def tracked_files() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    output = completed.stdout.decode("utf-8")
    return [path for path in output.split("\0") if path and (REPO_ROOT / path).exists()]


def is_checked_text_file(path: str) -> bool:
    return Path(path).suffix.lower() in TEXT_EXTENSIONS


def read_bytes(path: str) -> bytes:
    return (REPO_ROOT / path).read_bytes()


def check_lf_line_endings(paths: Sequence[str]) -> CheckResult:
    failures = [path for path in paths if is_checked_text_file(path) and b"\r\n" in read_bytes(path)]
    return CheckResult(
        name="LF line endings",
        failures=failures,
        hint="Convert tracked text files to LF line endings and recommit them.",
    )


def is_forbidden_tracked_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized in FORBIDDEN_EXACT_PATHS:
        return True
    if normalized.endswith(".egg-info") or ".egg-info/" in normalized:
        return True
    if normalized.endswith("/__pycache__") or "/__pycache__/" in normalized:
        return True
    if normalized.startswith(FORBIDDEN_PREFIXES):
        return True
    if any(part in f"/{normalized}/" for part in FORBIDDEN_PARTS):
        return True
    return normalized.endswith(FORBIDDEN_SUFFIXES)


def check_forbidden_tracked_paths(paths: Sequence[str]) -> CheckResult:
    failures = [path for path in paths if is_forbidden_tracked_path(path)]
    return CheckResult(
        name="Generated/local-only tracked paths",
        failures=failures,
        hint="Remove generated or local-only files from Git and keep them ignored.",
    )


def check_credential_files(paths: Sequence[str]) -> CheckResult:
    failures = [
        path
        for path in paths
        if Path(path.replace("\\", "/")).name in FORBIDDEN_EXACT_PATHS
        or path.replace("\\", "/").startswith((".secrets/", ".tokens/"))
    ]
    return CheckResult(
        name="Credential file avoidance",
        failures=failures,
        hint="Remove credential-bearing local files from Git; use local env files or repository secrets.",
    )


def check_portable_paths(paths: Sequence[str]) -> CheckResult:
    failures: list[str] = []
    for path in paths:
        if Path(path).suffix.lower() not in PATH_SCAN_EXTENSIONS:
            continue
        try:
            text = read_bytes(path).decode("utf-8")
        except UnicodeDecodeError:
            continue
        matches = []
        for pattern in LOCAL_PATH_PATTERNS:
            matches.extend(match.group(0) for match in pattern.finditer(text))
        if matches:
            failures.append(f"{path}: {', '.join(sorted(set(matches)))}")

    return CheckResult(
        name="Path portability",
        failures=failures,
        hint="Replace local absolute paths with repository-relative paths or portable examples.",
    )


def print_result(result: CheckResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    print(f"[{status}] {result.name}")
    if result.passed:
        return
    for failure in result.failures:
        print(f"  - {failure}")
    print(f"  Hint: {result.hint}")


def run_checks(paths: Sequence[str]) -> Iterable[CheckResult]:
    checks: Sequence[Callable[[Sequence[str]], CheckResult]] = (
        check_lf_line_endings,
        check_forbidden_tracked_paths,
        check_credential_files,
        check_portable_paths,
    )
    for check in checks:
        yield check(paths)


def main() -> int:
    try:
        paths = tracked_files()
    except subprocess.CalledProcessError as exc:
        print(f"Failed to list tracked files with git ls-files: {exc}", file=sys.stderr)
        return exc.returncode

    results = list(run_checks(paths))
    for result in results:
        print_result(result)

    if any(not result.passed for result in results):
        print("\nRepository hygiene check failed.")
        return 1

    print("\nRepository hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
