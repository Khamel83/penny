# Penny declared check and deployment contract — infra incident on `penny.doctor-readiness`

Incident marker (verbatim, for traceability): `infra-incident:70f416e08012bef7550c690ec152cade6eac6763c3ce1d555d704a420f2dfac8:1`
Issue: https://github.com/Khamel83/penny/issues/110 (state OPEN, label `g2k:acceptance-pending`)
Refs #110

Scope of this worker: read-only investigation inside this worktree at
`5d63847073dd00ac874611a8b0273611277b520b` (`origin/main`, also the worktree HEAD).
No code, configuration, secret, issue, or follow-up issue was modified; this report
is the only file written. The infra-side catalog (`Khamel83/infra:config/project-catalog.yml`,
named in `INFRA.md`) and the OCI observer are outside this worktree and were not
fetched or executed.

## Question

1. Which check does the owning repository declare, and does it correspond to the
   incident's `check_id` / `project_id` / `severity` / `declaration_hash`?
2. What deployment contract does the repository declare for that check, and is it
   currently satisfied?
3. What does the declared check actually evaluate, and which current, documented
   state would produce `failures: 3` as a *fresh* failure?

Out of scope: changing the check, the catalog, the runtime, or the declarations.

## Sources or evidence

Incident payload as given in the issue:

```json
{"check_id":"penny.doctor-readiness","declaration_hash":"5231cdb63a84213204f2b465f337d41681a7b5de492e1c2684f406854ac9fd01",
 "failures":3,"project_id":"penny","severity":"high"}
```

Repository declarations (`homelab.yaml`, unchanged at HEAD: sha256
`74a39a950a3e7e8da8eddb731be2072880f09dd2b7f5ed960d82a809c44941f9`):

- `homelab.yaml:36-45` — health checks are `id: penny.doctor, type: readiness,
  severity: high, repair_id: null` and `id: penny.backup, type: verification-receipt,
  severity: high, repair_id: null`. There is no second readiness check.
- `homelab.yaml:9-12` — `monitoring.state: observing`, `monitoring.source: penny-doctor`,
  `monitoring.evidence: metadata-only`.
- `homelab.yaml:13-18` — `runtime.production`: `host: macmini`, `managed_by: user-launchd`,
  `unit: penny`, `deployment_proof: exact-source-revision-plus-doctor`.
- `homelab.yaml:46-50` — `event_sink: homelab-api:/observations`,
  `event_sink_status: target-only-unverified`, `evidence_policy: sanitized`.
- `homelab.yaml:65-67` (operations) — `repair_ids: []`, `destructive_actions: disabled`.
- `INFRA.md` janitor catalog block — infra authority is
  `Khamel83/infra:config/project-catalog.yml`; this `INFRA.md` is the project's projection.

Declaration history (`git log -p --follow -- homelab.yaml`):

- `cf22785` (2026-07-14) first declared the single check `id: penny.launchd, type: catalog,
  severity: medium, repair_id: null`, with `managed_by: unknown`.
- `90e63b1` (2026-08-10) replaced it with the current two checks (`penny.doctor` / readiness /
  high, `penny.backup` / verification-receipt / high) and introduced
  `managed_by: user-launchd` plus `deployment_proof: exact-source-revision-plus-doctor`.
- `e01f5b7` (2026-08-10, last commit touching the file) changed only a credential
  *reference name* (`hermes-notification-credential`); the checks block is unchanged since
  `90e63b1`. `git log --all -S'doctor-readiness'` returns no commit at all.

Identity of the incident's check id:

- `grep -rn "penny\.doctor-readiness"` over the worktree: 0 matches. The literal
  `penny.doctor-readiness` appears nowhere in the repository or anywhere in its history.
- The only readiness declaration is `penny.doctor` / `readiness` / `high`, and it is the
  only declaration consistent with `project_id: penny`, `severity: high`, and the
  `-readiness` suffix under any composition of declared fields
  (`<project.id>.<monitoring.source minus prefix>-<check.type>` = `penny` + `doctor` + `-readiness`,
  or `<check.id>-<check.type>`). [INFERENCE] the catalog id is composed by infra from this
  declaration; the repository makes no such claim itself.

`declaration_hash` reproduction attempt (all sha256, none matched): raw file bytes at every
revision that ever contained the file (`cf22785`, `90e63b1`, `b40a705`, `9e27593`, `e01f5b7`,
HEAD), stripped variants, the git-blob form (`blob <len>\0<content>`), the `health:` block,
the checks list, the single check as JSON (multiple key orders/spacings/sorted variants),
YAML→JSON of the whole document and of the check, and ordered separator-joinings of
`{project_id, id, type, severity, repair_id}` plus the composite id string. No candidate matched.
Conclusion: `declaration_hash` is computed over an infra-side record schema not present in
this repository, so it cannot confirm or refute drift from worktree bytes alone.

What the declared check evaluates (the check's own policy):

- `scripts/penny_doctor.py:1-6,45-61` — CLI exit status is stable for automation:
  `0` ready, `1` degraded, `2` unready; output is metadata-only.
- `README.md:88-104` — the installed caller's `/ready` is the operational readiness source;
  `/ready` returns `200` for ready/degraded and `503` for unready.
- `docs/reliability.md:143-160` — Doctor is read-only/metadata-only; current failures and
  stale/unreadable source evidence remain readiness failures.
- `doctor.py:691-709` — Drop probe: `state = 'unready' if uncertain or failed or age > 900`,
  `reason = 'uncertain_effect'` when any Drop delivery row is `uncertain`.
- `doctor.py:1163-1176` — Voice Memos policy: coverage gap, current terminal failures,
  retryable failures ⇒ unready; historical acknowledged failures or unavailable rows ⇒
  degraded (`historical_unavailable`), not ready.
- `doctor.py:1177-1275` (archive, transcription, shared_whisper, apple_effects, maya, slack,
  backup, services) — e.g. `apple_effects` `uncertain_count > 0` ⇒ unready, `failed_count > 0`
  ⇒ unready, `migration_quarantine_count > 0` ⇒ unready, quarantined ⇒ degraded;
  `backup` unverified/stale/timestamp-invalid ⇒ unready; `services` health-file staleness,
  coverage gap, or launchd unavailability ⇒ unready.
- `docs/capture-health.md:14-31` — the fixed `voice_memos.historical_failure_before` cutoff
  (`config.toml:30` = `2026-09-22T16:45:38Z`) makes two pre-existing failures *historical*;
  historical failures produce **degraded**, and "Do not advance the cutoff merely to make
  health green". The cutoff lives in the checkout's `config.toml`
  (`config.py:24`, relative to `config.py`), not in the observer's shell environment.

Documented current runtime state (in-repo record, immediately before the incident):

- `docs/ssd-storage-20261009.md:51-52` — "HTTP 503 remains due to `drop: uncertain_effect`,
  also present in the saved pre-migration result"; `:64` — "Existing runtime component
  revision stamps remain unchanged; this is not a full source release".
- `docs/ssd-storage-20261009.md:49-51` — four continuous services running, shared ASR idle,
  archive/backup/SQLite/services/transcription ready.
- `CONTEXT.md:10-14`, `HANDOFF.md:11-17` — `/ready` 503 for the same pre-existing uncertain
  Drop effect; PR113 source review/merge pending at that time.
- `TODO.md:13-14` — open item: "Reconcile the pre-existing uncertain Drop receipt through its
  receipt-bound procedure; `/ready` remains 503 for `drop: uncertain_effect`. No replay done."
- `INFRA.md:44-53` — OCI `penny-health.timer` is the observation path; it invokes a bounded
  SSH Doctor that "does not inherit all launchd configuration, so its source is unknown and
  Drop appears disabled"; its supervised run "recorded degraded with Apple quarantine,
  historical Maya/Voice Memo exceptions and no unready component"; receipt path is
  `/home/ubuntu/.local/state/penny-health/receipts/`. `INFRA.md:44-46` records that the
  natural timer run recorded "the actual Apple provider failure".
- Preserved non-ready states (`CONTEXT.md:50-52`, `TODO.md` completed entries): one synthetic
  Apple quarantine, nine Maya dead letters, two old missing-audio failures, one unavailable
  memo, held row 769, synthetic quarantine row 493.

Deployment-contract evidence:

- `docs/macmini-deployment.md:1-6,67-82` — record the exact pushed SHA, runtime checkout SHA,
  launchd labels and Doctor result before calling a deployment complete; deploy with
  `venv/bin/python scripts/deploy_penny.py --apply` then the read-only re-run; "A Git push
  alone is not deployment".
- `docs/macmini-deployment.md:109-125` — acceptance evidence requires "pushed SHA equals the
  runtime checkout SHA", registered labels (not itself a health result), `penny doctor`
  exit/status, `/health` + `/ready` responses, one shared-Whisper owner, bound backup
  verification receipt, and ingress 401/413 behaviour.
- `scripts/deploy_penny.py:49-56` — `pushed_revision()` refuses a dirty checkout, a non-`main`
  branch, or a HEAD that differs from `origin/main`; `:187-211` stamps the revision, reloads
  labels, and reports `revision_drift` when a loaded `PENNY_SOURCE_REVISION` differs.
- Installed-state record (`INFRA.md:21-33`, `CONTEXT.md:34-37`): callers at
  `6ccf2286a2c6af1919e43b4eaba72465f8eb614b`, shared ASR and export at
  `c341598c484734ace251944f3f7ca56ab0bb0009`, while merged `main` is
  `5d63847073dd00ac874611a8b0273611277b520b`
  ("fix(storage): keep Penny data and runtime on the SSD (#113)", committer date
  2026-10-09 18:00:23 -0700 = 2026-10-10T01:00:23Z).
- Timing: the incident issue was created 2026-10-10T00:20:42Z, ~40 minutes *before* PR113's
  merge commit landed on `main`; the SSD relocation described by it was already installed at
  runtime ("runtime configuration is installed; old component revision stamps are retained",
  `HANDOFF.md:11-14`).

## Conclusion

F1. The owning repository does declare a readiness check that matches the incident:
`homelab.yaml:38-41` — `penny.doctor`, `type: readiness`, `severity: high`, `repair_id: null`,
with `monitoring.source: penny-doctor` and `evidence: metadata-only`. The literal
`penny.doctor-readiness` is nowhere in the repository or its history; it is infra's composed
id for this declaration. `penny.backup` (verification-receipt) is the only other declared check.

F2. There is no evidence of declaration drift. The checks block has been stable since
2026-08-10 (`90e63b1`); the last edit to `homelab.yaml` changed only a credential reference
name. [INFERENCE] `declaration_hash` cannot be reproduced from any in-worktree
representation of the declaration, so it is computed by infra over its own record schema —
its value neither confirms nor refutes a mismatch and must be checked catalog-side.

F3. The declared check is a runtime readiness observation, not a build/lint check. `failures: 3`
therefore records failing *readiness observations* of the deployed Penny, reached through the
OCI `penny-health.timer` observer (`INFRA.md:44-53`) and/or the installed `/ready` surface.
The repository's own CI (`.github/workflows/test.yml`) has no doctor/readiness job, and
`scripts/trust_check.py:280-285` fails the build if a private `health-check.yml` workflow is
reintroduced, so the check cannot be satisfied or broken by repository CI.

F4. On its own declared terms the check is legitimately red today, for two independent,
documented reasons:
- Unready: `/ready` is `503` because a Drop delivery row is `uncertain`
  (`doctor.py:706-707` ⇒ `reason: uncertain_effect`, `state: unready`), and that condition is
  still open in `TODO.md:13-14` with "No replay done". An unready Doctor exits `2`.
- Not fully ready even when that clears: the preserved historical exceptions
  (`docs/capture-health.md:14-31`, `CONTEXT.md:50-52`) keep components at `degraded`
  (`historical_unavailable`, `dead_letter`, `quarantine`), Doctor exits `1`, and the observer
  path additionally sees "Drop appears disabled" because it does not inherit launchd
  configuration (`INFRA.md:49-51`). Any readiness check keyed to exit `0`/`200` therefore
  fails repeatedly and by design until either the uncertain Drop effect is reconciled or the
  history is explicitly re-reviewed — and `docs/capture-health.md:23-24` forbids clearing
  history merely to make health green.

F5. The declared deployment contract (`deployment_proof: exact-source-revision-plus-doctor`,
`homelab.yaml:18`; elaborated in `docs/macmini-deployment.md`) is **not satisfied** for current
`main`. Merged source is `5d63847` (PR #113, merged 2026-10-10T01:00:23Z); installed component
revisions remain `6ccf2286` (callers) and `c341598c` (shared ASR/export), and the SSD
relocation itself is documented as "not a full source release"
(`docs/ssd-storage-20261009.md:64`). `deploy_penny.py` stamps and verifies exact revisions, so
the "exact reviewed merged source is deployed" acceptance line in issue #110 cannot be closed
by documentation alone.

F6. Nothing in the repository treats the incident as a declaration/catalog defect: no repair id
is declared (`repair_id: null`, `operations.repair_ids: []`,
`destructive_actions: disabled`), and `event_sink_status: target-only-unverified` plus
`evidence: metadata-only` mean the repository only publishes sanitized metadata observations.
The failure is an honest red on a real, bounded, already-tracked runtime condition — not a
missing check, not a stale declaration, and not something a source-only change fixes.

F7. Unproven here, and left explicitly unknown rather than inferred: (a) whether infra's
`readiness` threshold is exit `0` only or exit `2` only — the two readings correspond to F4's
two reasons and are indistinguishable from worktree evidence; (b) what the three failing
observations were and when; (c) the catalog-side `declaration_hash` value/derivation; (d) any
live runtime state newer than `docs/ssd-storage-20261009.md` (this worker has no Mac/OCI access
and must not create one).

## Next action

Ordered; each step names the evidence it must produce. No step is a closing action on #110, and
the reference line above stays non-closing (`Refs #110`).

1. Infra/catalog owner confirms the composed id and hash: verify in
   `Khamel83/infra:config/project-catalog.yml` that the `penny` entry contains
   `penny.doctor` (`type: readiness`, `severity: high`) whose composed id is
   `penny.doctor-readiness`, and that its `declaration_hash`
   (`5231cdb6…4ac9fd01`) reproduces from that catalog record, not from `homelab.yaml`
   bytes (`homelab.yaml` at HEAD hashes to
   `74a39a950a3e7e8da8eddb731be2072880f09dd2b7f5ed960d82a809c44941f9`). If it does not
   reproduce, treat it as catalog drift — the only finding that would make this a
   declaration issue rather than a runtime readiness failure.
2. Infra owner states which Doctor outcome counts as failure for a `readiness` check
   (exit `0` only, or exit `2` only). This decides whether F4's `503`/unready reason, its
   permanently-degraded historical reasons, or both are the reported failure.
3. Resolve the open runtime condition that makes `/ready` unready: run the receipt-bound
   reconciliation `venv/bin/python scripts/export_drop.py --reconcile --apply`
   (`scripts/export_drop.py:54,71-73` → `drop_delivery.reconcile_pending_drop`), which is
   read-only network reconciliation against Drop plus a guarded local receipt write, and
   record the before/after `drop_deliveries` status counts. Do not replay or fabricate a
   receipt; if the row cannot be reconciled, it stays `uncertain` and `TODO.md:13-14` stands.
4. Deploy the exact reviewed merged source and capture the deployment proof, per
   `docs/macmini-deployment.md:67-82,109-125`: on the Mac mini runtime checkout,
   `venv/bin/python scripts/deploy_penny.py --apply`, then the read-only re-run, then record
   pushed SHA == runtime checkout SHA, the five loaded `PENNY_SOURCE_REVISION` values, and the
   Doctor output; finally `curl -fsS http://127.0.0.1:5678/ready` and
   `http://127.0.0.1:10311/health`. Metadata-only evidence; no transcript/audio bodies.
5. Re-observe and record one fresh observer receipt (the `penny-health.timer` path in
   `INFRA.md:44-53`) showing the post-deploy Doctor overall state and per-component reason
   codes, so acceptance can be judged on fresh merged source rather than the pre-merge state.
6. Keep #110 open with `g2k:acceptance-pending` until steps 3-5 give deployed exact-source
   evidence plus downstream recovery verification. If step 3 is the only blocker left and it is
   explicitly accepted as a retained exception, that decision is the owner's and must be
   recorded in `CONTEXT.md`/`TODO.md` — it is not a worker action.
