#!/usr/bin/env python3
"""Durable evidence ledger and two-report compiler for the Infinite skill.

Standard library only. This helper validates structure, provenance fields,
ratings, references, and exact duplicate keys; it does NOT authenticate sources
or judge historical truth. Those remain the agent's documented research work.

Commands:
  init | status | lookup | evidence | revise | claim | search | note |
  compile [--final] | validate [--final]

State is append-only in <project>/.infinite/ledger.jsonl. Reports are written to
<project>/research/book-of-mormon-{for,against}.md. See
references/evidence-schema.md for the record format.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PROFILE = "book-of-mormon"
SIDES = ("for", "against")
CATEGORIES = (
    "bible", "book-of-mormon", "archaeology", "witnesses",
    "historical-events", "spiritual-experiences", "coherence", "probability",
)
AUTHENTICITY = ("verified", "disputed", "unverified", "fabricated")
OUTCOMES = ("accepted", "revised", "rejected", "deepened", "blocked", "no-new")
PRODUCTIVE = {"accepted", "revised", "deepened"}
DIMENSIONS = ("credibility", "accuracy", "relevance", "usefulness")
WEIGHTS = {"credibility": 0.30, "accuracy": 0.30, "relevance": 0.25, "usefulness": 0.15}
CAPS = {"verified": 100.0, "disputed": 69.0, "unverified": 49.0, "fabricated": 0.0}
BLOCKED_HOSTS = ("wikipedia.org", "reddit.com", "redd.it", "quora.com")
REPORTS = {"for": Path("research/book-of-mormon-for.md"),
           "against": Path("research/book-of-mormon-against.md")}
STOP_MARKER = Path(".openhands/guard/STOP_REQUESTED")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MODE_RE = re.compile(r"<!-- infinite-research-mode: (interim|final) -->")
DIGEST_RE = re.compile(r"<!-- infinite-research-ledger-sha256: ([0-9a-f]{64}) -->")


class ResearchError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def project_dir(explicit: str | None) -> Path:
    path = Path(explicit or ".").expanduser().resolve()
    return path.parent if path.name == ".infinite" else path


def ledger_path(project: Path) -> Path:
    return project / ".infinite" / "ledger.jsonl"


def read_json(path: Path, default: dict) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)
    return value if isinstance(value, dict) else dict(default)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_events(project: Path) -> list[dict]:
    path = ledger_path(project)
    if not path.exists():
        return []
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ResearchError(f"corrupt ledger line {number}: {exc}") from exc
        if not isinstance(event, dict):
            raise ResearchError(f"ledger line {number} is not an object")
        events.append(event)
    return events


def append_event(project: Path, event: str, **fields) -> None:
    path = ledger_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": now(), "event": event, **fields}, ensure_ascii=False) + "\n")


def ledger_digest(project: Path) -> str:
    path = ledger_path(project)
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def normalize(value: str) -> str:
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def keys_for(record: dict) -> set[str]:
    aliases = record.get("aliases", [])
    if not isinstance(aliases, list):
        aliases = []
    return {normalize(x) for x in [record.get("identity", ""), *aliases] if normalize(x)}


def text(value, label: str, errors: list[str], minimum: int = 1) -> None:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        errors.append(f"{label} must be a non-empty string")


def string_list(value, label: str, errors: list[str], nonempty: bool = False) -> None:
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        errors.append(f"{label} must be a list of non-empty strings")
    elif nonempty and not value:
        errors.append(f"{label} must not be empty")


def score(record: dict, label: str, errors: list[str], cap: float = 100.0) -> float:
    ratings = record.get("scores")
    reasons = record.get("score_reasons")
    if not isinstance(ratings, dict) or not isinstance(reasons, dict):
        errors.append(f"{label}: scores and score_reasons objects are required")
        return 0.0
    values = []
    for dim in DIMENSIONS:
        value = ratings.get(dim)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
            errors.append(f"{label}: {dim} must be a finite number from 0 to 100")
            values.append(0.0)
        else:
            values.append(float(value))
        text(reasons.get(dim), f"{label}: score_reasons.{dim}", errors)
    raw = math.prod(v ** WEIGHTS[d] for v, d in zip(values, DIMENSIONS))
    return round(min(raw, cap), 1)


def valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def blocked_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == domain or host.endswith("." + domain) for domain in BLOCKED_HOSTS)


def validate_source(source: dict, label: str, errors: list[str]) -> None:
    if not isinstance(source, dict):
        errors.append(f"{label} must be an object")
        return
    for key in ("id", "title", "reference", "locator", "kind", "independence_group", "bias", "verification"):
        text(source.get(key), f"{label}.{key}", errors)
    if not ID_RE.match(str(source.get("id", ""))):
        errors.append(f"{label}.id is invalid")
    accessed = source.get("accessed")
    if not isinstance(accessed, str) or not valid_date(accessed):
        errors.append(f"{label}.accessed must be an actual YYYY-MM-DD access date")
    elif date.fromisoformat(accessed) > datetime.now(timezone.utc).date():
        errors.append(f"{label}.accessed cannot be in the future")
    url = source.get("url")
    if url is not None:
        try:
            parsed = urlparse(url) if isinstance(url, str) else None
        except ValueError:
            parsed = None
        if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"{label}.url must be an http(s) URL")
        elif blocked_url(url):
            errors.append(f"{label}.url is an excluded unreliable source; use it only as a search lead")
    if source.get("excerpt") is not None:
        text(source["excerpt"], f"{label}.excerpt", errors)


def validate_counter(value: dict, label: str, errors: list[str], source_ids: set[str], require_sources: bool) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return
    text(value.get("analysis"), f"{label}.analysis", errors, 20)
    string_list(value.get("opposing_ids", []), f"{label}.opposing_ids", errors)
    refs = value.get("source_ids", [])
    string_list(refs, f"{label}.source_ids", errors)
    if require_sources and not refs:
        errors.append(f"{label}.source_ids must cite checked sources")
    unknown = set(refs) - source_ids
    if unknown:
        errors.append(f"{label} cites unknown sources: {sorted(unknown)}")


def base_errors(record: dict, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return [f"{label} must be an object"]
    if not ID_RE.match(str(record.get("id", ""))):
        errors.append(f"{label}.id must match [A-Za-z0-9][A-Za-z0-9_-]{{0,63}}")
    if record.get("side") not in SIDES:
        errors.append(f"{label}.side must be for or against")
    if record.get("category") not in CATEGORIES:
        errors.append(f"{label}.category is not a supported category")
    text(record.get("title"), f"{label}.title", errors)
    string_list(record.get("assumptions"), f"{label}.assumptions", errors)
    text(record.get("dependence"), f"{label}.dependence", errors)
    text(record.get("uncertainty"), f"{label}.uncertainty", errors)
    return errors


def validate_evidence(record: dict) -> list[str]:
    errors = base_errors(record, f"evidence {record.get('id', '?')}")
    if not isinstance(record, dict):
        return errors
    for key in ("identity", "proposition", "inference"):
        text(record.get(key), f"evidence {key}", errors)
    string_list(record.get("aliases", []), "evidence aliases", errors)
    if not keys_for(record):
        errors.append("evidence needs a stable identity for deduplication")
    auth = record.get("authenticity")
    if not isinstance(auth, dict) or auth.get("verdict") not in AUTHENTICITY:
        errors.append("evidence authenticity.verdict is invalid")
        cap = 0.0
    else:
        cap = CAPS[auth["verdict"]]
        string_list(auth.get("checks"), "authenticity.checks", errors, nonempty=True)
        text(auth.get("limitations"), "authenticity.limitations", errors)
    context = record.get("context")
    if not isinstance(context, dict):
        errors.append("evidence context object is required")
    else:
        for key in ("textual", "historical", "pov", "missing_facts"):
            text(context.get(key), f"context.{key}", errors)
    sources = record.get("sources")
    source_ids: set[str] = set()
    if not isinstance(sources, list) or not sources:
        errors.append("evidence sources must be a non-empty list")
    else:
        for index, source in enumerate(sources):
            validate_source(source, f"source[{index}]", errors)
            if isinstance(source, dict):
                sid = source.get("id")
                if sid in source_ids:
                    errors.append(f"duplicate source id {sid}")
                source_ids.add(sid)
    expected = score(record, "evidence", errors, cap)
    if record.get("overall_score") != expected:
        errors.append(f"evidence overall_score must be {expected}; use the helper to compute it")
    validate_counter(record.get("counter_evaluation"), "counter_evaluation", errors, source_ids, True)
    if record.get("original_synthesis") is not None:
        text(record["original_synthesis"], "original_synthesis", errors)
    return errors


def validate_claim(record: dict, evidence: dict[str, dict]) -> list[str]:
    errors = base_errors(record, f"claim {record.get('id', '?')}")
    if not isinstance(record, dict):
        return errors
    text(record.get("statement"), "claim.statement", errors)
    text(record.get("synthesis"), "claim.synthesis", errors, 20)
    refs = record.get("evidence_ids")
    string_list(refs, "claim.evidence_ids", errors, nonempty=True)
    usable = 0
    source_ids: set[str] = set()
    for eid in refs or []:
        item = evidence.get(eid)
        if item is None:
            errors.append(f"claim references unknown evidence {eid}")
            continue
        if item.get("side") != record.get("side"):
            errors.append(f"claim {record['id']} links opposite-side evidence {eid}; put it in counter_evaluation")
        if item.get("authenticity", {}).get("verdict") == "verified":
            usable += 1
            source_ids.update(s.get("id") for s in item.get("sources", []) if isinstance(s, dict))
        else:
            errors.append(f"claim links non-usable evidence {eid}; keep it in quarantine")
    if refs and usable == 0:
        errors.append("a claim needs at least one verified evidence item")
    expected = score(record, "claim", errors)
    if record.get("overall_score") != expected:
        errors.append(f"claim overall_score must be {expected}; use the helper to compute it")
    validate_counter(record.get("counter_evaluation"), "claim.counter_evaluation", errors, source_ids, False)
    return errors


def store(project: Path) -> dict:
    events = read_events(project)
    evidence: dict[str, dict] = {}
    claims: dict[str, dict] = {}
    for event in events:
        kind = event.get("event")
        if kind in {"evidence", "claim"}:
            record = event.get("record")
            if not isinstance(record, dict) or not ID_RE.match(str(record.get("id", ""))):
                raise ResearchError(f"malformed {kind} event")
            target = evidence if kind == "evidence" else claims
            record = dict(record)
            record["revision"] = int(target.get(record["id"], {}).get("revision", 0)) + 1
            target[record["id"]] = record
    return {
        "events": events,
        "evidence": evidence,
        "claims": claims,
        "rounds": [e for e in events if e.get("event") == "round" and (e.get("profile") == PROFILE or e.get("side") in SIDES)],
        "searches": [e for e in events if e.get("event") == "search"],
        "notes": [e for e in events if e.get("event") == "research_note"],
    }


def cross_errors(data: dict) -> list[str]:
    errors: list[str] = []
    evidence, claims = data["evidence"], data["claims"]
    seen: dict[str, str] = {}
    for eid, item in evidence.items():
        errors.extend(validate_evidence(item))
        for key in keys_for(item):
            if key in seen and seen[key] != eid:
                errors.append(f"duplicate evidence identity: {eid} repeats {seen[key]}")
            seen[key] = eid
    for cid, claim in claims.items():
        errors.extend(validate_claim(claim, evidence))
    for collection in (evidence, claims):
        for rid, record in collection.items():
            for oid in record.get("counter_evaluation", {}).get("opposing_ids", []):
                other = evidence.get(oid)
                if other is None:
                    errors.append(f"{rid} references unknown opposing evidence {oid}")
                elif other.get("side") == record.get("side"):
                    errors.append(f"{rid} opposing evidence {oid} is on the same side")
    previous_side = None
    previous_round = 0
    for entry in data["rounds"]:
        side, outcome = entry.get("side"), entry.get("outcome")
        number = entry.get("round")
        if side not in SIDES or outcome not in OUTCOMES:
            errors.append(f"research round {number} needs a valid side and outcome")
        if not isinstance(number, int) or number <= previous_round:
            errors.append(f"research round numbers must increase: {number}")
        else:
            previous_round = number
        if side == previous_side:
            errors.append(f"round {number} repeats side {side}; research rounds must alternate")
        previous_side = side
        text(entry.get("verification"), f"round {number} verification", errors)
        text(entry.get("next"), f"round {number} next", errors)
        eid = entry.get("evidence_id")
        if outcome in {"accepted", "revised", "deepened"} and not eid:
            errors.append(f"round {number} {outcome} needs an evidence_id")
        if eid and eid not in evidence:
            errors.append(f"round {number} references unknown evidence {eid}")
    for index, search in enumerate(data["searches"]):
        if search.get("side") not in SIDES:
            errors.append(f"search {index} has an invalid side")
        text(search.get("query"), f"search {index} query", errors)
        text(search.get("notes"), f"search {index} notes", errors)
        string_list(search.get("urls", []), f"search {index} urls", errors)
    for index, note in enumerate(data["notes"]):
        if note.get("side") not in SIDES or note.get("kind") not in {"method-limit", "original-synthesis", "closing-analysis"}:
            errors.append(f"research note {index} has an invalid side or kind")
        text(note.get("text"), f"research note {index} text", errors)
    return errors


def ranked(records: list[dict]) -> list[tuple[int, dict]]:
    ordered = sorted(records, key=lambda r: (-float(r.get("overall_score", 0)), str(r.get("id", ""))))
    result, previous, rank = [], None, 0
    for index, record in enumerate(ordered, 1):
        value = float(record.get("overall_score", 0))
        if value != previous:
            rank = index
            previous = value
        result.append((rank, record))
    return result


def md(value) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", "<br>")


def source_link(source: dict) -> str:
    title = md(source.get("title", source.get("id", "source")))
    url = source.get("url")
    return f"[{title}]({url})" if url else title


def ratings(record: dict) -> str:
    return " / ".join(str(record.get("scores", {}).get(d, "?")) for d in DIMENSIONS)


def render_side(project: Path, side: str, data: dict, final: bool) -> str:
    evidence = [e for e in data["evidence"].values() if e.get("side") == side]
    claims = [c for c in data["claims"].values() if c.get("side") == side]
    other_claims = [c for c in data["claims"].values() if c.get("side") != side]
    evidence_ranks = {item["id"]: rank for rank, item in ranked(evidence)}
    category_ranks: dict[str, dict[str, int]] = {}
    for category in CATEGORIES:
        category_ranks[category] = {item["id"]: rank for rank, item in ranked([c for c in claims if c.get("category") == category])}
    usable = [e for e in evidence if e.get("authenticity", {}).get("verdict") == "verified"]
    quarantined = [e for e in evidence if e not in usable]
    searches = [s for s in data["searches"] if s.get("side") == side]
    rounds = [r for r in data["rounds"] if r.get("side") == side]
    status = "FINAL snapshot at user stop" if final else "INTERIM working snapshot — research continues"
    lines = [
        f"# Book of Mormon: evidence {side}", "",
        f"<!-- infinite-research-mode: {'final' if final else 'interim'} -->",
        f"<!-- infinite-research-ledger-sha256: {ledger_digest(project)} -->", "",
        f"**Status:** {status}. Generated from the append-only ledger; do not hand-edit.", "",
        "## Scope, assumptions, and method", "",
        "This report investigates evidence bearing on Book of Mormon truth claims. The Bible is treated as true as the user's stipulated premise, not as an independently established result of this run. The Book of Mormon is primary evidence of its contents, not independent proof of its historicity. Each item distinguishes observation, inference, context, and uncertainty.", "",
        "Rounds alternate for/against. Sources were selected for provenance and independence; Wikipedia, Reddit, Quora, anonymous posts, and AI summaries are not evidence. Authentication and context checks recorded below are the agent's research judgments, not guarantees produced by this script.", "",
        "**Evidence Impact Score:** `C^0.30 × A^0.30 × R^0.25 × U^0.15`, rounded to one decimal. C=credibility, A=accuracy, R=relevance, U=usefulness. Fabricated items score 0; unverified provenance is capped at 49 and disputed provenance at 69. Scores are ordinal, not probabilities of truth. Do not add or subtract side totals.", "",
        "## Coverage", "",
        f"- Research rounds on this side: {len(rounds)}; searches logged: {len(searches)}.",
        f"- Canonical evidence items: {len(evidence)}; usable: {len(usable)}; quarantined/rejected: {len(quarantined)}.",
        f"- Ranked claims: {len(claims)}. Revisions remain in the ledger and are not counted as new evidence.",
        "- Category coverage: " + ", ".join(f"{c}={sum(e.get('category') == c for e in evidence)}" for c in CATEGORIES) + ".",
        "- Access failures and fruitless searches are listed below; no claim of exhaustive coverage is made.", "",
        "## Overall claim ranking", "",
        "| Overall rank | ID | Claim | Category | Category rank | Score | C/A/R/U |",
        "| ---: | --- | --- | --- | ---: | ---: | --- |",
    ]
    for rank, claim in ranked(claims):
        lines.append(f"| {rank} | {md(claim['id'])} | {md(claim['title'])} | {md(claim['category'])} | {category_ranks[claim['category']][claim['id']]} | {claim['overall_score']} | {ratings(claim)} |")
    if not claims:
        lines.append("| — | — | No claims recorded yet | — | — | — | — |")
    lines += ["", "## Category ranking", "",
              "Ranked by the strongest recorded claim in each category (a transparent ceiling, **not** cumulative proof). The opposite column provides comparison, not a net truth calculation.", "",
              "| Category rank | Category | Strongest claim | Score | Strongest opposite-side score |",
              "| ---: | --- | --- | ---: | ---: |"]
    ceilings = []
    for category in CATEGORIES:
        items = [c for c in claims if c.get("category") == category]
        opposite = [c.get("overall_score", 0) for c in other_claims if c.get("category") == category]
        if items:
            best = ranked(items)[0][1]
            ceilings.append((best["overall_score"], category, best["id"], max(opposite) if opposite else "—"))
        else:
            ceilings.append((-1, category, "Not yet assessed", max(opposite) if opposite else "—"))
    for rank, (value, category, cid, opposite) in enumerate(sorted(ceilings, key=lambda x: (-x[0], x[1])), 1):
        lines.append(f"| {rank if value >= 0 else '—'} | {category} | {md(cid)} | {value if value >= 0 else '—'} | {opposite} |")
    lines += ["", "## Claims and their evidence", ""]
    for rank, claim in ranked(claims):
        lines += [f"### {claim['id']} — {claim['title']}", "",
                  f"Overall rank {rank}; category rank {category_ranks[claim['category']][claim['id']]}; score **{claim['overall_score']}** (C/A/R/U: {ratings(claim)}).", "",
                  f"**Statement:** {claim['statement']}", "", f"**Synthesis:** {claim['synthesis']}", "",
                  f"**Assumptions:** {'; '.join(claim.get('assumptions', [])) or 'None recorded.'}",
                  f"**Dependence:** {claim['dependence']}", f"**Uncertainty:** {claim['uncertainty']}", "",
                  "**Score reasons:** " + "; ".join(f"{d}: {claim['score_reasons'][d]}" for d in DIMENSIONS), "",
                  f"**Against the other side:** {claim['counter_evaluation']['analysis']} Opposing IDs: {', '.join(claim['counter_evaluation'].get('opposing_ids', [])) or 'pending; source-backed comparison above'}.", "",
                  "| Evidence rank | ID | Evidence | Score | C/A/R/U |", "| ---: | --- | --- | ---: | --- |"]
        linked = [data["evidence"][eid] for eid in claim.get("evidence_ids", []) if eid in data["evidence"]]
        for _, item in ranked(linked):
            lines.append(f"| {evidence_ranks[item['id']]} | {md(item['id'])} | {md(item['title'])} | {item['overall_score']} | {ratings(item)} |")
        lines += ["", "Full evidence details appear once in the canonical register below.", ""]
    lines += ["## Canonical evidence register", "",
              "One entry per underlying observation. Shared evidence is referenced by ID under claims rather than duplicated. Component order is credibility / accuracy / relevance / usefulness.", "",
              "| Overall rank | ID | Category | Authenticity | Score | C/A/R/U |", "| ---: | --- | --- | --- | ---: | --- |"]
    for rank, item in ranked(evidence):
        lines.append(f"| {rank} | {md(item['id'])} | {item['category']} | {item['authenticity']['verdict']} | {item['overall_score']} | {ratings(item)} |")
    if not evidence:
        lines.append("| — | — | No evidence recorded yet | — | — | — |")
    for heading, items in (("Usable evidence details", usable), ("Quarantined and rejected leads", quarantined)):
        lines += ["", f"## {heading}", ""]
        if not items:
            lines += ["None recorded.", ""]
        for rank, item in ranked(items):
            auth, context = item["authenticity"], item["context"]
            lines += [f"### {item['id']} — {item['title']}", "",
                      f"Rank {evidence_ranks[item['id']]}; score **{item['overall_score']}**; authenticity **{auth['verdict']}**; revision {item.get('revision', 1)}.", "",
                      f"**Identity:** {item['identity']}", f"**Observation:** {item['proposition']}", f"**Inference:** {item['inference']}", "",
                      f"**Authentication checks:** {'; '.join(auth['checks'])}", f"**Provenance limits:** {auth['limitations']}", "",
                      f"**Textual context:** {context['textual']}", f"**Historical context:** {context['historical']}", f"**POV:** {context['pov']}", f"**Missing facts:** {context['missing_facts']}", "",
                      f"**Assumptions:** {'; '.join(item.get('assumptions', [])) or 'None recorded.'}",
                      f"**Dependence:** {item['dependence']}", f"**Uncertainty:** {item['uncertainty']}", "",
                      "**Score reasons:** " + "; ".join(f"{d}: {item['score_reasons'][d]}" for d in DIMENSIONS), "",
                      f"**Opposing-evidence evaluation:** {item['counter_evaluation']['analysis']} Opposing IDs: {', '.join(item['counter_evaluation'].get('opposing_ids', [])) or 'pending'}. Source IDs: {', '.join(item['counter_evaluation'].get('source_ids', []))}.", ""]
            if item.get("original_synthesis"):
                lines += [f"**Original synthesis (not a claimed new historical discovery):** {item['original_synthesis']}", ""]
            lines += ["**Sources:**", ""]
            for source in item.get("sources", []):
                lines.append(f"- `{md(source.get('id'))}` {source_link(source)} — {md(source.get('reference'))}; locator: {md(source.get('locator'))}; accessed {md(source.get('accessed'))}; kind: {md(source.get('kind'))}; independence group: {md(source.get('independence_group'))}; bias/POV: {md(source.get('bias'))}; verification: {md(source.get('verification'))}.")
                if source.get("excerpt"):
                    lines.append(f"  - Checked excerpt: {md(source['excerpt'])}")
            lines.append("")
    lines += ["## Source inventory and independence groups", "",
              "Sources are listed once per evidence record; identical independence groups mark shared chains rather than independent confirmations.", "",
              "| Evidence | Source | Title | Kind | Independence group | Accessed | Locator |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for item in sorted(evidence, key=lambda e: str(e.get("id"))):
        for source in item.get("sources", []):
            lines.append(f"| {md(item['id'])} | {md(source.get('id'))} | {source_link(source)} | {md(source.get('kind'))} | {md(source.get('independence_group'))} | {md(source.get('accessed'))} | {md(source.get('locator'))} |")
    if not evidence:
        lines.append("| — | — | No sources recorded yet | — | — | — | — |")
    lines += ["", "## Search and access log", "", "| Round | Query / primary-text scope | Outcome | Notes | URLs |", "| ---: | --- | --- | --- | --- |"]
    for search in searches:
        lines.append(f"| {md(search.get('round', '—'))} | {md(search['query'])} | {md(search.get('outcome', 'logged'))} | {md(search['notes'])} | {md('; '.join(search.get('urls', [])))} |")
    if not searches:
        lines.append("| — | No searches logged yet | — | — | — |")
    lines += ["", "## Research notes, limitations, and original synthesis", ""]
    notes = [n for n in data["notes"] if n.get("side") == side]
    for note in notes:
        lines.append(f"- **{md(note['kind'])}:** {md(note['text'])}")
    if not notes:
        lines.append("- No additional notes recorded. Coverage is limited to the searches and sources above.")
    lines += ["", "## Closing assessment", "",
              "The strongest recorded claims are ordered above; the canonical register preserves the evidence and its objections. This report does not compute a probability that the Book of Mormon is true, does not treat item counts as weight, and does not hide contrary findings. Unverified and fabricated leads remain separated from usable evidence.", ""]
    if final:
        lines += ["Research stopped at the user's request. This final snapshot includes the findings recorded before that stop; it does not imply that all possible evidence has been examined.", ""]
    return "\n".join(lines)


def compile_reports(project: Path, final: bool = False) -> list[str]:
    data = store(project)
    errors = cross_errors(data)
    if errors:
        raise ResearchError("cannot compile invalid research state:\n" + "\n".join(errors))
    written = []
    for side, rel in REPORTS.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(render_side(project, side, data, final), encoding="utf-8")
        tmp.replace(path)
        written.append(str(path))
    append_event(project, "compile", mode="final" if final else "interim", digest=ledger_digest(project))
    # The compile event itself changes the ledger; stamp the reports against the
    # post-event digest so validate can detect any later uncompiled change.
    digest = ledger_digest(project)
    for rel in REPORTS.values():
        path = project / rel
        content = DIGEST_RE.sub(f"<!-- infinite-research-ledger-sha256: {digest} -->", path.read_text(encoding="utf-8"))
        path.write_text(content, encoding="utf-8")
    return written


def validation_errors(project: Path, force_final: bool = False) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        data = store(project)
    except ResearchError as exc:
        return [str(exc)], warnings
    errors.extend(cross_errors(data))
    state = read_json(project / ".infinite" / "state.json", {})
    if state.get("profile") != PROFILE:
        errors.append("research state is not initialized; run init")
    final_required = force_final or (project / STOP_MARKER).exists()
    digest = ledger_digest(project)
    for side, rel in REPORTS.items():
        path = project / rel
        if not path.is_file():
            errors.append(f"missing report: {rel}")
            continue
        content = path.read_text(encoding="utf-8")
        mode = MODE_RE.search(content)
        stamp = DIGEST_RE.search(content)
        if not mode or not stamp:
            errors.append(f"{rel} lacks generated mode/digest markers")
            continue
        if stamp.group(1) != digest:
            errors.append(f"{rel} is stale; compile after the latest ledger change")
        if final_required and mode.group(1) != "final":
            errors.append(f"{rel} is not final; after the user's stop run compile --final")
    if final_required:
        for side in SIDES:
            unassigned = [eid for eid, e in data["evidence"].items() if e.get("side") == side and e.get("authenticity", {}).get("verdict") == "verified" and not any(eid in c.get("evidence_ids", []) for c in data["claims"].values())]
            if unassigned:
                errors.append(f"final {side} report has usable evidence not organized under a claim: {unassigned}")
    locator_owners: dict[str, list[str]] = {}
    for eid, item in data["evidence"].items():
        if not item.get("counter_evaluation", {}).get("opposing_ids"):
            warnings.append(f"{eid}: no opposite-side evidence ID linked yet; keep the source-backed comparison and research the other side")
        groups = {s.get("independence_group") for s in item.get("sources", []) if isinstance(s, dict)}
        if item.get("authenticity", {}).get("verdict") == "verified" and len(groups) < 2:
            warnings.append(f"{eid}: one independence group; seek an independent check where available")
        for source in item.get("sources", []):
            if not isinstance(source, dict):
                continue
            key = normalize(str(source.get("url") or source.get("reference", "")) + " " + str(source.get("locator", "")))
            if key:
                locator_owners.setdefault(key, []).append(eid)
    for owners in locator_owners.values():
        if len(set(owners)) > 1:
            warnings.append(f"shared primary locator across {sorted(set(owners))}; confirm these are distinct observations, not duplicates")
    return errors, warnings


def cmd_init(args) -> int:
    project = project_dir(args.dir)
    state_path = project / ".infinite" / "state.json"
    state = read_json(state_path, {"round": 0, "phase": "audit", "next_target": None})
    fresh = state.get("profile") != PROFILE
    state.setdefault("started_at", now())
    state.setdefault("task", args.task or "Research evidence for and against the Book of Mormon until the user says stop.")
    if args.task:
        state["task"] = args.task
    state.update({"profile": PROFILE, "updated_at": now()})
    if fresh:
        state.update({"next_side": "for", "dry_rounds": 0, "stop_requested": False})
        append_event(project, "research_init", profile=PROFILE, assumption="Bible true as the user's stipulated premise")
    write_json(state_path, state)
    compile_reports(project)
    print(f"research workspace: {project}")
    print(f"next side: {state.get('next_side', 'for')}; reports: {', '.join(str(r) for r in REPORTS.values())}")
    return 0


def load_record(path: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchError(f"cannot read record {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResearchError("record file must contain one JSON object")
    return value


def cmd_evidence(args) -> int:
    project = project_dir(args.dir)
    data = store(project)
    record = load_record(args.file)
    if "overall_score" not in record:
        verdict = record.get("authenticity", {}).get("verdict") if isinstance(record.get("authenticity"), dict) else None
        record["overall_score"] = score(record, "evidence", [], CAPS.get(verdict, 0.0))
    errors = validate_evidence(record)
    rid = record.get("id")
    if args.revise and rid not in data["evidence"]:
        errors.append(f"revise requires an existing evidence id: {rid}")
    if not args.revise and rid in data["evidence"]:
        errors.append(f"evidence {rid} already exists; use revise instead of repeating it")
    for key in keys_for(record):
        for eid, existing in data["evidence"].items():
            if eid != rid and key in keys_for(existing):
                errors.append(f"duplicate of {eid}; revise that item instead")
    for oid in record.get("counter_evaluation", {}).get("opposing_ids", []) if isinstance(record.get("counter_evaluation"), dict) else []:
        other = data["evidence"].get(oid)
        if other is None or other.get("side") == record.get("side"):
            errors.append(f"opposing evidence {oid} must already exist on the opposite side")
    if errors:
        raise ResearchError("\n".join(errors))
    append_event(project, "evidence", record=record)
    print(f"recorded evidence {rid} ({record['side']}), overall score {record['overall_score']}")
    return 0


def cmd_claim(args) -> int:
    project = project_dir(args.dir)
    data = store(project)
    record = load_record(args.file)
    if "overall_score" not in record:
        record["overall_score"] = score(record, "claim", [])
    errors = validate_claim(record, data["evidence"])
    for oid in record.get("counter_evaluation", {}).get("opposing_ids", []) if isinstance(record.get("counter_evaluation"), dict) else []:
        other = data["evidence"].get(oid)
        if other is None or other.get("side") == record.get("side"):
            errors.append(f"opposing evidence {oid} must exist on the opposite side")
    if errors:
        raise ResearchError("\n".join(errors))
    append_event(project, "claim", record=record)
    print(f"recorded claim {record['id']} ({record['side']}), overall score {record['overall_score']}")
    return 0


def cmd_search(args) -> int:
    project = project_dir(args.dir)
    state = read_json(project / ".infinite" / "state.json", {})
    append_event(project, "search", side=args.side, round=state.get("round", 0) + 1,
                 query=args.query, outcome=args.outcome, notes=args.notes, urls=args.url or [])
    print(f"logged {args.side} search: {args.outcome}")
    return 0


def cmd_note(args) -> int:
    project = project_dir(args.dir)
    append_event(project, "research_note", side=args.side, kind=args.kind, text=args.text)
    print(f"recorded {args.kind} note for {args.side}")
    return 0


def cmd_status(args) -> int:
    project = project_dir(args.dir)
    data = store(project)
    state = read_json(project / ".infinite" / "state.json", {})
    counts = Counter(e.get("authenticity", {}).get("verdict", "invalid") for e in data["evidence"].values())
    print(f"profile    : {state.get('profile', '(not initialized)')}")
    print(f"round      : {state.get('round', 0)}")
    print(f"next side  : {state.get('next_side', 'for')}")
    print(f"dry rounds : {state.get('dry_rounds', 0)} (deepen at 3; revisit confident/uncertain claims at 6)")
    print(f"evidence   : {len(data['evidence'])} canonical; {dict(counts)}")
    print(f"claims     : {len(data['claims'])}; searches: {len(data['searches'])}")
    print(f"next target: {state.get('next_target') or '(choose by impact x confidence / effort)'}")
    return 0


def cmd_lookup(args) -> int:
    data = store(project_dir(args.dir))
    terms = set(normalize(args.query).split())
    matches = []
    for item in data["evidence"].values():
        haystack = set(normalize(" ".join([item.get("title", ""), item.get("identity", ""), item.get("proposition", ""), *item.get("aliases", [])])).split())
        overlap = len(terms & haystack)
        if overlap:
            matches.append((overlap, item))
    for overlap, item in sorted(matches, key=lambda x: (-x[0], x[1]["id"]))[:args.limit]:
        print(f"{item['id']} [{item['side']}] score={item['overall_score']} overlap={overlap} — {item['title']}")
    if not matches:
        print("No exact token overlap. Still review near-synonyms and the same primary locator before adding.")
    return 0


def cmd_compile(args) -> int:
    project = project_dir(args.dir)
    if args.final:
        state_path = project / ".infinite" / "state.json"
        state = read_json(state_path, {})
        state["stop_requested"] = True
        state["updated_at"] = now()
        write_json(state_path, state)
        append_event(project, "stop_finalization", source="agent reports explicit user stop")
    for path in compile_reports(project, args.final):
        print(path)
    return 0


def cmd_validate(args) -> int:
    errors, warnings = validation_errors(project_dir(args.dir), args.final)
    for warning in warnings:
        print(f"warning: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("research ledger and both reports are structurally valid and current")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", help="project workspace (default: current directory)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init"); p.add_argument("--task"); p.set_defaults(func=cmd_init)
    p = sub.add_parser("status"); p.set_defaults(func=cmd_status)
    p = sub.add_parser("lookup"); p.add_argument("query"); p.add_argument("--limit", type=int, default=10); p.set_defaults(func=cmd_lookup)
    p = sub.add_parser("evidence"); p.add_argument("--file", required=True); p.set_defaults(func=cmd_evidence, revise=False)
    p = sub.add_parser("revise"); p.add_argument("--file", required=True); p.set_defaults(func=cmd_evidence, revise=True)
    p = sub.add_parser("claim"); p.add_argument("--file", required=True); p.set_defaults(func=cmd_claim)
    p = sub.add_parser("search"); p.add_argument("--side", choices=SIDES, required=True); p.add_argument("--query", required=True); p.add_argument("--outcome", choices=OUTCOMES, required=True); p.add_argument("--notes", required=True); p.add_argument("--url", action="append"); p.set_defaults(func=cmd_search)
    p = sub.add_parser("note"); p.add_argument("--side", choices=SIDES, required=True); p.add_argument("--kind", choices=["method-limit", "original-synthesis", "closing-analysis"], required=True); p.add_argument("--text", required=True); p.set_defaults(func=cmd_note)
    p = sub.add_parser("compile"); p.add_argument("--final", action="store_true", help="only after an explicit user stop"); p.set_defaults(func=cmd_compile)
    p = sub.add_parser("validate"); p.add_argument("--final", action="store_true"); p.set_defaults(func=cmd_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except ResearchError as exc:
        print(f"research error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"workspace error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
