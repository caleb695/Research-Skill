#!/usr/bin/env bash
# Smoke + adversarial tests for the `infinite` skill. bash + python3 only.
#
#   tests/smoke.sh
#
# The second half is the important half: it tries to disable enforcement the way
# an agent would, and asserts that every attempt fails closed.

set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../infinite" && pwd)"
S="$SKILL_DIR/scripts"
STATE="$S/infinite_state.py"
GUARD="$S/infinite_guard.py"
INSTALL="$S/install-openhands-hooks.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

FAILED=0
pass() { printf '  ok   %s\n' "$1"; }
fail() { printf '  FAIL %s\n' "$1"; FAILED=1; }
check() { if [ "$1" = "$2" ]; then pass "$3 ($1)"; else fail "$3 (got $1, want $2)"; fi; }

# --- helpers ---------------------------------------------------------------- #
stop_event() { printf '{"event_type":"Stop","working_dir":"%s"}' "$1"; }
pretool_event() { printf '{"event_type":"PreToolUse","working_dir":"%s","tool_name":"%s","tool_input":%s}' "$1" "$2" "$3"; }
prompt_event() { printf '{"event_type":"UserPromptSubmit","working_dir":"%s","message":"%s"}' "$1" "$2"; }

stop_code() { # project policy
    stop_event "$1" | OPENHANDS_PROJECT_DIR="$1" bash "$1/.openhands/hooks/infinite-stop.sh" --policy "$2" >/dev/null 2>&1
    echo $?
}
pretool_code() { # project tool json
    pretool_event "$1" "$2" "$3" | OPENHANDS_PROJECT_DIR="$1" bash "$1/.openhands/hooks/infinite-pretool.sh" >/dev/null 2>&1
    echo $?
}
prompt() { prompt_event "$1" "$2" | OPENHANDS_PROJECT_DIR="$1" bash "$1/.openhands/hooks/infinite-userprompt.sh" >/dev/null 2>&1; }

policy_of() {
    python3 - "$1/.openhands/hooks.json" <<'PY'
import json, sys
config = json.load(open(sys.argv[1]))
for entry in config["stop"]:
    for hook in entry["hooks"]:
        if "--policy" in hook["command"]:
            print(hook["command"].split("--policy ")[1].strip())
            raise SystemExit
raise SystemExit("no policy in hooks.json")
PY
}

echo "== package shape =="
python3 - "$SKILL_DIR/SKILL.md" <<'PY' || FAILED=1
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
assert match, "SKILL.md must start with frontmatter"
front = match.group(1)
assert re.search(r"^name: infinite$", front, re.M), "name must be 'infinite'"
assert re.search(r"^description:", front, re.M), "description required"
assert re.search(r"^triggers:", front, re.M), "triggers required"
print("  ok   frontmatter valid")
PY
[ "$(basename "$SKILL_DIR")" = "infinite" ] && pass "directory name matches skill name" || fail "directory name"

echo "== ledger helper =="
PROJ="$WORK/proj"
mkdir -p "$PROJ"
python3 "$STATE" --dir "$PROJ" init --task "smoke task" >/dev/null || fail "init"
python3 "$STATE" --dir "$PROJ" log --target "t" --verification "v" --next "n" >/dev/null || fail "log"
grep -q "round     : 1" < <(python3 "$STATE" --dir "$PROJ" status) && pass "log increments round" || fail "round increment"
python3 "$STATE" --dir "$PROJ" report | grep -q "| 1 |" && pass "report renders ledger" || fail "report"

echo "== installer =="
"$INSTALL" --dir "$PROJ" --gate "tests:test -f ok.txt" --gate "lint:true" >/dev/null 2>&1 || fail "install"
for f in .openhands/guard/infinite_guard.py .openhands/hooks/infinite-stop.sh \
         .openhands/hooks/infinite-pretool.sh .openhands/hooks/infinite-userprompt.sh \
         .openhands/hooks.json; do
    [ -e "$PROJ/$f" ] && pass "installed $f" || fail "missing $f"
done
POLICY="$(policy_of "$PROJ")"
[ -n "$POLICY" ] && pass "policy embedded in hook command" || fail "no embedded policy"

BEFORE="$(cat "$PROJ/.openhands/hooks.json")"
"$INSTALL" --dir "$PROJ" --gate "lint:true" >/dev/null 2>&1
COUNT="$(python3 -c "import json;print(len(json.load(open('$PROJ/.openhands/hooks.json'))['stop']))")"
check "$COUNT" "1" "installer is idempotent"

echo "== stop gate: the task being done is not a stop condition =="
check "$(stop_code "$PROJ" "$POLICY")" "2" "failing gate denies finish"
touch "$PROJ/ok.txt"
check "$(stop_code "$PROJ" "$POLICY")" "2" "no verified round denies finish"
python3 "$STATE" --dir "$PROJ" log --target "ok.txt" --verification "pass" --next "more" >/dev/null
check "$(stop_code "$PROJ" "$POLICY")" "2" "mode=required denies even after a clean round"
check "$(stop_code "$PROJ" "$POLICY")" "2" "repeated attempts stay denied"

echo "== the agent cannot disable its own enforcement =="
AGENT_ATTACKS=(
    '{"command":"python3 .openhands/guard/infinite_guard.py disarm"}'
    '{"command":"rm -rf .openhands"}'
    '{"command":"rm -rf .openhands/guard"}'
    '{"command":"bash skills/infinite/scripts/install-openhands-hooks.sh --uninstall"}'
    '{"command":"sed -i s/stop// .openhands/hooks.json"}'
    '{"command":"python3 -c open(\".openhands/hooks.json\",\"w\").write(\"{}\")"}'
    '{"command":"cat .openhands/guard/config.json"}'
    '{"path":".openhands/hooks.json"}'
    '{"path":".openhands/guard/config.json"}'
)
for attack in "${AGENT_ATTACKS[@]}"; do
    check "$(pretool_code "$PROJ" terminal "$attack")" "2" "blocked: $attack"
done

echo "== ordinary work is not blocked =="
check "$(pretool_code "$PROJ" terminal '{"command":"pytest -q"}')" "0" "test run allowed"
check "$(pretool_code "$PROJ" terminal '{"command":"git commit -am round-3"}')" "0" "commit allowed"
check "$(pretool_code "$PROJ" file_editor '{"path":"README.md","command":"str_replace"}')" "0" "doc edit allowed"
check "$(pretool_code "$PROJ" file_editor \
    '{"path":"docs/infinite.md","command":"create","file_text":"mentions .openhands/guard"}')" \
    "0" "prose mentioning the guard allowed"

echo "== tampering with state on disk does not disarm =="
echo '{"mode":"disabled","gates":[]}' > "$PROJ/.openhands/guard/config.json"
check "$(stop_code "$PROJ" "$POLICY")" "2" "rewritten config ignored (policy is in the hook)"
rm -f "$PROJ/.openhands/guard/config.json"
check "$(stop_code "$PROJ" "$POLICY")" "2" "deleted config fails closed"
printf '{"working_dir":"%s"}' "$PROJ" | OPENHANDS_PROJECT_DIR="$PROJ" \
    bash "$PROJ/.openhands/hooks/infinite-stop.sh" --policy "corrupted" >/dev/null 2>&1
check "$?" "2" "corrupted policy fails closed"
rm -rf "$PROJ/.openhands/guard"
stop_event "$PROJ" | OPENHANDS_PROJECT_DIR="$PROJ" \
    bash "$PROJ/.openhands/hooks/infinite-stop.sh" --policy "$POLICY" >/dev/null 2>&1
check "$?" "2" "deleting .openhands/guard does not disarm (second copy by the hooks)"

echo "== only the user ends infinite mode =="
prompt "$PROJ" "add a stop button to the UI"
check "$(stop_code "$PROJ" "$POLICY")" "2" "prose about a 'stop button' does not disarm"
prompt "$PROJ" "how does the stop hook work?"
check "$(stop_code "$PROJ" "$POLICY")" "2" "question about stopping does not disarm"
prompt "$PROJ" "stop"
check "$(stop_code "$PROJ" "$POLICY")" "0" "user says 'stop' -> finish allowed"
prompt "$PROJ" "/infinite continue"
check "$(stop_code "$PROJ" "$POLICY")" "2" "user says '/infinite' -> armed again"
"$INSTALL" --dir "$PROJ" --disarm >/dev/null 2>&1
check "$(stop_code "$PROJ" "$POLICY")" "0" "installer --disarm allows finish"
"$INSTALL" --dir "$PROJ" --uninstall >/dev/null 2>&1
grep -q "infinite" "$PROJ/.openhands/hooks.json" && fail "uninstall left hook entries" || pass "uninstall removes hook entries"

echo "== install paths =="
SLOT="$WORK/slot"
mkdir -p "$SLOT"
"$INSTALL" --dir "$SLOT" --install-skill --gate "tests:true" >/dev/null 2>&1
[ -f "$SLOT/.agents/skills/infinite/SKILL.md" ] && pass "installs into .agents/skills/infinite" \
    || fail "--install-skill did not create the skill slot"
[ -x "$SLOT/.agents/skills/infinite/scripts/infinite_guard.py" ] && pass "installed scripts are executable" \
    || fail "installed scripts lost the execute bit"

PROJ2="$WORK/proj2"
mkdir -p "$PROJ2"
cp -r "$SKILL_DIR" "$PROJ2/skillcopy"
( cd / && bash "$PROJ2/skillcopy/scripts/install-openhands-hooks.sh" --dir "$PROJ2" --gate "tests:true" >/dev/null 2>&1 ) \
    && pass "installer works from an unrelated cwd" || fail "installer failed from an unrelated cwd"
STOP_CMD="$(python3 -c "
import json;print(json.load(open('$PROJ2/.openhands/hooks.json'))['stop'][0]['hooks'][0]['command'])")"
case "$STOP_CMD" in "bash .openhands/hooks/"*) pass "hook command is repo-relative for Cloud portability";; *) fail "hook command is not portable: $STOP_CMD";; esac
OUT="$(printf '{"event_type":"Stop","session_id":"s","working_dir":"%s","metadata":{"reason":"agent_finished"}}' "$PROJ2" \
      | ( cd "$PROJ2" && OPENHANDS_PROJECT_DIR="$PROJ2" eval "$STOP_CMD" ) 2>/dev/null)"
[ -n "$OUT" ] && pass "hook runs from the relocated project cwd" || fail "hook produced no output from project cwd"
python3 - "$OUT" <<'PY2' && pass "deny payload carries gate detail for the agent" || fail "payload lacks gate detail"
import json, sys
payload = json.loads(sys.argv[1])
assert payload["decision"] == "deny"
assert "Gates:" in payload.get("additionalContext", ""), payload
PY2

echo "== gate availability probing =="
UNPASSABLE="$WORK/unpassable"
mkdir -p "$UNPASSABLE"
# A gate whose runner does not exist can never pass, so it must be skipped with a
# warning rather than armed (which would deny every finish forever).
OUT="$(python3 "$GUARD" --dir "$UNPASSABLE" policy --gate "missing:definitely-not-a-real-binary --run" 2>&1)"
case "$OUT" in
    *"skipping gate 'missing'"*) pass "unrunnable gate is skipped with a warning";;
    *) fail "unrunnable gate was not skipped";;
esac
POLICY_JSON="$(printf '%s\n' "$OUT" | tail -1 | python3 -c "
import base64, json, sys
blob = sys.stdin.read().strip()
blob += '=' * (-len(blob) % 4)
print(json.dumps(json.loads(base64.urlsafe_b64decode(blob))))")"
python3 - "$POLICY_JSON" <<'PY2' && pass "policy excludes the unrunnable gate" || fail "policy kept the unrunnable gate"
import json, sys
policy = json.loads(sys.argv[1])
assert policy["gates"] == [], policy
assert policy["skipped_gates"][0]["name"] == "missing", policy
PY2
OUT="$(python3 "$GUARD" --dir "$UNPASSABLE" policy --gate "ok:true" 2>&1)"
case "$OUT" in
    *warning*) fail "a runnable gate was skipped";;
    *) pass "runnable gate is kept";;
esac

echo "== standalone (curl | bash) install =="
RAWDIR="$WORK/raw/site/infinite"
mkdir -p "$RAWDIR"
cp -r "$SKILL_DIR/." "$RAWDIR/"
# Pick a free port so a leftover server from an interrupted run cannot poison
# this test.
PORT="$(python3 - <<'PY2'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY2
)"
( cd "$WORK/raw" && nohup python3 -m http.server "$PORT" --bind 127.0.0.1 >/dev/null 2>&1 & echo $! > "$WORK/raw.pid" )
READY=0
for _ in $(seq 1 20); do
    if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/site/infinite/SKILL.md" 2>/dev/null; then READY=1; break; fi
    sleep 0.25
done
[ "$READY" -eq 1 ] || fail "local test server did not start on port $PORT"
STAND="$WORK/standalone"
mkdir -p "$STAND/proj"
if curl -fsS "http://127.0.0.1:$PORT/site/infinite/scripts/install-openhands-hooks.sh" -o "$STAND/fetched.sh" 2>/dev/null; then
    pass "installer is fetchable on its own (curl | bash prerequisite)"
    if INFINITE_RAW_BASE="http://127.0.0.1:$PORT/site/infinite/scripts" \
        bash "$STAND/fetched.sh" --dir "$STAND/proj" --install-skill --gate "tests:true" >/dev/null 2>&1; then
        pass "standalone install fetches its own files"
    else
        fail "standalone install failed"
    fi
    [ -f "$STAND/proj/.agents/skills/infinite/SKILL.md" ] && pass "standalone install places the skill" \
        || fail "standalone install did not place the skill"
    [ -x "$STAND/proj/.openhands/hooks/infinite-stop.sh" ] && pass "standalone install arms enforcement" \
        || fail "standalone install did not wire hooks"
else
    fail "could not fetch the installer over HTTP"
fi
kill "$(cat "$WORK/raw.pid" 2>/dev/null)" 2>/dev/null || true

echo
if [ "$FAILED" -eq 0 ]; then echo "all tests passed"; else echo "FAILURES PRESENT" >&2; fi
exit "$FAILED"
