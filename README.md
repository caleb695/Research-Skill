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
3. Executes the fixed prompt's six per-item steps, each **enforced in code** by
   the ledger helper's schema (partial or shallow records are rejected):
   (1) authenticate with at least three substantive recorded checks;
   (2) record full textual/historical context, POV, incentives, dependencies,
   and missing facts; (3) check multiple sources from at least two independent
   chains and cite at least two distinct pieces of evidence in a corroboration
   block (biased/discovery sources are `lead-only` and cannot carry an item);
   (4) evaluate the strongest counters with a substantive analysis;
   (5) rate credibility, accuracy, relevance, and usefulness with specific
   reasons, plus one computed overall Evidence Impact Score (fabricated items
   score zero; unresolved/disputed provenance is capped and quarantined;
   witnesses are capped — the prompt weighs them less); (6) record the extensive
   investigation: queries run, sources consulted, leads ruled out, depth.
4. Deduplicates by underlying observation; revisions do not count as new items.
5. Evaluates the item against the strongest opposing evidence or alternative and
   links opposite-side IDs so contradictions render head-to-head.
6. Records searches/access limits, logs the round, compiles all three reports,
   syncs the Google Docs mirror, and validates before continuing.

The Bible-as-true assumption is treated as the user's stipulated premise and
labeled in all three reports. The Book of Mormon is a primary source for its contents,
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

The helper maintains three separate documents:

```text
research/book-of-mormon-for.md
research/book-of-mormon-against.md
research/book-of-mormon-comparison.md
```

The for and against reports each contain overall and within-category claim
rankings, category rankings, ranked canonical evidence with component ratings,
provenance/context/POV checks, opposing-evidence evaluations, assumptions,
limitations, rejected/quarantined leads, search coverage, and original synthesis.
Evidence shared by several claims is listed once and referenced by ID. The
comparison report is "one document with everything": direct contradictions where
opposing for/against points are shown head-to-head with both counter-analyses
and scores, claim and category face-offs, and the full combined register.

### Google Docs (via the Google Workspace CLI)

The deliverables are Google Documents, not just local Markdown.
`infinite/scripts/google_docs.py` creates and syncs three Google Docs (FOR,
AGAINST, COMPARISON) through the **Google Workspace CLI**
([github.com/googleworkspace/cli](https://github.com/googleworkspace/cli)),
which you install and authenticate once — `gws` owns all credentials, the skill
never handles tokens or secrets:

```bash
npm install -g @googleworkspace/cli   # or brew install googleworkspace-cli
gws auth setup                        # creates the Cloud project + OAuth client (needs gcloud)
gws auth login                        # or manual Console setup / exported credentials for headless
python3 infinite/scripts/google_docs.py --dir . setup   # creates the three Docs
```

Headless alternative: `gws auth export --unmasked > credentials.json` on a
browser machine, then `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/path/to/credentials.json`.
Full walkthrough (including the manual Google Cloud Console links):
[`infinite/references/google-docs.md`](infinite/references/google-docs.md).
`compile` auto-syncs whenever `gws` is authenticated, and **final validation
fails until all three Google Docs are synced at the final ledger digest** — the
run cannot finish on local files alone.

Say **`stop`** to end research. The skill then stops searching, compiles all
three final reports from recorded findings, and syncs the final Google Docs.
With research enforcement, the user-stop hook requests finalization and the
built-in validator blocks finishing only until the reports and Google Docs are
valid; it does not order more research. Say `continue` later to resume from the
ledger at the next round and side.

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
.infinite/gdocs.json     Google Docs receipt: document IDs/URLs + last sync digest
research/*.md            generated three-report deliverables (+ Google Docs mirror)
```

```bash
python3 infinite/scripts/infinite_research.py --dir . init
python3 infinite/scripts/infinite_research.py --dir . status
python3 infinite/scripts/infinite_research.py --dir . validate
python3 infinite/scripts/infinite_state.py --dir . status
python3 infinite/scripts/google_docs.py --dir . setup   # once, after installing + authenticating the gws CLI
python3 infinite/scripts/google_docs.py --dir . status
```

Record formats and the full command sequence are in
[`infinite/references/evidence-schema.md`](infinite/references/evidence-schema.md).
The validator checks structure, the six coded prompt steps with their substance
thresholds, scoring math and caps, duplicate keys, references, alternation,
report freshness for all three reports, and the Google Docs sync receipt. It
cannot authenticate history or guarantee that prose is fair; the recorded sources
and checks are the audit trail.

## Deterministic enforcement

The Mormon side is not just prompting. The user-owned guard installs Stop,
PreToolUse, and UserPromptSubmit hooks. The Stop hook has a built-in research
validator that cannot be removed with `--no-gates`; PreToolUse requires
helper-only ledger/report writes and blocks premature final reports or premature
final Google Docs syncs; only a real user message can stop or resume. While active, the agent cannot elect to finish
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
│   ├── references/                   fixed-task, research, schema, loop, Google Docs, Cloud, enforcement
│   ├── scripts/                      ledger/state/guard/google-docs/hooks/installer
│   └── assets/
├── tests/smoke.sh                    generic enforcement/install checks
├── tests/openhands_compat.py         loader + hook contract checks
├── tests/test_research.py            research mechanics + Cloud relocation
├── tests/test_gdocs.py               Google Docs converter/credential checks (offline)
└── SKILL.md                          repository-level pointer
```

## Development

```bash
bash tests/smoke.sh
python3 tests/openhands_compat.py
python3 tests/test_research.py
python3 tests/test_gdocs.py
```

## License

MIT — see [LICENSE](LICENSE).
