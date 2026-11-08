# Audit playbook — picking the weakest part

For Book of Mormon research, use `book-of-mormon-research.md` as the domain
playbook: the target is an evidence gap, weak citation, unresolved objection,
context/provenance problem, or primary-text comparison. Alternate for/against
rounds and score evidence with the four-dimension rubric; do not substitute the
coding checklist below for source verification. The selection rule still applies.

Each generic round needs exactly one target. This file is how to find it and how
to argue that it was the right one.

## Selection rule

Score each candidate: `impact × confidence ÷ effort`.

- **impact** — how much the user would notice or care (1-5)
- **confidence** — how sure you are that the weakness is real, based on evidence
  you can point at (1-5)
- **effort** — how much work to fix properly, in round-sized units (1-5)

Pick the highest score. Break ties toward the candidate with hard evidence
(failing command, stack trace, benchmark number) over a hunch.

Write the decision down before coding:

```
Round N target: <weakness> — because <evidence>. Score 4×5/2.
```

## Universal audit pass

Run this every few rounds regardless of domain:

1. Run every check the project defines (build, test, lint, typecheck, format,
   benchmark). Record exact counts.
2. Search for recent debt you introduced: `TODO`, `FIXME`, `XXX`, `HACK`,
   `skip`, `xfail`, `eslint-disable`, `noqa`, `# type: ignore`, `unwrap()`,
   `except: pass`, `console.log`.
3. Look at the last diff. Anything you touched that has no test is a candidate.
4. Look for unreachable branches, dead code, and error paths with no test.
5. Check the boundary of the change: empty input, one element, huge input,
   unicode, null/nil/none, negative numbers, concurrent calls, retries.

## Domain checklists

### Backend / library code

- Input validation at every public boundary; errors are typed and descriptive.
- Error paths tested, including upstream timeouts and partial failure.
- Idempotency and retries for anything that can be retried.
- Resource cleanup on every exit path (files, sockets, locks, temp dirs).
- Determinism: no reliance on wall-clock, random, or dict ordering in tests.
- Logging has no secrets, no PII, and is not the only evidence a path ran.

### CLI / tooling

- `--help` is accurate; every flag documented and tested.
- Exit codes are meaningful and non-zero on failure.
- Pipes, redirects, `head`, Ctrl-C, and broken stdout do not crash.
- Paths with spaces, unicode, symlinks, and read-only dirs behave sanely.
- Machine-readable output (`--json`) is stable and parseable.

### Frontend / UI

- Loading, empty, error, and partial states all exist.
- Keyboard navigation, focus order, and screen-reader labels.
- Responsive at narrow widths; no overflow or clipped text.
- No layout shift; images have dimensions; long text truncates.
- Interactions are optimistic or have visible pending feedback.

### Data / ML / analytics

- Schema and dtypes asserted; null and duplicate handling explicit.
- Split train/val/test without leakage; seeds fixed; runs reproducible.
- Metric computed by a tested function, not inline guesswork.
- Edge cases: single class, all nulls, out-of-range values, huge cardinality.
- Results report sample sizes and uncertainty, not just a point estimate.

### Research reports

- Every item has an authenticity verdict, actual checks, full context/POV, source
  locators, independence group, four rated dimensions with reasons, and one
  computed overall score.
- Check exact and semantic duplicates; revise the canonical item instead of
  counting a new URL or paraphrase as new evidence.
- Evaluate against the strongest opposite-side item or alternative; mark pending
  links and dependent source chains explicitly.
- Search/access failures and original synthesis are recorded honestly; a score is
  not a probability of truth and item counts are not weight.

### Docs / writing deliverables

- Every claim verified against the artefact or a source.
- Instructions reproduced exactly as written, from a clean state.
- Structure: what, why, how, limits, next steps — no filler.
- Examples run; commands copy-paste correctly.
- Consistency of terminology, tense, and naming.

### Security and privacy (apply everywhere)

- No secrets, tokens, keys, or personal data in code, logs, fixtures, or tests.
- Untrusted input escaped or parameterised (SQL, shell, HTML, paths).
- Authorization checked server-side, not just hidden in the UI.
- Dependencies pinned; no known-vulnerable versions added.
- File and network access constrained to what the task needs.

### Performance

- Measure before changing; keep the before/after numbers in the round log.
- Look for repeated work in loops, N+1 access, needless copies, blocking I/O in
  hot paths, unindexed queries, unbounded caches.
- Add a benchmark or a timing assertion so the gain cannot silently regress.

## Escalation ladder

When easy wins run out, climb rather than repeat:

1. **Fix** the specific defect.
2. **Generalise** — fix the class of defect (validation layer, helper, type).
3. **Prove** — add the test, property test, fuzz seed, or benchmark that makes
   the fix permanent.
4. **Harden** — handle hostile input, capacity, failure, and concurrency.
5. **Simplify** — remove the abstraction that made the defect possible.
6. **Extend** — add the capability the weakness was hinting at.
7. **Surface** — document, demo, or report so the improvement is visible.

Track the rung in the round notes. Three rounds in a row on rungs 1-2 is a
signal to climb higher or switch axis, not to keep polishing.

## Worked example

Task: *"Make the CSV exporter production-ready."* The user never says stop.

```
Round 1 — implemented the exporter; tests 61/61, lint clean.
Round 2 — target: header-only file returns an empty row (evidence: `wc -l` on
          a 1-line fixture). Fixed, added fixture. tests 63/63.
Round 3 — target: values containing embedded newlines corrupt output (evidence:
          round-trip fails on seed 4). Switched to RFC 4180 quoting. tests 66/66.
Round 4 — target: no test covers quoting at all; added property test comparing
          write→read round trips. tests 71/71. Climbed from "fix" to "prove".
Round 5 — target: 200 MB file consumed 1.9 GB RAM (evidence: /usr/bin/time).
          Streamed rows instead of building a list; peak 41 MB. Added a
          benchmark assertion. tests 72/72.
Round 6 — target: no docs for the new `--dialect` flag; README command was
          stale and failed when copy-pasted. Fixed and verified from a clean
          shell.
Round 7 — target: hostile input — formula injection on `=`, `+`, `-`, `@` when
          opened in a spreadsheet. Added opt-in escaping with a test matrix.
```

Note what never happens in that sequence: no round asks "shall I continue?", no
round ends with "the task is complete", and no two rounds polish the same line.
Each round is one sentence of evidence, one change, one verification.

## Signal that a round was worth it

Answer yes to at least one:

- A user-visible behaviour changed for the better.
- A test now catches something it did not catch before.
- A number moved (latency, coverage, error rate, bundle size, test count).
- A class of failure is now impossible or contained.
- A future reader or contributor is measurably less likely to get it wrong.

If the answer is no, say so in the log, then either climb the ladder or pick a
different target next round. Never invent a fix to look productive.
