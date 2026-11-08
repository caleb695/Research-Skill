---
name: ai-infinite-skill
description: >-
  Repository entry point for a single-purpose Infinite skill. Use when the user
  says "use this skill", "use infinite", "use the infinite skill", or "/infinite".
  It runs one fixed bundled Book of Mormon evidence-research prompt without
  requiring task arguments: source authentication, context/POV checks, alternating
  for/against rounds, one overall evidence score, deduplication, cross-side
  evaluation, and two ranked final reports on stop. It does not accept a
  replacement task.
triggers:
- use this skill
- use the infinite skill
- use infinite skill
- use infinite
- /infinite
license: MIT
compatibility: OpenHands Cloud, Agent Canvas, CLI, SDK, Claude Code, and Agent Skills clients. Canonical package is infinite/; project discovery launcher is .agents/skills/infinite/SKILL.md.
metadata:
  author: caleb695
  version: "1.2.0"
  canonical: infinite/SKILL.md
---

# Infinite — repository entry point

The canonical, self-contained skill is [`infinite/SKILL.md`](infinite/SKILL.md).
Read it in full before starting, then read the references it names. This root
file is a pointer for clients that read a repository-level skill; OpenHands
project discovery uses [`.agents/skills/infinite/SKILL.md`](.agents/skills/infinite/SKILL.md),
which launches the same canonical package.

## Fixed-task contract in brief

The user only has to say `use this skill`, `use infinite`, `use the infinite
skill`, or `/infinite`. The authoritative task is
[`infinite/references/fixed-task.md`](infinite/references/fixed-task.md); arguments
do not replace it. Then:

1. Initialize the durable research ledger and two working reports.
2. Alternate **for → against → for → against** rounds until an explicit user stop.
3. Authenticate each item, read full context and POV, investigate deeply, and
   record credibility/accuracy/relevance/usefulness ratings with reasons. The
   helper computes one overall score; scores are not truth probabilities.
4. Deduplicate by underlying observation, revise instead of repeating, and
   evaluate every item against the strongest opposing evidence or alternative.
5. Use reliable primary/scholarly sources; exclude Wikipedia, Reddit, Quora,
   anonymous posts, and AI summaries as evidence. Label bias and dependence.
6. When novelty dries up, deepen primary-text/dependency work and revisit uncertain
   and confident claims. Log blocked searches honestly; never invent findings.
7. On stop, cease research and compile `research/book-of-mormon-for.md` and
   `research/book-of-mormon-against.md`, with overall/category claim rankings and
   ranked evidence. Present both before finishing.

The Bible-as-true assumption is the user's stipulated premise and must be labeled.
The Book of Mormon is primary evidence of its contents, not independent proof of
its historicity. Historically documented spiritual experiences are evidence of
reported belief/experience, not automatic public verification of a supernatural
cause.

Do not run unrelated tasks from this skill. Platform iteration/budget/network
limits are checkpoint/resume boundaries, not permission to fabricate progress or
override the user.

## Resources

| Path | Purpose |
| --- | --- |
| [`infinite/SKILL.md`](infinite/SKILL.md) | Canonical round contract |
| [`infinite/references/fixed-task.md`](infinite/references/fixed-task.md) | Authoritative fixed prompt |
| [`infinite/references/book-of-mormon-research.md`](infinite/references/book-of-mormon-research.md) | Verification, context, scoring, categories, deepening |
| [`infinite/references/evidence-schema.md`](infinite/references/evidence-schema.md) | Ledger records and helper commands |
| [`infinite/references/loop-protocol.md`](infinite/references/loop-protocol.md) | Durable state, resume, stop/finalization |
| [`infinite/references/openhands-cloud.md`](infinite/references/openhands-cloud.md) | Cloud loading, portable hooks, limits |
| [`infinite/references/openhands-enforcement.md`](infinite/references/openhands-enforcement.md) | Optional user-owned enforcement |

Install the complete package and optional research enforcement with:

```bash
bash infinite/scripts/install-openhands-hooks.sh --dir . --research --install-skill
```

Run installation before starting the OpenHands conversation. The agent must not
edit or bypass user-owned enforcement. See the README for Cloud import options.
