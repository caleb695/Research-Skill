#!/usr/bin/env bash
# Install, arm, disarm, or uninstall the `infinite` skill's enforcement hooks.
#
#   bash install-openhands-hooks.sh                     # install + arm in $PWD
#   bash install-openhands-hooks.sh --dir ~/proj        # another project
#   bash install-openhands-hooks.sh --no-arm            # install in standby; arm by saying "use this skill"
#   bash install-openhands-hooks.sh --gate "tests:pytest -q" --gate "lint:ruff check ."
#   bash install-openhands-hooks.sh --mode allow-when-green
#   bash install-openhands-hooks.sh --install-skill     # fixed skill + Book of Mormon enforcement (default)
#   bash install-openhands-hooks.sh --generic           # legacy generic infinite-loop enforcement
#   bash install-openhands-hooks.sh --status            # mode, gates, rounds, decisions
#   bash install-openhands-hooks.sh --disarm            # user says stop: allow finishing
#   bash install-openhands-hooks.sh --uninstall         # remove hooks and guard state
#
# Works three ways:
#   1. from a clone:      bash infinite/scripts/install-openhands-hooks.sh --dir .
#   2. from anywhere:     bash /path/to/infinite/scripts/install-openhands-hooks.sh --dir .
#   3. standalone:        curl -fsSL <raw-url>/infinite/scripts/install-openhands-hooks.sh | bash -s -- --dir .
#      (fetches the rest of the files from the same commit automatically; override
#       the source with INFINITE_RAW_BASE=<skill-dir-url> INFINITE_REF=<branch|tag|sha>)
#
# This script is the user's control surface. The agent is blocked from running it
# (and from running the guard directly) by the PreToolUse hook installed here.
#
# The policy - mode, gates, required rounds - is written into the hook command in
# .openhands/hooks.json. OpenHands reads that file when the conversation starts,
# so a running conversation's policy cannot be weakened by the agent.
#
# Gates are auto-detected per project (npm / pytest / ruff / go / cargo / make)
# unless --gate or --no-gates is given. Idempotent: other hook entries in
# .openhands/hooks.json are preserved and never duplicated.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "")"
TARGET_DIR="${OPENHANDS_PROJECT_DIR:-$PWD}"
DRY_RUN=0
ACTION="install"
ARM=1
GATES=()
NO_GATES=0
MODE=""
REQUIRE_ROUNDS=""
DISARM_REASON=""
INSTALL_SKILL=0
RESEARCH=1
SCOPE="project"
REF="${INFINITE_REF:-main}"
# Base URL of the skill directory (the one containing SKILL.md and scripts/).
# Only used when this script runs standalone (curl | bash) with no siblings.
# A value ending in /scripts is accepted too, for convenience.
RAW_BASE="${INFINITE_RAW_BASE:-https://raw.githubusercontent.com/caleb695/Research-Skill/$REF/infinite}"
RAW_BASE="${RAW_BASE%/}"
case "$RAW_BASE" in
    */scripts) RAW_BASE="${RAW_BASE%/scripts}" ;;
esac

while [ $# -gt 0 ]; do
    case "$1" in
        --dir) TARGET_DIR="$2"; shift 2 ;;
        --print|--dry-run) DRY_RUN=1; shift ;;
        --no-arm) ARM=0; shift ;;
        --status) ACTION="status"; shift ;;
        --disarm|--stop) ACTION="disarm"; shift ;;
        --uninstall|--remove) ACTION="uninstall"; shift ;;
        --gate) GATES+=("$2"); shift 2 ;;
        --no-gates) NO_GATES=1; shift ;;
        --mode) MODE="$2"; shift 2 ;;
        --research) RESEARCH=1; shift ;;
        --generic) RESEARCH=0; shift ;;
        --require-rounds) REQUIRE_ROUNDS="$2"; shift 2 ;;
        --reason) DISARM_REASON="$2"; shift 2 ;;
        --ref) REF="$2"; shift 2 ;;
        --install-skill) INSTALL_SKILL=1; shift ;;
        --scope) SCOPE="$2"; shift 2 ;;
        -h|--help) sed -n '2,32p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

# This package is a single-purpose Book of Mormon research skill. Installing it
# installs deterministic research enforcement by default; --generic is only for
# the legacy non-research loop. --no-arm installs standby hooks that a real user
# message arms ("use this skill" / "/infinite"); --mode disabled turns them off.
if [ "$ARM" -eq 0 ] && [ -z "$MODE" ]; then
    MODE="standby"
fi

TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
GUARD_DIR="$TARGET_DIR/.openhands/guard"
HOOK_DIR="$TARGET_DIR/.openhands/hooks"
HOOKS_JSON="$TARGET_DIR/.openhands/hooks.json"
GUARD="$GUARD_DIR/infinite_guard.py"

guard_cli() { python3 "$GUARD" --dir "$TARGET_DIR" "$@"; }

require_python() {
    command -v python3 >/dev/null 2>&1 || {
        echo "python3 is required for enforcement (guard + gate runner)" >&2
        exit 1
    }
}

# Copy a file from the local checkout, or fetch it when this script was run
# standalone (curl | bash) with no siblings on disk. `rel` is relative to the
# skill root (e.g. scripts/infinite_guard.py).
fetch_or_copy() {
    local rel="$1" dest="$2"
    mkdir -p "$(dirname "$dest")"
    if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/../$rel" ]; then
        cp "$SCRIPT_DIR/../$rel" "$dest"
        return 0
    fi
    local base="$RAW_BASE"
    if ! curl -fsSL --max-time 60 "$base/$rel" -o "$dest"; then
        echo "could not obtain $rel (tried $base/$rel)." >&2
        echo "Run this script from a checkout of the skill instead:" >&2
        echo "  git clone https://github.com/caleb695/Research-Skill && bash Research-Skill/infinite/scripts/install-openhands-hooks.sh --dir $TARGET_DIR" >&2
        exit 1
    fi
}

fetch_or_copy_skill() {
    fetch_or_copy "$1" "$2"
}

install_skill_files() {
    local dest="$1"
    mkdir -p "$dest"
    local files=(
        SKILL.md README.md
        references/fixed-task.md
        references/loop-protocol.md
        references/audit-playbook.md
        references/openhands-enforcement.md
        references/book-of-mormon-research.md
        references/evidence-schema.md
        references/openhands-cloud.md
        references/google-docs.md
        commands/infinite.md
        assets/project.gitignore.fragment
        scripts/infinite_guard.py
        scripts/infinite_state.py
        scripts/infinite_research.py
        scripts/google_docs.py
        scripts/stop_hook.sh
        scripts/pretool_hook.sh
        scripts/userprompt_hook.sh
        scripts/install-openhands-hooks.sh
    )
    for rel in "${files[@]}"; do
        fetch_or_copy_skill "$rel" "$dest/$rel"
    done
    chmod +x "$dest"/scripts/*.sh "$dest"/scripts/*.py 2>/dev/null || true
    echo "installed skill:  $dest"
    echo "                  (SKILL.md + references + scripts; agent loads it on demand)"
}

if [ "$INSTALL_SKILL" -eq 1 ]; then
    case "$SCOPE" in
        project) SKILL_DEST="$TARGET_DIR/.agents/skills/infinite" ;;
        user) SKILL_DEST="$HOME/.agents/skills/infinite" ;;
        *) echo "--scope must be 'project' or 'user'" >&2; exit 2 ;;
    esac
    install_skill_files "$SKILL_DEST"
    echo
    echo "Next:"
    echo "  * Agent Canvas: Customize > Skills, enable 'infinite'."
    echo "  * CLI/headless: project skills in .agents/skills are loaded automatically."
    echo "  * Trigger it by typing /infinite in a message."
fi

if [ "$ACTION" = "status" ] && [ ! -f "$GUARD" ]; then
    echo "infinite mode is not installed in $TARGET_DIR" >&2
    exit 1
fi

# Self-heal for the user's control actions: the agent may have deleted the guard
# directory, which must never prevent the user from stopping.
if [ "$ACTION" != "install" ] && [ "$ACTION" != "status" ]; then
    require_python
    fetch_or_copy scripts/infinite_guard.py "$GUARD"
    fetch_or_copy scripts/infinite_guard.py "$HOOK_DIR/infinite_guard.py"
    chmod +x "$GUARD" "$HOOK_DIR/infinite_guard.py"
fi

case "$ACTION" in
    status)
        guard_cli status
        echo
        echo "Last hook decisions:"
        tail -n 5 "$GUARD_DIR/events.jsonl" 2>/dev/null | sed 's/^/  /' || echo "  (none yet)"
        exit 0
        ;;
    disarm)
        guard_cli disarm --reason "${DISARM_REASON:-user said stop}"
        echo "The agent may now finish normally. Re-arm with:"
        echo "  bash $0 --dir $TARGET_DIR"
        exit 0
        ;;
    uninstall)
        guard_cli uninstall
        exit 0
        ;;
esac

if [ "$DRY_RUN" -eq 1 ]; then
    echo "would install guard:  $GUARD"
    echo "would install hooks:  $HOOK_DIR/infinite-{stop,pretool,userprompt}.sh"
    [ "$RESEARCH" -eq 1 ] && echo "would install built-in Book of Mormon research validator"
    echo "would update config:  $HOOKS_JSON"
    exit 0
fi

require_python

fetch_or_copy scripts/infinite_guard.py "$GUARD"
fetch_or_copy scripts/infinite_guard.py "$HOOK_DIR/infinite_guard.py"
fetch_or_copy scripts/stop_hook.sh "$HOOK_DIR/infinite-stop.sh"
fetch_or_copy scripts/pretool_hook.sh "$HOOK_DIR/infinite-pretool.sh"
fetch_or_copy scripts/userprompt_hook.sh "$HOOK_DIR/infinite-userprompt.sh"
fetch_or_copy scripts/infinite_state.py "$HOOK_DIR/infinite_state.py"
if [ "$RESEARCH" -eq 1 ]; then
    fetch_or_copy scripts/infinite_research.py "$HOOK_DIR/infinite_research.py"
    fetch_or_copy scripts/google_docs.py "$HOOK_DIR/google_docs.py"
    chmod +x "$HOOK_DIR/infinite_research.py" "$HOOK_DIR/google_docs.py"
    # The research validator is built into the Stop hook for this profile. It is
    # not a removable shell gate, so --no-gates still enforces the fixed task.
    # The Google Docs mirror is part of final validation (three documents).
fi
chmod +x "$GUARD" "$HOOK_DIR"/infinite-*.sh "$HOOK_DIR/infinite_state.py" "$HOOK_DIR/infinite_guard.py"
echo "installed guard:  $GUARD"
echo "installed hooks:  $HOOK_DIR/infinite-{stop,pretool,userprompt}.sh"
[ "$RESEARCH" -eq 1 ] && echo "research enforcement: built-in ledger/report validator + helper-only writes"

# Build the policy now, so the hook command carries it.
policy_args=(policy)
[ "$RESEARCH" -eq 1 ] && policy_args+=(--research)
[ -n "$MODE" ] && policy_args+=(--mode "$MODE")
[ "$NO_GATES" -eq 1 ] && policy_args+=(--no-gates)
[ -n "$REQUIRE_ROUNDS" ] && policy_args+=(--require-rounds "$REQUIRE_ROUNDS")
for gate in "${GATES[@]:-}"; do
    [ -n "$gate" ] && policy_args+=(--gate "$gate")
done
POLICY="$(guard_cli "${policy_args[@]}")"

python3 - "$HOOKS_JSON" "$POLICY" "$GUARD_DIR" <<'PY'
import json
import shlex
import sys
from pathlib import Path

hooks_path = Path(sys.argv[1])
policy = sys.argv[2].strip()
guard_dir = sys.argv[3]
if not policy:
    raise SystemExit("empty policy blob; refusing to wire an unenforced hook")

try:
    config = json.loads(hooks_path.read_text(encoding="utf-8")) if hooks_path.exists() else {}
except json.JSONDecodeError as exc:
    raise SystemExit(f"{hooks_path} is not valid JSON: {exc}. Fix it and re-run.")
if not isinstance(config, dict):
    raise SystemExit(f"{hooks_path} must contain a JSON object.")

# Repo-relative commands are portable across Cloud/CLI checkout paths. OpenHands
# runs hooks with cwd=the conversation working folder; each dispatcher resolves
# its own directory with BASH_SOURCE. Do not bake this machine's absolute path
# into committed hooks.json.
import base64
policy_obj = json.loads(base64.urlsafe_b64decode(policy + "=" * (-len(policy) % 4)))
q = shlex.quote
python = q(sys.executable or "python3")

wanted = {
    "stop": f"bash .openhands/hooks/infinite-stop.sh --policy {q(policy)}",
    "pre_tool_use": f"bash .openhands/hooks/infinite-pretool.sh --policy {q(policy)}",
    "user_prompt_submit": f"bash .openhands/hooks/infinite-userprompt.sh --policy {q(policy)}",
}
# The Stop hook must outlive its gates; otherwise a long gate times out at the
# hook layer and OpenHands treats it as a non-blocking error.
gate_budget = sum(int(g.get("timeout", 600)) for g in policy_obj.get("gates", []))
research_budget = 30 if policy_obj.get("profile") == "book-of-mormon" else 0
timeouts = {"stop": max(60, gate_budget + research_budget + 15), "pre_tool_use": 20, "user_prompt_submit": 15}

for event, command in wanted.items():
    entries = config.setdefault(event, [])
    cleaned = []
    for entry in entries:
        hooks = [h for h in entry.get("hooks", []) if "infinite" not in str(h.get("command", ""))]
        if hooks:
            entry["hooks"] = hooks
            cleaned.append(entry)
    cleaned.append({"matcher": "*", "hooks": [{"command": command, "timeout": timeouts[event]}]})
    config[event] = cleaned

hooks_path.parent.mkdir(parents=True, exist_ok=True)
hooks_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
print(f"wired enforcement hooks: {hooks_path}")
print(f"hook interpreter: {python}")
PY

# Stop hooks are invoked by OpenHands, not by a shell: make sure they are
# executable and start with a shebang, then verify by running one.
for hook in "$HOOK_DIR"/infinite-stop.sh "$HOOK_DIR"/infinite-pretool.sh "$HOOK_DIR"/infinite-userprompt.sh; do
    head -c 2 "$hook" | grep -q '#!' || { echo "$hook is missing a shebang" >&2; exit 1; }
    chmod +x "$hook"
done

if [ "$RESEARCH" -eq 1 ]; then
    python3 "$HOOK_DIR/infinite_research.py" --dir "$TARGET_DIR" init
fi

if [ "$ARM" -eq 1 ]; then
    guard_cli arm "${policy_args[@]:1}"
    echo
    echo "Policy is embedded in hooks.json; the agent cannot weaken it mid-conversation."
    echo "Hook commands are repo-relative for OpenHands Cloud portability; start a new conversation after installing."
    echo "Check:  bash $0 --dir $TARGET_DIR --status"
    echo "Gates:  python3 $GUARD doctor --dir $TARGET_DIR"
else
    guard_cli arm "${policy_args[@]:1}" >/dev/null 2>&1 || true
    echo "installed in ${MODE:-standby}. Arm by saying 'use this skill' / '/infinite', or run: bash $0 --dir $TARGET_DIR"
fi

# --- self-check: does a simulated finish attempt match the installed mode? ---
SELFTEST="$(echo '{"event_type":"Stop"}' | OPENHANDS_PROJECT_DIR="$TARGET_DIR" bash "$HOOK_DIR/infinite-stop.sh" --policy "$POLICY" >/dev/null 2>&1; echo $?)"
EXPECTED=2
case "${MODE:-required}" in
    disabled|standby) EXPECTED=0 ;;
esac
if [ "$ARM" -eq 1 ] && [ "$SELFTEST" != "$EXPECTED" ]; then
    echo "WARNING: self-check failed - a finish attempt returned $SELFTEST, expected $EXPECTED." >&2
    echo "Run 'bash $0 --dir $TARGET_DIR --status' and check .openhands/hooks.json." >&2
    exit 1
fi
if [ "$ARM" -eq 1 ]; then
    if [ "$EXPECTED" = "2" ]; then
        echo "self-check: finish attempt correctly denied (exit 2)"
    else
        echo "self-check: finish attempt correctly allowed before arming (exit 0)"
    fi
fi

echo
echo "Ending infinite mode (the user's call, never the agent's):"
echo "  say 'stop' in the conversation, or run:"
echo "  bash $0 --dir $TARGET_DIR --disarm"
echo "Removing enforcement entirely:"
echo "  bash $0 --dir $TARGET_DIR --uninstall"
