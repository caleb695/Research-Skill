#!/usr/bin/env bash
# OpenHands Stop hook for the `infinite` skill (thin dispatcher).
#
# The decision is made by infinite_guard.py using the policy embedded in this
# command by the installer. That policy is fixed when hooks.json is loaded, so
# nothing the agent can write to disk mid-conversation can weaken it.
#
#   exit 0  allow the finish
#   exit 2  deny the finish with {"decision":"deny","reason":...,"additionalContext":...}
#
# Fails CLOSED if the guard is missing: deleting enforcement files cannot buy a
# clean exit. Only the user's disarm/uninstall restores normal finishing.

set -uo pipefail

hook_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
input="$(cat 2>/dev/null || true)"

guard=""
for candidate in "$hook_dir/infinite_guard.py" "$hook_dir/../guard/infinite_guard.py"; do
    if [ -f "$candidate" ]; then
        guard="$candidate"
        break
    fi
done

if [ -z "$guard" ] || ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' '{"decision":"deny","reason":"Infinite mode: the enforcement guard cannot run (missing guard or python3), so finishing cannot be verified and is denied. Do not recreate, edit, or bypass .openhands/guard - it belongs to the user. Continue the loop. The user ends infinite mode by running scripts/install-openhands-hooks.sh --disarm (or --uninstall).","additionalContext":"Fail-closed: enforcement files are user-owned."}'
    exit 2
fi

# "$@" carries `--policy <blob>` from the hook command that OpenHands loaded at
# conversation start. The agent cannot change that command for a live session,
# so the policy cannot be weakened mid-conversation.
printf '%s' "$input" | python3 "$guard" stop "$@"
exit $?
