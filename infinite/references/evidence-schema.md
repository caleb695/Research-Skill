# Evidence ledger and report schema

The helper is `scripts/infinite_research.py` (Python 3 standard library). It is
the **code enforcement of the fixed prompt's six steps**: every evidence record
must carry each step with recorded substance, or the only write path into the
ledger rejects it. The helper checks structure, consistency, and depth
thresholds; it cannot tell whether a source is truthful. The agent must perform
and record the actual research before using these commands.

## Six-step contract (coded)

| Prompt step | Required fields | Enforced floor |
| --- | --- | --- |
| 1. Check the evidence is real | `authenticity.verdict/checks/limitations` | ≥ 3 checks, each ≥ 30 chars; limitations ≥ 20 chars |
| 2. Context and POV | `context.textual/historical/pov/missing_facts` | each ≥ 80 chars |
| 3. Multiple sources, multiple cited pieces | `sources[]` (+`role`), `corroboration.cross_checks/cited_evidence[]` | verified items: ≥ 2 evidence-role sources from ≥ 2 independence groups; ≥ 2 cited pieces from ≥ 2 distinct sources; cross-check prose ≥ 60 chars; `lead-only` sources never count |
| 4. Counters | `counter_evaluation.analysis/opposing_ids/source_ids` | analysis ≥ 120 chars; `source_ids` non-empty |
| 5. Rankings | `scores` (4 dims), `score_reasons`, computed `overall_score` | each reason ≥ 30 chars; formula + provenance caps; `witnesses` category capped at 69 ("weighed less!") |
| 6. Extensive investigation | `investigation.queries/sources_consulted/rejected_leads/depth` | ≥ 2 queries (each ≥ 8 chars); sources_consulted ≥ 2; rejected_leads ≥ 40 chars; depth ≥ 80 chars |

Thresholds live as `MIN_*` constants at the top of the helper. Quarantined items
(`disputed`/`unverified`/`fabricated`) keep every depth requirement but may rest
on a single source and a single cited piece — that is often exactly why they are
quarantined.

## Workspace and commands

Run from the project workspace, replacing `infinite/scripts` with the loaded
skill's actual script directory when installed elsewhere:

```bash
H=infinite/scripts/infinite_research.py
python3 "$H" --dir . init
python3 "$H" --dir . status
python3 "$H" --dir . lookup "exact claim, names, or primary locator"

# Write one JSON object to a scratch file, then record it.
python3 "$H" --dir . evidence --file .infinite/candidate.json
python3 "$H" --dir . revise --file .infinite/candidate.json   # same evidence ID
python3 "$H" --dir . claim --file .infinite/claim.json
python3 "$H" --dir . search --side for --query "..." --outcome no-new \
  --notes "Databases, date range, access failures, and what was ruled out." \
  --url "https://consulted-source.example/article"
python3 "$H" --dir . note --side against --kind method-limit --text "..."

# Log the round with the generic state helper, then checkpoint all three reports.
python3 infinite/scripts/infinite_state.py --dir . log \
  --side for --outcome accepted --evidence-id F001 \
  --target "Check the primary source for claim X" \
  --change "Added F001 with provenance and context checks" \
  --verification "Original located; wording and locator checked; validator passed" \
  --next "Investigate the strongest against-side objection to X"
python3 "$H" --dir . compile     # also mirrors to Google Docs via gws when authenticated
python3 "$H" --dir . validate
```

`init` preserves an existing round cursor. `evidence` rejects an existing ID or a
matching normalized identity/alias; use `revise` for corrections or stronger
sources. `claim` is an upsert by claim ID. Revisions append events and do not
increase the canonical evidence count. Lookup uses token overlap only; the agent
must still check synonyms, paraphrases, and shared primary locators manually.

After an actual user stop:

```bash
python3 "$H" --dir . compile --final
python3 infinite/scripts/google_docs.py --dir . sync --mode final
python3 "$H" --dir . validate --final
```

After a later user `continue` or `/infinite`:

```bash
python3 infinite/scripts/infinite_state.py --dir . resume
python3 "$H" --dir . status
python3 "$H" --dir . compile   # new interim snapshot; preserve the ledger
```

Do not use `--final` to escape the loop. With research enforcement, the
user-stop hook writes a user-owned `STOP_REQUESTED` marker; PreToolUse blocks
`compile --final` before that marker exists, and the built-in Stop gate requires
final reports whose digest matches the ledger. Ledger, state, reports, and
validating helpers are helper-only writes; hand edits are denied. `--disarm`
remains the user's emergency override.

## Evidence record

Required fields are below. The example is a **synthetic schema illustration**,
not a finding about the Book of Mormon. Replace every fixture value with checked
research. Omit `overall_score` and the helper computes it; if supplied, it must
match the formula and provenance cap exactly.

```json
{
  "id": "F001",
  "side": "for",
  "category": "bible",
  "title": "Short neutral title",
  "identity": "The underlying observation, independent of wording or conclusion",
  "aliases": ["known alternative name for the same observation"],
  "proposition": "What the checked source or artifact actually shows.",
  "inference": "Why that observation bears on the stated truth claim.",
  "assumptions": ["Bible true as the user's stipulated premise", "Other model assumptions"],
  "dependence": "Shared manuscripts, datasets, authors, informants, or assumptions.",
  "uncertainty": "What remains unknown and how it affects the inference.",
  "authenticity": {
    "verdict": "verified",
    "checks": [
      "Earliest accessible edition located with full bibliographic description",
      "Exact wording and locator compared against the original line by line",
      "Correction/retraction/forgery search performed; results recorded even when negative"
    ],
    "limitations": "Remaining provenance or transmission limits, stated explicitly."
  },
  "context": {
    "textual": "Surrounding passage/chapter, speaker, genre, translation and variants (>= 80 chars).",
    "historical": "Dates, actors, sequence, contemporary versus later records (>= 80 chars).",
    "pov": "Author/institution purpose, commitments, incentives, audience (>= 80 chars).",
    "missing_facts": "What would change the interpretation, and what remains unknown (>= 80 chars)."
  },
  "sources": [
    {
      "id": "S1",
      "title": "Checked source title",
      "reference": "Author, edition/date, publisher or archive, full citation (>= 20 chars)",
      "url": "https://example.org/checked-primary-source",
      "locator": "page, verse, figure, catalog ID, or manuscript folio",
      "accessed": "2026-11-07",
      "kind": "primary|peer-reviewed|academic|official|contemporary-account|other",
      "role": "evidence",
      "independence_group": "Stable label for the underlying source chain",
      "bias": "Institutional POV and how it was checked; not a dismissal by label",
      "verification": "What was actually compared or authenticated (>= 20 chars)",
      "excerpt": "Optional short exact excerpt actually checked"
    },
    {
      "id": "S2",
      "title": "Second independent source (verified items need >= 2 evidence-role sources from >= 2 independence groups)",
      "reference": "Full citation of the independent check (>= 20 chars)",
      "url": "https://example.org/independent-check",
      "locator": "precise locator",
      "accessed": "2026-11-07",
      "kind": "peer-reviewed",
      "role": "evidence",
      "independence_group": "A different source chain than S1",
      "bias": "Affiliation labeled and checked",
      "verification": "What was actually compared"
    }
  ],
  "corroboration": {
    "cross_checks": "How the sources were compared with each other: agreements, discrepancies, and which reading the comparison supports (>= 60 chars).",
    "cited_evidence": [
      {"source_id": "S1", "piece": "The exact passage/data cited (>= 15 chars)", "what_it_shows": "What this piece establishes (>= 15 chars)"},
      {"source_id": "S2", "piece": "Second distinct piece of evidence cited", "what_it_shows": "Its independent contribution"}
    ]
  },
  "scores": {"credibility": 80, "accuracy": 90, "relevance": 70, "usefulness": 60},
  "score_reasons": {
    "credibility": "Specific provenance/independence reason (>= 30 chars).",
    "accuracy": "Specific wording/context reason (>= 30 chars).",
    "relevance": "Specific connection to the stated proposition (>= 30 chars).",
    "usefulness": "Specific incremental/discriminating value after alternatives (>= 30 chars)."
  },
  "counter_evaluation": {
    "analysis": "Strongest opposing evidence or alternative, whether it defeats/weakens/limits the item, and residual uncertainty (>= 120 chars).",
    "opposing_ids": ["A001"],
    "source_ids": ["S1"]
  },
  "investigation": {
    "queries": ["Actual search query or primary-text route #1", "Actual search query or route #2"],
    "sources_consulted": 5,
    "rejected_leads": "Leads chased and ruled out for this item, and why (>= 40 chars).",
    "depth": "What was read in full, traced to primary sources, and cross-checked — not one website look (>= 80 chars)."
  },
  "original_synthesis": "Optional reproducible new comparison or hypothesis; not a claimed new artifact."
}
```

`role` defaults to `evidence`; mark biased/discovery-only sources `lead-only` —
they never count toward the step-3 source minimums and cannot appear in
`corroboration.cited_evidence`. The fixed prompt's "witnesses (weighed less!)"
is a hard cap: `witnesses`-category evidence and claims cannot score above 69
overall, on either side.

`opposing_ids` may be empty while the other side has no matching registered item;
the analysis and checked `source_ids` are still required. Once an opposite-side
item exists, link it by revision. IDs must refer to existing evidence on the
opposite side. Source IDs are local to the evidence record. Offline primary
sources may omit `url` but still need a full reference and precise locator.
`accessed` must be the actual access/check date, not a placeholder.

Authenticity verdicts: `verified`, `disputed`, `unverified`, `fabricated`.
Only `verified` items may support ranked claims. The others remain visible in
the quarantine/rejected appendix. A real artifact with a contested interpretation
can be `verified`; describe the interpretive dispute in context and ratings.

## Claim record

```json
{
  "id": "C001",
  "side": "for",
  "category": "bible",
  "title": "The argument being ranked",
  "statement": "Precise claim, including scope and model dependence.",
  "synthesis": "How the evidence supports the claim after objections and dependencies.",
  "evidence_ids": ["F001"],
  "assumptions": ["Explicit premises"],
  "dependence": "Which evidence items are not independent.",
  "uncertainty": "What could overturn or narrow the claim.",
  "scores": {"credibility": 75, "accuracy": 85, "relevance": 65, "usefulness": 55},
  "score_reasons": {
    "credibility": "Reason for the whole argument.",
    "accuracy": "Reason for the whole argument.",
    "relevance": "Reason for the whole argument.",
    "usefulness": "Reason for the whole argument."
  },
  "counter_evaluation": {
    "analysis": "Best opposite-side case and the resulting assessment.",
    "opposing_ids": ["A001"],
    "source_ids": []
  }
}
```

Claim evidence IDs must be same-side, existing, and verified. Put opposite-side
items in `counter_evaluation`, not in the supporting list. Claim scores judge the
whole argument; they are not sums or averages of evidence scores. Final reports
reject usable evidence that has not been organized under at least one claim.

Categories: `bible`, `book-of-mormon`, `archaeology`, `witnesses` (score-capped:
weighed less per the fixed prompt), `historical-events`, `spiritual-experiences`,
`coherence`, `probability`, and `other` (the prompt's "any other evidence, these
are just examples"). Sides: `for`, `against`. Round outcomes: `accepted`,
`revised`, `rejected`, `deepened`, `blocked`, `no-new`. Accepted, revised, and
deepened rounds require an evidence ID so productive work remains tied to a
ranked item.

## Storage, ranking, and validation

`.infinite/ledger.jsonl` mixes generic round events with `research_init`,
`evidence`, `claim`, `search`, `research_note`, `compile`, and finalization events.
The latest event for an evidence/claim ID is its current revision; history stays
append-only. `.infinite/state.json` stores the round, next side, dry-round count,
and next target. `.infinite/gdocs.json` is the Google Docs sync receipt written
only by `scripts/google_docs.py`. Scratch candidate files belong under
`.infinite/` and should not be committed. The three generated Markdown reports
are deliverables and may be committed when the user wants research output
preserved; their published form is the Google Docs mirror.

The for/against reports rank claims overall and within category, rank categories
by their strongest claim (explicitly a non-cumulative ceiling), and rank every
canonical evidence item. The comparison report renders linked opposite-side
items as head-to-head contradictions (both counter-analyses, both scores, and
which currently scores higher on the recorded rubric), claim and category
face-offs, unlinked items pending an opponent, and the full combined register
with detail for every item on both sides. Ties share a rank; IDs break display
order deterministically. Claims list evidence by reference so shared items are
not duplicated. Each report header carries a ledger SHA-256 digest; validation
fails if the ledger changed without recompiling.

The validator checks required fields, the six-step substance thresholds,
ratings/reasons, formula/provenance/witness caps, excluded source domains,
lead-only misuse, duplicate identities/aliases, cross-side links, claim
membership, round alternation, verification/next fields, freshness/finality of
all three reports, and — at finalization — that the Google Docs receipt shows
all three documents synced at the current digest in final mode. It prints
warnings for pending opposite-side links and unsynced interim Google Docs. It
does **not** verify URLs, historical truth, source independence, or whether
prose is fair; those require the research protocol and human-auditable
citations.
