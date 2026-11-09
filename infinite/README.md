# infinite — Book of Mormon evidence research

A single-purpose Infinite skill. It runs one fixed bundled prompt: keep
researching evidence for and against the Book of Mormon until the user says stop,
then compile three ranked reports (for, against, head-to-head comparison) mirrored
to Google Docs. The user only has to say `use this skill` or
`/infinite`; no task arguments are required or accepted as a replacement task.

## Trigger

`use this skill`, `use infinite`, `use the infinite skill`, or `/infinite`.
These start or resume the fixed prompt in `references/fixed-task.md`.

## Research round

1. Check for an explicit user stop; otherwise restore the ledger and next side.
2. Alternate **for → against → for → against**, even after rejected/blocked rounds.
3. Pick one high-value evidence gap or objection; search reliable sources.
4. Authenticate the item, read full context/POV, and investigate the strongest
   reply and disconfirming evidence.
5. Deduplicate by underlying observation; rate credibility, accuracy, relevance,
   and usefulness with reasons; compute one overall Evidence Impact Score.
6. Compare against the other side, record evidence/claim/search events, log the
   round, compile all three reports, sync Google Docs, validate, and continue.

Three nonproductive rounds trigger deeper primary-text/dependency work; six
trigger review of uncertain and confident claims. Original synthesis is labeled
as such, not passed off as a new historical discovery. Blocked access is logged,
never fabricated.

## Files

- `SKILL.md` — canonical contract.
- `references/fixed-task.md` — authoritative fixed prompt.
- `references/book-of-mormon-research.md` — source standards, context, rubric,
  category playbook, adversarial comparison, deepening.
- `references/evidence-schema.md` — JSON records and helper commands.
- `references/loop-protocol.md` — durable state, resume, stop/finalization.
- `references/google-docs.md` — Google Docs deliverables, Google Cloud Console
  phone-only device-code login, `gws` CLI install/auth walkthrough, sync commands, enforcement.
- `references/openhands-cloud.md` — Cloud loading and portability checks.
- `references/openhands-enforcement.md` — deterministic user-owned hooks.
- `scripts/infinite_research.py` — stdlib ledger, scoring, dedup, validator, and
  three-report compiler with the six-step evidence validator.
- `scripts/google_docs.py` — stdlib Google Docs mirror that publishes the three
  reports through the Google Workspace CLI (`gws`) when installed, else direct
  Google Docs/Drive REST calls (device-code `login` supported for phone-only
  users); writes the sync receipt the final validator requires.
- `scripts/infinite_state.py` — round cursor, alternating side, dry-round count.
- `scripts/infinite_guard.py` and hook dispatchers — deterministic enforcement.

The workspace receives `.infinite/` scratch state and three deliverables:
`research/book-of-mormon-for.md`, `research/book-of-mormon-against.md`, and
`research/book-of-mormon-comparison.md` — all three mirrored to Google Docs
published through the user's own Google authentication (`gws` CLI or the
helper's built-in REST transport).

## Install

```bash
# complete skill + Book of Mormon enforcement (default); run before the conversation
bash infinite/scripts/install-openhands-hooks.sh --dir . --install-skill

# standby hooks: arm later by saying "use this skill" or "/infinite"
bash infinite/scripts/install-openhands-hooks.sh --dir . --install-skill --no-arm
```

The canonical package installs to `.agents/skills/infinite/`. OpenHands Cloud can
also load `infinite/` directly as a Git-hosted skill/plugin; this repository ships
a project launcher at `.agents/skills/infinite/SKILL.md` for workspace discovery.
Hook commands are repo-relative so a Cloud checkout path does not break them.

## Use

```text
use this skill
```

Say `stop` to end research and compile all three final reports plus the final
Google Docs sync. With research hooks,
the stop message requests finalization and the built-in gate waits for valid final
reports rather than ordering more research. The agent cannot hand-edit the ledger
or reports, compile final reports before the stop, or disarm itself. Say
`continue` later to resume from the ledger.

## Requirements and limits

Python 3 standard library for helpers; bash for enforcement hooks; an agent with
web/browser access for online research. The Google Docs deliverables need a
one-time user authentication: either the Google Workspace CLI
(`npm install -g @googleworkspace/cli` then `gws auth login`), or — with no CLI
and no computer — `google_docs.py login` (device-code flow approved from a
phone; see `references/google-docs.md`). The skill never displays or transmits
credentials. The skill does not grant network access. OpenHands iteration/budget/context limits still apply;
checkpoint and resume. Scores are ordinal research judgments, not probabilities
of truth. The validator checks structure and consistency, not historical
reality.

## License

MIT
