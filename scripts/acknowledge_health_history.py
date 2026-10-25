#!/usr/bin/env python3
"""Preview or explicitly acknowledge existing terminal health exceptions."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from health_history import acknowledge, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Freeze this reviewed set once; retain every ledger row')
    args = parser.parse_args()
    if args.apply:
        acknowledge()
    print(json.dumps({'applied': args.apply, 'exception_counts': {k: len(v) for k, v in snapshot().items()}}, sort_keys=True))


if __name__ == '__main__':
    main()
