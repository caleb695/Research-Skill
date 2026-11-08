# infinite — Book of Mormon evidence research

A single-purpose Infinite skill. It runs one fixed bundled prompt: keep
researching evidence for and against the Book of Mormon until the user says stop,
then compile two ranked reports. The user only has to say `use this skill` or
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
   round, compile both reports, validate, and continue.

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
- `references/openhands-cloud.md` — Cloud loading and portability checks.
- `references/openhands-enforcement.md` — deterministic user-owned hooks.
- `scripts/infinite_research.py` — stdlib ledger, scoring, dedup, validator, and
  two-report compiler.
- `scripts/infinite_state.py` — round cursor, alternating side, dry-round count.
- `scripts/infinite_guard.py` and hook dispatchers — deterministic enforcement.

The workspace receives `.infinite/` scratch state and two deliverables:
`research/book-of-mormon-for.md` and `research/book-of-mormon-against.md`.

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

Say `stop` to end research and compile both final reports. With research hooks,
the stop message requests finalization and the built-in gate waits for valid final
reports rather than ordering more research. The agent cannot hand-edit the ledger
or reports, compile final reports before the stop, or disarm itself. Say
`continue` later to resume from the ledger.

## Requirements and limits

Python 3 standard library for helpers; bash for enforcement hooks; an agent with
web/browser access for online research. The skill does not grant network access.
OpenHands iteration/budget/context limits still apply; checkpoint and resume.
Scores are ordinal research judgments, not probabilities of truth. The validator
checks structure and consistency, not historical reality.

## License

MIT
