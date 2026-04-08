#!/usr/bin/env python3
"""Pre-deploy trust check for Penny.

This script is intentionally lightweight and offline-safe:
- compiles all Python files
- checks for accidental duplicate __main__ entrypoints
- validates core config invariants
- validates launchd templates include required reliability keys
- runs unit tests
"""
from __future__ import annotations

import ast
import os
import py_compile
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

ROOT = Path(__file__).resolve().parent.parent

EXCLUDE_DIR_NAMES = {".git", "__pycache__", "venv", ".venv"}
# Note: com.penny.export.plist.template intentionally sets RunAtLoad and
# KeepAlive to <false/> (StartInterval-based, not persistent). The check
# verifies the keys exist (reliability documentation), not their values.
REQUIRED_LAUNCHD_KEYS = (
    "<key>RunAtLoad</key>",
    "<key>KeepAlive</key>",
    "<key>WorkingDirectory</key>",
    "<key>EnvironmentVariables</key>",
    "<key>PATH</key>",
    "<key>StandardOutPath</key>",
    "<key>StandardErrorPath</key>",
    "<key>SoftResourceLimits</key>",
)


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
            continue
        yield path


def compile_all(py_files: List[Path]) -> None:
    print("[1/6] Compiling Python files...", flush=True)
    for path in py_files:
        py_compile.compile(str(path), doraise=True)
    print(f"  OK: compiled {len(py_files)} file(s)", flush=True)


def _is_main_guard(node: ast.If) -> bool:
    test = node.test
    if not isinstance(test, ast.Compare):
        return False
    if len(test.ops) != 1 or len(test.comparators) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False

    left, right = test.left, test.comparators[0]
    if not isinstance(left, ast.Name) or left.id != "__name__":
        return False
    if isinstance(right, ast.Constant):
        return right.value == "__main__"
    return False


def check_duplicate_entrypoints(py_files: List[Path]) -> None:
    print("[2/6] Checking for duplicate __main__ entrypoints...", flush=True)
    offenders: List[Tuple[Path, int]] = []
    for path in py_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        count = sum(1 for node in ast.walk(tree) if isinstance(node, ast.If) and _is_main_guard(node))
        if count > 1:
            offenders.append((path, count))
    if offenders:
        details = ", ".join(f"{path.relative_to(ROOT)} ({count})" for path, count in offenders)
        raise SystemExit(f"FAIL: Duplicate entrypoints found: {details}")
    print("  OK: no duplicate entrypoints found", flush=True)


def check_sqlite_context_manager_antipattern(py_files: List[Path]) -> None:
    """Check for 'with sqlite3.connect()' which leaks connections.

    The sqlite3 context manager manages TRANSACTIONS, not connections.
    Using 'with sqlite3.connect()' leaves connections open.
    """
    print("[3/6] Checking for sqlite3 connection leaks...", flush=True)
    offenders: List[Tuple[Path, int]] = []
    for path in py_files:
        # Skip test files and this script itself
        if "test_" in path.name or path.name == "trust_check.py":
            continue

        text = path.read_text(encoding="utf-8")
        # Look for the anti-pattern: with sqlite3.connect(...)
        if "with sqlite3.connect(" in text:
            # Find line numbers, excluding comments
            lines = text.split("\n")
            line_nums = []
            for i, line in enumerate(lines):
                if "with sqlite3.connect(" in line:
                    # Skip if it's in a comment
                    code = line.split("#")[0]
                    if "with sqlite3.connect(" in code:
                        line_nums.append(i + 1)
            if line_nums:
                offenders.append((path, line_nums))
    if offenders:
        details = "; ".join(
            f"{path.relative_to(ROOT)}: line(s) {nums}" for path, nums in offenders
        )
        raise SystemExit(
            f"FAIL: sqlite3 connection leak detected!\n"
            f"  'with sqlite3.connect()' does NOT close connections.\n"
            f"  Use 'conn = sqlite3.connect()' + 'finally: conn.close()' instead.\n"
            f"  Found in: {details}"
        )
    print("  OK: no sqlite3 connection leaks found", flush=True)


def check_config_invariants() -> None:
    print("[4/6] Validating config invariants...", flush=True)

    # Keep runtime state/log writes in /tmp during validation.
    os.environ.setdefault("HOME", "/tmp/penny_trust_check_home")
    os.environ.setdefault("OPENROUTER_API_KEY", "trust-check-placeholder")
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "trust-check-placeholder")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "0")
    os.environ.setdefault(
        "GOOGLE_CREDENTIALS_FILE", "/tmp/penny_trust_check_home/.penny/google_credentials.json"
    )
    os.environ.setdefault("GOOGLE_TOKEN_FILE", "/tmp/penny_trust_check_home/.penny/google_token.json")

    sys.path.insert(0, str(ROOT))
    import config  # pylint: disable=import-outside-toplevel

    config._config = None
    cfg = config.get_config()

    assert cfg.google_tasks.list_name == "My Tasks", (
        "google_tasks.list_name must remain 'My Tasks' for Google Home integration"
    )
    assert cfg.apple_reminders.default_list in cfg.apple_reminders.lists, (
        "apple_reminders.default_list must be present in apple_reminders.lists"
    )
    assert cfg.google_tasks.poll_interval_seconds > 0
    assert cfg.voice_memos.poll_interval_seconds > 0
    assert cfg.voice_memos.max_file_size_mb > 0
    assert cfg.voice_memos.startup_process_limit > 0
    assert cfg.webhook.port > 0
    print("  OK: config.toml invariants validated", flush=True)


def check_launchd_templates() -> None:
    print("[5/6] Validating launchd templates...", flush=True)
    template_paths = sorted((ROOT / "launchd").glob("*.plist.template"))
    if not template_paths:
        raise SystemExit("FAIL: No launchd templates found in launchd/")

    for template in template_paths:
        text = template.read_text(encoding="utf-8")
        missing = [key for key in REQUIRED_LAUNCHD_KEYS if key not in text]
        if missing:
            raise SystemExit(f"FAIL: {template.relative_to(ROOT)} missing keys: {', '.join(missing)}")
    print(f"  OK: validated {len(template_paths)} launchd template(s)", flush=True)


def run_unit_tests() -> None:
    print("[6/6] Running unit tests...", flush=True)
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
    subprocess.run(cmd, cwd=ROOT, check=True)
    print("  OK: unit tests passed", flush=True)


def main() -> None:
    py_files = sorted(iter_python_files(ROOT))
    if not py_files:
        raise SystemExit("FAIL: No Python files found")

    compile_all(py_files)
    check_duplicate_entrypoints(py_files)
    check_sqlite_context_manager_antipattern(py_files)
    check_config_invariants()
    check_launchd_templates()
    run_unit_tests()
    print("\nPASS: Penny trust check passed", flush=True)


if __name__ == "__main__":
    main()
