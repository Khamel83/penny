# Infra incident: penny / penny.doctor-readiness — issue #176

Incident marker: `infra-incident:70f416e08012bef7550c690ec152cade6eac6763c3ce1d555d704a420f2dfac8:8`

## Blocker

This worktree cannot establish the cause of the reported three fresh failures.
No sanitized observation timestamps, failed Doctor component/reason codes, or
deployed source revision are available in the repository or its history. The
declaration hash cannot be reproduced from any in-worktree representation, and
the literal check id `penny.doctor-readiness` does not appear in source.

The declared check (`homelab.yaml`: `penny.doctor`, type `readiness`,
severity `high`, `repair_id: null`) is a runtime observation, not a build or
test. Repository CI has no doctor/readiness job, so no source change here can
be verified against it. Deployment proof requires
`exact-source-revision-plus-doctor` on the Mac runtime, which this worker
cannot access.

## What was checked

- `git fetch origin` succeeded; default branch `main` at `e927a0f`.
- `homelab.yaml` unchanged since 2026-08-10; `repair_ids: []`,
  `destructive_actions: disabled`.
- `_default_probe_drop` already handles missing DB, missing table, and
  DatabaseError; tests pass (38/38).
- No failing or skipped test identifies a regression.

## Required to proceed

Human/Infra must supply sanitized metadata for the three fresh failures
(timestamps, Doctor component status/reason codes, observed deployed revision),
the matching catalog declaration, and the permitted deployment boundary. Then
reproduce the specific failed check locally before selecting a repair.

No source, configuration, credential, or runtime mutation performed. No PR
push or merge attempted. Keep acceptance pending until exact reviewed merged
deployment and three fresh downstream successes.
Refs #176
" path">
docs/research/g2k-issue-176.md