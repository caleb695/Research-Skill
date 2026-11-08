#!/usr/bin/env python3
"""State helper for the `infinite` skill.

Keeps the loop durable across context compaction and session restarts, and
provides the armed/disarmed flag that the OpenHands Stop hook reads.

Standard library only. Usage:

    python3 infinite_state.py init --task "fix the parser"
    python3 infinite_state.py status
    python3 infinite_state.py next-target "add property tests for parse_config"
    python3 infinite_state.py log --target "empty input crash" \
        --change "guard len==0 in parse_config" --verification "tests 84/84, lint clean" \
        --next "property tests for parse_config"
    python3 infinite_state.py report

State lives in .infinite/ at the project root by default:
    .infinite/ledger.jsonl   append-only round history (one JSON object per line)
    .infinite/state.json     current round, current target, phase

This helper records progress only. Arming and disarming the loop is the user's
job and lives in the enforcement guard (see openhands-enforcement.md); the agent
is blocked from doing it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DIR = ".infinite"


def state_dir(explicit: str | None) -> Path:
    """Resolve the state directory.

    `explicit` may be either a project directory (state lands in
    `<project>/.infinite`) or the state directory itself.
    """
    if explicit:
        given = Path(explicit).expanduser().resolve()
        if given.name == DEFAULT_DIR or any(
            (given / name).exists() for name in ("state.json", "ledger.jsonl", "ARMED")
        ):
            return given
        return given / DEFAULT_DIR
    env = os.environ.get("INFINITE_STATE_DIR")
    if env:
        return state_dir(env)
    # Walk up so the state is found from subdirectories of a project.
    here = Path.cwd().resolve()
    for candidate in [here, *here.parents]:
        if (candidate / DEFAULT_DIR).is_dir():
            return candidate / DEFAULT_DIR
    return here / DEFAULT_DIR


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)


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


def paths(root: Path) -> dict[str, Path]:
    return {
        "root": root,
        "state": root / "state.json",
        "ledger": root / "ledger.jsonl",
        "armed": root / "ARMED",
    }


def cmd_init(args: argparse.Namespace) -> int:
    root = state_dir(args.dir)
    p = paths(root)
    root.mkdir(parents=True, exist_ok=True)
    state = read_json(
        p["state"],
        {
            "task": args.task or "(unspecified)",
            "round": 0,
            "phase": "audit",
            "next_target": None,
            "armed": False,
            "started_at": now(),
        },
    )
    state["task"] = args.task or state.get("task") or "(unspecified)"
    state["profile"] = args.profile or state.get("profile", "generic")
    if state["profile"] == "book-of-mormon":
        state.setdefault("next_side", "for")
        state.setdefault("dry_rounds", 0)
    state["updated_at"] = now()
    write_json(p["state"], state)
    if args.arm:
        p["armed"].write_text(f"armed {now()}\n", encoding="utf-8")
        state["armed"] = True
        write_json(p["state"], state)
    append_jsonl(p["ledger"], {"ts": now(), "event": "init", "task": state["task"]})
    print(f"initialized infinite loop in {root}")
    print(f"  task: {state['task']}")
    print(f"  armed: {state['armed']}")
    return 0


def cmd_arm(args: argparse.Namespace) -> int:
    root = state_dir(args.dir)
    p = paths(root)
    root.mkdir(parents=True, exist_ok=True)
    p["armed"].write_text(f"armed {now()}\n", encoding="utf-8")
    state = read_json(p["state"], {})
    state["armed"] = True
    state["updated_at"] = now()
    write_json(p["state"], state)
    append_jsonl(p["ledger"], {"ts": now(), "event": "arm", "reason": args.reason})
    print("armed: the loop will not finish until disarmed or the user stops it")
    return 0


def cmd_disarm(args: argparse.Namespace) -> int:
    root = state_dir(args.dir)
    p = paths(root)
    p["armed"].unlink(missing_ok=True)
    state = read_json(p["state"], {})
    state["armed"] = False
    state["updated_at"] = now()
    write_json(p["state"], state)
    append_jsonl(p["ledger"], {"ts": now(), "event": "disarm", "reason": args.reason})
    print("disarmed: the loop may finish normally")
    return 0


def cmd_next_target(args: argparse.Namespace) -> int:
    root = state_dir(args.dir)
    p = paths(root)
    state = read_json(p["state"], {"round": 0, "phase": "audit"})
    state["next_target"] = args.target
    state["phase"] = "improve"
    state["updated_at"] = now()
    write_json(p["state"], state)
    append_jsonl(
        p["ledger"],
        {"ts": now(), "event": "target", "round": state.get("round", 0), "target": args.target},
    )
    print(f"next target: {args.target}")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    root = state_dir(args.dir)
    p = paths(root)
    state = read_json(
        p["state"],
        {"task": "(unspecified)", "round": 0, "phase": "audit", "next_target": None},
    )
    profile = state.get("profile", "generic")
    if profile == "book-of-mormon":
        if state.get("stop_requested"):
            print("research is stopped; compile final reports, or use resume after the user says continue", file=sys.stderr)
            return 2
        if args.side not in {"for", "against"} or args.outcome not in {"accepted", "revised", "rejected", "deepened", "blocked", "no-new"}:
            print("research rounds require --side and --outcome", file=sys.stderr)
            return 2
        expected = state.get("next_side", "for")
        if args.side != expected:
            print(f"research sides must alternate; next side is {expected}", file=sys.stderr)
            return 2
        if not args.verification or not args.next:
            print("research rounds require --verification and --next", file=sys.stderr)
            return 2
        if args.outcome in {"accepted", "revised", "deepened"} and not args.evidence_id:
            print("accepted/revised/deepened research rounds require --evidence-id", file=sys.stderr)
            return 2
        state["next_side"] = "against" if args.side == "for" else "for"
        state["dry_rounds"] = 0 if args.outcome in {"accepted", "revised", "deepened"} else int(state.get("dry_rounds", 0)) + 1
        state["last_side"] = args.side
    state["round"] = int(args.round if args.round is not None else state.get("round", 0) + 1)
    state["phase"] = "audit"
    state["next_target"] = args.next or state.get("next_target")
    state["updated_at"] = now()
    write_json(p["state"], state)
    append_jsonl(
        p["ledger"],
        {
            "ts": now(),
            "event": "round",
            "round": state["round"],
            "profile": profile,
            "side": args.side,
            "outcome": args.outcome,
            "evidence_id": args.evidence_id,
            "target": args.target,
            "change": args.change,
            "verification": args.verification,
            "next": args.next,
            "notes": args.notes,
        },
    )
    print(f"Round {state['round']} ✓ — {args.target}")
    if args.verification:
        print(f"Verified: {args.verification}")
    if args.next:
        print(f"Next: {args.next}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    root = state_dir(args.dir)
    p = paths(root)
    state = read_json(p["state"], {})
    if not state:
        print("no state to resume; initialize the task first", file=sys.stderr)
        return 1
    state["stop_requested"] = False
    state["phase"] = "audit"
    if args.next:
        state["next_target"] = args.next
    state["updated_at"] = now()
    write_json(p["state"], state)
    append_jsonl(p["ledger"], {"ts": now(), "event": "resume", "round": state.get("round", 0), "next_side": state.get("next_side")})
    print(f"resuming after round {state.get('round', 0)}; next side: {state.get('next_side', 'for')}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = state_dir(args.dir)
    p = paths(root)
    state = read_json(p["state"], {})
    if not state:
        print(f"no infinite state in {root} (run: infinite_state.py init --task ...)")
        return 0
    print(f"state dir : {root}")
    print(f"task      : {state.get('task', '(unspecified)')}")
    print(f"round     : {state.get('round', 0)}")
    print(f"profile   : {state.get('profile', 'generic')}")
    if state.get("profile") == "book-of-mormon":
        print(f"next side : {state.get('next_side', 'for')}")
        print(f"dry rounds: {state.get('dry_rounds', 0)}")
    print(f"phase     : {state.get('phase', 'audit')}")
    print(f"next      : {state.get('next_target') or '(not chosen yet)'}")
    print(f"armed     : {p['armed'].exists()}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    root = state_dir(args.dir)
    p = paths(root)
    entries = read_jsonl(p["ledger"])
    rounds = [e for e in entries if e.get("event") == "round"]
    print(f"# Infinite loop report — {root}")
    print()
    print(f"- rounds logged: {len(rounds)}")
    if rounds:
        print(f"- last round: {rounds[-1].get('round')} at {rounds[-1].get('ts')}")
        print()
        print("| Round | Target | Verification |")
        print("| --- | --- | --- |")
        for entry in rounds[-args.limit :]:
            target = str(entry.get("target", "")).replace("|", "\\|")
            verification = str(entry.get("verification", "")).replace("|", "\\|")
            print(f"| {entry.get('round')} | {target} | {verification} |")
    stops = [e for e in entries if e.get("event") == "disarm"]
    if stops:
        print()
        print(f"- last stop: {stops[-1].get('ts')} ({stops[-1].get('reason') or 'no reason'})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="State helper for the infinite skill")
    parser.add_argument(
        "--dir",
        help="project directory or state directory (default: ./.infinite)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create or update the ledger")
    init.add_argument("--task", help="the user's task, verbatim where possible")
    init.add_argument("--profile", choices=["generic", "book-of-mormon"], help="task profile (default: preserve existing or generic)")
    init.add_argument("--arm", action="store_true", help="also arm the loop")
    init.set_defaults(func=cmd_init)

    arm = sub.add_parser("arm", help="(legacy) user-side flag; enforcement uses infinite_guard.py")
    arm.add_argument("--reason")
    arm.set_defaults(func=cmd_arm)

    disarm = sub.add_parser("disarm", help="(legacy) user-side flag; enforcement uses infinite_guard.py")
    disarm.add_argument("--reason")
    disarm.set_defaults(func=cmd_disarm)

    target = sub.add_parser("next-target", help="record the target of the next round")
    target.add_argument("target")
    target.set_defaults(func=cmd_next_target)

    log = sub.add_parser("log", help="append a completed round")
    log.add_argument("--target", required=True)
    log.add_argument("--change")
    log.add_argument("--verification")
    log.add_argument("--next")
    log.add_argument("--notes")
    log.add_argument("--round", type=int, help="force the round number")
    log.add_argument("--side", choices=["for", "against"], help="required for Book of Mormon research rounds")
    log.add_argument("--outcome", choices=["accepted", "revised", "rejected", "deepened", "blocked", "no-new"])
    log.add_argument("--evidence-id", help="canonical evidence added or revised this round")
    log.set_defaults(func=cmd_log)

    resume = sub.add_parser("resume", help="resume after the user says continue; preserve round and side")
    resume.add_argument("--next", help="optional replacement target")
    resume.set_defaults(func=cmd_resume)

    status = sub.add_parser("status", help="print the current state")
    status.set_defaults(func=cmd_status)

    report = sub.add_parser("report", help="print the round history")
    report.add_argument("--limit", type=int, default=20)
    report.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
