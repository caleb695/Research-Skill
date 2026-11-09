---
name: ai-infinite-skill
description: >-
  Repository entry point for a single-purpose Infinite skill. Use when the user
  says "use this skill", "use infinite", "use the infinite skill", or "/infinite".
  It runs one fixed bundled Book of Mormon evidence-research prompt without
  requiring task arguments. Six code-enforced steps per evidence item (source
  authentication, full context/POV, multiple sources with cited corroboration,
  counters, ranked scores with reasons, extensive investigation), alternating
  for/against rounds, deduplication, cross-side evaluation, and three ranked
  final reports on stop — for, against, and head-to-head comparison — mirrored
  to Google Docs through the Google Workspace CLI (gws) or a built-in REST
  transport — including a phone-only device-code login. It does not accept a
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
  version: "1.4.0"
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

1. Initialize the durable research ledger and three working reports (for,
   against, comparison).
2. Alternate **for → against → for → against** rounds until an explicit user stop.
3. Execute all six coded prompt steps for every item — the ledger helper rejects
   partial work: (1) authenticate with at least three recorded checks,
   (2) record full context and POV, (3) check multiple sources from independent
   chains and cite multiple pieces of evidence, (4) evaluate the strongest
   counters, (5) record credibility/accuracy/relevance/usefulness ratings with
   specific reasons plus the one computed overall score (witnesses are capped —
   weighed less), and (6) record the extensive investigation (queries, sources
   consulted, leads ruled out, depth). Scores are not truth probabilities.
4. Deduplicate by underlying observation, revise instead of repeating, and
   evaluate every item against the strongest opposing evidence or alternative;
   linked contradictions render head-to-head in the comparison report.
5. Use reliable primary/scholarly sources; exclude Wikipedia, Reddit, Quora,
   anonymous posts, and AI summaries as evidence. Biased sources are leads only
   (`role: lead-only`) and never count as evidence. Label bias and dependence.
6. When novelty dries up, deepen primary-text/dependency work and revisit uncertain
   and confident claims. Log blocked searches honestly; never invent findings.
7. On stop, cease research and compile `research/book-of-mormon-for.md`,
   `research/book-of-mormon-against.md`, and
   `research/book-of-mormon-comparison.md`, with overall/category claim rankings
   and ranked evidence; sync all three to the user's Google Docs
   (`google_docs.py sync --mode final`). Final validation fails until the
   Google Docs are current. Present all three before finishing.

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
| [`infinite/references/google-docs.md`](infinite/references/google-docs.md) | Google Docs deliverables, gws CLI setup, sync |
| [`infinite/references/openhands-cloud.md`](infinite/references/openhands-cloud.md) | Cloud loading, portable hooks, limits |
| [`infinite/references/openhands-enforcement.md`](infinite/references/openhands-enforcement.md) | Deterministic user-owned enforcement |

Install the complete package with Book of Mormon enforcement enabled by default:

```bash
bash infinite/scripts/install-openhands-hooks.sh --dir . --install-skill
```

The research side is enforced by hooks, not only by prose: a built-in Stop
validator, helper-only ledger/report writes, and user-only stop/resume control.
Use `--no-arm` to install standby hooks that arm on `use this skill`.

Run installation before starting the OpenHands conversation. The agent must not
edit or bypass user-owned enforcement. See the README for Cloud import options.
