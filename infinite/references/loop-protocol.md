# Loop protocol — durable state for long research runs

Keep the loop in files so context compaction, a new conversation, or an iteration
cap does not erase findings. For Book of Mormon research, follow this protocol
with `book-of-mormon-research.md` and `evidence-schema.md`; for other tasks use
the generic audit/improve/verify round.

## Where state lives

```text
<project>/.infinite/
├── state.json       round, profile, next side/target, dry-round count
└── ledger.jsonl     append-only rounds, evidence revisions, claims, searches, notes

<project>/research/
├── book-of-mormon-for.md
└── book-of-mormon-against.md

<project>/.openhands/guard/   user-owned enforcement state
├── config.json       mirror of the loaded policy
├── attempts.json     finish-attempt history
├── DISARMED          generic stop or user override
├── STOP_REQUESTED    research stop; final reports still required
└── events.jsonl      arm/disarm/deny audit trail
```

`.infinite/` is scratch state; keep it out of Git unless the user explicitly wants
the raw ledger preserved. The two Markdown reports are deliverables. Never commit
`.openhands/guard/`. Hook wiring may be committed when the user wants it to travel
with the repo; use the installer's portable relative commands.

## Initialize and log

```bash
python3 infinite/scripts/infinite_research.py --dir . init
python3 infinite/scripts/infinite_state.py --dir . status
python3 infinite/scripts/infinite_research.py --dir . status
```

Replace `infinite/scripts` with the actual loaded skill's script directory. `init`
is idempotent: it preserves the round, next side, and existing findings.

A completed research round uses the state helper:

```bash
python3 infinite/scripts/infinite_state.py --dir . log \
  --side against --outcome accepted --evidence-id A001 \
  --target "Check the strongest objection to the previous item" \
  --change "Added A001 after primary-source and context checks" \
  --verification "Locator/provenance checked; helper validate passed" \
  --next "Return to the for side and test the reply to A001"
```

Sides must alternate `for → against → for`, including rejected, blocked, and
no-new rounds. Outcomes are `accepted`, `revised`, `rejected`, `deepened`,
`blocked`, `no-new`. Accepted/revised/deepened rounds require an evidence ID. Every round
requires verification actually performed and a next target. The helper advances
the side and tracks consecutive nonproductive rounds; three triggers deeper
primary work and six triggers review of uncertain and confident claims.

Research events are appended by `infinite_research.py evidence|revise|claim|search|
note`. A revision keeps the same ID and updates the current record; it is not a
new piece of evidence. Compile and validate after logging:

```bash
python3 infinite/scripts/infinite_research.py --dir . compile
python3 infinite/scripts/infinite_research.py --dir . validate
```

A round record looks like:

```json
{"ts":"2026-11-07T23:00:00+00:00","event":"round","round":7,"profile":"book-of-mormon","side":"against","outcome":"accepted","evidence_id":"A001","target":"primary-source objection","change":"added A001","verification":"original and context checked; validator passed","next":"for-side reply","notes":"source chain mapped"}
```

Append only. Never rewrite history to look better. If a source was wrong, append
a revision and keep the rejected/corrected trail. Do not log a check you did not
perform. If scripts are unavailable, maintain the same fields by hand and keep
the two reports current; do not silently drop findings.

## Resuming

On `continue`, `/infinite`, compaction, or a new run:

1. Read `state.json`, recent ledger events, and both reports.
2. Run the research validator; repair stale reports or broken references from the
   ledger before adding new findings.
3. If a prior user stop was recorded and the user now explicitly continues, run
   `infinite_state.py resume` and compile a new interim snapshot.
4. Continue at `round + 1` with the recorded next side and target. Do not restart
   numbering, re-announce the task, or duplicate evidence already registered.
5. Re-check access limits; a previously blocked source is a new route to try, not
   permission to repeat an identical failing command.

If no state exists but the user's instruction still holds, reconstruct what can be
supported from the conversation and mark uncertain reconstructions explicitly.

## When the user says stop

1. Stop searching immediately. Finish only the current atomic file write.
2. Do not start another research round. Reconcile recorded findings, duplicates,
   corrections, and claim links.
3. Run `infinite_research.py compile --final`, then `validate --final`. With the
   research hook installed, the user's stop message creates `STOP_REQUESTED`; the
   Stop gate checks the final reports and allows finishing when they pass. The
   user's installer `--disarm` is an override, not an agent action.
4. Present both reports and a short closing summary: strongest claims each side,
   category coverage, decisive uncertainties, rejected leads, access limits, and
   resume instructions. This is the one time a final summary is appropriate.
5. A later explicit continue resumes from the ledger; it does not erase history.

For a generic non-research task, a stop disarms immediately; finish the atomic
step, run checks, and summarize. Never try to disarm research enforcement yourself.

## Checkpoints and anti-patterns

- Leave each round with valid ledger/report state; commit checkpoints when the
  user asked for repository changes and it is safe to do so.
- Never force-push shared history, commit secrets, or publish without permission.
- Do not store the only copy of findings in conversation memory.
- Do not repeat identical failing searches/commands; change source class or route.
- Do not invent evidence to reset the dry-round counter or satisfy a gate.
- Do not treat a generated report as authentication. The citations and recorded
  checks must support every entry.
