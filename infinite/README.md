# infinite — Book of Mormon evidence research

An Infinite skill specialized for the request: keep researching evidence for and
against the Book of Mormon until the user says stop, then compile two ranked
reports. It retains the generic audit/improve/verify loop for unrelated tasks.

## Trigger

`/infinite`, `/forever`, `/never-stop`, `Book of Mormon`, `indefinitely research`,
or phrases such as “never stop,” “keep going,” and “until I say stop.”

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
- `references/book-of-mormon-research.md` — source standards, context, rubric,
  category playbook, adversarial comparison, deepening.
- `references/evidence-schema.md` — JSON records and helper commands.
- `references/loop-protocol.md` — durable state, resume, stop/finalization.
- `references/openhands-cloud.md` — Cloud loading and portability checks.
- `references/openhands-enforcement.md` — optional user-owned hooks.
- `scripts/infinite_research.py` — stdlib ledger, scoring, dedup, validator, and
  two-report compiler.
- `scripts/infinite_state.py` — round cursor, alternating side, dry-round count.
- `scripts/infinite_guard.py` and hook dispatchers — optional enforcement.

The workspace receives `.infinite/` scratch state and two deliverables:
`research/book-of-mormon-for.md` and `research/book-of-mormon-against.md`.

## Install

```bash
# complete skill + research enforcement; run before starting the conversation
bash infinite/scripts/install-openhands-hooks.sh --dir . --research --install-skill

# skill only, no enforcement
bash infinite/scripts/install-openhands-hooks.sh --dir . --install-skill --no-arm
```

The canonical package installs to `.agents/skills/infinite/`. OpenHands Cloud can
also load `infinite/` directly as a Git-hosted skill/plugin; this repository ships
a project launcher at `.agents/skills/infinite/SKILL.md` for workspace discovery.
Hook commands are repo-relative so a Cloud checkout path does not break them.

## Use

```text
/infinite Research evidence for and against the Book of Mormon until I say stop.
Verify every item, read full context, score it, compare both sides, avoid repeats,
and keep the two reports current.
```

Say `stop` to end research and compile both final reports. With research hooks,
the stop message requests finalization and the gate waits for valid final reports
rather than ordering more research. Say `continue` later to resume from the ledger.

## Requirements and limits

Python 3 standard library for helpers; bash for optional hooks; an agent with
web/browser access for online research. The skill does not grant network access.
OpenHands iteration/budget/context limits still apply; checkpoint and resume.
Scores are ordinal research judgments, not probabilities of truth. The validator
checks structure and consistency, not historical reality.

## License

MIT
