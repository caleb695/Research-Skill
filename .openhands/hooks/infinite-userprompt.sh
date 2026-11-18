#!/usr/bin/env bash
# OpenHands UserPromptSubmit hook for the `infinite` skill (thin dispatcher).
#
# This is the only channel through which infinite mode can be armed or disarmed
# by words, and it fires only on a real user message - the agent cannot inject
# one. A stop phrase ("stop", "cancel", "that's enough", "/stop", ...) disarms
# the guard; an infinite phrase ("/infinite", "never stop", ...) re-arms it.
#
# Exit 0 always: the user's message is never blocked. "$@" may carry the
# installer's immutable policy so research stop behavior cannot be changed by
# editing the agent-owned state mirror.

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
    exit 0
fi

printf '%s' "$input" | python3 "$guard" userprompt "$@"
exit 0
