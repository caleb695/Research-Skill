# OpenHands Cloud compatibility

Checked on 2026-11-07 against the current OpenHands documentation repository
(`OpenHands/docs`, commit `bde5151ccf7cd0d53f248c05d4cbed6927d6f258`) and SDK
(`OpenHands/software-agent-sdk`, commit
`18f6390502e0c1b5c162937294be9e19340b4a94`). This is a source/contract check plus
local tests, not a claim that a live hosted Cloud conversation was run here.

## What Cloud supports

- Agent Skills are discovered as `<skills-dir>/<name>/SKILL.md`. The name must
  match the directory, use lowercase letters/digits/single hyphens, and be at
  most 64 characters; description is required and limited to 1024 characters.
- Project skills live at `.agents/skills/` in the conversation workspace. This
  repo ships `.agents/skills/infinite/SKILL.md` as a launcher to the canonical
  `infinite/` package, so selecting this repo as the workspace exposes the skill.
- Cloud can also import/load a Git-hosted skill or plugin by repository path.
  Select `infinite/` as the skill directory; current plugin loaders also accept a
  single root `SKILL.md` in a plugin package. The canonical package is
  self-contained after installation.
- Repository hooks are loaded from `.openhands/hooks.json` in the working folder.
  Current docs explicitly include OpenHands Cloud. Command hooks run with cwd set
  to the working folder and receive `OPENHANDS_PROJECT_DIR` plus JSON on stdin.
- Exit code 2 blocks; other nonzero codes are non-blocking errors. Stop feedback
  must be in `additionalContext` to reach the agent reliably.

Sources in the checked docs checkout:
`overview/skills.mdx`, `overview/skills/adding.mdx`,
`openhands/usage/customization/hooks.mdx`,
`openhands/usage/customization/repository.mdx`,
`openhands/usage/cloud/plugin-launcher.mdx`. SDK sources:
`openhands-sdk/openhands/sdk/skills/{skill,utils}.py` and
`openhands-sdk/openhands/sdk/hooks/{config,executor,conversation_hooks}.py`.

## Use the skill in Cloud

1. Push this repository/branch and connect it to OpenHands Cloud.
2. Start a conversation with this repository as the workspace, or import the
   `infinite/` directory as a Git-hosted skill. Enable/select `infinite` if the UI
   presents a skill catalog. Start a new conversation after changing skill files.
3. Send the research request, e.g. `/infinite Research evidence for and against
   the Book of Mormon until I say stop; use the bundled research protocol.`
4. The launcher reads `infinite/SKILL.md`; the agent initializes the ledger and
   alternates for/against rounds using the workspace's web/browser tools.

The skill does not grant network access. If the Cloud environment restricts
hosts, lacks a browser, or hits a paywall, record the limitation and use accessible
primary texts/other source classes. Never pretend a blocked source was checked.

## Optional enforcement in Cloud

Install from a terminal/setup environment **before starting the conversation**:

```bash
bash infinite/scripts/install-openhands-hooks.sh --dir . --research --install-skill
```

This installs the complete skill, copies the research validator beside the hooks,
adds a `research` gate, initializes the two reports, and writes hooks with
**repo-relative commands** such as:

```json
{
  "stop": [{"matcher": "*", "hooks": [{
    "command": "bash .openhands/hooks/infinite-stop.sh --policy <blob>",
    "timeout": 615
  }]}]
}
```

The exact timeout is derived from configured gate budgets so the hook does not
time out before its gates. Commit the generated `.openhands/hooks.json` and hook
scripts if you want the wiring to travel with the repository; keep
`.openhands/guard/` and `.infinite/` scratch state out of Git. Do not commit a
policy containing secrets. Start a new conversation after installation because
hooks are loaded at conversation start.

The installer's embedded policy is fixed for that loaded hook command. The agent
cannot weaken it by editing the on-disk mirror. User stop in research mode writes
`STOP_REQUESTED`; the gate then blocks finishing only until both final reports are
compiled and validated. It does not order more research. The user can always run
the installer with `--disarm` or `--uninstall` from their own terminal.

Without hooks, the skill still runs as instructions and the agent must obey the
stop/final-report protocol. Cloud iteration/budget limits still end a run; the
ledger and reports make `continue` resumable. Nothing here overrides the user,
Cloud policy, or platform limits.

## Portability rules enforced by tests

- No installer-generated hook command may contain the build machine's absolute
  project path. Commands are relative to the Cloud working folder; dispatchers
  resolve their own directory for guard lookup.
- A copied/relocated checkout must still deny a finish attempt and run the
  research gate from the new path.
- The project launcher and canonical skill must pass strict name/description/
  trigger checks; no `paths:` key may shadow the keyword trigger.
- Hook JSON uses snake_case events, synchronous command hooks, exit 2 for denial,
  and actionable `additionalContext`.
- The Stop hook timeout exceeds the sum of gate timeouts.

Run:

```bash
bash tests/smoke.sh
python3 tests/openhands_compat.py
python3 tests/test_research.py
```

`tests/openhands_compat.py` is a faithful subset of the SDK contract, not the SDK
itself. A live Cloud smoke test remains the final deployment check: start a new
conversation, confirm `infinite` loads, verify one for/against checkpoint, say
`stop`, and confirm both final reports are produced before the run finishes.
