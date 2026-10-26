# iCloud transcript view deployment — October 26, 2026 UTC

## Source and controlled deployment

[PR146](https://github.com/Khamel83/penny/pull/146) merged as
`b4181aa8268d39d163ef877591927fef79a00e6b`, after trusted PASS on exact
head `6ab0c2256da659cef038515a9f6f1f44929fc32c` and both hosted checks.
The partner explicitly authorized deploying that exact merge through the
existing documented procedure. The clean runtime main was fast-forwarded
from `0fd1273b`; no new runtime checkout was created.

From `/Volumes/2TB_SSD/penny-runtime`:

```sh
venv/bin/python scripts/deploy_penny.py --apply
venv/bin/python scripts/deploy_penny.py
```

The first attempt stopped at `checkout_dirty` before activation because the
associate's progress notes were accidentally written into runtime records.
Only those own additions were moved into the task worktree, restoring clean
main. The second attempt completed the normal trust-check, verified-backup and
activation path. No deployment checks were bypassed.

Private deployment receipt:
`~/.penny/deployments/20261026T042312Z/receipt.json`, SHA-256
`60ee406f288b8d7d796e8a59b71e84a829e83f85cd29098478c30c613add5582`.
It reports `activated` at the exact merged revision. Follow-up deployment check
reports `current`, with all five labels loaded at that revision. The four
continuous services are running; scheduled export is loaded and idle.
At 04:24:47 UTC the watcher retained PID 87077, `/ready` returned HTTP 200,
`overall=ready`, source `b4181aa`, and every component was ready. Shared ASR
health returned HTTP 200, idle, without a resident worker. Runtime main remains
clean. No synthetic audio or recording was created.

## Snapshot and downstream boundary

Before activation, metadata inventory found 346 Markdown files: 345 transcripts
with 345 unique canonical IDs plus INDEX.md; zero duplicates and zero
non-Markdown files. Relative-path inventory SHA-256:
`7e2176db9cbfcc5968bf00567fbd8b036e6d566c42dd29f5cbd2bff0e4f30bf9`.
After activation the same baseline paths remained, still 346 files/345 unique
IDs, zero duplicates and zero non-Markdown files. All 346 initially had the
File Provider dataless flag. No retired cloud archive was accessed or restored.

INDEX.md subsequently read successfully, SHA-256:
`26c2283f9a4e7842b726314c6318bac6d96cdf2f44a937fd0bd4bb2018ab226d`.
A full private byte/hash comparison against accepted ledger text did not
finish within its 25-second deadline. The watcher logged two bounded view
failures by 04:24:47 UTC while remaining healthy. **Snapshot reconciliation
and transcript byte hashes are not verified.** Counts, an index hash, and
process health do not prove successful projection delivery.

The ledger has 544 rows, maximum ID 796, and 214 passed rows. The original
snapshot has 202 passed IDs and 143 retained nonpassed IDs. No quality state
was changed. Private metadata receipts and the natural-arrival baseline are
under `~/.penny/deployments/icloud136-20261026/`; no names or transcript text
are published here.

The observed blocker is File Provider content materialization/read latency.
Do not run an unbounded scan or restart Apple providers as a shortcut. Once
ordinary access to the existing Markdown view is responsive, allow the existing
watcher to reconcile it and repeat a bounded private byte/hash comparison.
The successful result must preserve all 345 baseline IDs and paths, have no
duplicate IDs or non-Markdown files, match accepted ledger Markdown bytes,
and include every exported ID exactly once in the updated index. The total
may grow as already accepted rows missing from the snapshot are exported.

The merged revision still probes `DEFAULT_ROOT.is_dir()` in the parent watcher
before launching its bounded child. A review on the earlier head flagged that
metadata call as outside the deadline; the later exact-head PASS did not change
the code. This deployment preserves the explicitly requested exact revision.
The observed timeouts were bounded child failures, not proof that every possible
File Provider stall is isolated. Any source correction requires separate review.

## Natural acceptance and next check

[#136](https://github.com/Khamel83/penny/issues/136) remains open. First complete
snapshot reconciliation; then observe an ordinary accepted ledger row beyond
the private baseline (current maximum ID 796). Do not fabricate input, replay
historical delivery or manually run projection writes to manufacture acceptance.

Privately compare that row's generated Markdown bytes/hash with the canonical
passed text and provenance, verify its canonical ID appears exactly once in
the automatically updated index, and confirm watcher revision/health independently.
Record counts, hashes, timestamps and the source revision only. A new file alone
is insufficient; verify the index update too. Local readback does not establish
cross-device synchronization. No natural-arrival acceptance is claimed here.

Task records remain in the reused `.worktrees/icloud-transcript-view-136`,
branch `docs/icloud-view-deployment-20261026`. Its existing untracked venv
symlink is preserved. Retain the worktree for remaining acceptance; no sibling
or separate acceptance worktree was created.
