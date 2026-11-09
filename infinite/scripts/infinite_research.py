#!/usr/bin/env python3
"""Durable evidence ledger and three-report compiler for the Infinite skill.

Standard library only. This helper is the CODE ENFORCEMENT of the fixed prompt's
six numbered steps: an evidence record cannot enter the ledger unless every step
was performed with recorded substance (minimum checks, context lengths, source
counts, corroboration citations, counter-analysis depth, score reasons, and an
investigation record). It validates structure, provenance fields, ratings,
references, and exact duplicate keys; it does NOT authenticate sources or judge
historical truth. Those remain the agent's documented research work.

Commands:
  init | status | lookup | evidence | revise | claim | search | note |
  compile [--final] | validate [--final]

State is append-only in <project>/.infinite/ledger.jsonl. Reports are written to
<project>/research/book-of-mormon-{for,against,comparison}.md and mirrored to
Google Docs by scripts/google_docs.py (see references/google-docs.md). See
references/evidence-schema.md for the record format.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
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
    "other",
)
AUTHENTICITY = ("verified", "disputed", "unverified", "fabricated")
OUTCOMES = ("accepted", "revised", "rejected", "deepened", "blocked", "no-new")
PRODUCTIVE = {"accepted", "revised", "deepened"}
DIMENSIONS = ("credibility", "accuracy", "relevance", "usefulness")
WEIGHTS = {"credibility": 0.30, "accuracy": 0.30, "relevance": 0.25, "usefulness": 0.15}
CAPS = {"verified": 100.0, "disputed": 69.0, "unverified": 49.0, "fabricated": 0.0}
# The fixed prompt says witnesses are "weighed less!": a hard ceiling on the
# witnesses category, applied to evidence and claims on both sides.
CATEGORY_CAPS = {"witnesses": 69.0}
SOURCE_ROLES = ("evidence", "lead-only")
BLOCKED_HOSTS = ("wikipedia.org", "reddit.com", "redd.it", "quora.com")

# Code-enforced substance thresholds for the prompt's six steps. These are the
# "not a quick thing either" floor: an item that merely mentions a step fails.
MIN_AUTH_CHECKS = 3        # step 1: distinct substantive verification checks
MIN_AUTH_CHECK_LEN = 30    # step 1: chars per recorded check
MIN_AUTH_LIMITS_LEN = 20   # step 1: provenance-limitations prose
MIN_CONTEXT_LEN = 80       # step 2: chars per context field (textual/historical/pov/missing)
MIN_SOURCES = 2            # step 3: independent evidence-role sources (verified items)
MIN_INDEPENDENCE_GROUPS = 2  # step 3: distinct source chains (verified items)
MIN_CORROB_CROSS_LEN = 60  # step 3: cross-check comparison prose
MIN_CORROB_CITED = 2       # step 3: distinct cited pieces of evidence (verified items)
MIN_CORROB_PIECE_LEN = 15  # step 3: chars per cited piece / what-it-shows
MIN_COUNTER_LEN = 120      # step 4: strongest-opposition analysis
MIN_SCORE_REASON_LEN = 30  # step 5: chars per dimension reason
MIN_INV_QUERIES = 2        # step 6: recorded search queries
MIN_INV_QUERY_LEN = 8      # step 6: chars per query
MIN_INV_CONSULTED = 2      # step 6: sources actually consulted
MIN_INV_REJECTED_LEN = 40  # step 6: ruled-out leads prose
MIN_INV_DEPTH_LEN = 80     # step 6: depth-of-research prose
MIN_CLAIM_SYNTHESIS_LEN = 120  # claim-level analysis floor
MIN_SOURCE_TEXT_LEN = 20   # reference/verification/bias prose per source
MIN_LOCATOR_LEN = 3        # precise locator per source

REPORTS = {"for": Path("research/book-of-mormon-for.md"),
           "against": Path("research/book-of-mormon-against.md"),
           "comparison": Path("research/book-of-mormon-comparison.md")}
GDOCS_RECEIPT = Path(".infinite/gdocs.json")
GDOCS_SETUP_HINT = (
    "Google Docs deliverables are required by the fixed prompt. They are published "
    "through the Google Workspace CLI (https://github.com/googleworkspace/cli): "
    "install it once (npm install -g @googleworkspace/cli), authenticate as the "
    "user (gws auth setup / gws auth login; headless: exported credentials via "
    "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE, or the exported JSON stored as a "
    "GOOGLE_WORKSPACE_CLI_CREDENTIALS_JSON secret on hosted sandboxes), then run "
    "scripts/google_docs.py setup and sync (see references/google-docs.md)."
)
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


def score(record: dict, label: str, errors: list[str], cap: float = 100.0, step: str = "") -> float:
    ratings = record.get("scores")
    reasons = record.get("score_reasons")
    prefix = f"{step} " if step else ""
    if not isinstance(ratings, dict) or not isinstance(reasons, dict):
        errors.append(f"{prefix}{label}: scores and score_reasons objects are required")
        return 0.0
    values = []
    for dim in DIMENSIONS:
        value = ratings.get(dim)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
            errors.append(f"{prefix}{label}: {dim} must be a finite number from 0 to 100 (one overall score AND multiple independent scores)")
            values.append(0.0)
        else:
            values.append(float(value))
        reason = reasons.get(dim)
        if not isinstance(reason, str) or len(reason.strip()) < MIN_SCORE_REASON_LEN:
            errors.append(
                f"{prefix}{label}: score_reasons.{dim} must give a specific reason of at least "
                f"{MIN_SCORE_REASON_LEN} characters, not a one-word judgment"
            )
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
    for key in ("id", "title", "kind", "independence_group"):
        text(source.get(key), f"{label}.{key}", errors)
    for key in ("reference", "bias", "verification"):
        text(source.get(key), f"{label}.{key}", errors, MIN_SOURCE_TEXT_LEN)
    text(source.get("locator"), f"{label}.locator", errors, MIN_LOCATOR_LEN)
    role = source.get("role", "evidence")
    if role not in SOURCE_ROLES:
        errors.append(f"{label}.role must be one of {SOURCE_ROLES} (biased/discovery sources are 'lead-only')")
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


def validate_counter(value: dict, label: str, errors: list[str], source_ids: set[str], require_sources: bool, step: str) -> None:
    if not isinstance(value, dict):
        errors.append(f"{step} {label} must be an object")
        return
    analysis = value.get("analysis")
    if not isinstance(analysis, str) or len(analysis.strip()) < MIN_COUNTER_LEN:
        errors.append(
            f"{step} {label}.analysis must state the STRONGEST opposing evidence/alternative, "
            f"its effect, and residual uncertainty in at least {MIN_COUNTER_LEN} characters "
            f"(got {len(analysis.strip()) if isinstance(analysis, str) else 0})"
        )
    string_list(value.get("opposing_ids", []), f"{label}.opposing_ids", errors)
    refs = value.get("source_ids", [])
    string_list(refs, f"{label}.source_ids", errors)
    if require_sources and not refs:
        errors.append(f"{step} {label}.source_ids must cite checked sources")
    unknown = set(refs) - source_ids
    if unknown:
        errors.append(f"{label} cites unknown sources: {sorted(unknown)}")


def evidence_cap(record: dict) -> float:
    """Provenance cap combined with the prompt's category caps (witnesses weighed less)."""
    verdict = record.get("authenticity", {}).get("verdict") if isinstance(record.get("authenticity"), dict) else None
    provenance = CAPS.get(verdict, 0.0) if verdict in CAPS else 0.0
    return min(provenance, CATEGORY_CAPS.get(str(record.get("category")), 100.0))


def claim_cap(record: dict) -> float:
    return CATEGORY_CAPS.get(str(record.get("category")), 100.0)


def validate_corroboration(record: dict, sources: list, errors: list[str]) -> None:
    """Prompt step 3: 'Check multiple sources for this evidence and cite multiple
    pieces of evidence.' Encoded as hard requirements, not advice."""
    step = "[prompt step 3 — check multiple sources and cite multiple pieces of evidence]"
    verified = record.get("authenticity", {}).get("verdict") == "verified"
    cor = record.get("corroboration")
    if not isinstance(cor, dict):
        errors.append(f"{step} corroboration object is required (cross_checks + cited_evidence)")
        return
    text(cor.get("cross_checks"), f"{step} corroboration.cross_checks", errors, MIN_CORROB_CROSS_LEN)
    cited = cor.get("cited_evidence")
    source_by_id = {s.get("id"): s for s in sources if isinstance(s, dict)}
    if not isinstance(cited, list) or not cited:
        errors.append(f"{step} corroboration.cited_evidence must be a non-empty list")
        return
    min_cited = MIN_CORROB_CITED if verified else 1
    if len(cited) < min_cited:
        errors.append(
            f"{step} corroboration.cited_evidence needs at least {min_cited} distinct pieces "
            f"of evidence for a {record.get('authenticity', {}).get('verdict', '?')} item (got {len(cited)})"
        )
    used: set[str] = set()
    for index, entry in enumerate(cited):
        label = f"{step} cited_evidence[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object")
            continue
        sid = entry.get("source_id")
        if sid not in source_by_id:
            errors.append(f"{label}.source_id must reference a source listed in this record")
            continue
        if source_by_id[sid].get("role", "evidence") == "lead-only":
            errors.append(f"{label} cites {sid}, which is marked lead-only; biased/discovery sources are NOT sources of evidence")
        text(entry.get("piece"), f"{label}.piece (the exact passage/data cited)", errors, MIN_CORROB_PIECE_LEN)
        text(entry.get("what_it_shows"), f"{label}.what_it_shows", errors, MIN_CORROB_PIECE_LEN)
        used.add(sid)
    if verified and len(used) < MIN_INDEPENDENCE_GROUPS:
        errors.append(
            f"{step} a verified item must cite pieces of evidence from at least "
            f"{MIN_INDEPENDENCE_GROUPS} distinct sources (got {len(used)})"
        )
    # Multiple-source requirement for verified items.
    evidence_sources = [s for s in sources if isinstance(s, dict) and s.get("role", "evidence") == "evidence"]
    groups = {s.get("independence_group") for s in evidence_sources}
    if verified:
        if len(evidence_sources) < MIN_SOURCES:
            errors.append(
                f"{step} a verified item needs at least {MIN_SOURCES} evidence-role sources "
                f"(lead-only sources do not count; got {len(evidence_sources)})"
            )
        if len(groups) < MIN_INDEPENDENCE_GROUPS:
            errors.append(
                f"{step} a verified item needs sources from at least {MIN_INDEPENDENCE_GROUPS} "
                f"distinct independence groups — repeated retellings of one chain count once (got {len(groups)})"
            )


def validate_investigation(record: dict, errors: list[str]) -> None:
    """Prompt step 6: 'Generally research the fact extensively … not just one
    website look, but multiple sources, counters, and tons of evidence.'"""
    step = "[prompt step 6 — research the fact extensively]"
    inv = record.get("investigation")
    if not isinstance(inv, dict):
        errors.append(f"{step} investigation object is required (queries, sources_consulted, rejected_leads, depth)")
        return
    queries = inv.get("queries")
    if not isinstance(queries, list) or len(queries) < MIN_INV_QUERIES or any(
        not isinstance(q, str) or len(q.strip()) < MIN_INV_QUERY_LEN for q in queries or []
    ):
        errors.append(
            f"{step} investigation.queries must list at least {MIN_INV_QUERIES} actual search "
            f"queries/routes used for THIS item, each at least {MIN_INV_QUERY_LEN} characters"
        )
    consulted = inv.get("sources_consulted")
    if isinstance(consulted, bool) or not isinstance(consulted, int) or consulted < MIN_INV_CONSULTED:
        errors.append(f"{step} investigation.sources_consulted must be an integer >= {MIN_INV_CONSULTED}")
    text(inv.get("rejected_leads"), f"{step} investigation.rejected_leads (what was ruled out and why)", errors, MIN_INV_REJECTED_LEN)
    text(inv.get("depth"), f"{step} investigation.depth (what was read in full, traced to primary sources, cross-checked)", errors, MIN_INV_DEPTH_LEN)


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
    """Enforce the fixed prompt's six steps as code. Every step maps to required
    fields with substance thresholds; a partial or shallow record is rejected."""
    errors = base_errors(record, f"evidence {record.get('id', '?')}")
    if not isinstance(record, dict):
        return errors
    for key in ("identity", "proposition", "inference"):
        text(record.get(key), f"evidence {key}", errors)
    string_list(record.get("aliases", []), "evidence aliases", errors)
    if not keys_for(record):
        errors.append("evidence needs a stable identity for deduplication")

    # --- Prompt step 1: check that the evidence is real, not made up --------- #
    step1 = "[prompt step 1 — check the evidence is real, not made up]"
    auth = record.get("authenticity")
    if not isinstance(auth, dict) or auth.get("verdict") not in AUTHENTICITY:
        errors.append(f"{step1} authenticity.verdict must be one of {AUTHENTICITY}")
    else:
        checks = auth.get("checks")
        if not isinstance(checks, list) or len(checks) < MIN_AUTH_CHECKS or any(
            not isinstance(c, str) or len(c.strip()) < MIN_AUTH_CHECK_LEN for c in checks or []
        ):
            errors.append(
                f"{step1} authenticity.checks must record at least {MIN_AUTH_CHECKS} distinct "
                f"verification checks actually performed (earliest source located, exact wording/"
                f"locator compared, correction/retraction/forgery search, provenance), each at "
                f"least {MIN_AUTH_CHECK_LEN} characters"
            )
        text(auth.get("limitations"), f"{step1} authenticity.limitations", errors, MIN_AUTH_LIMITS_LEN)

    # --- Prompt step 2: full context and POV -------------------------------- #
    step2 = "[prompt step 2 — context and POV, all the facts]"
    context = record.get("context")
    if not isinstance(context, dict):
        errors.append(f"{step2} context object is required")
    else:
        for key in ("textual", "historical", "pov", "missing_facts"):
            value = context.get(key)
            if not isinstance(value, str) or len(value.strip()) < MIN_CONTEXT_LEN:
                errors.append(
                    f"{step2} context.{key} must be substantive (at least {MIN_CONTEXT_LEN} characters; "
                    f"got {len(value.strip()) if isinstance(value, str) else 0}). Read the surrounding "
                    "passage/document/excavation context, not just the extracted sentence."
                )

    # --- Prompt step 3: multiple sources, multiple cited pieces ------------- #
    sources = record.get("sources")
    source_ids: set[str] = set()
    if not isinstance(sources, list) or not sources:
        errors.append("[prompt step 3] evidence sources must be a non-empty list")
        sources = []
    else:
        for index, source in enumerate(sources):
            validate_source(source, f"source[{index}]", errors)
            if isinstance(source, dict):
                sid = source.get("id")
                if sid in source_ids:
                    errors.append(f"duplicate source id {sid}")
                source_ids.add(sid)
    validate_corroboration(record, sources if isinstance(sources, list) else [], errors)

    # --- Prompt step 4: counters to the evidence ---------------------------- #
    validate_counter(record.get("counter_evaluation"), "counter_evaluation", errors, source_ids, True,
                     "[prompt step 4 — look at counters to the evidence]")

    # --- Prompt step 5: credibility/relevance/usefulness + rankings --------- #
    step5 = "[prompt step 5 — rank credibility, accuracy, relevance, usefulness; one overall score]"
    cap = evidence_cap(record)
    expected = score(record, "evidence", errors, cap, step5)
    if record.get("overall_score") != expected:
        errors.append(f"{step5} overall_score must be {expected} (witnesses category is capped at {CATEGORY_CAPS.get('witnesses')}); use the helper to compute it")

    # --- Prompt step 6: extensive research ---------------------------------- #
    validate_investigation(record, errors)

    if record.get("original_synthesis") is not None:
        text(record["original_synthesis"], "original_synthesis", errors)
    return errors


def validate_claim(record: dict, evidence: dict[str, dict]) -> list[str]:
    errors = base_errors(record, f"claim {record.get('id', '?')}")
    if not isinstance(record, dict):
        return errors
    text(record.get("statement"), "claim.statement", errors)
    text(record.get("synthesis"), "claim.synthesis", errors, MIN_CLAIM_SYNTHESIS_LEN)
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
    expected = score(record, "claim", errors, claim_cap(record), "[prompt step 5 — rank the whole argument]")
    if record.get("overall_score") != expected:
        errors.append(f"claim overall_score must be {expected} (witnesses category is capped at {CATEGORY_CAPS.get('witnesses')}); use the helper to compute it")
    validate_counter(record.get("counter_evaluation"), "claim.counter_evaluation", errors, source_ids, False,
                     "[prompt step 4 — look at counters to the claim]")
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
        f"**Status:** {status}. Generated from the append-only ledger; do not hand-edit.",
        f"**Companion documents:** research/book-of-mormon-for.md, research/book-of-mormon-against.md, research/book-of-mormon-comparison.md — all three are mirrored to Google Docs (references/google-docs.md).", "",
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
                      "**Multiple sources checked (prompt step 3):** " + (item.get("corroboration", {}).get("cross_checks", "Not recorded.") if isinstance(item.get("corroboration"), dict) else "Not recorded."), ""]
            for cited in (item.get("corroboration", {}) or {}).get("cited_evidence", []) if isinstance(item.get("corroboration"), dict) else []:
                lines.append(f"- Cited piece (`{md(cited.get('source_id'))}`): {md(cited.get('piece'))} — shows: {md(cited.get('what_it_shows'))}")
            if (item.get("corroboration", {}) or {}).get("cited_evidence"):
                lines.append("")
            inv = item.get("investigation", {}) if isinstance(item.get("investigation"), dict) else {}
            lines += [
                "**Extensive research record (prompt step 6):** " + md(inv.get("depth", "Not recorded.")),
                f"- Queries run: {'; '.join(md(q) for q in inv.get('queries', [])) or 'Not recorded.'}",
                f"- Sources consulted: {inv.get('sources_consulted', '?')}",
                f"- Leads ruled out: {md(inv.get('rejected_leads', 'Not recorded.'))}", "",
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


def opposing_pairs(records: dict[str, dict]) -> list[tuple[dict, dict]]:
    """Deduplicated (record, opponent) pairs from counter_evaluation.opposing_ids."""
    pairs: dict[tuple[str, str], tuple[dict, dict]] = {}
    for rid, record in records.items():
        for oid in record.get("counter_evaluation", {}).get("opposing_ids", []):
            other = records.get(oid)
            if other is None or other.get("side") == record.get("side"):
                continue
            key = tuple(sorted((rid, oid)))
            first, second = (record, other) if record.get("side") == "for" else (other, record)
            pairs[key] = (first, second)
    return [pairs[key] for key in sorted(pairs)]


def render_comparison(project: Path, data: dict, final: bool) -> str:
    """The third document: everything on both sides, pointed against each other."""
    evidence, claims = data["evidence"], data["claims"]
    all_evidence = list(evidence.values())
    all_claims = list(claims.values())
    for_rank = {item["id"]: rank for rank, item in ranked([e for e in all_evidence if e.get("side") == "for"])}
    against_rank = {item["id"]: rank for rank, item in ranked([e for e in all_evidence if e.get("side") == "against"])}
    status = "FINAL snapshot at user stop" if final else "INTERIM working snapshot — research continues"
    lines = [
        "# Book of Mormon: for vs against — head-to-head comparison", "",
        f"<!-- infinite-research-mode: {'final' if final else 'interim'} -->",
        f"<!-- infinite-research-ledger-sha256: {ledger_digest(project)} -->", "",
        f"**Status:** {status}. Generated from the append-only ledger; do not hand-edit.",
        "**Companion documents:** research/book-of-mormon-for.md, research/book-of-mormon-against.md — all three are mirrored to Google Docs (references/google-docs.md).", "",
        "## How to read this document", "",
        "This is the third deliverable required by the fixed prompt: one document with everything, where the evidence and the points are pointed against each other. Contradicting items recorded on the for and against sides appear below as explicit head-to-head pairs, each with both sides' counter-analyses and scores. Scores are ordinal research judgments on a common rubric — they are never added, subtracted, or averaged into a verdict, and a higher score does not 'prove' a side. The Bible is treated as true as the user's stipulated premise. Witnesses-category items are capped (weighed less) per the fixed prompt.", "",
        "## Direct contradictions — evidence pointed against evidence", "",
    ]
    pairs = opposing_pairs(evidence)
    if not pairs:
        lines += ["No opposite-side evidence links have been recorded yet. Every item keeps a source-backed comparison in its counter-evaluation; register the opposing item and revise to create a direct link.", ""]
    for for_item, against_item in pairs:
        lines += [f"### {for_item['id']} (for) vs {against_item['id']} (against)", "",
                  "| Side | ID | Title | Category | Authenticity | Side rank | Score | C/A/R/U |", "| --- | --- | --- | --- | --- | ---: | ---: | --- |",
                  f"| for | {md(for_item['id'])} | {md(for_item['title'])} | {md(for_item['category'])} | {for_item['authenticity']['verdict']} | {for_rank.get(for_item['id'], '—')} | {for_item['overall_score']} | {ratings(for_item)} |",
                  f"| against | {md(against_item['id'])} | {md(against_item['title'])} | {md(against_item['category'])} | {against_item['authenticity']['verdict']} | {against_rank.get(against_item['id'], '—')} | {against_item['overall_score']} | {ratings(against_item)} |", "",
                  f"**For-side observation:** {for_item['proposition']}",
                  f"**Against-side observation:** {against_item['proposition']}", "",
                  f"**How the for side evaluates this contradiction:** {for_item['counter_evaluation']['analysis']}", "",
                  f"**How the against side evaluates this contradiction:** {against_item['counter_evaluation']['analysis']}", ""]
        stronger, weaker = (for_item, against_item) if for_item["overall_score"] >= against_item["overall_score"] else (against_item, for_item)
        lines += [f"**Current standing on the recorded rubric:** `{stronger['id']}` scores {stronger['overall_score']} vs `{weaker['id']}` at {weaker['overall_score']}. This is a comparison of recorded judgments, not a truth calculation; see each item's uncertainty and dependence before relying on it.", ""]
    lines += ["## Direct contradictions — claims pointed against claims", ""]
    claim_pairs = opposing_pairs(claims)
    if not claim_pairs:
        lines += ["No opposite-side claim links recorded yet.", ""]
    for for_claim, against_claim in claim_pairs:
        lines += [f"### {for_claim['id']} (for) vs {against_claim['id']} (against)", "",
                  f"**For claim:** {for_claim['statement']}",
                  f"**Against claim:** {against_claim['statement']}", "",
                  f"| Side | ID | Title | Category | Score | C/A/R/U |", "| --- | --- | --- | --- | ---: | --- |",
                  f"| for | {md(for_claim['id'])} | {md(for_claim['title'])} | {md(for_claim['category'])} | {for_claim['overall_score']} | {ratings(for_claim)} |",
                  f"| against | {md(against_claim['id'])} | {md(against_claim['title'])} | {md(against_claim['category'])} | {against_claim['overall_score']} | {ratings(against_claim)} |", "",
                  f"**For-side assessment of the opposition:** {for_claim['counter_evaluation']['analysis']}", "",
                  f"**Against-side assessment of the opposition:** {against_claim['counter_evaluation']['analysis']}", ""]
    lines += ["## Category face-offs", "",
              "Strongest recorded claim per side in each category, with usable-evidence counts. This is a ceiling comparison per category, not cumulative proof.", "",
              "| Category | Strongest for claim | For score | Strongest against claim | Against score | Usable evidence (for/against) |",
              "| --- | --- | ---: | --- | ---: | --- |"]
    for category in CATEGORIES:
        for_claims = ranked([c for c in all_claims if c.get("category") == category and c.get("side") == "for"])
        against_claims = ranked([c for c in all_claims if c.get("category") == category and c.get("side") == "against"])
        for_use = sum(1 for e in all_evidence if e.get("category") == category and e.get("side") == "for" and e.get("authenticity", {}).get("verdict") == "verified")
        against_use = sum(1 for e in all_evidence if e.get("category") == category and e.get("side") == "against" and e.get("authenticity", {}).get("verdict") == "verified")
        f_cell = f"{md(for_claims[0][1]['id'])} — {md(for_claims[0][1]['title'])}" if for_claims else "none recorded"
        a_cell = f"{md(against_claims[0][1]['id'])} — {md(against_claims[0][1]['title'])}" if against_claims else "none recorded"
        lines.append(f"| {category} | {f_cell} | {for_claims[0][1]['overall_score'] if for_claims else '—'} | {a_cell} | {against_claims[0][1]['overall_score'] if against_claims else '—'} | {for_use}/{against_use} |")
    lines += ["", "## Items not yet directly linked to an opponent", "",
              "These items carry a source-backed counter-evaluation but no registered opposite-side ID yet. The loop protocol requires researching the other side and revising each item into a direct link.", ""]
    unlinked = [e for e in all_evidence if not e.get("counter_evaluation", {}).get("opposing_ids")]
    if unlinked:
        lines += ["| ID | Side | Title | Score | Recorded counter-evaluation |", "| --- | --- | --- | ---: | --- |"]
        for item in sorted(unlinked, key=lambda e: str(e.get("id"))):
            lines.append(f"| {md(item['id'])} | {item['side']} | {md(item['title'])} | {item['overall_score']} | {md(item['counter_evaluation']['analysis'])} |")
    else:
        lines.append("Every recorded item has at least one direct opposite-side link.")
    lines += ["", "## Complete ranked evidence register — both sides together", "",
              "All evidence from both sides on one rubric. 'Side rank' is the rank within that side's own report.", "",
              "| Combined rank | ID | Side | Side rank | Category | Authenticity | Title | Score | C/A/R/U |",
              "| ---: | --- | --- | ---: | --- | --- | --- | ---: | --- |"]
    for rank, item in ranked(all_evidence):
        side_rank = for_rank.get(item["id"]) if item.get("side") == "for" else against_rank.get(item["id"])
        lines.append(f"| {rank} | {md(item['id'])} | {item['side']} | {side_rank or '—'} | {md(item['category'])} | {item['authenticity']['verdict']} | {md(item['title'])} | {item['overall_score']} | {ratings(item)} |")
    if not all_evidence:
        lines.append("| — | — | — | — | — | — | No evidence recorded yet | — | — |")
    lines += ["", "## Complete claim ranking — both sides together", "",
              "| Combined rank | ID | Side | Category | Title | Score | C/A/R/U |", "| ---: | --- | --- | --- | --- | ---: | --- |"]
    for rank, item in ranked(all_claims):
        lines.append(f"| {rank} | {md(item['id'])} | {item['side']} | {md(item['category'])} | {md(item['title'])} | {item['overall_score']} | {ratings(item)} |")
    if not all_claims:
        lines.append("| — | — | — | — | No claims recorded yet | — | — |")
    lines += ["", "## Full evidence detail — everything on both sides", "",
              "Every recorded item in full, with its opposing links inline so contradicting points face each other. Components are credibility / accuracy / relevance / usefulness.", ""]
    for rank, item in ranked(all_evidence):
        auth, context = item["authenticity"], item["context"]
        opponents = ", ".join(item["counter_evaluation"].get("opposing_ids", [])) or "pending — source-backed comparison recorded"
        lines += [f"### {item['id']} ({item['side']}) — {item['title']}", "",
                  f"Combined rank {rank}; score **{item['overall_score']}** (C/A/R/U: {ratings(item)}); authenticity **{auth['verdict']}**; revision {item.get('revision', 1)}; pointed against: **{opponents}**.", "",
                  f"**Identity:** {item['identity']}",
                  f"**Observation:** {item['proposition']}", f"**Inference:** {item['inference']}", "",
                  f"**Authentication checks (step 1):** {'; '.join(auth['checks'])}", f"**Provenance limits:** {auth['limitations']}", "",
                  f"**Textual context (step 2):** {context['textual']}", f"**Historical context:** {context['historical']}", f"**POV:** {context['pov']}", f"**Missing facts:** {context['missing_facts']}", "",
                  f"**Multiple sources checked (step 3):** " + (item.get("corroboration", {}).get("cross_checks", "Not recorded.") if isinstance(item.get("corroboration"), dict) else "Not recorded.")]
        for cited in (item.get("corroboration", {}) or {}).get("cited_evidence", []) if isinstance(item.get("corroboration"), dict) else []:
            lines.append(f"- Cited piece (`{md(cited.get('source_id'))}`): {md(cited.get('piece'))} — shows: {md(cited.get('what_it_shows'))}")
        inv = item.get("investigation", {}) if isinstance(item.get("investigation"), dict) else {}
        lines += ["",
                  f"**Extensive research record (step 6):** {md(inv.get('depth', 'Not recorded.'))}",
                  f"- Queries run: {'; '.join(md(q) for q in inv.get('queries', [])) or 'Not recorded.'}",
                  f"- Sources consulted: {inv.get('sources_consulted', '?')}",
                  f"- Leads ruled out: {md(inv.get('rejected_leads', 'Not recorded.'))}", "",
                  f"**Assumptions:** {'; '.join(item.get('assumptions', [])) or 'None recorded.'}",
                  f"**Dependence:** {item['dependence']}", f"**Uncertainty:** {item['uncertainty']}", "",
                  "**Score reasons (step 5):** " + "; ".join(f"{d}: {item['score_reasons'][d]}" for d in DIMENSIONS), "",
                  f"**Counter-evaluation (step 4):** {item['counter_evaluation']['analysis']} Source IDs: {', '.join(item['counter_evaluation'].get('source_ids', []))}.", "",
                  "**Sources:**", ""]
        for source in item.get("sources", []):
            role = source.get("role", "evidence")
            lines.append(f"- `{md(source.get('id'))}` {source_link(source)} — {md(source.get('reference'))}; locator: {md(source.get('locator'))}; accessed {md(source.get('accessed'))}; kind: {md(source.get('kind'))}; role: {md(role)}; independence group: {md(source.get('independence_group'))}; bias/POV: {md(source.get('bias'))}; verification: {md(source.get('verification'))}.")
        if item.get("original_synthesis"):
            lines += ["", f"**Original synthesis (not a claimed new historical discovery):** {item['original_synthesis']}"]
        lines.append("")
    lines += ["## Closing assessment", "",
              "This document shows the recorded evidence pointed against itself, as the fixed prompt requires. It does not compute a net score, does not declare a winner, and does not hide items that weaken either side. Quarantined, disputed, and fabricated leads remain visible in the side reports' appendices and are marked by authenticity verdict above.", ""]
    if final:
        lines += ["Research stopped at the user's request. This final snapshot includes the findings recorded before that stop; it does not imply that all possible evidence has been examined.", ""]
    return "\n".join(lines)


def compile_reports(project: Path, final: bool = False) -> list[str]:
    data = store(project)
    errors = cross_errors(data)
    if errors:
        raise ResearchError("cannot compile invalid research state:\n" + "\n".join(errors))
    written = []
    for name, rel in REPORTS.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".md.tmp")
        body = render_comparison(project, data, final) if name == "comparison" else render_side(project, name, data, final)
        tmp.write_text(body, encoding="utf-8")
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

    # --- Google Docs deliverables (fixed prompt: the documents are Google Docs) ---
    if os.environ.get("INFINITE_GDOCS", "").strip().lower() not in {"off", "0", "no", "false"}:
        receipt = read_json(project / GDOCS_RECEIPT, {})
        docs = receipt.get("documents") if isinstance(receipt.get("documents"), dict) else {}
        synced = receipt.get("last_sync") if isinstance(receipt.get("last_sync"), dict) else {}
        missing = [name for name in REPORTS
                   if not isinstance(docs.get(name), dict) or not docs[name].get("id") or not docs[name].get("url")]
        if final_required:
            if missing:
                errors.append(f"Google Docs deliverables are missing for: {', '.join(missing)}. {GDOCS_SETUP_HINT}")
            elif synced.get("digest") != digest:
                errors.append("Google Docs are stale: after the latest compile run scripts/google_docs.py sync --mode final so all three documents match the current ledger digest")
            elif synced.get("mode") != "final":
                errors.append("Google Docs were last synced in interim mode: after compile --final run scripts/google_docs.py sync --mode final")
        else:
            if missing:
                warnings.append(f"Google Docs deliverables are not configured yet ({', '.join(missing) or 'none'}). {GDOCS_SETUP_HINT}")
            elif synced.get("digest") != digest:
                warnings.append("Google Docs are stale; sync them after the next compile (scripts/google_docs.py sync)")
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
    print("google docs: the three reports are mirrored to Google Docs via scripts/google_docs.py (see references/google-docs.md)")
    return 0


def _load_gdocs_module():
    path = Path(__file__).resolve().with_name("google_docs.py")
    if not path.is_file():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("infinite_google_docs", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    return module


def sync_google_docs(project: Path, mode: str) -> tuple[str, str]:
    """Best-effort mirror of the three compiled reports into Google Docs.

    Returns (status, message) with status in {"synced", "skipped", "failed"}.
    Enforcement lives in validation: final reports do not validate until the
    sync receipt shows all three documents current at the final ledger digest.
    """
    if os.environ.get("INFINITE_GDOCS", "").strip().lower() in {"off", "0", "no", "false"}:
        return "skipped", "INFINITE_GDOCS=off; Google Docs mirror disabled by the user"
    module = _load_gdocs_module()
    if module is None:
        return "skipped", "google_docs.py helper not found next to infinite_research.py"
    try:
        return module.maybe_sync(project, mode)
    except Exception as exc:  # never crash the compile because the mirror failed
        return "failed", f"google_docs sync error: {exc}"


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
        record["overall_score"] = score(record, "evidence", [], evidence_cap(record))
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
        record["overall_score"] = score(record, "claim", [], claim_cap(record))
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
    mode = "final" if args.final else "interim"
    status, message = sync_google_docs(project, mode)
    if status == "synced":
        print(f"google docs: {message}")
    elif status == "failed":
        print(f"google docs sync FAILED: {message}", file=sys.stderr)
        if args.final:
            print("final validation will not pass until the sync succeeds: fix credentials/network, "
                  "then run google_docs.py sync --mode final", file=sys.stderr)
    else:
        print(f"google docs: skipped — {message}", file=sys.stderr)
        if args.final:
            print(GDOCS_SETUP_HINT, file=sys.stderr)
    return 0


def cmd_validate(args) -> int:
    errors, warnings = validation_errors(project_dir(args.dir), args.final)
    for warning in warnings:
        print(f"warning: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("research ledger, all three reports (for/against/comparison), and the Google Docs deliverables are structurally valid and current")
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
