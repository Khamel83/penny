#!/usr/bin/env python3
"""Re-evaluate one retained Penny transcript under the current quality policy.

The command is metadata-only at its boundary: it never prints transcript or
audio content.  A successful promotion leaves the normal watcher and outbox
workers to perform downstream delivery.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from transcript_log import (  # noqa: E402
    QualityReviewStatus,
    re_evaluate_quality_review,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript-id", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = re_evaluate_quality_review(args.transcript_id)
    print(
        json.dumps(
            {
                "transcript_id": result.transcript_id,
                "status": result.status,
                "reason": result.reason,
                "slack_queued": result.slack_queued,
                "maya_queued": result.maya_queued,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return int(
        result.status
        not in {
            QualityReviewStatus.PROMOTED.value,
            QualityReviewStatus.ALREADY_PROMOTED.value,
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
