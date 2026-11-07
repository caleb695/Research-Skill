# Book of Mormon research protocol

Use this reference for every candidate item. The goal is a traceable,
adversarial investigation, not a collection of quotations or a vote count.

## 1. Define the proposition

Write the exact claim before assigning a side:

- **Observation:** what the source or artifact actually shows.
- **Inference:** why that observation might support or challenge a Book of Mormon
  truth claim.
- **Target:** historicity, ancient authorship, translation, divine origin, or a
  narrower claim such as a proposed geographical identification.
- **Assumptions:** the user's biblical-truth premise, a geography model, a
  translation model, dating assumptions, or a reference class.

A finding about Joseph Smith's sincerity is not automatically a finding about
ancient plates. A finding about one geography model is not a finding about every
possible model. Keep these distinctions visible in the reports.

## 2. Authenticate before interpreting

For each item record an authenticity verdict:

| Verdict | Meaning | Handling |
| --- | --- | --- |
| `verified` | The cited object/text/account exists as described, with provenance adequate for the limited observation | May enter the usable register after context and scoring |
| `disputed` | Existence or provenance has a substantive unresolved challenge | Quarantine; explain the dispute and cap the score |
| `unverified` | Could not check the original or essential provenance | Quarantine; never present as established |
| `fabricated` | Demonstrably invented, altered, misattributed, or retracted | Keep in the rejected appendix with score 0 |

Checklist:

1. Locate the earliest accessible edition, manuscript, excavation report,
   catalog entry, legal record, or signed account. Record author, title, date,
   publisher, URL, and page/verse/figure/catalog locator.
2. Compare the exact quotation with the original. Note ellipses, translation
   choices, editorial headings, later revisions, and whether a copy is signed or
   merely attributed.
3. Check provenance: who held the object/document, when, and how it was found or
   transmitted. For artifacts distinguish excavated context from antiquities
  -market objects with no secure findspot.
4. Search for corrections, retractions, forgery analyses, and methodological
   critiques. Record the checks actually performed, including negative results.
5. Identify independence. Two apologists citing the same speculative article,
   or two critics citing the same unverified claim, are one source chain.
6. Separate “this person said X” from “X happened.” A historical account can be
   authentic as an account while its explanation remains unverified.

A successful HTTP fetch proves only that a page was retrieved. It does not prove
the page's historical claim. Do not invent citations, access dates, quotations,
or archive identifiers to satisfy the schema.

## 3. Source selection and bias

Prefer, in roughly this order when available:

- Primary texts in identifiable editions; manuscript facsimiles and transcription
  projects; contemporaneous documents with known custody.
- Peer-reviewed archaeology/history/textual scholarship, university presses,
  excavation reports, museum and government records.
- Signed, attributable historical testimony evaluated against contemporary
  records and later memory effects.
- Institutional primary sources for what an institution taught or did.

Wikipedia, Reddit, Quora, anonymous forums, social-media posts, AI-generated
summaries, and unsourced blogs are **not evidence**. They may suggest a search
term or a primary citation to verify. A reliable outlet's summary is a lead to
the underlying study or document, not a substitute for checking it.

Do not exclude a source merely because it is LDS-affiliated or critical. Label
the affiliation, funding/purpose where known, expertise, and whether the source
publishes data or only interpretation. Seek independent checks and the best
opposing scholarship. Church sources can establish Church statements and events;
they are not independent confirmation of supernatural claims. Critical sources
can expose a weak apologetic argument without disproving the core claim.

Record `independence_group` for each source. Count source chains, not URLs.
Paywalls and unavailable archives are limitations to report, not invitations to
guess what they say.

## 4. Context and point of view

For every item write a context note covering:

- **Textual:** speaker, audience, surrounding verses/paragraphs, chapter argument,
  genre, narrative voice, cross-references, translation and textual variants.
- **Historical:** date, place, actors, sequence of events, what was known when,
  later recollection versus contemporary recording, incentives and pressures.
- **Archaeological:** findspot, stratigraphy, dating method, publication history,
  survey coverage, and whether an identification is proposed or established.
- **POV:** author's commitments, institutional setting, intended audience,
  selection effects, and what the source is actually trying to establish.
- **Missing facts:** what would change the interpretation and what remains unknown.

Example rule: never score a Bible verse from a snippet. Read the surrounding
literary unit and relevant canonical context; then distinguish what the text
says under the user's premise from what a particular interpretation adds.

## 5. Four ratings and one overall score

Rate each dimension 0–100 and supply a specific reason. Use anchors consistently
across both sides; do not grade one side on a harsher curve.

| Dimension | Question | Anchors |
| --- | --- | --- |
| Credibility | How trustworthy are the source and transmission for this observation? | 0 fabricated/unknown; 25 weak or dependent; 50 plausible with caveats; 75 strong attributable source; 95 primary or rigorous independent support |
| Accuracy | How faithfully is the item stated in its full context? | 0 false/misquoted; 25 material distortion; 50 partly supported; 75 faithful with minor uncertainty; 95 exact and context-complete |
| Relevance | Does it bear on the stated Book of Mormon proposition? | 0 none; 25 background only; 50 indirect; 75 direct but model-dependent; 95 directly tests a central claim |
| Usefulness | How much new, discriminating information survives alternatives and overlap? | 0 redundant; 25 weak increment; 50 modest; 75 substantially narrows explanations; 95 strongly discriminates between live explanations |

The helper computes:

```text
raw = credibility^0.30 × accuracy^0.30 × relevance^0.25 × usefulness^0.15
overall = round(raw, 1)
```

Any zero makes the overall score zero. The geometric mean prevents excellent
relevance from compensating for a fabricated or irrelevant source. Provenance
caps apply after the calculation: `fabricated` → 0, `unverified` → at most 49,
`disputed` → at most 69. An authentic object with a disputed interpretation can
still be `verified`; put the interpretive uncertainty in the ratings and context.

Scores are **ordinal research judgments**, not calibrated probabilities or a
truth percentage. Do not add them, average them into a verdict, or subtract the
against total from the for total. Ten dependent low-value items do not outweigh
one strong, independent, directly relevant item merely by count.

Claims receive their own four ratings and the same formula, judging the entire
argument including dependencies and objections. A claim score is not the sum or
mean of its evidence scores. Category rankings use the strongest nonredundant
claim as a transparent ceiling, explicitly not cumulative category proof.

## 6. Adversarial comparison and dependence

For every evidence item and claim:

1. State the strongest opposing explanation or evidence, not a straw man.
2. Link opposite-side evidence IDs when they exist; otherwise cite sources for
   the alternative and mark the registry link pending.
3. Explain whether the opposition defeats, weakens, limits, or leaves the item
   intact, and what uncertainty remains.
4. Check whether apparently separate items share a manuscript, excavation,
   informant, dataset, author, or assumption. Record dependence explicitly.
5. Ask what would be expected if the Book of Mormon were not true. Compatibility
   with truth is weaker than evidence that discriminates against live alternatives.

Absence arguments require a defined search space: what should be found, where,
when, under which model, and how thoroughly that area has been surveyed. Do not
convert “not yet identified” into “impossible.” Conversely, do not treat an
unprovenanced resemblance as a confirmed identification.

## 7. Category playbook

Use these as research queues, not pre-scored conclusions.

| Category | Investigate | Guard against |
| --- | --- | --- |
| `bible` | Whole-unit parallels, prophetic texts, theology, textual/translation history, Deutero-Isaiah debates, KJV transmission arguments | Verse snippets; assuming one contested dating or translation model is settled |
| `book-of-mormon` | Internal chronology, narrative structure, named places, textual variants, translation claims, manuscript history | Treating the book's assertion as independent proof of its historicity |
| `archaeology` | Provenanced artifacts, inscriptions, settlements, dating, survey coverage, proposed Old/New World contacts | Unprovenanced objects, speculative identifications, arguments from silence without scope |
| `witnesses` | Earliest Three/Eight Witness accounts, signatures vs. autographs, later interviews, recantation claims, relationships and incentives | Collapsing “never denied the testimony” into a single unchanging account |
| `historical-events` | Translation/dictation timeline, scribes and printers, legal records, Church history, succession traditions, documented experiences | Hagiography, hostile rumor, or later institutional claims treated as contemporary fact |
| `spiritual-experiences` | Historically attributable reports, circumstances, consistency, alternative psychological/social explanations | Treating sincerity as public verification of a supernatural cause; dismissing experience as evidence of belief |
| `coherence` | Things claimed to be difficult to explain otherwise; anachronisms; translation and authorship models; consistency across records | “I cannot explain it” as proof; ignoring a plausible natural account |
| `probability` | Stylometry/wordprints, dictation feasibility, demographic/genetic expectations, explicit likelihood comparisons | Invented numbers, bad reference classes, correlated features, unsupported priors |

Cross-cutting topics include horses and other named animals, metals and weapons,
plants, cement, chariots, elephants, Jaredite animals, geography models, NHM/
Nahom proposals, modern versus ancient DNA, and the book's introduction changes.
These are leads to investigate, not findings asserted by this skill.

## 8. Go deeper and do original work

When novelty dries up, change the operation rather than repeating the query:

- Read whole biblical and Book of Mormon units and build a verse-by-verse
  comparison table with edition and translation notes.
- Trace a frequently repeated claim back through footnotes to the earliest
  publication; check whether later authors added certainty.
- Reconstruct a chronology from dated primary records and mark conflicting dates.
- Compare a proposed artifact identification with the published excavation
  context and the full range of scholarly alternatives.
- Revisit high-confidence items for dependence, translation drift, and stronger
  objections; revisit uncertain items for newly accessible primary evidence.
- Form a falsifiable hypothesis and state exactly what evidence would test it.

Original synthesis must be reproducible and labeled as such. A new comparison,
dependency map, or hypothesis is valuable; it is not a newly discovered artifact
or historical event. Search prior literature before calling anything overlooked.

## 9. Round outcomes and stagnation

Every completed research round records a side and one outcome:

- `accepted`: a usable item was added or materially improved.
- `revised`: an existing item/claim was corrected or strengthened.
- `rejected`: a lead failed authentication/context checks; kept with score 0 or
  quarantined, not silently discarded.
- `deepened`: primary-text or dependency work produced a documented synthesis.
- `blocked`: access/tool limits prevented the check; exact blocker and next route
  are recorded.
- `no-new`: a real search found no new usable item; queries and scope are recorded.

Sides still alternate on non-accepted rounds. Three consecutive non-accepted
rounds trigger deeper primary work; six trigger a review of both uncertain and
confident claims. Rotate category and source class. Never fabricate an item to
reset the counter.

## 10. Final reports

The helper renders exactly two side-specific Markdown reports from the ledger.
Each includes methods and assumptions; overall and within-category claim ranks;
category rankings; a canonical evidence register with one overall score and the
four component ratings; full provenance/context/counter-evaluation detail;
rejected/quarantined leads; source inventory; search coverage; limitations; and
original synthesis. Claims reference evidence IDs so a shared item is not copied
into multiple full entries.

The final prose must explain the strongest case on each side and the most
important unresolved disputes. It must not announce a numerical probability of
truth, manufacture equal weight, or hide evidence that weakened the report's own
side. Stop means stop searching; finalization uses only the recorded findings.
