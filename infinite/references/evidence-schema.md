# Evidence ledger and report schema

The helper is `scripts/infinite_research.py` (Python 3 standard library). It
checks structure and consistency; it cannot tell whether a source is truthful.
The agent must perform and record the actual research before using these commands.

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

# Log the round with the generic state helper, then checkpoint both reports.
python3 infinite/scripts/infinite_state.py --dir . log \
  --side for --outcome accepted --evidence-id F001 \
  --target "Check the primary source for claim X" \
  --change "Added F001 with provenance and context checks" \
  --verification "Original located; wording and locator checked; validator passed" \
  --next "Investigate the strongest against-side objection to X"
python3 "$H" --dir . compile
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
python3 "$H" --dir . validate --final
```

After a later user `continue` or `/infinite`:

```bash
python3 infinite/scripts/infinite_state.py --dir . resume
python3 "$H" --dir . status
python3 "$H" --dir . compile   # new interim snapshot; preserve the ledger
```

Do not use `--final` to escape the loop. With optional research enforcement, the
user-stop hook writes a user-owned `STOP_REQUESTED` marker; the Stop gate then
requires final reports whose digest matches the ledger. `--disarm` remains the
user's emergency override.

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
    "checks": ["Earliest edition located", "Exact wording and locator compared", "Correction/retraction search performed"],
    "limitations": "Remaining provenance or transmission limits."
  },
  "context": {
    "textual": "Surrounding passage/chapter, speaker, genre, translation and variants.",
    "historical": "Dates, actors, sequence, contemporary versus later records.",
    "pov": "Author/institution purpose, commitments, incentives, audience.",
    "missing_facts": "What would change the interpretation."
  },
  "sources": [
    {
      "id": "S1",
      "title": "Checked source title",
      "reference": "Author, edition/date, publisher or archive, full citation",
      "url": "https://example.org/checked-primary-source",
      "locator": "page, verse, figure, catalog ID, or manuscript folio",
      "accessed": "2026-11-07",
      "kind": "primary|peer-reviewed|academic|official|contemporary-account|other",
      "independence_group": "Stable label for the underlying source chain",
      "bias": "Institutional POV and how it was checked; not a dismissal by label",
      "verification": "What was actually compared or authenticated",
      "excerpt": "Optional short exact excerpt actually checked"
    }
  ],
  "scores": {"credibility": 80, "accuracy": 90, "relevance": 70, "usefulness": 60},
  "score_reasons": {
    "credibility": "Specific provenance/independence reason.",
    "accuracy": "Specific wording/context reason.",
    "relevance": "Specific connection to the stated proposition.",
    "usefulness": "Specific incremental/discriminating value after alternatives."
  },
  "counter_evaluation": {
    "analysis": "Strongest opposing evidence or alternative, its effect, and residual uncertainty.",
    "opposing_ids": ["A001"],
    "source_ids": ["S1"]
  },
  "original_synthesis": "Optional reproducible new comparison or hypothesis; not a claimed new artifact."
}
```

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

Categories: `bible`, `book-of-mormon`, `archaeology`, `witnesses`,
`historical-events`, `spiritual-experiences`, `coherence`, `probability`.
Sides: `for`, `against`. Round outcomes: `accepted`, `revised`, `rejected`,
`deepened`, `blocked`, `no-new`. Accepted, revised, and deepened rounds require an
evidence ID so productive work remains tied to a ranked item.

## Storage, ranking, and validation

`.infinite/ledger.jsonl` mixes generic round events with `research_init`,
`evidence`, `claim`, `search`, `research_note`, `compile`, and finalization events.
The latest event for an evidence/claim ID is its current revision; history stays
append-only. `.infinite/state.json` stores the round, next side, dry-round count,
and next target. Scratch candidate files belong under `.infinite/` and should not
be committed. The two generated Markdown reports are deliverables and may be
committed when the user wants research output preserved.

Reports rank claims overall and within category, rank categories by their
strongest claim (explicitly a non-cumulative ceiling), and rank every canonical
evidence item. Ties share a rank; IDs break display order deterministically.
Claims list evidence by reference so shared items are not duplicated. The report
header carries a ledger SHA-256 digest; validation fails if the ledger changed
without recompiling.

The validator checks required fields, ratings/reasons, formula/caps, excluded
source domains, duplicate identities/aliases, cross-side links, claim membership,
round alternation, verification/next fields, and report freshness/finality. It
prints warnings for pending opposite-side links. It does **not** verify URLs,
historical truth, source independence, or whether prose is fair; those require
the research protocol and human-auditable citations.
