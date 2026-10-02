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
is committed. Next commands and the remaining authentication gate are below.

## Next executable gate

The owner must authenticate the system-service restart on the Mac because the
agent's noninteractive sudo cannot obtain that authentication:

```bash
sudo launchctl kickstart -k system/com.apple.coreservices.appleevents
```

This restarts Apple Events transport, leaving existing TCC privacy permissions
unchanged. It may briefly interrupt Apple Events from other applications. Do not
reset TCC or change accounts. If this does not recover read-only provider calls,
inspect the current service/app stacks before proposing a coordinated login or
machine restart. No restart was reported as successful.

After authentication, the agent rechecks the exact installed Penny Notes marker
lookup before touching the failed effect. Provider absence/presence and durable
payload identity must be established; do not blindly reset capped/quarantined rows.
The synthetic quarantine remains preserved. A normal note receipt, canonical
ledger, archive and downstream effects must be reported independently.

```bash
curl -fsS http://127.0.0.1:10311/health
venv/bin/python scripts/penny_doctor.py --json
```

Doctor's command needs the installed launchd environment for equivalent shared
ASR authentication. Load it locally without printing its credential values.
Private diagnostic scripts/receipts already capture that equivalent context.
Historical exceptions remain visible; readiness is not manufactured by removing
failure rows. Pending new natural Penny capture and sustained memory remain open.
