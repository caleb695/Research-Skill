# Fixed task prompt — authoritative

This is the complete task this skill runs. It is not a template and it is not
replaced by command arguments. Read it before the first round and treat it as the
user's task statement for every round, resume, and final report. Every numbered
step below is also enforced by code in `scripts/infinite_research.py`: an
evidence record that skips or shortchanges any step is rejected by the only
write path into the ledger, and the Stop-hook validator re-checks all of it
before a run may finish.

```text
Use the Infinite skill for this task:

I want you to indefinitely research online for evidence for and against the Book of Mormon being true.

Look for this nhs online like archeological evidence, bible evidence, accounts, etc.

In each piece of evidence you find I want you to

1. First, Check to make sure this piece of evidence is real and not just made up (ex: if someone gave misinformation).
2. Second, Look at the context of the situation to understand the POV and all the facts (ex: a verse from the bible but a couple verses later it adds on to that verse)
3. Third, Check multiple sources for this evidence and cite multiple pieces of evidence.
4. Fourth, look at counters to the evidence.
5. Decide how credible, relevant, and useful this evidence is (ex: does this really provide more evidence for or against it or is it something that could be not true or faked)
6. Generally research the fact extensively to understand everything about it not just one website look, but multiple sources, counters, and tons of evidence for one claim.

Note that people can lie and people can be wrong so don’t take everything at face value. Also note that not every one piece of evidence is equal to another piece of evidence (ex: just because there are several pieces of evidence supporting one claim, one piece of evidence could be worth more on the other side. Rank each piece of evidence you find for how credible, accurate, relevant, and useful the evidence actually is overall (one overall score and multiple independent scores)

- Don’t repeat pieces of evidence.
- Use many reliable sources (as many reliable sources as you can find) and do not use unreliable sources such as Wikipedia, Reddit, quora, etc. and try not to use biased sources, only to find a claim to research for evidence but those are NOT sources of evidence.
- Once you find evidence for it, look for evidence against it, then back to evidence for it and repeat.
- Create two separate documents, one for it, and one against it.
- Evaluate each piece of evidence against evidence on the other side.
- For evidence use the bible and Book of Mormon (assuming the bible is true) like things in the bible that would make sense if the BoM was true, witnesses (weighed less!), archeological evidence, things that wouldn’t make sense if the Book of Mormon wasn’t true, the likelihood of something, events from throughout history that are involved with the Mormon church, and other categories (any other evidence, these are just examples). And use all evidence from throughout history. Even things such as spiritual experiences (but things known historically not like a random unreliable person sharing a story)
- If you can’t find more evidence, go deeper and don’t just rely on things that other people have found, also try to find/uncover things yourself that haven’t been found or considered largely yet.
- If you need to, read the bible and Book of Mormon to search it all for evidence instead of just what people find.
- If you keep searching and have been searching without finding something for a large amount of time, then look back on things you are unsure of or things you are sure of for just more evidence to support a claim.
- Also note that not every piece of evidence has to prove the BoM is true directly, some things that are more creative and less directly proving (but still proving in some kind of way)
- When I say stop, stop researching and compile everything you have found for 3, overall reports with organized information and claims each with an overall ranking (and one for each category) and evidence for the claim listed each also with an overall ranking and a ranking for each piece of evidence. One document for, one against, and one with both against each other. Until then, keep working.
```

## Operational reading

- The phrase “Look for this nhs online” is preserved verbatim above; operationally
  read it as looking for things online such as archaeological evidence, biblical
  evidence, accounts, and related primary/scholarly sources.
- “Assuming the bible is true” is the user's stipulated premise. Label it in all
  three reports; still check text, translation, context, and interpretation.
- The six numbered steps are a **code-enforced contract**, not advice. Each maps
  to required schema fields with minimum substance thresholds in
  `scripts/infinite_research.py`: (1) `authenticity` with at least three
  substantive recorded checks; (2) full `context` (textual/historical/POV/
  missing facts); (3) at least two independent sources plus a `corroboration`
  block citing at least two distinct pieces of evidence; (4) a
  `counter_evaluation` with a substantive strongest-opposition analysis;
  (5) four independent ratings (credibility, accuracy, relevance, usefulness)
  each with a specific reason, plus one computed overall score; (6) an
  `investigation` block recording the queries run, sources consulted, leads
  ruled out, and depth of primary-source reading. Records that fail any step
  cannot enter the ledger, and the ledger is the only source for the reports.
- “Witnesses (weighed less!)” is encoded as a hard scoring cap on the
  `witnesses` category (overall score ≤ 69), applied on both sides.
- “Try not to use biased sources, only to find a claim to research for evidence
  but those are NOT sources of evidence” is encoded with a per-source
  `role: lead-only` marker: lead-only sources never count toward the
  multiple-source requirement and may not appear in `corroboration`.
- “One overall score and multiple independent scores” is the four 0–100
  component ratings plus the single computed Evidence Impact Score.
- The final deliverables are **three** reports — for, against, and a head-to-head
  comparison where every contradicting point is pointed against its opposite —
  and all three are mirrored into **Google Docs** created with the user's own
  Google API credentials (see `references/google-docs.md`). Final validation
  fails until all three Google Docs are synced at the final ledger digest.
- The rest of this skill package defines how to execute the fixed prompt:
  alternating for/against rounds, authentication, context/POV, multi-source
  corroboration, counters, scoring, deduplication, cross-side evaluation, a
  durable ledger, and three ranked reports on stop. It does not authorize a
  different task.
- The research side is backed by deterministic enforcement when hooks are
  installed: a built-in Stop validator, helper-only ledger/report writes, and
  user-only stop/resume control. The prompt is not the only enforcement layer.
