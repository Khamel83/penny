#!/usr/bin/env python3
"""Run Penny's offline, read-only repository trust checks.

This command checks the source tree and its runtime contracts.  It never
contacts a provider, changes launchd state, changes the ledger, or repairs a
runtime service.  A template is checked as a contract; it is not treated as
proof about an installed plist.
"""
from __future__ import annotations

import ast
import os
import plistlib
import py_compile
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

ROOT = Path(__file__).resolve().parent.parent

if sys.version_info < (3, 11):
    raise SystemExit(
        "FAIL: Penny requires Python 3.11+. Run: python3.12 scripts/trust_check.py"
    )

EXCLUDE_DIR_NAMES = {".git", "__pycache__", "venv", ".venv", "venv.brew-python.bak"}
# The check is routinely run from an isolated worktree.  In the primary
# checkout, avoid recursively inspecting sibling worktrees; inside one, the
# worktree itself is the repository root and must remain visible.
if ".worktrees" not in ROOT.parts:
    EXCLUDE_DIR_NAMES.add(".worktrees")
MODEL_REVISION = "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"
MODEL_PATH = f"/Users/macmini/.penny/models/whisper-large-v3-turbo/{MODEL_REVISION}"
SOURCE_PLACEHOLDER = "YOUR_PENNY_SOURCE_REVISION_HERE"

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

# Health automation may transport a Doctor report, but it may not mutate or
# inspect runtime state through ad-hoc commands.
FORBIDDEN_WORKFLOW_TOKENS = (
    "launchctl list",
    "launchctl kickstart",
    "launchctl bootstrap",
    "launchctl bootout",
    "pgrep",
    "tail ",
    "open -a",
    "rm -",
    "reset",
    "delete",
    "replay",
    "repair",
)


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
            continue
        yield path


def compile_all(py_files: List[Path]) -> None:
    print("[1/8] Compiling Python files...", flush=True)
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
    return isinstance(right, ast.Constant) and right.value == "__main__"


def check_duplicate_entrypoints(py_files: List[Path]) -> None:
    print("[2/8] Checking for duplicate __main__ entrypoints...", flush=True)
    offenders: List[Tuple[Path, int]] = []
    for path in py_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.If) and _is_main_guard(node)
        )
        if count > 1:
            offenders.append((path, count))
    if offenders:
        details = ", ".join(
            f"{path.relative_to(ROOT)} ({count})" for path, count in offenders
        )
        raise SystemExit(f"FAIL: duplicate entrypoints found: {details}")
    print("  OK: no duplicate entrypoints found", flush=True)


def check_sqlite_context_manager_antipattern(py_files: List[Path]) -> None:
    """Reject the sqlite context-manager form that leaves connections open."""
    print("[3/8] Checking for sqlite3 connection leaks...", flush=True)
    offenders: List[Tuple[Path, list[int]]] = []
    for path in py_files:
        if "test_" in path.name or path.name == "trust_check.py":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        line_nums = [
            index
            for index, line in enumerate(lines, 1)
            if "with sqlite3.connect(" in line and not line.lstrip().startswith("#")
        ]
        if line_nums:
            offenders.append((path, line_nums))
    if offenders:
        details = "; ".join(
            f"{path.relative_to(ROOT)}: line(s) {nums}" for path, nums in offenders
        )
        raise SystemExit(
            "FAIL: sqlite3 connection leak detected; use an explicit close in a finally block.\n"
            f"  Found in: {details}"
        )
    print("  OK: no sqlite3 connection leaks found", flush=True)


def check_config_invariants() -> None:
    print("[4/8] Validating config invariants...", flush=True)
    # Use harmless throwaway values and force local-only mode for this check.
    os.environ["OPENROUTER_API_KEY"] = "trust-check-placeholder"
    os.environ["PENNY_INGEST_TOKEN"] = "ingest-test-token"
    os.environ.pop("PENNY_WEBHOOK_SECRET", None)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["PENNY_SOURCE_REVISION"] = "a" * 40
    os.environ["GOOGLE_CREDENTIALS_FILE"] = (
        "/tmp/penny_trust_check_home/.penny/google_credentials.json"
    )
    os.environ["GOOGLE_TOKEN_FILE"] = "/tmp/penny_trust_check_home/.penny/google_token.json"

    sys.path.insert(0, str(ROOT))
    import config  # pylint: disable=import-outside-toplevel

    config._config = None
    cfg = config.get_config()
    assert cfg.google_tasks.list_name == "My Tasks"
    assert cfg.apple_reminders.default_list in cfg.apple_reminders.lists
    assert cfg.google_tasks.poll_interval_seconds > 0
    assert cfg.voice_memos.poll_interval_seconds > 0
    assert cfg.voice_memos.max_file_size_mb > 0
    assert cfg.voice_memos.startup_process_limit > 0
    assert cfg.voice_memos.whisper_model_revision == MODEL_REVISION
    assert cfg.webhook.port > 0
    assert cfg.webhook.host == "127.0.0.1"
    assert cfg.webhook.ingest_token == "ingest-test-token"
    print("  OK: config.toml invariants validated", flush=True)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SystemExit(f"FAIL: cannot read required artifact {path.relative_to(ROOT)}") from exc


def _require_environment(environment: dict[str, object], key: str, expected: object, template: Path) -> None:
    if environment.get(key) != expected:
        raise SystemExit(
            f"FAIL: {template.relative_to(ROOT)} must set {key} to {expected!r}"
        )


def check_phase_a_contracts() -> None:
    """Validate tracked secrets, runtime templates, workflow, and safe docs."""
    print("[5/8] Validating Phase A contract artifacts...", flush=True)

    secrets = _read_text(ROOT / "secrets.env.example")
    if re.search(r"(?mi)^\s*TELEGRAM_(?:BOT_TOKEN|CHAT_ID)\s*=", secrets):
        raise SystemExit("FAIL: Telegram credentials remain in secrets.env.example")
    required_secret_keys = (
        "PENNY_INGEST_TOKEN",
        "PENNY_WEBHOOK_SECRET",
        "PENNY_HERMES_WEBHOOK_SECRET",
        "HERMES_WEBHOOK_URL",
        "PENNY_SOURCE_REVISION",
        "PENNY_ARCHIVE_OBJECT_ROOT",
        "PENNY_ARCHIVE_MIRROR_ROOT",
        "PENNY_BACKUP_ROOT",
        "PENNY_BACKUP_REMOTE",
        "PENNY_BACKUP_VERIFICATION_RECEIPT",
        "PENNY_WHISPER_MODEL_PATH",
    )
    for key in required_secret_keys:
        if not re.search(rf"(?m)^\s*{re.escape(key)}\s*=", secrets):
            raise SystemExit(f"FAIL: secrets.env.example is missing {key}")
    if "HF_HUB_OFFLINE=1" not in secrets or MODEL_REVISION not in secrets:
        raise SystemExit("FAIL: secrets.env.example is missing the pinned offline model contract")
    if "transitional" not in secrets.lower() or "OPENROUTER_API_KEY" not in secrets:
        raise SystemExit("FAIL: direct OpenRouter use is not classified as transitional")
    if "PENNY_WEBHOOK_HOST=127.0.0.1" not in secrets:
        raise SystemExit("FAIL: secrets.env.example must default webhook to loopback")

    template_paths = sorted((ROOT / "launchd").glob("*.plist.template"))
    if not template_paths:
        raise SystemExit("FAIL: no launchd templates found")
    for template in template_paths:
        text = _read_text(template)
        if "TELEGRAM" in text:
            raise SystemExit(f"FAIL: Telegram configuration remains in {template.relative_to(ROOT)}")
        missing = [key for key in REQUIRED_LAUNCHD_KEYS if key not in text]
        if missing:
            raise SystemExit(
                f"FAIL: {template.relative_to(ROOT)} missing keys: {', '.join(missing)}"
            )
        try:
            environment = plistlib.loads(template.read_bytes())["EnvironmentVariables"]
        except (OSError, plistlib.InvalidFileException, KeyError, TypeError) as exc:
            raise SystemExit(f"FAIL: invalid launchd template {template.relative_to(ROOT)}") from exc
        _require_environment(environment, "PENNY_SOURCE_REVISION", SOURCE_PLACEHOLDER, template)

    for template_name in (
        "com.penny.watcher.plist.template",
        "com.penny.webhook.plist.template",
        "com.penny.tasks.plist.template",
    ):
        template = ROOT / "launchd" / template_name
        environment = plistlib.loads(template.read_bytes())["EnvironmentVariables"]
        _require_environment(environment, "MAYA_TRANSCRIPT_URL", "YOUR_MAYA_TRANSCRIPT_URL_HERE", template)
        _require_environment(environment, "MAYA_INGEST_TOKEN", "YOUR_MAYA_INGEST_TOKEN_HERE", template)

    watcher = plistlib.loads(
        (ROOT / "launchd" / "com.penny.watcher.plist.template").read_bytes()
    )["EnvironmentVariables"]
    _require_environment(watcher, "HF_HUB_OFFLINE", "1", ROOT / "launchd" / "com.penny.watcher.plist.template")
    _require_environment(watcher, "PENNY_WHISPER_MODEL_PATH", MODEL_PATH, ROOT / "launchd" / "com.penny.watcher.plist.template")
    _require_environment(watcher, "PENNY_SLACK_CHANNEL_ID", "C0BKS0QT7FU", ROOT / "launchd" / "com.penny.watcher.plist.template")
    _require_environment(watcher, "PENNY_MAYA_LEDGER_CHANNEL_ID", "YOUR_MAYA_LEDGER_CHANNEL_ID_HERE", ROOT / "launchd" / "com.penny.watcher.plist.template")
    _require_environment(watcher, "MAYA_DELIVERY_TIMEOUT_SECONDS", "10", ROOT / "launchd" / "com.penny.watcher.plist.template")
    if "PENNY_WEBHOOK_SECRET" in watcher:
        raise SystemExit(
            "FAIL: watcher template must not reuse the webhook callback credential"
        )

    webhook_path = ROOT / "launchd" / "com.penny.webhook.plist.template"
    webhook = plistlib.loads(webhook_path.read_bytes())["EnvironmentVariables"]
    _require_environment(webhook, "HF_HUB_OFFLINE", "1", webhook_path)
    _require_environment(webhook, "PENNY_WHISPER_MODEL_PATH", MODEL_PATH, webhook_path)
    _require_environment(webhook, "PENNY_WEBHOOK_HOST", "127.0.0.1", webhook_path)
    _require_environment(webhook, "PENNY_WEBHOOK_ALLOW_NONLOOPBACK", "0", webhook_path)
    _require_environment(webhook, "PENNY_INGEST_TOKEN", "YOUR_PENNY_INGEST_TOKEN_HERE", webhook_path)
    _require_environment(webhook, "PENNY_WEBHOOK_SECRET", "YOUR_PENNY_WEBHOOK_SECRET_HERE", webhook_path)
    _require_environment(webhook, "PENNY_HERMES_WEBHOOK_SECRET", "YOUR_PENNY_HERMES_WEBHOOK_SECRET_HERE", webhook_path)

    for template_name in (
        "com.penny.watcher.plist.template",
        "com.penny.tasks.plist.template",
    ):
        template = ROOT / "launchd" / template_name
        environment = plistlib.loads(template.read_bytes())["EnvironmentVariables"]
        _require_environment(environment, "PENNY_HERMES_WEBHOOK_SECRET", "YOUR_PENNY_HERMES_WEBHOOK_SECRET_HERE", template)
        _require_environment(environment, "HERMES_WEBHOOK_URL", "YOUR_HERMES_WEBHOOK_URL_HERE", template)

    export_path = ROOT / "launchd" / "com.penny.export.plist.template"
    export = plistlib.loads(export_path.read_bytes())["EnvironmentVariables"]
    for key in (
        "PENNY_TRANSCRIPT_DB",
        "PENNY_ARCHIVE_OBJECT_ROOT",
        "PENNY_BACKUP_ROOT",
        "PENNY_BACKUP_REMOTE",
        "PENNY_BACKUP_VERIFICATION_RECEIPT",
        "PENNY_BACKUP_SCRATCH_ROOT",
    ):
        if not str(export.get(key, "")).strip():
            raise SystemExit(f"FAIL: export template is missing {key}")

    workflow = _read_text(ROOT / ".github" / "workflows" / "health-check.yml")
    if "scripts/penny_doctor.py --json" not in workflow:
        raise SystemExit("FAIL: health-check workflow must run the read-only Penny Doctor")
    workflow_lower = workflow.lower()
    for token in FORBIDDEN_WORKFLOW_TOKENS:
        if token in workflow_lower:
            raise SystemExit(f"FAIL: health-check workflow contains forbidden token {token!r}")

    docs = {
        "README.md": _read_text(ROOT / "README.md"),
        "HANDOFF.md": _read_text(ROOT / "HANDOFF.md"),
        "LLM-OVERVIEW.md": _read_text(ROOT / "LLM-OVERVIEW.md"),
        "docs/reliability.md": _read_text(ROOT / "docs" / "reliability.md"),
        "docs/macmini-deployment.md": _read_text(ROOT / "docs" / "macmini-deployment.md"),
    }
    required_doc_strings = {
        "README.md": ("Penny Archive", "template"),
        "HANDOFF.md": ("local routing", "independent Slack", "independent Maya v2"),
        "LLM-OVERVIEW.md": ("transitional", "HF_HUB_OFFLINE=1"),
        "docs/reliability.md": ("Penny Archive", "metadata-only", "watcher.system.log"),
        "docs/macmini-deployment.md": ("runtime artifacts", "watcher.system.log"),
    }
    for name, needles in required_doc_strings.items():
        for needle in needles:
            if needle not in docs[name]:
                raise SystemExit(f"FAIL: {name} is missing required contract phrase {needle!r}")
    print(f"  OK: validated {len(template_paths)} launchd templates and Phase A docs", flush=True)


def _hermetic_test_environment() -> dict[str, str]:
    """Build a minimal, secret-free environment for repository tests.

    Only process plumbing and explicit fixture values are carried into the
    child. Provider credentials, URLs, and legacy notification settings are
    intentionally absent. Invalid loopback proxies make an accidental network
    call fail quickly rather than reaching a real provider.
    """
    env: dict[str, str] = {}
    for key in ("PATH", "LANG", "LC_ALL", "TZ"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    trust_home = "/tmp/penny-trust-check-home"
    env.update(
        {
            "HOME": trust_home,
            "TMPDIR": "/tmp",
            "PYTHONNOUSERSITE": "1",
            "PYTHONUNBUFFERED": "1",
            "HF_HUB_OFFLINE": "1",
            "PENNY_INGEST_TOKEN": "ingest-test-token",
            "PENNY_WEBHOOK_HOST": "127.0.0.1",
            "PENNY_WEBHOOK_ALLOW_NONLOOPBACK": "0",
            "PENNY_SOURCE_REVISION": "a" * 40,
            "GOOGLE_CREDENTIALS_FILE": f"{trust_home}/google_credentials.json",
            "GOOGLE_TOKEN_FILE": f"{trust_home}/google_token.json",
            "PENNY_TRANSCRIPT_DB": f"{trust_home}/transcripts.db",
            "PENNY_ARCHIVE_OBJECT_ROOT": f"{trust_home}/archive/objects",
            "PENNY_ARCHIVE_MIRROR_ROOT": f"{trust_home}/Penny Archive",
            "PENNY_BACKUP_ROOT": f"{trust_home}/backup",
            "PENNY_BACKUP_VERIFICATION_RECEIPT": f"{trust_home}/backup/last_verification.json",
            "PENNY_BACKUP_SCRATCH_ROOT": f"{trust_home}/backup-scratch",
            "PENNY_HEALTH_FILE": f"{trust_home}/health.txt",
            "PENNY_TASKS_HEALTH_FILE": f"{trust_home}/health_tasks.txt",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "http_proxy": "http://127.0.0.1:9",
            "https_proxy": "http://127.0.0.1:9",
            "all_proxy": "http://127.0.0.1:9",
            "NO_PROXY": "",
            "no_proxy": "",
        }
    )
    return env


def run_unit_tests() -> None:
    print("[6/8] Running hermetic unit tests...", flush=True)
    venv_python = ROOT / "venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else sys.executable
    env = _hermetic_test_environment()
    cmd = [python, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)
    print("  OK: unit tests passed", flush=True)


def main() -> None:
    py_files = sorted(iter_python_files(ROOT))
    if not py_files:
        raise SystemExit("FAIL: no Python files found")
    compile_all(py_files)
    check_duplicate_entrypoints(py_files)
    check_sqlite_context_manager_antipattern(py_files)
    check_config_invariants()
    check_phase_a_contracts()
    run_unit_tests()
    print("\nPASS: Penny trust check passed", flush=True)


if __name__ == "__main__":
    main()
