#!/usr/bin/env python3
"""Print the read-only Penny Doctor report.

Exit status is stable for automation: 0 ready, 1 degraded, 2 unready.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from doctor import render_human, render_json, run_doctor  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        report = run_doctor()
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        # A Doctor failure is itself an unready result; never print exception
        # text, paths, provider output, or secrets.
        print('{"overall":"unready","components":{},"source_revision":"unknown"}')
        return 2
    print(render_json(report) if args.json else render_human(report))
    return {"ready": 0, "degraded": 1, "unready": 2}.get(report.overall, 2)


if __name__ == "__main__":
    raise SystemExit(main())
