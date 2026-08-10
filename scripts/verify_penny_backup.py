#!/usr/bin/env python3
"""Verify one Penny backup set in an explicitly supplied scratch directory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from backup import BackupError, VerificationReceipt, verify_backup_set  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("set_path", type=Path, help="absolute backup-set directory")
    parser.add_argument("scratch_root", type=Path, help="absolute scratch directory")
    return parser


def _summary(receipt: VerificationReceipt) -> dict[str, object]:
    # Keep output useful for health checks without leaking paths, transcript
    # bodies, catalog contents, or provider errors.
    return {
        "status": receipt.status,
        "valid": receipt.valid,
        "backup_set_id": receipt.backup_set_id,
        "row_count": receipt.row_count,
        "max_transcript_id": receipt.max_transcript_id,
        "error_count": len(receipt.errors),
        "warning_count": len(receipt.warnings),
    }


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        # argparse uses 2 for usage errors; preserve that contract when this
        # function is called directly in a test or operator wrapper.
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        receipt = verify_backup_set(args.set_path, args.scratch_root)
    except (BackupError, OSError, ValueError):
        print(
            json.dumps(
                {
                    "status": "safety_error",
                    "valid": False,
                    "error_count": 1,
                    "warning_count": 0,
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(_summary(receipt), sort_keys=True))
    return 0 if receipt.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

