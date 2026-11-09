#!/usr/bin/env python3
"""Deterministic enforcement engine for the `infinite` skill (OpenHands hooks).

The skill's instructions are a prompt; this program is not. The agent never
decides whether it may finish. The Stop hook asks this engine and the engine
answers from a policy that the agent cannot change while the conversation runs.

Why the policy is immutable mid-session
---------------------------------------
The policy (mode, gates, round requirement) is serialized and embedded in the
hook command inside `.openhands/hooks.json`, which OpenHands loads when the
conversation starts. Editing files on disk afterwards cannot change the policy
of the running conversation, so an agent with shell access cannot weaken its own
enforcement. The on-disk config is only a mirror for `status` / `doctor`.

Disarming is user-gated: either the user types a stop phrase (delivered by the
`UserPromptSubmit` hook, which only a real user message can trigger) or the user
runs the installer in their own terminal. The agent is blocked from both by the
`PreToolUse` hook, which refuses to execute or edit enforcement files.

Events
------
  stop        decide on a finish attempt (exit 0 allow / 2 deny)
  pretool     block the agent from disabling enforcement or faking research state
  userprompt  the user's message: disarm on a stop phrase, arm on an infinite one

Commands (user side)
--------------------
  policy --mode M --gate NAME:COMMAND ...   emit the policy blob for the installer
  arm / disarm / status / doctor / uninstall

Standard library only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
import shlex
import shutil
from pathlib import Path

GUARD_DIR = Path(".openhands") / "guard"
LEDGER_REL = Path(".infinite") / "ledger.jsonl"
RESEARCH_PROFILE = "book-of-mormon"
STOP_REQUESTED = "STOP_REQUESTED"
ARMED = "ARMED"
DEFAULT_TIMEOUT = 600
MAX_TAIL_LINES = 12

# Phrases that count as the user stopping infinite mode (README examples).
STOP_PATTERNS = [
    r"\bstop\b",
    r"\bhalt\b",
    r"\bcancel\b",
    r"\bquit\b",
    r"\bthat'?s enough\b",
    r"\byou can stop\b",
    r"\benough for now\b",
    r"/stop\b",
    r"\bexit infinite mode\b",
    r"^\s*(?:please\s+)?stop (?:researching|research|the research)\b",
]
ARM_PATTERNS = [
    r"/infinite\b",
    r"/forever\b",
    r"/never-stop\b",
    r"\binfinite mode\b",
    r"\bnever stop\b",
    r"\bdon'?t stop\b",
    r"\bdo not stop\b",
    r"\bkeep going\b",
    r"\bkeep improving\b",
    r"\bwork forever\b",
    r"\buntil i say stop\b",
    r"\bindefinitely research\b",
    r"\buse this skill\b",
    r"\buse the infinite skill\b",
    r"\buse infinite skill\b",
    r"\buse infinite\b",
]

# Commands the agent must never run: they would change enforcement.
PROTECTED_COMMAND_PATTERNS = [
    r"infinite_guard\.py",
    r"install-openhands-hooks\.sh",
    r"infinite_state\.py\s+(arm|disarm)\b",
    r"stop_hook\.sh",
    r"pretool_hook\.sh",
    r"userprompt_hook\.sh",
    r"\.openhands/hooks/[^\s]*",
    r"\.openhands/guard",
    r"\.infinit[ey]/ARMED",
]

# Paths the agent must never write to (guard state, hook wiring, ledger arming).
PROTECTED_PATH_PATTERNS = [
    r"\.openhands/guard",
    r"\.openhands/hooks\.json",
    r"\.openhands/hooks/[^\s]*infinite",
]

# A destructive verb applied to the enforcement tree as a whole.
DESTRUCTIVE_COMMAND = r"(rm|rmdir|mv|truncate|shred|unlink|chmod|chown|sed\s+-i|tee|>>?)\b"
PROTECTED_TREE = r"\.openhands\b|\binfinite_guard\b|\binfinite_(-stop|-pretool|-userprompt)\.sh\b"


# --------------------------------------------------------------------------- #
# small utilities
# --------------------------------------------------------------------------- #
def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default: dict | None = None) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default or {})


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def find_project(start: str | None = None) -> Path:
    here = Path(start or os.environ.get("OPENHANDS_PROJECT_DIR") or os.getcwd()).expanduser()
    try:
        here = here.resolve()
    except OSError:
        here = Path.cwd()
    if here.name == "guard" and here.parent.name == ".openhands":
        return here.parent.parent
    for candidate in [here, *here.parents]:
        if (candidate / GUARD_DIR).is_dir():
            return candidate
        if (candidate / ".infinite").is_dir():
            return candidate
        if (candidate / ".openhands" / "hooks.json").exists():
            return candidate
    return here


def project_from_arg(explicit: str | None) -> Path:
    if not explicit:
        return find_project()
    given = Path(explicit).expanduser()
    try:
        given = given.resolve()
    except OSError:
        pass
    if given.name == "guard":
        return given.parent.parent
    if given.name == ".infinite":
        return given.parent
    if given.name == ".openhands":
        return given.parent
    return given


def log_event(project: Path, event: str, **fields) -> None:
    try:
        append_jsonl(project / GUARD_DIR / "events.jsonl", {"ts": now(), "event": event, **fields})
    except OSError:
        pass


def emit_deny(reason: str, context: str = "") -> int:
    """Deny an operation.

    OpenHands' Stop path forwards only ``additionalContext`` to the agent (the
    ``reason`` goes to the UI/logs), so the actionable half of a denial must be
    included in both fields.
    """
    payload = {"decision": "deny", "reason": reason}
    additional = reason if not context else f"{reason}\n\n{context}"
    payload["additionalContext"] = additional
    print(json.dumps(payload))
    return 2


def emit_allow(reason: str = "") -> int:
    if reason:
        print(json.dumps({"decision": "allow", "reason": reason}))
    return 0


def read_stdin() -> str:
    if sys.stdin.isatty():
        return ""
    try:
        return sys.stdin.read()
    except OSError:
        return ""


# --------------------------------------------------------------------------- #
# policy blob: immutable for the lifetime of the conversation
# --------------------------------------------------------------------------- #
def encode_policy(policy: dict) -> str:
    raw = json.dumps(policy, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_policy(blob: str) -> dict:
    padded = blob + "=" * (-len(blob) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))


def policy_digest(policy: dict) -> str:
    raw = json.dumps(policy, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# gates and ledger
# --------------------------------------------------------------------------- #
def run_gate(project: Path, gate: dict) -> dict:
    name = str(gate.get("name") or gate.get("command") or "gate")
    command = str(gate.get("command") or "")
    timeout = int(gate.get("timeout") or DEFAULT_TIMEOUT)
    if not command:
        return {"name": name, "ok": False, "status": "no command", "tail": ""}
    try:
        proc = subprocess.run(  # noqa: S602 - commands come from the user's install
            command,
            shell=True,
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"name": name, "ok": False, "status": f"timeout after {timeout}s", "tail": ""}
    except OSError as exc:
        return {"name": name, "ok": False, "status": f"error: {exc}", "tail": ""}
    output = f"{proc.stdout}\n{proc.stderr}".strip()
    return {
        "name": name,
        "ok": proc.returncode == 0,
        "status": f"exit {proc.returncode}",
        "tail": "\n".join(output.splitlines()[-MAX_TAIL_LINES:]),
    }


def research_helper_path(project: Path) -> Path | None:
    candidates = [
        project / ".openhands" / "hooks" / "infinite_research.py",
        project / "infinite" / "scripts" / "infinite_research.py",
        project / ".agents" / "skills" / "infinite" / "scripts" / "infinite_research.py",
        Path(__file__).resolve().with_name("infinite_research.py"),
    ]
    return next((c for c in candidates if c.is_file()), None)


def run_research_validator(project: Path) -> dict:
    """Built-in deterministic gate for the fixed Book of Mormon task.

    This is not a prompt instruction and not a removable shell gate: the Stop
    hook itself validates the append-only ledger, alternating rounds, evidence
    schema, provenance caps, dedup keys, cross-side references, and both report
    digests before it allows a finish.
    """
    helper = research_helper_path(project)
    if helper is None:
        return {"name": "research-validator", "ok": False, "status": "missing helper",
                "tail": "infinite_research.py not found; reinstall the skill enforcement"}
    try:
        proc = subprocess.run(
            [sys.executable or "python3", str(helper), "--dir", str(project), "validate"],
            capture_output=True, text=True, timeout=30, cwd=str(project),
        )
    except subprocess.TimeoutExpired:
        return {"name": "research-validator", "ok": False, "status": "timeout after 30s", "tail": ""}
    except OSError as exc:
        return {"name": "research-validator", "ok": False, "status": f"error: {exc}", "tail": ""}
    output = f"{proc.stdout}\n{proc.stderr}".strip()
    return {"name": "research-validator", "ok": proc.returncode == 0,
            "status": f"exit {proc.returncode}",
            "tail": "\n".join(output.splitlines()[-MAX_TAIL_LINES:])}


def gate_report(gates: list[dict]) -> str:
    if not gates:
        return "Gates: none configured."
    summary = "; ".join(
        f"{gate['name']}: {'PASS' if gate['ok'] else 'FAIL'} ({gate['status']})" for gate in gates
    )
    detail = "".join(
        f"\n--- {gate['name']} output ---\n{gate['tail']}" for gate in gates if not gate["ok"] and gate["tail"]
    )
    return "Gates: " + summary + detail


def ledger_status(project: Path, policy: dict) -> dict:
    rounds = [e for e in read_jsonl(project / LEDGER_REL) if e.get("event") == "round"]
    armed_at = str(policy.get("armed_at") or "")
    since = [r for r in rounds if str(r.get("ts") or "") >= armed_at] if armed_at else rounds
    last = rounds[-1] if rounds else {}
    return {
        "rounds_total": len(rounds),
        "rounds_since_arm": len(since),
        "last_round": last.get("round"),
        "last_target": last.get("target"),
        "last_verified": bool(last.get("verification")) and bool(last.get("next")),
    }


def ledger_round_label(project: Path) -> object:
    rounds = [e for e in read_jsonl(project / LEDGER_REL) if e.get("event") == "round"]
    return rounds[-1].get("round") if rounds else None


def loop_context(project: Path, profile: str = "generic") -> str:
    if profile == RESEARCH_PROFILE:
        state = read_json(project / ".infinite" / "state.json", {})
        side = state.get("next_side", "for")
        dry = int(state.get("dry_rounds", 0))
        depth = " After three dry rounds, deepen primary-text/dependency work; after six, revisit uncertain and confident claims." if dry >= 3 else ""
        return (
            f"Fixed Book of Mormon research protocol: read references/fixed-task.md and infinite/SKILL.md "
            f"(or the loaded skill directory), restore the ledger, and start the next {side} round. "
            "Execute ALL SIX coded prompt steps per item: (1) authenticate with at least three recorded "
            "checks, (2) read full context/POV, (3) check multiple sources and cite multiple pieces of "
            "evidence (corroboration), (4) evaluate the strongest counters, (5) score credibility/"
            "accuracy/relevance/usefulness with specific reasons plus the one computed overall score, "
            "(6) record the extensive investigation (queries, sources consulted, leads ruled out, depth). "
            "Deduplicate, compare against the other side, record the item and round, compile all three "
            "reports (for/against/comparison, mirrored to Google Docs), and validate. Alternate "
            "sides even after a rejected or fruitless round; log searches and access limits honestly."
            + depth + " Only an explicit user stop ends research; then compile the three final reports "
            "and sync the final Google Docs. "
            f"Enforcement ({project / GUARD_DIR}) belongs to the user; do not edit or bypass it."
        )
    return (
        "Infinite loop protocol: (1) re-read the latest user message and stop only if it "
        "explicitly says stop; (2) snapshot state and re-run the checks; (3) pick the "
        "weakest part by impact x confidence / effort; (4) make one meaningful change; "
        "(5) verify with the specific check and the full suite; (6) log the round and "
        "post one short progress line, then repeat. Enforcement is owned by the user "
        f"({project / GUARD_DIR}); do not edit, delete, or bypass it."
    )


# --------------------------------------------------------------------------- #
# stop
# --------------------------------------------------------------------------- #
def cmd_stop(payload: dict, project: Path, policy: dict | None, policy_supplied: bool = False) -> int:
    if policy is None and policy_supplied:
        # --policy was given but is unreadable/tampered. Never fall back to a
        # file the agent can write; fail closed.
        return emit_deny(
            "Infinite mode: the per-session enforcement policy could not be read, so "
            "finishing cannot be verified and is denied. Do not attempt to repair or "
            "rewrite the hook - it belongs to the user. Continue the loop; the user can "
            "end infinite mode with scripts/install-openhands-hooks.sh --disarm.",
            "Fail-closed: the agent cannot substitute its own policy.",
        )
    if policy is None:
        # No policy argument at all (manual invocation): use the on-disk mirror.
        policy = read_json(project / GUARD_DIR / "config.json")
    if not policy:
        # Never installed. If an infinite hook is still wired we cannot verify
        # anything, so fail closed; otherwise this hook is irrelevant.
        try:
            wired = "infinite" in (project / ".openhands" / "hooks.json").read_text(encoding="utf-8")
        except OSError:
            wired = False
        if not wired:
            return emit_allow()
        return emit_deny(
            "Infinite mode: enforcement state is missing while the Stop hook is still "
            "registered. Do not recreate or edit .openhands/guard - that belongs to the "
            "user. Continue the loop; to end infinite mode the user must run the "
            "installer with --disarm or --uninstall.",
            "Fail-closed: enforcement files are user-owned.",
        )

    mode = str(policy.get("mode") or "required")
    stop_requested = policy.get("profile") == RESEARCH_PROFILE and (project / GUARD_DIR / STOP_REQUESTED).exists()
    if mode == "disabled" or (project / GUARD_DIR / "DISARMED").exists():
        log_event(project, "stop_allowed", mode=mode, round=ledger_round_label(project))
        return emit_allow()
    if mode == "standby" and not (project / GUARD_DIR / ARMED).exists():
        log_event(project, "stop_allowed", mode=mode, reason="standby; fixed skill not invoked")
        return emit_allow()

    ledger = ledger_status(project, policy)
    attempts_file = project / GUARD_DIR / "attempts.json"
    attempts = read_json(attempts_file, {"count": 0, "last_round": None})
    attempts["count"] = int(attempts.get("count", 0)) + 1
    repeated = attempts.get("last_round") == ledger["last_round"]
    attempts["last_round"] = ledger["last_round"]
    attempts["updated_at"] = now()
    attempts["session"] = payload.get("session_id") or attempts.get("session")
    write_json(attempts_file, attempts)

    if mode == "always" and policy.get("profile") != RESEARCH_PROFILE:
        gates: list[dict] = []
    else:
        gates = [run_gate(project, gate) for gate in policy.get("gates", [])]
    if policy.get("profile") == RESEARCH_PROFILE:
        # The fixed research task has a built-in validator gate. It is not a
        # shell gate the agent can delete from the policy, and it still runs
        # when the user installs with --no-gates or chooses mode=always.
        gates.append(run_research_validator(project))
    failing = [gate for gate in gates if not gate["ok"]]

    if stop_requested:
        report = gate_report(gates)
        if failing:
            log_event(project, "finalization_denied", round=ledger["last_round"], failing=[g["name"] for g in failing])
            return emit_deny(
                "Research has stopped at the user's request, but the final reports are not ready. "
                "Do not resume searching. Reconcile the existing ledger, run compile --final, fix "
                "validation errors, sync the three Google Docs (google_docs.py sync --mode final), "
                "and present all three reports (for, against, comparison) with their Google Docs "
                "links. " + report,
                "Finalization only: use recorded findings; no new research round. The user may "
                "override with the installer's --disarm command.",
            )
        if mode == "standby":
            (project / GUARD_DIR / ARMED).unlink(missing_ok=True)
            (project / GUARD_DIR / STOP_REQUESTED).unlink(missing_ok=True)
        log_event(project, "stop_allowed", reason="user stop; final reports validated", round=ledger["last_round"])
        return emit_allow("Research stopped; all three final reports (for, against, comparison) and their Google Docs passed the deterministic research gate.")

    require_rounds = int(policy.get("require_rounds") or 0)
    needs_round = ledger["rounds_since_arm"] < require_rounds
    no_evidence = require_rounds > 0 and not ledger["last_verified"]

    ledger_report = (
        f"Rounds logged: {ledger['rounds_total']} ({ledger['rounds_since_arm']} since arming). "
        f"Last round: {ledger['last_round'] or 'none'} - target: {ledger['last_target'] or 'none'} - "
        f"verification recorded: {'yes' if ledger['last_verified'] else 'no'}."
    )
    report = gate_report(gates) + " " + ledger_report

    if mode == "allow-when-green":
        if gates and not failing and not needs_round and not no_evidence and not repeated:
            log_event(project, "stop_allowed", mode=mode, round=ledger["last_round"])
            return emit_allow("Infinite mode: every gate is green and a verified round was logged.")
        log_event(
            project,
            "stop_denied",
            mode=mode,
            round=ledger["last_round"],
            failing=[gate["name"] for gate in failing],
            needs_round=needs_round,
            repeated=repeated,
        )
        return emit_deny(
            "Infinite mode is ON (allow-when-green): finishing requires every gate to pass and "
            "a newly verified round since the last attempt. " + report,
            loop_context(project, str(policy.get("profile", "generic"))),
        )

    if failing:
        head = (
            f"Infinite mode is ON ({mode}). Finishing is blocked because {len(failing)} gate(s) "
            "fail. Fix them, log the round, and continue."
        )
    elif needs_round or no_evidence:
        head = (
            f"Infinite mode is ON ({mode}). Finishing is blocked because no verified round has "
            "been logged since this mode was armed. Do a round: audit, improve, verify, log."
        )
    elif repeated:
        head = (
            "Infinite mode is ON and you attempted to finish again without completing a new "
            "round. That is exactly what this guard blocks. Complete a round now: pick the "
            "weakest part, change it, verify it, log it, then continue to the next round."
        )
    elif policy.get("profile") == RESEARCH_PROFILE:
        head = (
            f"Infinite research mode is ON ({mode}). A completed search or report is not a stop. "
            "Start the next alternating for/against evidence round now; execute all six coded "
            "prompt steps per item (authenticate, contextualize, corroborate with multiple "
            "sources, evaluate counters, score with reasons, investigate extensively), "
            "deduplicate, compare, log, compile all three reports, sync Google Docs, and validate."
        )
    else:
        head = (
            f"Infinite mode is ON ({mode}). The task being complete is not a stop condition. "
            "Start the next round now: audit the current state, pick the single weakest part, "
            "improve it, verify it, log it, repeat."
        )
    log_event(
        project,
        "stop_denied",
        mode=mode,
        round=ledger["last_round"],
        failing=[gate["name"] for gate in failing],
        needs_round=needs_round,
        repeated=repeated,
    )
    return emit_deny(head + " " + report, loop_context(project, str(policy.get("profile", "generic"))))


# --------------------------------------------------------------------------- #
# pretool: the agent may not touch enforcement
# --------------------------------------------------------------------------- #
TERMINAL_TOOL = re.compile(r"terminal|bash|shell|exec|command|cmd|run", re.I)
PATH_KEYS = {"path", "file_path", "filename", "file", "target", "destination"}


def protected_reason(tool_name: str, tool_input: dict) -> str | None:
    """Enforcement is off limits to the agent.

    Terminal-style tools are denied whenever they touch enforcement paths or
    names at all. File-editing tools are denied only when the *path* they edit
    is protected, so documentation may still mention these paths.
    """
    strings = {
        key: value
        for key, value in tool_input.items()
        if isinstance(value, str)
    }
    name = str(tool_name or "")
    is_terminal = bool(TERMINAL_TOOL.search(name)) if name else "command" in strings

    for key, value in strings.items():
        if is_terminal and re.search(PROTECTED_TREE, value, re.I):
            return (
                "Blocked: this command references infinite-mode enforcement, which only "
                "the user controls. Do not run, read, edit, delete, or bypass the guard. "
                "Continue the loop: audit, improve, verify, log, repeat."
            )
        targets_enforcement = key in PATH_KEYS or is_terminal
        if targets_enforcement and any(re.search(p, value, re.I) for p in PROTECTED_PATH_PATTERNS):
            return (
                "Blocked: this path holds infinite-mode enforcement state. The user owns "
                "it, not the agent. Continue the loop instead of changing the guard."
            )
        if targets_enforcement and any(re.search(p, value, re.I) for p in PROTECTED_COMMAND_PATTERNS):
            return (
                "Blocked: this would operate on infinite-mode enforcement. Only the user "
                "can arm, disarm, or remove it. Continue the loop instead."
            )
    return None


RESEARCH_WRITE_PATHS = [
    r"(^|[^A-Za-z0-9_])\.infinite/ledger\.jsonl\b",
    r"(^|[^A-Za-z0-9_])\.infinite/state\.json\b",
    r"(^|[^A-Za-z0-9_])\.infinite/gdocs(-oauth|-sa)?\.json\b",
    r"(^|[^A-Za-z0-9_])research/book-of-mormon-(for|against|comparison)\.md\b",
]
RESEARCH_CODE_PATHS = [
    r"(^|[^A-Za-z0-9_])infinite_(research|state|guard)\.py\b",
    r"(^|[^A-Za-z0-9_])google_docs\.py\b",
    r"(^|[^A-Za-z0-9_])install-openhands-hooks\.sh\b",
    r"(^|[^A-Za-z0-9_])(stop|pretool|userprompt)_hook\.sh\b",
    r"(^|[^A-Za-z0-9_])infinite-(stop|pretool|userprompt)\.sh\b",
]
WRITE_VERB = re.compile(
    r"(\brm\b|\brmdir\b|\bmv\b|\bcp\b|\btruncate\b|\bshred\b|\bunlink\b|"
    r"\bsed\s+-i|\btee\b|>{1,2}|\bchmod\b|\bchown\b|\bdd\b|"
    r"\bopen\s*\([^)]*['\"][wax]|\bwrite_text\b|\bwrite_bytes\b|\bjson\.dump\b)",
    re.I,
)
READ_ONLY_TOOL = re.compile(r"read|view|cat|grep|list", re.I)


def research_active(project: Path, policy: dict | None) -> bool:
    if policy is not None:
        return policy.get("profile") == RESEARCH_PROFILE and policy.get("mode") != "disabled"
    config = read_json(project / GUARD_DIR / "config.json", {})
    state = read_json(project / ".infinite" / "state.json", {})
    return (config.get("profile") == RESEARCH_PROFILE or state.get("profile") == RESEARCH_PROFILE) and config.get("mode", "required") != "disabled"


def research_protected_reason(tool_name: str, tool_input: dict, project: Path, policy: dict | None) -> str | None:
    """Deterministic anti-tamper rules for the fixed Book of Mormon task.

    The ledger, state, generated reports, and validating helpers are not
    hand-editable by the agent. Reads and helper invocations are allowed;
    writes must go through the helper that enforces the research schema.
    """
    if not research_active(project, policy):
        return None
    strings = {k: v for k, v in tool_input.items() if isinstance(v, str)}
    name = str(tool_name or "")
    is_terminal = bool(TERMINAL_TOOL.search(name)) if name else "command" in strings
    if is_terminal:
        command = strings.get("command", "")
        if not command:
            return None
        write_paths = any(re.search(p, command) for p in RESEARCH_WRITE_PATHS)
        code_paths = any(re.search(p, command) for p in RESEARCH_CODE_PATHS)
        helper = re.search(r"infinite_(research|state)\.py|google_docs\.py", command)
        if helper:
            if re.search(r"infinite_state\.py[^\n]*\b(arm|disarm)\b", command):
                return "Blocked: arming/disarming is user-owned. Continue the fixed research task."
            stopped = (project / GUARD_DIR / STOP_REQUESTED).exists()
            if re.search(r"infinite_research\.py[^\n]*\bcompile\b[^\n]*--final", command) and not stopped:
                return ("Blocked: final reports may be compiled only after the user says stop. "
                        "The user-stop hook has not recorded STOP_REQUESTED. Continue interim research rounds.")
            if re.search(r"google_docs\.py[^\n]*\bsync\b[^\n]*--mode\s+final", command) and not stopped:
                return ("Blocked: the Google Docs final sync may run only after the user says stop "
                        "(STOP_REQUESTED is not recorded). Continue interim research rounds; interim "
                        "syncs happen automatically on compile.")
            if stopped and re.search(r"infinite_state\.py[^\n]*\b(resume|log)\b", command):
                return ("Blocked: research is stopped. Only a real user continue/resume message re-arms the loop; "
                        "until then only final-report reconciliation is allowed.")
            if stopped and re.search(r"infinite_research\.py[^\n]*\b(evidence|revise|search|note)\b", command):
                return ("Blocked: research is stopped. Do not record new evidence/searches; reconcile the existing "
                        "ledger and compile final reports.")
            chained_code_write = code_paths and re.search(
                r"(?:\brm\b|\bmv\b|\bcp\b|\btruncate\b|\bshred\b|\bunlink\b|\bchmod\b|\bchown\b|\bdd\b|\bsed\s+-i|\btee\b|>{1,2})[^;|&]*(?:infinite_(?:research|state|guard)|google_docs)\.py",
                command,
            )
            if WRITE_VERB.search(command) and (write_paths or chained_code_write):
                return "Blocked: write research state/reports through the validating helper, not shell redirection or chained edits."
            return None
        if re.search(r"\bpython\d*(?:\.\d+)?\s+(?:-c|-m|-)\b", command) and (write_paths or code_paths):
            return ("Blocked: inline interpreters may not write the research ledger, state, reports, or validating helpers. "
                    "Use the research helper commands instead.")
        if WRITE_VERB.search(command) and (write_paths or code_paths):
            return ("Blocked: the research ledger, generated reports, and validating helpers are not hand-editable. "
                    "Use the validating research helper for ledger/report writes; continue the fixed task.")
        return None
    path_values = [v for k, v in strings.items() if k in PATH_KEYS]
    command = str(tool_input.get("command", ""))
    read_intent = bool(READ_ONLY_TOOL.search(name)) or command.lower() in {"view", "read", "cat"}
    write_intent = any(k in tool_input for k in ("file_text", "content", "new_str", "old_str", "text")) or re.search(r"create|write|replace|insert|delete|edit|undo", command, re.I)
    if not read_intent and (write_intent or path_values):
        for value in path_values:
            if any(re.search(p, value) for p in RESEARCH_WRITE_PATHS + RESEARCH_CODE_PATHS):
                return ("Blocked: this path is deterministic research/enforcement state. Read it if needed, but write "
                        "ledger/reports only through the validating helper and never edit the validating helpers.")
    return None


def cmd_pretool(payload: dict, project: Path, policy: dict | None = None) -> int:
    if not (project / GUARD_DIR).exists() and not enforcement_installed(project):
        return emit_allow()  # enforcement not installed here: nothing to protect
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {"raw": str(tool_input)}
    reason = protected_reason(str(payload.get("tool_name") or ""), tool_input)
    if reason is None:
        reason = research_protected_reason(str(payload.get("tool_name") or ""), tool_input, project, policy)
    if reason:
        append_jsonl(
            project / GUARD_DIR / "events.jsonl",
            {
                "ts": now(),
                "event": "pretool_denied",
                "tool": payload.get("tool_name"),
                "input": str(tool_input)[:500],
            },
        )
        return emit_deny(reason)
    return emit_allow()


# --------------------------------------------------------------------------- #
# userprompt: only a real user message can arm or disarm
# --------------------------------------------------------------------------- #
MAX_COMMAND_WORDS = 6
TASK_VERB = re.compile(
    r"^\s*(add|build|create|implement|fix|write|refactor|make|update|remove|change|"
    r"design|draw|improve|test|debug|explain|why|how|what|where|who|convert|generate|"
    r"review|check|run|install|deploy|rename|move|delete|continue|keep)\b",
    re.I,
)


def enforcement_installed(project: Path) -> bool:
    if (project / GUARD_DIR).is_dir():
        return True
    try:
        return "infinite" in (project / ".openhands" / "hooks.json").read_text(encoding="utf-8")
    except OSError:
        return False


def cmd_userprompt(payload: dict, project: Path, policy: dict | None = None) -> int:
    message = str(payload.get("message") or payload.get("prompt") or payload.get("content") or "")
    if not message or not enforcement_installed(project):
        return emit_allow()

    words = len(message.split())
    is_task = bool(TASK_VERB.search(message))
    short = words <= MAX_COMMAND_WORDS and not is_task
    # Slash commands are unambiguous even inside a longer message.
    explicit = bool(re.search(r"(^|\s)/(stop|halt|cancel|quit)\b", message, re.I))
    research_stop = bool(re.search(r"^\s*(?:please\s+)?stop (?:researching|research|the research)\b", message, re.I))
    research_arm = bool(re.search(r"\bindefinitely research\b", message, re.I))
    negated_fixed = bool(re.search(r"\b(?:do not|don't|never)\s+use (?:this|the infinite|infinite) skill\b", message, re.I))
    fixed_invocation = bool(re.search(r"(^|\s)(?:please\s+)?use (?:this|the infinite|infinite) skill\b", message, re.I)) and not negated_fixed
    fixed_resume = bool(re.search(r"^\s*(?:please\s+)?(?:continue|resume)(?:\s+(?:the\s+)?research)?\s*[.!]?\s*$", message, re.I))

    def hit(patterns: list[str]) -> bool:
        return any(re.search(pattern, message, re.I) for pattern in patterns)

    # "add a stop button to the UI" must not disarm: prose only counts when it is
    # short enough to be an instruction, or when it uses an explicit command.
    if (short and hit(STOP_PATTERNS)) or explicit or research_stop:
        (project / GUARD_DIR).mkdir(parents=True, exist_ok=True)
        state = read_json(project / ".infinite" / "state.json", {})
        config = read_json(project / GUARD_DIR / "config.json", {})
        if policy is not None:
            mode = policy.get("mode")
            research_active = policy.get("profile") == RESEARCH_PROFILE and mode != "disabled" and (mode != "standby" or (project / GUARD_DIR / ARMED).exists())
        else:
            mode = config.get("mode", "required")
            research_active = state.get("profile") == RESEARCH_PROFILE and mode != "disabled" and (mode != "standby" or (project / GUARD_DIR / ARMED).exists())
        if research_active:
            (project / GUARD_DIR / STOP_REQUESTED).write_text(
                f"stop requested {now()} by user message: {message[:200]}\n", encoding="utf-8"
            )
            append_jsonl(
                project / GUARD_DIR / "events.jsonl",
                {"ts": now(), "event": "stop_requested", "source": "user_message", "message": message[:200]},
            )
            return emit_allow(
                "Stop research now. Do not start another round. Reconcile recorded findings, "
                "run the research helper's compile --final, sync the three Google Docs "
                "(google_docs.py sync --mode final), run validate, then present all three reports "
                "(for, against, comparison) with their Google Docs links. "
                "The Stop hook allows finishing once the configured final-report gates pass."
            )
        (project / GUARD_DIR / "DISARMED").write_text(
            f"disarmed {now()} by user message: {message[:200]}\n", encoding="utf-8"
        )
        append_jsonl(
            project / GUARD_DIR / "events.jsonl",
            {"ts": now(), "event": "disarm", "source": "user_message", "message": message[:200]},
        )
        return emit_allow("Infinite mode disarmed by the user's stop message.")
    arm_explicit = bool(re.search(r"(^|\s)/(infinite|forever|never-stop)\b", message, re.I))
    if (words <= MAX_COMMAND_WORDS and hit(ARM_PATTERNS) and not negated_fixed) or arm_explicit or research_arm or fixed_invocation or fixed_resume:
        (project / GUARD_DIR).mkdir(parents=True, exist_ok=True)
        (project / GUARD_DIR / "DISARMED").unlink(missing_ok=True)
        (project / GUARD_DIR / STOP_REQUESTED).unlink(missing_ok=True)
        arm_mode = (policy or {}).get("mode") or read_json(project / GUARD_DIR / "config.json", {}).get("mode")
        if arm_mode == "standby":
            (project / GUARD_DIR / ARMED).write_text(f"armed {now()} by user message: {message[:200]}\n", encoding="utf-8")
        append_jsonl(
            project / GUARD_DIR / "events.jsonl",
            {"ts": now(), "event": "arm", "source": "user_message", "message": message[:200]},
        )
        return emit_allow("Infinite mode armed by the user's message.")
    return emit_allow()


# --------------------------------------------------------------------------- #
# user-side commands
# --------------------------------------------------------------------------- #
def detect_gates(project: Path) -> list[dict]:
    gates: list[dict] = []
    seen: set[str] = set()

    def add(name: str, command: str) -> None:
        if name not in seen:
            seen.add(name)
            gates.append({"name": name, "command": command, "timeout": DEFAULT_TIMEOUT})

    package = read_json(project / "package.json")
    scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
    if "test" in scripts:
        add("tests", "npm test --silent")
    if "lint" in scripts:
        add("lint", "npm run lint --silent")
    if any((project / p).exists() for p in ("pyproject.toml", "pytest.ini", "tests", "test")):
        add("tests", "python3 -m pytest -q")
    if any((project / p).exists() for p in ("ruff.toml", ".ruff.toml")):
        add("lint", "python3 -m ruff check .")
    if (project / "go.mod").exists():
        add("tests", "go test ./...")
    if (project / "Cargo.toml").exists():
        add("tests", "cargo test --quiet")
    makefile = project / "Makefile"
    if makefile.exists():
        text = makefile.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"^test:", text, re.M):
            add("tests", "make test")
        if re.search(r"^lint:", text, re.M):
            add("lint", "make lint")
    return gates


def probe_gate(gate: dict) -> tuple[bool, str]:
    """Return (available, reason).

    A gate whose runner is not installed can never pass, so it must not be armed:
    that would deny every finish for a reason the agent cannot fix. Probing is
    static (no test execution), so it costs milliseconds at install time.
    """
    command = str(gate.get("command") or "").strip()
    if not command:
        return False, "empty command"
    try:
        tokens = shlex.split(command)
    except ValueError:
        return True, "unparsed command"
    if not tokens:
        return False, "empty command"

    # `python3 -m <module>` / `python -m <module>`
    if len(tokens) >= 3 and re.match(r"^python[0-9.]*$", tokens[0]) and tokens[1] == "-m":
        module = tokens[2]
        try:
            proc = subprocess.run(
                [tokens[0], "-c", f"import importlib.util,sys;sys.exit(0 if importlib.util.find_spec({module!r}) else 1)"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                return False, f"python module '{module}' is not installed"
        except (OSError, subprocess.TimeoutExpired):
            return False, f"cannot run {tokens[0]}"
        return True, "ok"

    # npm/pnpm/yarn/cargo/go/make: the runner itself must exist
    if shutil.which(tokens[0]) is None:
        return False, f"'{tokens[0]}' is not installed"
    # Runner availability is probed statically; the gate itself reports failures.
    return True, "ok"


def partition_gates(project: Path, gates: list[dict]) -> tuple[list[dict], list[dict]]:
    available, skipped = [], []
    for gate in gates:
        gate = dict(gate)
        gate.setdefault("project", str(project))
        ok, reason = probe_gate(gate)
        gate.pop("project", None)
        if ok:
            available.append(gate)
        else:
            skipped.append({"name": gate.get("name"), "command": gate.get("command"), "reason": reason})
    return available, skipped


def parse_gates(specs: list[str]) -> list[dict]:
    gates = []
    for spec in specs:
        if ":" in spec:
            name, command = spec.split(":", 1)
        else:
            name, command = spec, spec
        gates.append(
            {"name": name.strip(), "command": command.strip(), "timeout": DEFAULT_TIMEOUT}
        )
    return gates


def build_policy(project: Path, mode: str, gates: list[dict], require_rounds: int, profile: str = "generic") -> dict:
    return {
        "v": 2,
        "profile": profile,
        "mode": mode,
        "gates": gates,
        "require_rounds": require_rounds,
        "armed_at": now(),
    }


def cmd_policy(args) -> int:
    project = project_from_arg(args.dir)
    gates = parse_gates(args.gate or [])
    if not gates and not args.no_gates:
        gates = detect_gates(project)
    mode = args.mode or "required"
    if mode not in {"required", "always", "allow-when-green", "disabled", "standby"}:
        print(f"unknown mode: {mode}", file=sys.stderr)
        return 2
    gates, skipped = partition_gates(project, gates)
    for item in skipped:
        print(
            f"warning: skipping gate '{item['name']}' ({item['command']}): {item['reason']}",
            file=sys.stderr,
        )
    policy = build_policy(project, mode, gates, int(args.require_rounds), RESEARCH_PROFILE if args.research else "generic")
    if skipped:
        policy["skipped_gates"] = skipped
    print(encode_policy(policy))
    return 0


def cmd_arm(args) -> int:
    project = project_from_arg(args.dir)
    gates = parse_gates(args.gate or [])
    existing = read_json(project / GUARD_DIR / "config.json")
    if not gates and not args.no_gates:
        gates = existing.get("gates") or detect_gates(project)
    gates, skipped = partition_gates(project, gates)
    for item in skipped:
        print(f"warning: skipping gate '{item['name']}': {item['reason']}", file=sys.stderr)
    policy = build_policy(
        project,
        args.mode or "required",
        gates,
        int(args.require_rounds if args.require_rounds is not None else 1),
        RESEARCH_PROFILE if args.research else existing.get("profile", "generic"),
    )
    if skipped:
        policy["skipped_gates"] = skipped
    write_json(project / GUARD_DIR / "config.json", {**policy, "policy_blob": encode_policy(policy)})
    (project / GUARD_DIR / "DISARMED").unlink(missing_ok=True)
    (project / GUARD_DIR / STOP_REQUESTED).unlink(missing_ok=True)
    if policy["mode"] == "standby":
        (project / GUARD_DIR / ARMED).unlink(missing_ok=True)
    write_json(project / GUARD_DIR / "attempts.json", {"count": 0, "last_round": None})
    append_jsonl(
        project / GUARD_DIR / "events.jsonl",
        {"ts": now(), "event": "arm", "mode": policy["mode"], "gates": [g["name"] for g in gates]},
    )
    print(f"armed infinite mode ({policy['mode']}) in {project}")
    for gate in gates:
        print(f"  gate: {gate['name']}: {gate['command']}")
    if not gates:
        print("  gates: none (finish denial is unconditional)")
    print(f"  policy: {encode_policy(policy)}")
    return 0


def cmd_disarm(args) -> int:
    project = project_from_arg(args.dir)
    config = read_json(project / GUARD_DIR / "config.json")
    reason = args.reason or "user said stop"
    (project / GUARD_DIR).mkdir(parents=True, exist_ok=True)
    (project / GUARD_DIR / "DISARMED").write_text(f"disarmed {now()}: {reason}\n", encoding="utf-8")
    (project / GUARD_DIR / ARMED).unlink(missing_ok=True)
    if config:
        config["mode"] = "disabled"
        config["disarmed_at"] = now()
        config["disarmed_reason"] = reason
        write_json(project / GUARD_DIR / "config.json", config)
    append_jsonl(
        project / GUARD_DIR / "events.jsonl",
        {"ts": now(), "event": "disarm", "source": "installer", "reason": reason},
    )
    print(f"disarmed infinite mode in {project} ({reason}) - the agent may finish normally")
    return 0


def cmd_status(args) -> int:
    project = project_from_arg(args.dir)
    config = read_json(project / GUARD_DIR / "config.json")
    if not config:
        print(f"infinite mode: not installed in {project}")
        return 0
    ledger = ledger_status(project, config)
    attempts = read_json(project / GUARD_DIR / "attempts.json", {})
    disarmed = (project / GUARD_DIR / "DISARMED").exists()
    print(f"project    : {project}")
    print(f"mode       : {config.get('mode')}{' (disarmed)' if disarmed else ''}")
    print(f"armed at   : {config.get('armed_at')}")
    print(f"gates      : {', '.join(g['name'] for g in config.get('gates', [])) or 'none'}")
    skipped = config.get("skipped_gates") or []
    if skipped:
        for item in skipped:
            print(f"  skipped  : {item.get('name')} ({item.get('reason')})")
    print(f"rounds     : {ledger['rounds_total']} total / {ledger['rounds_since_arm']} since arming")
    print(f"last round : {ledger['last_round']} (verified: {ledger['last_verified']})")
    print(f"attempts   : {attempts.get('count', 0)} finish attempts recorded")
    print(f"policy     : {policy_digest(config)}  (hash of the immutable per-session policy)")
    return 0


def cmd_doctor(args) -> int:
    project = project_from_arg(args.dir)
    config = read_json(project / GUARD_DIR / "config.json")
    if not config:
        print(f"infinite mode: not installed in {project}")
        return 1
    gates = config.get("gates", [])
    print(f"evaluating {len(gates)} gate(s) in {project}")
    failed = 0
    for gate in gates:
        result = run_gate(project, gate)
        print(f"  {'PASS' if result['ok'] else 'FAIL'}  {result['name']} ({result['status']})")
        if not result["ok"]:
            failed += 1
            if result["tail"]:
                print("        " + result["tail"].replace("\n", "\n        "))
    return 1 if failed else 0


def cmd_uninstall(args) -> int:
    project = project_from_arg(args.dir)
    path = project / ".openhands" / "hooks.json"
    config = read_json(path)
    if config:
        kept_entries = []
        for entry in config.get("stop") or []:
            hooks = [h for h in entry.get("hooks", []) if "infinite" not in str(h.get("command", ""))]
            if hooks:
                entry["hooks"] = hooks
                kept_entries.append(entry)
        for key in ("stop", "pre_tool_use", "user_prompt_submit"):
            entries = config.get(key)
            if not isinstance(entries, list):
                continue
            kept = []
            for entry in entries:
                hooks = [h for h in entry.get("hooks", []) if "infinite" not in str(h.get("command", ""))]
                if hooks:
                    entry["hooks"] = hooks
                    kept.append(entry)
            if kept:
                config[key] = kept
            else:
                config.pop(key, None)
        write_json(path, config)
    for name in ("config.json", "attempts.json", "DISARMED", ARMED, STOP_REQUESTED, "events.jsonl"):
        (project / GUARD_DIR / name).unlink(missing_ok=True)
    print(f"uninstalled infinite-mode enforcement from {project}")
    return 0


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 0

    event = argv[0]
    if event in {"stop", "pretool", "userprompt"}:
        argv = argv[1:]
        policy: dict | None = None
        policy_supplied = "--policy" in argv
        if policy_supplied:
            index = argv.index("--policy")
            try:
                policy = decode_policy(argv[index + 1])
            except (IndexError, ValueError, json.JSONDecodeError):
                policy = None
        stdin_text = read_stdin()
        try:
            payload = json.loads(stdin_text or "{}")
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        project = find_project(str(payload.get("working_dir") or "") or None)
        if event == "stop":
            return cmd_stop(payload, project, policy, policy_supplied)
        if event == "pretool":
            if policy_supplied and policy is None:
                return emit_deny(
                    "Infinite mode: the per-session enforcement policy could not be read, "
                    "so tool use cannot be checked against the fixed research protocol.",
                    "Fail-closed: the agent cannot substitute its own policy.",
                )
            return cmd_pretool(payload, project, policy)
        return cmd_userprompt(payload, project, policy)

    import argparse

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", default=argparse.SUPPRESS, help="project directory")
    parser = argparse.ArgumentParser(prog="infinite_guard.py", description=__doc__, parents=[common])
    sub = parser.add_subparsers(dest="sub", required=True)

    policy = sub.add_parser("policy", parents=[common], help="emit the policy blob")
    policy.add_argument("--mode", default=None, choices=["required", "always", "allow-when-green", "disabled", "standby"])
    policy.add_argument("--gate", action="append", metavar="NAME:COMMAND")
    policy.add_argument("--no-gates", action="store_true")
    policy.add_argument("--require-rounds", type=int, default=1)
    policy.add_argument("--research", action="store_true", help="use the Book of Mormon research profile")
    policy.set_defaults(func=cmd_policy)

    arm = sub.add_parser("arm", parents=[common], help="record the policy on disk (user action)")
    arm.add_argument("--mode", default=None, choices=["required", "always", "allow-when-green", "disabled", "standby"])
    arm.add_argument("--gate", action="append", metavar="NAME:COMMAND")
    arm.add_argument("--no-gates", action="store_true")
    arm.add_argument("--require-rounds", type=int, default=None)
    arm.add_argument("--research", action="store_true", help="use the Book of Mormon research profile")
    arm.set_defaults(func=cmd_arm)

    disarm = sub.add_parser("disarm", parents=[common], help="end infinite mode (user action)")
    disarm.add_argument("--reason", default=None)
    disarm.set_defaults(func=cmd_disarm)

    status = sub.add_parser("status", parents=[common], help="show mode, gates, rounds, attempts")
    status.set_defaults(func=cmd_status)

    doctor = sub.add_parser("doctor", parents=[common], help="run the gates and print results")
    doctor.set_defaults(func=cmd_doctor)

    uninstall = sub.add_parser("uninstall", parents=[common], help="remove hooks and guard state")
    uninstall.set_defaults(func=cmd_uninstall)

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # An agent invoking control commands with bad arguments must not get a
        # clean exit; a user reading the terminal sees the usage message.
        return int(exc.code or 0)
    if not hasattr(args, "dir"):
        args.dir = None
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
