# Penny declared check and deployment contract — infra incident `penny.doctor-readiness`

Incident marker (verbatim, for traceability):
`infra-incident:70f416e08012bef7550c690ec152cade6eac6763c3ce1d555d704a420f2dfac8:1`
Issue: https://github.com/Khamel83/penny/issues/110 (OPEN, label `g2k:acceptance-pending`,
created 2026-10-10T00:20:42Z, updated 2026-10-12T02:52:44Z). Refs #110.

Scope and method: read-only investigation inside this worktree. Source facts are read from the
fetched default branch `origin/main` = `6e975d7fb7e2d67a49c544b138bd353f6d98e53e`
("Reconcile all open work into the owning repository plan (#118)"); the local worktree branch
`g2k/issue-110` is two commits behind that tip. Retained-candidate facts are read from
`refs/pull/115/head` = `192aeb07e4548a46156967ba4d58ed4d1a3d5845` (no checkout, `git diff`
only). At inspection, the worktree also contained staged source edits in `doctor.py` and
`transcript_log.py`; this artifact records the origin/retained-candidate facts separately from
that local candidate. No code, configuration, secret, issue, or follow-up issue was modified
while collecting the original evidence. The infra-side catalog
(`Khamel83/infra:config/project-catalog.yml`, named in `INFRA.md`) and the OCI observer were not
fetched or executed; no credentials, browser session, or file outside this worktree was
accessed. The report is a research-v1 artifact: it identifies exact current source, gap and
acceptance path, and deliberately makes no live runtime claim.

## Question

1. Which check does the owning repository declare, and does it correspond to the incident's
   `check_id` / `project_id` / `severity` / `declaration_hash`?
2. What deployment contract does the repository declare for that check, and is it satisfied?
3. What does the declared check evaluate, and which current, documented state produces
   `failures: 3` as a *fresh* failure?
4. Does a retained candidate already close the source-side gap, and what is actually left?

Out of scope: changing the check, the catalog, the runtime, or the declarations.

## Sources or evidence

Incident payload as given in issue #110:

```json
{"check_id":"penny.doctor-readiness","declaration_hash":"5231cdb63a84213204f2b465f337d41681a7b5de492e1c2684f406854ac9fd01",
 "failures":3,"project_id":"penny","severity":"high"}
```

Repository declarations — `homelab.yaml` at `origin/main`, unchanged since 2026-08-10,
sha256 `74a39a950a3e7e8da8eddb731be2072880f09dd2b7f5ed960d82a809c44941f9` (identical to the
hash of the same file one commit earlier at `5d63847`, i.e. no declaration change in the two
newest `main` commits):

- `homelab.yaml:36-45` — checks are `id: penny.doctor, type: readiness, severity: high,
  repair_id: null` and `id: penny.backup, type: verification-receipt, severity: high,
  repair_id: null`. There is no second readiness check and no literal `penny.doctor-readiness`.
- `homelab.yaml:9-12` — `monitoring.state: observing`, `source: penny-doctor`,
  `evidence: metadata-only`.
- `homelab.yaml:13-18` — `runtime.production`: `host: macmini`, `managed_by: user-launchd`,
  `unit: penny`, `deployment_proof: exact-source-revision-plus-doctor`.
- `homelab.yaml:47-50` — `event_sink: homelab-api:/observations`,
  `event_sink_status: target-only-unverified`, `evidence_policy: sanitized`.
- `homelab.yaml:66-67` — `operations.repair_ids: []`, `destructive_actions: disabled`.
- `INFRA.md` janitor block — infra owns the catalog; this `INFRA.md` is the project projection.

Identity and history of the check id:

- `grep -rn "penny\.doctor-readiness"` over the worktree and
  `git log --all -S'doctor-readiness'`: 0 matches. The literal id is infra-composed, not
  repository text. It is consistent only with `project.id: penny` +
  `monitoring.source: penny-doctor` + `check.type: readiness` (or `<check.id>-<check.type>`).
  [INFERENCE] composition happens catalog-side; the repository claims nothing about it.
- `git log -p --follow -- homelab.yaml`: `cf22785` (2026-07-14) declared one check
  `penny.launchd` / `catalog` / `medium`; `90e63b1` (2026-08-10) replaced it with the current
  two checks and `managed_by: user-launchd` + `deployment_proof:
  exact-source-revision-plus-doctor`; `e01f5b7` (2026-08-10) changed only a credential
  reference name. The checks block is unchanged since 2026-08-10.
- `declaration_hash` reproduction attempt (all sha256, none matched): raw bytes of
  `homelab.yaml` at every revision that contained it (`cf22785`, `90e63b1`, `b40a705`,
  `9e27593`, `e01f5b7`, `5d63847`, `6e975d7`), stripped variants, the git-blob form
  (`blob <len>\0<content>`), the `health:` block, the checks list, the single check as JSON
  (multiple key orders/spacings/sorted variants), YAML→JSON of the document and of the check,
  ordered separator-joinings of `{project_id, id, type, severity, repair_id}`, and the
  composed id string. No candidate matched, so `declaration_hash` is computed over an
  infra-side record schema not present here.

What the declared readiness check evaluates:

- `scripts/penny_doctor.py:1-6,45-61` — CLI exit status is stable for automation: `0` ready,
  `1` degraded, `2` unready; output is metadata-only; any internal exception becomes an
  unready report rather than leaking text/paths.
- `doctor.py:691-710` (`_default_probe_drop`, `origin/main`) — reads `drop_deliveries`
  read-only; `state = 'unready' if uncertain or failed or age > 900 else ('degraded' if
  pending else 'ready')`, `reason = 'uncertain_effect'` when any row is `uncertain`. A
  `skipped` row is already neither uncertain, nor failed, nor pending, so **merged source
  does not count it** — there is no `skipped` handling in `doctor.py` on `origin/main`
  (`git show origin/main:doctor.py | grep -n skipped` → empty).
- `doctor.py:1169-1175` — Voice Memos: current terminal failures over the historical cutoff
  ⇒ unready; historical-only failures or unavailable rows ⇒ `degraded`,
  `historical_unavailable`.
- `tests/test_drop_delivery.py:20-31` — `test_health_is_unready_for_uncertain_handoff` pins
  the uncertain ⇒ unready contract.
- `docs/capture-health.md:14-31` — the fixed `voice_memos.historical_failure_before` cutoff
  (`config.toml:30` = `2026-09-22T16:45:38Z`) makes two pre-existing failures historical;
  historical failures produce degraded, and "Do not advance the cutoff merely to make health
  green".

Documented current runtime state (in-repo record at `origin/main`, i.e. pre-skip):

- `CONTEXT.md` "Current storage decision and state — October 9" — "`/ready` remains 503 for
  the same pre-existing uncertain Drop effect"; four continuous services run; SQLite,
  archive, backup and transcription checks pass.
- `HANDOFF.md` "Current checkpoint — October 9" — "`/ready` is 503 for that same reason";
  Drop158 open; last-verified component revisions remain `6ccf2286` (three callers) and
  `c341598c` (shared ASR/export), while `main` is `5d63847`.
- `TODO.md:13-20` — transcript 779 / outbox 335 handoff unresolved "via
  [Drop158](https://github.com/Khamel83/drop/issues/158)"; "/ready remains 503 for
  `drop: uncertain_effect`. No replay done."; owner preference for skip vs retry pending.
- `INFRA.md:44-53` — OCI `penny-health.timer` is the observation path; it invokes a bounded
  SSH Doctor that "does not inherit all launchd configuration, so its source is unknown and
  Drop appears disabled"; the supervised run "recorded degraded with Apple quarantine,
  historical Maya/Voice Memo exceptions and no unready component"; receipts live at
  `/home/ubuntu/.local/state/penny-health/receipts/`. The natural 09:00 UTC run recorded the
  actual Apple provider failure.
- `CONTEXT.md` "Verified state" — retained non-ready states: one synthetic Apple quarantine,
  nine Maya dead letters, two old missing-audio failures, one unavailable memo, held row 769.

Deployment contract evidence:

- `docs/macmini-deployment.md:1-6` — the runbook "does not claim that the current host is on
  this revision. Record the exact pushed SHA, runtime checkout SHA, launchd labels, and
  Doctor result before calling a deployment complete."
- `docs/macmini-deployment.md:109-125` — acceptance evidence requires pushed SHA == runtime
  checkout SHA, registered labels (not itself a health result), `penny doctor` exit/status and
  component reason codes, `/health` and `/ready` responses, one shared-Whisper owner, a bound
  backup verification receipt, and ingress 401/413 behavior.
- `scripts/deploy_penny.py:49-56,126,211` — `pushed_revision()` requires a clean checkout on
  `main` equal to `origin/main`; the deploy stamps `PENNY_SOURCE_REVISION` into every label
  and reports `revision_drift` when a loaded value differs. "A Git push alone is not
  deployment" (`docs/macmini-deployment.md:82`).
- CI is not the check: `.github/workflows/test.yml` runs `pytest tests/` and
  `scripts/trust_check.py` on hosted runners for `python-version: ["3.11","3.12"]`; there is
  no doctor/readiness job, and `scripts/trust_check.py:280-285` fails the build if a private
  `health-check.yml` workflow is reintroduced. Repository CI therefore cannot satisfy or
  break `penny.doctor-readiness`.

Retained candidate (issue said "inspect current owning source and retained candidate"):

- `refs/pull/115/head` = `192aeb07e4548a46156967ba4d58ed4d1a3d5845`, branch
  `fix/drop-owner-skip-779`, PR #115 "fix(health): record owner-skipped Drop delivery and
  restore readiness", OPEN, base `cfcae61`, merge state CLEAN, last updated
  2026-10-10T07:03:01Z.
- Its source diff against `origin/main` in `doctor.py` is two lines only: add
  `"skipped_count"` to `_SAFE_DETAIL_KEYS` and report `skipped_count=states.get('skipped', 0)`
  in the Drop probe; plus `tests/test_drop_delivery.py::test_owner_skipped_handoff_is_visible_and_never_resent`
  and documentation edits (`docs/drop-delivery.md`, `docs/drop-owner-skip-779-20261010.md`,
  `CONTEXT.md`, `HANDOFF.md`, `TODO.md`). It does not change the unready computation.
- Two OCI reviewer passes are on record for that head: `findings` at `21348c3e` (MEDIUM: any
  row reaching `skipped` turns `/ready` green through an unguarded transition; LOW: dropped
  SSD-mount/no-replay guidance; LOW: October 9 section rewritten with October 10 facts; LOW:
  Drop158 closure asserted without evidence) and `blocked` at `192aeb07` (MEDIUM: contradictory
  October 9 no-mutation claim; MEDIUM: no audit linkage enforced on skips; LOW: installed
  runtime not traceable to the reviewed head; LOW: Drop158 status wording). PR #115 is
  therefore unmerged and currently blocked.
- PR #115's body claims a runtime effect already occurred out of band: owner skip of note 779,
  "installed readiness HTTP 200, zero unready components, Drop skipped=1", "only scoped Doctor
  counters were installed; only webhook was reloaded". No source revision or content hash is
  named, and the same reviewer pass flags exactly that traceability gap.

The bounded local candidate now differs from that retained PR: `transcript_log.py`
adds additive `owner_skip_ref`/`skipped_at` columns and
`owner_skip_drop_delivery`, which requires a bounded decision reference and refuses
accepted or live-claimed rows; `doctor.py` exposes `skipped_count` without counting
skipped rows as pending, failed, or uncertain. Focused tests cover reference
validation, evidence preservation, live-claim/accepted-row protection, and
metadata-only Doctor visibility. This remains source-only until native CI, exact-head
review, merge, deployment, and downstream acceptance.

Post-issue record movement: `origin/main` advanced from `5d63847` to `6e975d7` via `cfcae61`
("docs: track unresolved Drop handoff 779 (#114)") and `6e975d7` ("Reconcile all open work
into the owning repository plan (#118)"). Those commits change only `CONTEXT.md`, `HANDOFF.md`,
`TODO.md`, and add `docs/REPO_PLAN.md`; `docs/REPO_PLAN.md` parks #110 as "Executor hold
remains" and lists PR #115 as needing exact-head review before any transcript-779 claim.

## Conclusion

F1. The owning repository does declare the readiness check the incident refers to:
`homelab.yaml:38-41` — `penny.doctor`, `type: readiness`, `severity: high`, `repair_id: null`,
under `monitoring.source: penny-doctor`, `evidence: metadata-only`. The literal
`penny.doctor-readiness` appears nowhere in the repository or its history; it is infra's
composed id. `penny.backup` is the only other declared check, and the declaration file has not
changed since 2026-08-10, including across the two commits that landed after the incident.

F2. There is no evidence of declaration drift from the worktree. `homelab.yaml` at
`origin/main` hashes to
`74a39a950a3e7e8da8eddb731be2072880f09dd2b7f5ed960d82a809c44941f9`, and its checks block is
unchanged since `90e63b1`. [INFERENCE] `declaration_hash` cannot be reproduced from any
in-worktree representation, so it is computed by infra over its own record schema; its value
neither confirms nor refutes a mismatch and must be checked catalog-side.

F3. The declared check is a runtime readiness observation, not a build/lint check.
`failures: 3` records three failing *readiness observations* of the deployed Penny, taken
through the OCI `penny-health.timer` observer and/or the installed `/ready` surface.
Repository CI has no doctor/readiness job (`test.yml`; `trust_check.py:280-285`), so this check
cannot be satisfied by a source-only change.

F4. On its declared terms the check is legitimately and repeatedly red, for two independent,
documented reasons:
- *Unready, pre-skip.* At incident time `/ready` was `503` because one `drop_deliveries` row was
  `uncertain` (`doctor.py:705-707` ⇒ `reason: uncertain_effect`, `state: unready`; pinned by
  `tests/test_drop_delivery.py:20-31`), and that condition is still open in `TODO.md:13-20`
  ("No replay done"). An unready Doctor exits `2`.
- *Never-ready through the observer path, even after the Drop row clears.* The observer's
  bounded SSH Doctor does not inherit launchd configuration, so Drop appears disabled, and its
  supervised run recorded **degraded** from a retained Apple quarantine plus historical
  Maya/Voice Memo exceptions (`INFRA.md:44-53`; `CONTEXT.md` "Historical exceptions remain
  visible"). Degraded is not ready. Any readiness check keyed to a ready-only threshold
  therefore fails repeatedly and by design, on retained history that
  `docs/capture-health.md:23-24` forbids clearing merely to make health green.
[INFERENCE] The two reasons above are indistinguishable from worktree evidence when only
`failures: 3` is known; both are consistent with it, and the observed severity `high` matches
the declaration.

F5. The declared deployment contract (`deployment_proof:
exact-source-revision-plus-doctor`, `homelab.yaml:18`; elaborated in
`docs/macmini-deployment.md`) is **not satisfied** for current `main`. Merged source is
`6e975d7` (upstream tip), installed component revisions remain `6ccf2286` (callers) and
`c341598c` (shared ASR/export), and the SSD relocation itself is recorded as "not a full
source release" (`docs/ssd-storage-20261009.md:64`). PR #115's own reviewer flagged that the
claimed installed Doctor change names no source revision, so the current installed state cannot
be tied to any reviewed head. The issue's "exact reviewed merged source is deployed"
acceptance line cannot be closed by documentation or by an unmerged candidate.

F6. No source change is required to make a *skipped* Drop row non-blocking: `origin/main`'s
probe already ignores rows whose status is `skipped` because only `uncertain`/`failed`/fresh
`pending` are counted (`doctor.py:691-710`; `grep skipped` on `origin/main:doctor.py` → empty).
The retained candidate PR #115 is therefore not the readiness fix it is titled to be — it adds
a `skipped_count` visibility counter, a regression test and record edits. Its "restore
readiness" effect is attributable to the out-of-band SQL status transition on outbox 335, not
to the diff. That transition is exactly what the two independent reviewer passes blocked on:
an unguarded `skipped` status with no enforced owner-decision/audit linkage can turn `/ready`
green for a genuinely uncertain or failed delivery.

F7. There is no in-repository declaration defect to repair: `repair_id: null`,
`operations.repair_ids: []`, `destructive_actions: disabled`, `evidence: metadata-only`,
`event_sink_status: target-only-unverified` mean the repository only publishes sanitized
metadata observations of a real, bounded, already-tracked runtime condition. The honest source
deliverable for #110 is this bounded research artifact plus the retained candidate's completion
under exact-head review — not a new platform or an invented fix.

F8. Unproven here, and left explicitly unknown rather than inferred: (a) whether infra's
`readiness` threshold is ready-only or treats degraded as healthy — the two readings correspond
to F4's two reasons; (b) the three failing observations' times and payloads; (c) the
catalog-side `declaration_hash` value/derivation; (d) whether the claimed runtime skip and
partial Doctor install actually occurred, and under which source revision (this worker has no
Mac/OCI access and must not create one).

## Next action

Ordered; each step names the evidence it must produce. No step closes #110, and the reference
line at the top stays non-closing (`Refs #110`); `g2k:acceptance-pending` is retained.

1. Infra/catalog owner confirms the composed id and hash: in
   `Khamel83/infra:config/project-catalog.yml`, the `penny` entry's
   `penny.doctor` (`type: readiness`, `severity: high`) must compose to `penny.doctor-readiness`
   and its `declaration_hash` must reproduce from that catalog record — not from `homelab.yaml`
   bytes, which hash to `74a39a95…c44941f9`. Non-reproduction is the only finding that would
   make this a declaration issue rather than a runtime readiness failure.
2. Infra owner states which Doctor outcome counts as failure for a `readiness` check
   (ready-only, or unready-only). This decides whether F4's post-skip observer degradation, its
   pre-skip uncertain reason, or both are the reported failure.
3. Land the retained candidate correctly rather than reopening it: PR #115 must either add a
   guarded skip transition that requires an owner-decision reference and refuses rows in
   `failed`/`uncertain` state without it (or explicitly document the transition as a manual
   operator procedure whose rows `/ready` must not silently ignore), plus a negative-control
   test, or it must be closed as superseded. Verify the exact head, native CI, and trusted
   exact-head review; do not merge on the existing `blocked` verdict.
4. Resolve the underlying runtime condition through its receipt-bound path, not by waiver: the
   skipped/uncertain transcript 779 / outbox 335 row keeps its frozen bytes; owner preference
   for keep-local-skip versus retry is recorded in `TODO.md:13-20` as still pending, and
   Drop158 is the tracking record. Record before/after `drop_deliveries` status counts from the
   installed ledger; no replay, resend, or fabricated receipt.
5. Deploy the exact reviewed merged source and capture the deployment proof per
   `docs/macmini-deployment.md:67-82,109-125`: on the Mac mini runtime checkout run
   `venv/bin/python scripts/deploy_penny.py --apply` (inspect `--help` first), then the
   read-only re-run, then record pushed SHA == runtime checkout SHA, the five loaded
   `PENNY_SOURCE_REVISION` values, and Doctor exit/status with component reason codes; finally
   `curl -fsS http://127.0.0.1:5678/ready` and `http://127.0.0.1:10311/health`. Metadata-only
   evidence; no transcript or audio bodies.
6. Re-observe and record one fresh observer receipt on the `penny-health.timer` path
   (`INFRA.md:44-53`) showing post-deploy overall state and per-component reason codes, so
   acceptance is judged on fresh merged source rather than the pre-merge state.
7. Keep #110 open with `g2k:acceptance-pending` until steps 4-6 give deployed exact-source
   evidence plus downstream recovery verification. If step 4's retained exception is the only
   remaining blocker, accepting it is the owner's decision and must be recorded in
   `CONTEXT.md`/`TODO.md` — it is not a worker action.
