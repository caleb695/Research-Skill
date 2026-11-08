# Research-Skill — Infinite evidence research

An [Agent Skills](https://docs.openhands.dev/overview/skills) package that runs
**one fixed task only**: the complete Book of Mormon evidence-research prompt
bundled in [`infinite/references/fixed-task.md`](infinite/references/fixed-task.md).
The user should basically only have to say:

```text
use this skill
```

or `/infinite`. No long prompt or task arguments are required. The skill does not
accept a replacement task and does not fall back to generic coding/improvement
work.

Compatible with OpenHands Cloud, Agent Canvas, CLI, SDK, Claude Code, and clients
that read `SKILL.md`. Helpers use only the Python 3 standard library;
enforcement hooks use bash.

## What the research skill does

Each round alternates **for → against → for → against** and:

1. Checks for a real user stop and restores the durable ledger.
2. Picks one high-value evidence gap, objection, or weak citation.
3. Authenticates the candidate against primary/scholarly sources.
4. Reads full textual/historical context and identifies POV, incentives,
   dependencies, and missing facts.
5. Deduplicates by underlying observation; revisions do not count as new items.
6. Rates credibility, accuracy, relevance, and usefulness with reasons, then
   computes one overall Evidence Impact Score. Fabricated items score zero;
   unresolved/disputed provenance is capped and quarantined.
7. Evaluates the item against the strongest opposing evidence or alternative.
8. Records searches/access limits, logs the round, compiles both reports, and
   validates before continuing.

The Bible-as-true assumption is treated as the user's stipulated premise and
labeled in both reports. The Book of Mormon is a primary source for its contents,
not independent proof of its historicity. Historically documented spiritual
experiences are handled as evidence of reported experience/belief, not automatic
public verification of a supernatural cause.

Wikipedia, Reddit, Quora, anonymous posts, social-media assertions, and AI
summaries are not evidence. LDS-affiliated and critical sources are not excluded
by label; their provenance, independence, data, and interpretation are checked.
Scores are ordinal research judgments—not probabilities of truth—and item counts
are never treated as weight.

When new items dry up, the skill deepens: primary-text comparison, footnote
tracing, chronology reconstruction, dependency mapping, and revisiting both
uncertain and confident claims. Original synthesis is labeled as such. A blocked
or fruitless search is logged honestly; findings are never invented to keep the
loop moving.

## Deliverables and stop behavior

The helper maintains two separate documents:

```text
research/book-of-mormon-for.md
research/book-of-mormon-against.md
```

Each contains overall and within-category claim rankings, category rankings,
ranked canonical evidence with component ratings, provenance/context/POV checks,
opposing-evidence evaluations, assumptions, limitations, rejected/quarantined
leads, search coverage, and original synthesis. Evidence shared by several claims
is listed once and referenced by ID.

Say **`stop`** to end research. The skill then stops searching and compiles both
final reports from recorded findings. With research enforcement, the user-stop
hook requests finalization and the built-in validator blocks finishing only until
the reports are valid; it does not order more research. Say `continue` later to
resume from the ledger at the next round and side.

## Install and use

```bash
git clone https://github.com/caleb695/Research-Skill
cd Research-Skill

# Complete skill + Book of Mormon enforcement (default). Run before the conversation.
bash infinite/scripts/install-openhands-hooks.sh --dir . --install-skill

# Or install standby hooks that arm when you say "use this skill":
bash infinite/scripts/install-openhands-hooks.sh --dir . --install-skill --no-arm
```

The self-contained package installs to `.agents/skills/infinite/`. Trigger it
with only:

```text
use this skill
```

### OpenHands Cloud

- Use this repository as the conversation workspace: the project launcher at
  `.agents/skills/infinite/SKILL.md` points to the canonical `infinite/` package.
- Or import/load the Git-hosted `infinite/` directory as a skill/plugin and select
  `infinite` for the conversation.
- For enforcement, run the installer before the conversation and commit the
  generated `.openhands/hooks.json` plus hook scripts if you want the wiring to
  travel with the repo. Keep `.openhands/guard/` and `.infinite/` scratch state
  out of Git. Start a new conversation after installing/changing skills or hooks.

Hook commands are repo-relative, not tied to the installer's checkout path, and
the Stop hook timeout is derived from its gate budgets. See
[`infinite/references/openhands-cloud.md`](infinite/references/openhands-cloud.md)
for the checked Cloud contract and the remaining live-deployment smoke test.

## Durable state and helpers

```text
.infinite/state.json     round, profile, next side/target, dry-round count
.infinite/ledger.jsonl   append-only rounds, evidence revisions, claims, searches
research/*.md            generated two-report deliverables
```

```bash
python3 infinite/scripts/infinite_research.py --dir . init
python3 infinite/scripts/infinite_research.py --dir . status
python3 infinite/scripts/infinite_research.py --dir . validate
python3 infinite/scripts/infinite_state.py --dir . status
```

Record formats and the full command sequence are in
[`infinite/references/evidence-schema.md`](infinite/references/evidence-schema.md).
The validator checks structure, scoring math, duplicate keys, references,
alternation, and report freshness. It cannot authenticate history or guarantee
that prose is fair; the recorded sources and checks are the audit trail.

## Deterministic enforcement

The Mormon side is not just prompting. The user-owned guard installs Stop,
PreToolUse, and UserPromptSubmit hooks. The Stop hook has a built-in research
validator that cannot be removed with `--no-gates`; PreToolUse requires
helper-only ledger/report writes and blocks premature final reports; only a real
user message can stop or resume. While active, the agent cannot elect to finish
or disable enforcement. The user can always override from their own terminal:

```bash
bash infinite/scripts/install-openhands-hooks.sh --dir . --status
bash infinite/scripts/install-openhands-hooks.sh --dir . --disarm
bash infinite/scripts/install-openhands-hooks.sh --dir . --uninstall
```

Details and limits:
[`infinite/references/openhands-enforcement.md`](infinite/references/openhands-enforcement.md).
Do not arm hooks in a shared repository without the owner's knowledge.

## Limits, honestly

- The skill does not grant web access. Host restrictions, missing browsers,
  paywalls, and rate limits are recorded and worked around with accessible
  sources; blocked checks are never pretended.
- OpenHands still enforces iteration, budget, context, and stuck-detection limits.
  The ledger makes those boundaries resumable; “infinite” means the agent does
  not elect to stop, not that it can override the platform or user.
- Scores and category ceilings are transparent comparative judgments, not a
  mathematical proof or probability of truth.
- Compatibility was checked against current OpenHands docs/SDK source and local
  contract/relocation tests; a live hosted Cloud conversation was not run here.

## Repository layout

```text
Research-Skill/
├── .agents/skills/infinite/SKILL.md   Cloud/project discovery launcher
├── infinite/                         canonical self-contained skill
│   ├── SKILL.md
│   ├── commands/infinite.md
│   ├── references/                   fixed-task, research, schema, loop, Cloud, enforcement
│   ├── scripts/                      ledger/state/guard/hooks/installer
│   └── assets/
├── tests/smoke.sh                    generic enforcement/install checks
├── tests/openhands_compat.py         loader + hook contract checks
├── tests/test_research.py            research mechanics + Cloud relocation
└── SKILL.md                          repository-level pointer
```

## Development

```bash
bash tests/smoke.sh
python3 tests/openhands_compat.py
python3 tests/test_research.py
```

## License

MIT — see [LICENSE](LICENSE).
