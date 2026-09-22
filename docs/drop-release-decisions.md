# Drop release decisions — 2026-09-22

These decisions preserve the approved narrow boundary. Source tests, installation,
intake, archive, Slack and Maya are separate claims. See [operations](drop-delivery.md)
for live evidence and remaining exceptions.

1. Keep canonical SQLite initialization in `transcript_log.py`; a pure payload
   helper may be separated later. Wrong-call cost: a local refactor.
2. Keep historical recovery local-only; use explicit export for external delivery.
   Wrong-call cost: recovered text waits for an export pass.
3. Implement persisted ownership with insertion, before the later import task.
   Wrong-call cost: later ownership changes need regression coverage.
4. Treat interrupted Slack byte uploads as uncertain without positive share proof.
   Wrong-call cost: rare attempts need operator reconciliation.
5. Keep runtime/privacy/provider/rendering/receipt gates with the deploying agent,
   not inferred from source review. Wrong-call cost: deployment remains incomplete
   until every claimed boundary is independently proven.
6. Hold cutover when initial canaries exposed Maya notices, then resume only after
   the user's explicit Maya extension approval. Wrong-call cost: delayed import.
7. Use strict Penny validation in Maya's existing ingest path, with no new schema,
   endpoint or reader. Wrong-call cost: malformed envelopes are visibly refused.
8. Follow Maya's canonical-checkout rule over the usual worktree preference;
   preserve unrelated untracked documents. Wrong-call cost: shared-checkout work
   needs exact-path staging.
9. Freeze the expired Gmail test fixture clock, not its production age guard.
   Wrong-call cost: the test would stop representing its allowed seven-day request.
10. Do not reactivate retired Hermes projections to satisfy unrelated legacy tests.
    Wrong-call cost: broader legacy execution/readiness failures remain unresolved.
11. Hold Drop's Maya cursor on an invalid Penny receipt or permanent refusal.
    Wrong-call cost: one bad Penny item delays later Maya items; Slack is independent.
12. After an interrupted full archive copy, build from the Dockerfile's exact
    committed runtime inputs only. Wrong-call cost: a missing input fails the build
    before deployment. The failed first build left the running service unchanged.
13. Report the broad-search timeout and missing full-text index separately; do
    not add a schema/index change to the narrow ingestion release. Direct byte
    retrieval works. Wrong-call cost: broad Maya search stays slow until that
    follow-up is approved and verified. That follow-up is now complete: see
    [operations](drop-delivery.md) for the deployed index and durable-download
    repair, including 320 authenticated search and hash-matched download checks.
14. Integrate the concurrent approved SSD-backup documentation and preserve its
    installed mount guard/environment in pre-deployment backup and agent reload.
    Wrong-call cost: a deployment would be blocked or recreate internal staging;
    two test-first regressions guard this compatibility path.

## Deferred review minors

Additional negative Maya-receipt variants (415, namespace/version/classification,
empty ID, malformed JSON and strict-type permutations) and a Penny-specific
persisted-cursor assertion are not each directly tested. Existing common cursor
tests and independent code review cover that path. The accepted guard cases and
full Drop suite passed; these extra permutations remain follow-up test coverage.
The final SSD compatibility review also deferred a wrapped-export reload
round-trip, conflicting shell-versus-installed environment values, and wrong
wrapper-interpreter/other-service rejection permutations. Focused compatibility
tests and full Penny suite pass; installed guard/placement verification is a
separate live gate.

## Review and preservation

Independent reviews found and resolved ambiguous storage handling, uncertain
queue starvation, Slack normalized-text reconciliation, definite refusal retry,
and Maya source-namespace normalization. Each material fix was reproduced in a
failing test before the fix. Drop's receipt-guard review found no material issue.
No captured instructions were authorized for execution. No original recordings,
production ledgers, old synthetic receipts, consumer cursors, or unrelated working
changes were deleted. Disposable SQLite rehearsal copies were moved to Trash.
