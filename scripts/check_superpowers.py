#!/usr/bin/env python3
"""Verify Penny's pinned, vendored Superpowers skill set."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

EXPECTED_REPOSITORY = "https://github.com/obra/superpowers"
EXPECTED_REVISION = "b36e0829c6d0140e93cfef2ca599b1b07d4a7797"
EXPECTED_LICENSE = "MIT"
EXPECTED_SKILLS = {
    "brainstorming",
    "writing-plans",
    "test-driven-development",
    "systematic-debugging",
    "subagent-driven-development",
    "requesting-code-review",
    "verification-before-completion",
}
MANIFEST_RELATIVE_PATH = Path("docs/superpowers/superpowers-manifest.json")
VENDOR_RELATIVE_PATH = Path(".agents/skills/superpowers")
SOURCE_SKILLS_PREFIX = "skills/"


def _is_selected_skill_path(source_path: str) -> bool:
    return any(
        source_path.startswith(f"skills/{skill}/") for skill in EXPECTED_SKILLS
    )


class ManifestError(Exception):
    """A manifest or vendored artifact violates the pinned contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_file(path_value: str, repo_root: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute() or ".." in path.parts:
        raise ManifestError(f"unsafe vendored path: {path_value}")
    resolved = (repo_root / path).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ManifestError(f"vendored path escapes repository: {path_value}") from exc
    return repo_root / path


def _check_entry(
    entry: dict[str, str],
    repo_root: Path,
    expected_prefix: str,
) -> Path:
    if not isinstance(entry, dict):
        raise ManifestError("each artifact entry must be an object")
    source_path = entry.get("source_path")
    vendored_path = entry.get("vendored_path")
    recorded_hash = entry.get("sha256")
    if not isinstance(source_path, str) or not isinstance(vendored_path, str):
        raise ManifestError("each artifact needs source_path and vendored_path")
    if not isinstance(recorded_hash, str):
        raise ManifestError("each artifact needs sha256")
    if expected_prefix == "LICENSE":
        valid_source_path = source_path == "LICENSE"
    else:
        valid_source_path = (
            source_path.startswith(expected_prefix)
            and _is_selected_skill_path(source_path)
        )
    if not valid_source_path:
        raise ManifestError(f"source path outside selected skills: {source_path}")
    if len(recorded_hash) != 64 or any(
        c not in "0123456789abcdef" for c in recorded_hash
    ):
        raise ManifestError(f"invalid sha256 for {vendored_path}")

    path = _relative_file(vendored_path, repo_root)
    if path.is_symlink() or not path.is_file():
        raise ManifestError(f"missing regular vendored artifact: {vendored_path}")
    actual_hash = _sha256(path)
    if actual_hash != recorded_hash:
        raise ManifestError(
            f"revision drift in {vendored_path}: expected {recorded_hash}, got {actual_hash}"
        )
    return path


def verify(repo_root: Path) -> int:
    manifest_path = repo_root / MANIFEST_RELATIVE_PATH
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source = manifest["source"]
        integration = manifest["penny_integration"]
        selected = manifest["selected_skills"]
        supporting = manifest["supporting_files"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ManifestError(f"cannot read manifest: {exc}") from exc

    if not isinstance(source, dict) or not isinstance(integration, dict):
        raise ManifestError("source and Penny integration metadata must be objects")
    if not isinstance(selected, list) or not isinstance(supporting, list):
        raise ManifestError("selected_skills and supporting_files must be arrays")
    if source["repository"] != EXPECTED_REPOSITORY:
        raise ManifestError("source repository drifted")
    if source["revision"] != EXPECTED_REVISION or len(source["revision"]) != 40:
        raise ManifestError("source revision drifted from the approved commit")
    if source["license"] != EXPECTED_LICENSE or source["license_file"] != "LICENSE":
        raise ManifestError("source license metadata drifted")
    if integration["method"] != "vendored_selected_skill_files":
        raise ManifestError("unsupported Penny integration method")
    if integration["runtime_dependency_added"] is not False:
        raise ManifestError("Penny integration must not add a runtime dependency")
    if integration["moving_default_branch_tracked"] is not False:
        raise ManifestError("Penny integration must not track a moving branch")

    names = [
        entry.get("name") if isinstance(entry, dict) else None for entry in selected
    ]
    if set(names) != EXPECTED_SKILLS or len(names) != len(EXPECTED_SKILLS):
        raise ManifestError("selected skill set is outside the approved scope")

    entries = []
    for entry in selected:
        name = entry.get("name")
        if entry.get("source_path") != f"skills/{name}/SKILL.md":
            raise ManifestError(f"unexpected source path for selected skill: {name}")
        entries.append(_check_entry(entry, repo_root, f"skills/{name}/"))
    for entry in supporting:
        if not isinstance(entry, dict):
            raise ManifestError("each artifact entry must be an object")
        source_path = entry.get("source_path")
        prefix = "LICENSE" if source_path == "LICENSE" else SOURCE_SKILLS_PREFIX
        entries.append(_check_entry(entry, repo_root, prefix))
    if len(entries) != len(set(entries)):
        raise ManifestError("manifest contains duplicate vendored artifacts")

    vendor_root = repo_root / VENDOR_RELATIVE_PATH

    actual_files = {
        path.relative_to(repo_root)
        for path in vendor_root.rglob("*")
        if path.is_file()
    }
    expected_files = set(path.relative_to(repo_root) for path in entries)
    if actual_files != expected_files:
        extra = sorted(str(path) for path in actual_files - expected_files)
        missing = sorted(str(path) for path in expected_files - actual_files)
        raise ManifestError(f"vendored file set drifted; extra={extra}, missing={missing}")
    return len(entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Penny repository root (default: inferred from this script)",
    )
    args = parser.parse_args()
    try:
        artifact_count = verify(args.root.resolve())
    except ManifestError as exc:
        print(f"Superpowers manifest FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        "Superpowers manifest OK: "
        f"revision={EXPECTED_REVISION} selected_skills={len(EXPECTED_SKILLS)} "
        f"vendored_files={artifact_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
