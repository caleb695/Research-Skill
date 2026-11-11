# Fixed task prompt — authoritative

This is the complete task this skill runs. It is not a template and it is not
replaced by command arguments. Read it before the first round and treat it as the
user's task statement for every round, resume, and final report.

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
- Once you find evidence for the Book of Mormon, look for evidence against it, then back to evidence for it and repeat. 
- Create three separate documents: one for, one against, and one comparing both.
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
- “Assuming the bible is true” is the user's stipulated premise. Label it in both
  reports; still check text, translation, context, and interpretation.
- The rest of this skill package defines how to execute the fixed prompt:
  alternating for/against rounds, authentication, context/POV, one overall score,
  deduplication, cross-side evaluation, durable ledger, and three ranked reports on
  stop. It does not authorize a different task.
- The research side is backed by deterministic enforcement when hooks are
  installed: a built-in Stop validator, helper-only ledger/report writes, and
  user-only stop/resume control. The prompt is not the only enforcement layer.
- Google Docs integration is supported via `infinite/scripts/google_docs_client.py`
  and logged in the ledger as search/note events. Credentials must be placed in
  `.google/credentials.json` or specified via `GOOGLE_APPLICATION_CREDENTIALS`.
