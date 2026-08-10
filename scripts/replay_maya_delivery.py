#!/usr/bin/env python3
"""Explicitly replay one terminal Maya delivery.

This command only resets the selected canonical row's Maya scheduling state. It
does not send a request, reset a batch, or change any other outbox/provider
state. The normal watcher will pick up the reopened pending row.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from transcript_log import replay_maya_delivery  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reopen exactly one failed or dead-lettered Maya delivery"
    )
    parser.add_argument("--transcript-id", type=int, required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    return 0 if replay_maya_delivery(args.transcript_id, now=now) else 1


if __name__ == "__main__":
    raise SystemExit(main())
