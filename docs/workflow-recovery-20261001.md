# Workflow recovery — October 1, 2026

## Workflow recovery checkpoint — October 1, 2026

Owner authorized remaining workflow diagnosis and repair. Penny installed code stays
`f4909d33`; fresh metadata-only Doctor at `2026-10-02T00:36:50Z` reports capture,
Parakeet, archive, backup, Drop, Slack and SQLite ready. Overall remains unready
from Apple provider failure, with historical Maya and Voice Memo degradation.

Nine legacy Maya dead letters have unique successful Drop `store_only` receipts;
all nine raw payload hashes/sizes and current canonical object bytes match. Zero
missing/conflicting receipts. Legacy flat-file paths are absent, so this is current
canonical storage proof, not proof of historical flat-file migration. Do not resend
or forge success for the original direct Maya failures.

Actual launchd-context inventory finds both historical Voice Memo source rows.
One has zero duration and no audio file. The other has a 1,586-byte AAC file with
3.285-second container metadata but decoding exits 69, emits zero samples and
reports invalid AAC data. Preserve originals/history; no ASR or canonical rewrite
was performed. Native-source inventory succeeds; agent-shell access denial does
not establish a capture failure. Temporary diagnostic LaunchAgents were removed.

Notes UI is responsive. Actual provider marker/account queries time out, including
from installed Penny launchd context; generic Finder-window and Reminders-list
queries also time out. Normal Notes quit/reopen did not fix it. UI exact-marker
search for the recent capped effect returned no results, but this does not replace
provider reconciliation. An older synthetic effect remains quarantined. There were
zero active Apple-effect leases. The bounded system Apple Events service restart
was attempted and blocked by `sudo: a password is required`; no privacy grants,
TCC reset, note recreation or account changes occurred.

Atlas receipt-schema, relative-manifest-entrypoint and missing canonical queue-link
repairs passed native verification. A following natural drain completed pull/import
but failed after typed ASR deferral; fresh readiness returned 503. PR167 exposes
only the safe typed code; final deployment/cause resolution is still in flight.
MinusPod has at least one natural completion after resume; identity/publication
remain distinct acceptance gates. See Atlas's current audit package.

Private receipts (0600) are under `~/.penny/recovery/20261001`; no personal content
is committed. Corrected recovery guidance and recheck commands are below.

## Recovery correction — October 2, 2026

The owner authenticated the suggested system Apple Events kickstart, but macOS
rejected it with error150 because System Integrity Protection is engaged. The
previous diagnosis of an authentication-only gate was incorrect. Do not retry
this protected-service command, disable SIP, or reset TCC.

Fresh read-only probes show Notes account access succeeds while Finder-window
and Reminders-list access time out; a local AppleScript succeeds. This is a mixed
provider result, not proof that all Apple Events transport is broken or repaired.
The service is running; process presence does not prove RPC responsiveness.
Private bounded probe receipts live under `~/.penny/recovery/20261002-sip-recovery/`.

Exact existing Notes marker lookups now succeed from both the agent shell and
an equivalent launchd job using installed watcher environment; both outstanding
note effects return zero matches in their requested folders. The failed row and
older synthetic quarantined row remain unchanged. This proves bounded marker
absence at these observations, not delivered content or recovery of other apps.
The temporary diagnostic LaunchAgent was removed. A Mac restart is not required
for the currently reachable Notes path. Do not mark failed delivery succeeded or
reset its cap merely because the provider responds.

Recheck the exact existing Notes markers before any delivery repair. A failed
ledger row keeps Doctor unready even when a basic provider probe succeeds;
Doctor's provider_failure is a durable-state classification, not a live RPC test.
Preserve capped and quarantined history. Do not create duplicate notes or reset
uncertain effects based on an empty UI search or successful account query.

If target-provider calls remain stuck in the installed launchd context, a normal
macOS restart is the next supported recovery candidate, not a proven fix. First
coordinate the Mac's shared ASR consumers and any active work; do not restart this
shared machine automatically. After saving work and draining/checkpointing
consumers, the owner can use Apple menu > Restart. Recheck provider calls, model
owner, installed agents and exact effect receipts after login before resuming
admission. No restart has been authorized or performed by this correction.

Apple references:
[System Integrity Protection](https://support.apple.com/en-gb/102149) and
[restart a Mac](https://support.apple.com/en-au/guide/mac-help/mchlp2522/mac).

```bash
curl -fsS http://127.0.0.1:10311/health
venv/bin/python scripts/penny_doctor.py --json
```

Doctor's command needs the installed launchd environment for equivalent shared
ASR authentication. Load it locally without printing its credential values.
Private diagnostic scripts/receipts already capture that equivalent context.
Historical exceptions remain visible; readiness is not manufactured by removing
failure rows. Pending new natural Penny capture and sustained memory remain open.
