# Enforcement in OpenHands — the agent does not get to decide

Prompting is advisory: the model can end a run anyway. This document describes
the part of the skill that is not advisory. Three hooks and a policy the agent
cannot change decide whether a run may finish.

| Layer | Mechanism | Who controls it |
| --- | --- | --- |
| Instructions | [`SKILL.md`](../SKILL.md) | Prompt — advisory, may be ignored |
| **Enforcement** | `Stop` hook → `infinite_guard.py` (exit 2 = deny) | **The user** |
| **Self-protection** | `PreToolUse` hook blocks editing/running enforcement | **The user** |
| **Exit control** | `UserPromptSubmit` hook: only a real user message can arm/disarm | **The user** |
| Progress record | `.infinite/ledger.jsonl` | The agent (auditable) |

## Install

```bash
# Book of Mormon research profile + built-in validator (default):
bash infinite/scripts/install-openhands-hooks.sh --dir /path/to/project --install-skill
# Standby hooks; arm by saying "use this skill" / "/infinite":
bash infinite/scripts/install-openhands-hooks.sh --dir /path/to/project --install-skill --no-arm
# Legacy generic infinite loop only:
bash infinite/scripts/install-openhands-hooks.sh --dir /path/to/project --generic
```

Add `--install-skill` to also place the skill at `.agents/skills/infinite/`
(`--scope user` for `~/.agents/skills/`).

That single command:

1. copies the guard to `.openhands/guard/infinite_guard.py` **and**
   `.openhands/hooks/infinite_guard.py` (two copies, so deleting one directory
   cannot disable enforcement);
2. copies three thin hook scripts into `.openhands/hooks/`;
3. **embeds the policy** — profile, mode, gates, required rounds — as a base64
   blob in the Stop, PreToolUse, and UserPromptSubmit hook commands inside
   `.openhands/hooks.json`;
4. preserves any existing hook entries and never duplicates its own.

```json
{
  "stop": [
    { "matcher": "*", "hooks": [
      { "command": "bash .openhands/hooks/infinite-stop.sh --policy eyJ2IjoyLCJtb2RlIjoicmVxdWlyZWQi...", "timeout": 615 }
    ]}
  ],
  "pre_tool_use": [
    { "matcher": "*", "hooks": [{ "command": "bash .openhands/hooks/infinite-pretool.sh --policy eyJ2IjoyLCJwcm9maWxlIjoi...", "timeout": 20 }] }
  ],
  "user_prompt_submit": [
    { "matcher": "*", "hooks": [{ "command": "bash .openhands/hooks/infinite-userprompt.sh --policy eyJ2IjoyLCJwcm9maWxlIjoi...", "timeout": 15 }] }
  ]
}
```

### Why the policy is in the hook command

The agent has shell access and can rewrite any file in the repository. What it
cannot do is change the hook command of the **running** conversation: OpenHands
loads `hooks.json` when the conversation starts. So the policy travels on the
command line, and the on-disk `config.json` is only a mirror for `status`.

The Stop, PreToolUse, and UserPromptSubmit hooks forward `"$@"` (the policy) to
the guard. If the policy argument is present but unreadable, the guard **fails closed** — it never
falls back to a file the agent could have written. Hook commands are repo-relative
because the SDK executor runs them with cwd set to the conversation working
folder; this is portable across OpenHands Cloud checkout paths. The Stop hook
timeout is derived from the configured gate budgets plus the built-in research
validator so a gate cannot outlive its hook.

## The three hooks

### `stop` — the finish gate

Every finish attempt runs the gates and checks the ledger, then denies with
`exit 2` and a reason the agent must act on:

```
Infinite mode is ON (required). Finishing is blocked because 2 gate(s) fail.
Fix them, log the round, and continue.
Gates: tests: FAIL (exit 1) --- tests output --- <last 12 lines>; lint: PASS (exit 0)
Rounds logged: 12 (8 since arming). Last round: 12 - target: quoting - verification recorded: yes.
```

The deny payload also carries `additionalContext` with the loop protocol, so the
next turn restarts the loop instead of arguing about it.

Repeated finish attempts with no new verified round get a sharper message
(`... you attempted to finish again without completing a new round`) and are
counted in `.openhands/guard/attempts.json`.

Modes (`--mode`):

| Mode | Allows a finish when |
| --- | --- |
| `required` (default) | Never while active. Each finish attempt becomes the next round. In the research profile, a user stop switches to final-report validation instead |
| `standby` | Installed but unarmed; a real `use this skill` / `/infinite` message arms it. After final reports pass, it returns to standby |
| `allow-when-green` | Every gate passes **and** a newly verified round was logged |
| `always` | Never; configured gates are skipped for generic work, but the research profile still runs its built-in validator |
| `disabled` | Installed but off |

### `pre_tool_use` — the agent cannot switch it off

Denied outright:

- running the guard, the installer, or any hook (`disarm`, `--uninstall`, ...);
- `rm`, `mv`, `sed -i`, `chmod`, `tee`, `>` and friends aimed at `.openhands`
  or any `infinite*` file;
- reading `.openhands/guard` state;
- editing `.openhands/hooks.json` or the guard through a file tool;
- in the research profile, hand-editing `.infinite/ledger.jsonl`,
  `.infinite/state.json`, the three generated reports (for/against/comparison),
  the Google Docs receipt `.infinite/gdocs.json`, the user's Google credentials
  files, or the validating helpers (`infinite_research.py`, `infinite_state.py`,
  `google_docs.py`);
- in the research profile, `compile --final` or `google_docs.py sync --mode
  final` before a real user stop, or agent-side `arm`/`disarm`/`resume` after a
  stop until the user continues.

Still allowed: tests, builds, commits, ordinary file edits, and documentation
that merely *mentions* these paths (the rule is path-based for file tools,
text-based only for shell tools). Denials are logged to `events.jsonl`.

### `user_prompt_submit` — only the user can end it

A real user message is the one input the agent cannot forge. It disarms on a
stop phrase and re-arms on an infinite phrase. The installer also forwards the
immutable policy here, so research stop/finalization behavior does not depend on
an agent-editable state mirror.

- **Disarms:** `stop`, `halt`, `cancel`, `quit`, `that's enough`, `/stop`,
  short imperative messages like "ok stop now". In an active research profile,
  `stop` or `stop researching and compile the final reports` writes
  `STOP_REQUESTED` instead of immediately disarming: research ends, but finishing
  waits for all three final reports (for, against, comparison) plus the synced
  Google Docs to pass the configured gates. The user can still
  override with the installer's `--disarm`.
- **Arms:** `use this skill`, `use infinite`, `use the infinite skill`, `/infinite`,
  and legacy infinite phrases such as "never stop" or "until I say stop".
  Re-arming clears a prior `STOP_REQUESTED`; the agent then resumes the fixed
  prompt from the ledger.
- **Ignored:** prose and questions — "add a stop button to the UI", "how does the
  stop hook work?", "why did the build stop?" — so normal work does not
  accidentally end the loop.

## Ending it (the user's commands)

```bash
# in the conversation
stop

# or from your own terminal
bash infinite/scripts/install-openhands-hooks.sh --dir . --disarm
bash infinite/scripts/install-openhands-hooks.sh --dir . --uninstall
```

Both self-heal: even if the agent deleted the guard directory, these commands
restore it and then honour your request. That is deliberate — the user must
always be able to stop the loop, no matter what state the repository is in.

## Verify it yourself

```bash
scripts/install-openhands-hooks.sh --dir . --status   # mode, gates, rounds, attempts, last decisions
.openhands/guard/infinite_guard.py doctor --dir .     # run the gates now
```

Manual hook test without a conversation:

```bash
echo '{"event_type":"Stop","working_dir":"'"$PWD"'"}' \
  | OPENHANDS_PROJECT_DIR="$PWD" bash .openhands/hooks/infinite-stop.sh --policy "$POLICY"; echo "exit=$?"
```

`tests/smoke.sh` automates the enforcement checks (including nine attack
attempts); `tests/openhands_compat.py` verifies the loader and hook contract
above with the SDK's payload shape and working-directory rule; and
`tests/test_research.py` checks research scoring/finalization, helper-only
writes, built-in validation with no shell gates, standby arming, and a relocated
Cloud-style checkout. These are local contract tests, not a live hosted Cloud run.

## Verified against the OpenHands SDK source

These are not assumptions; they were read out of `openhands-sdk` and are covered
by `tests/openhands_compat.py`:

| Behaviour | Where it comes from | Consequence for this skill |
| --- | --- | --- |
| `SKILL.md` is discovered only as an immediate child of a skills dir | `sdk/skills/utils.py:find_skill_md_directories` | the skill ships as `infinite/SKILL.md`, installed to `.agents/skills/infinite/` |
| Strict name rules: must equal the directory, `^[a-z0-9]+(-[a-z0-9]+)*$`, ≤64 chars | `sdk/skills/utils.py:validate_skill_name` | name is `infinite`, directory is `infinite` |
| `description` is the AgentSkills required field, truncated past 1024 chars | `sdk/skills/skill.py:MAX_DESCRIPTION_LENGTH` | description is ~470 chars |
| `triggers:` (a YAML list) becomes a `KeywordTrigger`; matching is whole-token, case-insensitive | `sdk/skills/skill.py:_keyword_matches` | `/infinite`, "never stop", "keep going" all fire |
| A `paths:` key takes precedence and turns the skill into a path rule | `sdk/skills/skill.py:_create_skill_from_metadata` | never set `paths:` here |
| Hook `command` runs with `shell=True`, `timeout`, and the hook's `cwd` = project dir | `sdk/hooks/executor.py` | commands use portable repo-relative paths; dispatchers resolve their own directory |
| Exit code `2` blocks; stdout `{"decision":"deny"}` also blocks | `sdk/hooks/executor.py` | both are sent |
| Stop hook blocking flips the run from `FINISHED` back to `RUNNING` | `sdk/conversation/impl/local_conversation.py` | the loop continues automatically |
| **The Stop path forwards only `additionalContext`** to the agent (role `user`, source `environment`); `reason` is not forwarded | `sdk/hooks/conversation_hooks.py:run_stop` | denials put the gate results and next target in **both** fields |
| Stdin is a `HookEvent`: `event_type`, `tool_name`, `tool_input`, `tool_response`, `message`, `session_id`, `working_dir`, `metadata` | `sdk/hooks/types.py` | the guard tolerates every field and unknown keys |
| `OPENHANDS_PROJECT_DIR` is exported to hooks | `sdk/hooks/executor.py` | used to locate the project |

## Research profile

The installer enables `profile: book-of-mormon` by default, copies the stdlib
research helper beside the hooks, and initializes the three working reports. The
Stop hook itself runs a built-in `research-validator` gate; it is not a removable
shell gate, so `--no-gates` and `mode=always` still enforce the fixed task. The
validator enforces the prompt's six coded steps per evidence item, the witnesses
score cap, all three report digests, and — at finalization — the Google Docs
sync receipt. Deny context names the next for/against side and the evidence
protocol instead of generic coding work. A user stop creates `STOP_REQUESTED`;
the gate then requires `compile --final` reports whose ledger digest is current
and three Google Docs synced at that digest in final mode. PreToolUse makes the
ledger/report/helper writes helper-only and blocks premature finalization. It
never asks for another research round after that stop. See
[`openhands-cloud.md`](openhands-cloud.md) and [`evidence-schema.md`](evidence-schema.md).

## What enforcement still cannot do

- **A deleted hook script stops the hook from running.** OpenHands treats a hook
  that errors as an error, not a denial. Enforcement cannot survive an agent that
  removes every copy and restarts the conversation; that is why the backup copy
  lives beside the hooks and why `--status` reports `last decisions`.
- **Iteration ceiling.** A run still ends at `max_iterations` (default 500). The
  ledger makes the boundary resumable; raise the limit for longer runs.
- **Stuck detection.** Identical repeated actions trip it. The loop protocol
  forbids repeating a failing command, and the deny payload always names the next
  target.
- **A user who kills the process** outranks any hook. "Never stop" means the
  agent never *elects* to stop.

## Safety

- Arm only when the user asked for an infinite loop.
- The deny payloads never contain secrets; gate output is truncated to 12 lines.
- `--uninstall` leaves unrelated hooks untouched.
- Never commit `.openhands/guard` state; see
  [`assets/project.gitignore.fragment`](../assets/project.gitignore.fragment).

## See also

- Hooks reference: <https://docs.openhands.dev/openhands/usage/customization/hooks>
- Skills overview: <https://docs.openhands.dev/overview/skills>
- Agent Skills format: <https://docs.openhands.dev/sdk/guides/skill>
