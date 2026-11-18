# OpenHands Cloud compatibility

Checked on 2026-11-11 against the upstream OpenHands documentation repository
(`OpenHands/docs`), SDK & Agent Server (`OpenHands/software-agent-sdk`),
frontend/Cloud app client (`OpenHands/OpenHands`), and official extensions
(`OpenHands/extensions`).

## Why Cloud requires conversation-start wiring

In OpenHands Cloud, each conversation provisions a sandbox runtime and loads
skills, plugins, and lifecycle hooks (`LocalConversation._ensure_plugins_loaded`)
when the conversation starts:

- Project skills are discovered from `<workspace>/.agents/skills/<name>/SKILL.md`.
  Every `SKILL.md` must start with valid YAML frontmatter (`name` matching the
  directory name, `description` <= 1024 chars, and `triggers` list for automatic
  keyword injection on phrases like `use this skill` or `/infinite`).
- Repository hooks in `<workspace>/.openhands/hooks.json` and plugin hooks in
  `<plugin>/hooks/hooks.json` (with `PLUGIN_ROOT` exported by the SDK hook
  executor) are bound once at conversation initialization. Writing
  `.openhands/hooks.json` mid-conversation does **not** attach hooks to the
  already-running conversation.
- `/add-skill` sparse-checkouts the target directory into
  `<workspace>/.agents/skills/infinite/`; OpenHands rebuilds the skill catalog on
  the **next new conversation** in that workspace.

## Supported OpenHands Cloud workflows

### 1. Use this repository directly as the Cloud workspace (zero manual setup)

1. Connect `caleb695/Research-Skill` in OpenHands Cloud and start a conversation.
2. `.agents/skills/infinite/SKILL.md` exposes the `infinite` project skill,
   `.openhands/setup.sh` ensures executable permissions and installs optional
   Google Docs client libraries, and `.openhands/hooks.json` pre-loads the
   deterministic Book of Mormon hooks in **standby mode** (`mode=standby`).
3. Ordinary non-skill prompts run and finish normally because `.openhands/guard/ARMED`
   is absent in standby mode.
4. Send `use this skill` or `/infinite`: `UserPromptSubmit` immediately arms
   `.openhands/guard/ARMED` in the running Cloud conversation, and `PreToolUse` +
   `Stop` enforce the full alternating research loop until you say `stop`.

### 2. Launch on any repository via OpenHands Cloud Plugin Launcher (`/launch` or Plugins UI)

Both `infinite/` (`repo_path: "infinite"`) and the repository root ship valid
OpenHands plugin manifests (`.plugin/plugin.json` and `.claude-plugin/plugin.json`)
plus `hooks/hooks.json` using `${PLUGIN_ROOT}`:

```json
[
  {
    "source": "github:caleb695/Research-Skill",
    "ref": "main",
    "repo_path": "infinite"
  }
]
```

Or quick test URL format:

```text
https://app.all-hands.dev/launch?plugin_source=github:caleb695/Research-Skill&plugin_ref=main&plugin_repo_path=infinite&message=use%20this%20skill
```

When attached as a Cloud plugin, OpenHands loads the `infinite` skill, `/infinite:infinite`
command, and `${PLUGIN_ROOT}` standby enforcement hooks into the conversation
from turn 1—even on an empty sandbox or another repository. Note that
`infinite_guard.py` explicitly allows executing helpers and reading references
from OpenHands' `~/.openhands/{plugins,skills,cache}` directories while still
blocking any tampering with `<workspace>/.openhands/{guard,hooks,hooks.json}`.

### 3. Import into another workspace via `/add-skill` or installer

- In an existing Cloud workspace, run:
  `/add-skill https://github.com/caleb695/Research-Skill/tree/main/infinite`
  (or `bash infinite/scripts/install-openhands-hooks.sh --dir . --install-skill --no-arm`),
  then **start a new conversation** on that workspace so OpenHands reloads the
  skill catalog (and `.openhands/hooks.json` if installed).

## Google Docs & Cloud Secrets

To use Google Docs viewing/editing in OpenHands Cloud:
- Add a Cloud Secret named `GOOGLE_SERVICE_ACCOUNT_JSON` (raw or base64 JSON of
  the service account key) or `GOOGLE_APPLICATION_CREDENTIALS`, **or**
- Place the key in `.google/credentials.json` or `.google` in the workspace.

## Portability rules enforced by tests

- All committed `.openhands/hooks.json` commands are repo-relative (`bash .openhands/hooks/...`),
  and all plugin `hooks/hooks.json` commands resolve through `${PLUGIN_ROOT}`.
- Relocated checkouts and empty workspaces using `PLUGIN_ROOT` both enforce
  `UserPromptSubmit`, `PreToolUse`, and `Stop` identically.
- Canonical `infinite/SKILL.md`, launcher `.agents/skills/infinite/SKILL.md`, and
  root `SKILL.md` all pass strict AgentSkills frontmatter and trigger checks.

Run locally:

```bash
bash tests/smoke.sh
python3 tests/openhands_compat.py
python3 tests/test_research.py
```
