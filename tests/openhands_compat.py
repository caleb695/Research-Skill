#!/usr/bin/env python3
"""Conformance checks against OpenHands' real skill + hook contract.

OpenHands' skill loader and hook executor are Python 3.12+ and cannot be
installed in every environment, so this script reimplements the *rules* that
matter (taken from the SDK source) and asserts this skill and its installed
hooks satisfy them. It is a faithful subset, not a substitute for an end-to-end
run in a real OpenHands conversation.

Rules enforced (see openhands-sdk: sdk/skills/utils.py, sdk/skills/skill.py,
sdk/hooks/config.py, sdk/hooks/executor.py, sdk/conversation/...):

  skills
    * SKILL.md is discovered only in subdirectories of a skills dir
    * skill name must match the parent directory name
    * name matches ^[a-z0-9]+(-[a-z0-9]+)*$ and is <= 64 chars
    * description is required by the AgentSkills standard, <= 1024 chars
    * triggers must be a YAML list -> KeywordTrigger (auto-inject)
    * resources/ dirs are scripts/, references/, assets/

  hooks
    * hooks.json is an object keyed by snake_case event names from
      {pre_tool_use, post_tool_use, user_prompt_submit, session_start,
       session_end, stop}
    * each entry is {matcher, hooks: [{type, command, timeout}]}
    * exit code 2 (or {"decision":"deny"}) blocks
    * a Stop hook that blocks sets the run back to RUNNING
    * command hooks run with cwd=working_dir; committed commands stay repo-relative
    * the agent receives `additionalContext`; the Stop path forwards nothing else

Usage: python3 tests/openhands_compat.py [--project DIR]
Exits 0 when every check passes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / "infinite"
SKILL_MD = SKILL_DIR / "SKILL.md"
# The repo root also carries a SKILL.md, so this repository can be used directly
# as a working directory without copying anything.
ROOT_SKILL_MD = REPO / "SKILL.md"

# --- rules copied from the SDK ------------------------------------------------ #
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
RESOURCE_DIRECTORIES = ("scripts", "references", "assets")
HOOK_EVENT_FIELDS = {
    "pre_tool_use",
    "post_tool_use",
    "user_prompt_submit",
    "session_start",
    "session_end",
    "stop",
}

failures: list[str] = []
COMPAT_TMP: list[str] = []


def check(condition: bool, label: str, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}{f' — {detail}' if detail else ''}")


# --- a tiny frontmatter parser (no PyYAML dependency) ------------------------- #
def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    raw = text[4:end]
    body = text[end + 5 :]
    data: dict = {}
    key = None
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  ") or line.startswith("- "):
            # nested metadata or list item
            item = line.strip()
            if item.startswith("- "):
                if isinstance(data.get(key), list):
                    data[key].append(item[2:].strip().strip("'\""))
                else:
                    data[key] = [item[2:].strip().strip("'\"")]
            elif key and isinstance(data.get(key), dict):
                k, _, v = item.partition(":")
                data[key][k.strip()] = v.strip().strip("'\"")
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value in {"", ">-", ">", "|", "|-"}:
                data[key] = {} if value in {">-", ">", "|", "|-"} else []
                key = key
            elif value.startswith("[") and value.endswith("]"):
                data[key] = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
            else:
                data[key] = value.strip("'\"")
    # multi-line folded descriptions
    if isinstance(data.get("description"), dict):
        lines = []
        collecting = False
        for line in raw.splitlines():
            if line.startswith("description:"):
                collecting = True
                continue
            if collecting:
                if re.match(r"^[a-zA-Z_-]+:", line):
                    break
                lines.append(line.strip())
        data["description"] = " ".join(part for part in lines if part)
    return data, body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", help="an installed project to verify hooks in")
    args = parser.parse_args()

    print("== discovery layout ==")
    check(SKILL_MD.is_file(), "SKILL.md exists at the path OpenHands scans", str(SKILL_MD))
    check(
        SKILL_DIR.name == "infinite",
        "skill directory is skills/<name>/",
        SKILL_DIR.name,
    )
    for resource in RESOURCE_DIRECTORIES:
        if (SKILL_DIR / resource).is_dir():
            print(f"  ok   resource dir '{resource}/' is a standard AgentSkills directory")
    # OpenHands only reads scripts/, references/ and assets/ as resources; other
    # directories inside a skill are inert (it loads SKILL.md dirs, not their
    # contents). `commands/` is part of the Claude plugin layout we also ship.
    inert_allowed = {"commands"}
    unexpected = [
        d.name
        for d in SKILL_DIR.iterdir()
        if d.is_dir() and d.name not in RESOURCE_DIRECTORIES and d.name not in inert_allowed
        and not d.name.startswith(".")
    ]
    check(not unexpected, "no unexpected subdirectories", str(unexpected))

    print("== frontmatter ==")
    meta, body = parse_frontmatter(SKILL_MD.read_text(encoding="utf-8"))
    name = str(meta.get("name", ""))
    description = str(meta.get("description", ""))
    check(bool(name), "name is present")
    check(name == SKILL_DIR.name, "name matches the directory name (strict loader)")
    check(
        bool(SKILL_NAME_PATTERN.match(name)),
        "name matches ^[a-z0-9]+(-[a-z0-9]+)*$",
        name,
    )
    check(len(name) <= MAX_NAME_LENGTH, f"name is <= {MAX_NAME_LENGTH} chars", str(len(name)))
    check(bool(description), "description is present (AgentSkills standard)")
    check(
        len(description) <= MAX_DESCRIPTION_LENGTH,
        f"description is <= {MAX_DESCRIPTION_LENGTH} chars (longer is truncated)",
        str(len(description)),
    )
    triggers = meta.get("triggers")
    check(isinstance(triggers, list) and bool(triggers), "triggers is a non-empty list")
    if isinstance(triggers, list):
        check(
            all(isinstance(t, str) and t.strip() for t in triggers),
            "every trigger is a non-empty string",
        )
        check(
            "/infinite" in triggers,
            "slash-command trigger '/infinite' present (whole-token match)",
        )
        check(
            "use this skill" in triggers,
            "minimal fixed-task trigger 'use this skill' present",
        )
        non_ascii = [t for t in triggers if not t.isascii()]
        check(not non_ascii, "triggers are ASCII (safe whole-token matching)", str(non_ascii))
    check(bool(body.strip()), "body content is present after the frontmatter")
    fixed_task = SKILL_DIR / "references" / "fixed-task.md"
    check(fixed_task.is_file(), "authoritative fixed-task prompt is bundled")
    if fixed_task.is_file():
        fixed_text = fixed_task.read_text(encoding="utf-8")
        check("indefinitely research online for evidence for and against the Book of Mormon" in fixed_text,
              "fixed prompt contains the original research task")
        check("When I say stop" in fixed_text, "fixed prompt contains the original stop/report instruction")
    check("generic audit" not in body and "unrelated coding task" not in body,
          "canonical skill does not fall back to generic unrelated work")

    print("== unknown frontmatter keys are harmless ==")
    known = {
        "name", "description", "license", "compatibility", "metadata",
        "allowed-tools", "triggers", "paths", "inputs", "version",
        "disable-model-invocation", "mcp_tools",
    }
    unknown = sorted(set(meta) - known)
    check(not unknown, "only standard/OpenHands fields are used", str(unknown))
    check("paths" not in meta, "no `paths:` (it would shadow triggers and disable invocation)")

    print("== root SKILL.md (repo used directly as a working dir) ==")
    if ROOT_SKILL_MD.is_file():
        root_meta, root_body = parse_frontmatter(ROOT_SKILL_MD.read_text(encoding="utf-8"))
        root_name = str(root_meta.get("name", ""))
        check(
            bool(SKILL_NAME_PATTERN.match(root_name)),
            "root name matches ^[a-z0-9]+(-[a-z0-9]+)*$",
            root_name,
        )
        check(len(root_name) <= MAX_NAME_LENGTH, "root name is <= 64 chars")
        check(
            root_name != SKILL_DIR.name,
            "root skill name differs from the nested one (no silent shadowing)",
            root_name,
        )
        root_desc = str(root_meta.get("description", ""))
        check(
            0 < len(root_desc) <= MAX_DESCRIPTION_LENGTH,
            f"root description is 1-{MAX_DESCRIPTION_LENGTH} chars",
            str(len(root_desc)),
        )
        check(isinstance(root_meta.get("triggers"), list), "root triggers is a list")
        check(bool(root_body.strip()), "root body is present")
    else:
        print("  --   no root SKILL.md (skill installs via .agents/skills/ only)")

    print("== Cloud project launcher ==")
    launcher = REPO / ".agents" / "skills" / "infinite" / "SKILL.md"
    check(launcher.is_file(), "standard .agents/skills/infinite/SKILL.md entry point exists")
    if launcher.is_file():
        launch_meta, launch_body = parse_frontmatter(launcher.read_text(encoding="utf-8"))
        check(launch_meta.get("name") == "infinite", "launcher name matches its directory")
        check(isinstance(launch_meta.get("triggers"), list), "launcher has keyword triggers")
        check("infinite/SKILL.md" in launch_body, "launcher points to the canonical package")
        check("paths" not in launch_meta, "launcher does not shadow triggers with paths")

    print("== command shim ==")
    shim = SKILL_DIR / "commands" / "infinite.md"
    if shim.is_file():
        shim_meta, _ = parse_frontmatter(shim.read_text(encoding="utf-8"))
        has_header = shim.read_text(encoding="utf-8").startswith("---")
        check(
            (not has_header) or bool(shim_meta.get("description")),
            "command file starts with a valid header or none at all",
        )
        shim_text = shim.read_text(encoding="utf-8")
        check("$ARGUMENTS" not in shim_text, "command shim does not substitute arguments as the task")
        check("fixed-task.md" in shim_text, "command shim points to the fixed prompt")

    project = Path(args.project).resolve() if args.project else None
    if project is None:
        tmp = tempfile.mkdtemp(prefix="infinite-compat-")
        COMPAT_TMP.append(tmp)
        project = Path(tmp) / "proj"
        project.mkdir()
        install = SKILL_DIR / "scripts" / "install-openhands-hooks.sh"
        proc = subprocess.run(
            ["bash", str(install), "--dir", str(project), "--generic", "--gate", "tests:true"],
            capture_output=True,
            text=True,
        )
        check(proc.returncode == 0, "installer runs cleanly", proc.stderr[-300:])
    else:
        check(
            (project / ".openhands/hooks.json").is_file(),
            f"{project} has installed hooks",
        )

    print("== hooks.json conforms to HookConfig ==")
    hooks_path = project / ".openhands" / "hooks.json"
    config = json.loads(hooks_path.read_text(encoding="utf-8"))
    check(isinstance(config, dict), "hooks.json is a JSON object")
    check(
        set(config) <= HOOK_EVENT_FIELDS,
        "every event key is a valid HOOK_EVENT_FIELD",
        str(set(config) - HOOK_EVENT_FIELDS),
    )
    for event, entries in config.items():
        check(isinstance(entries, list), f"'{event}' is a list of matchers")
        for entry in entries:
            check(
                isinstance(entry, dict) and "hooks" in entry and isinstance(entry["hooks"], list),
                f"'{event}' entries have a 'hooks' list",
            )
            check(
                "matcher" in entry or True,
                f"'{event}' matcher optional (defaults to '*')",
            )
            for hook in entry.get("hooks", []):
                check(
                    hook.get("type", "command") == "command",
                    f"'{event}' hook type is command",
                )
                check(bool(hook.get("command")), f"'{event}' hook has a command")
                check(
                    isinstance(hook.get("timeout", 60), int),
                    f"'{event}' timeout is an int",
                )
                check(
                    not hook.get("async", False),
                    f"'{event}' hook is synchronous (async cannot block)",
                )

    print("== hook behaviour matches the executor ==")
    stop_cmd = config["stop"][0]["hooks"][0]["command"]
    check("--policy" in stop_cmd, "Stop hook carries the immutable policy")
    check(
        stop_cmd.startswith("bash .openhands/hooks/"),
        "Stop hook uses a portable repo-relative command",
        stop_cmd[:80],
    )
    check(
        str(project) not in stop_cmd,
        "Stop hook does not bake in the installer's checkout path",
        stop_cmd[:80],
    )
    gate_timeout = sum(
        int(g.get("timeout", 600))
        for entry in config["stop"] for h in entry["hooks"]
        for g in json.loads(__import__("base64").urlsafe_b64decode(
            h["command"].split("--policy ", 1)[1].strip("'") + "==="
        )).get("gates", [])
    )
    check(
        config["stop"][0]["hooks"][0]["timeout"] > gate_timeout,
        "Stop hook timeout exceeds the configured gate budget",
    )

    def run(cmd: str, payload: dict, env_extra: dict | None = None) -> tuple[int, str]:
        env = dict(os.environ)
        env["OPENHANDS_PROJECT_DIR"] = str(project)
        env.update(env_extra or {})
        proc = subprocess.run(
            cmd,
            shell=True,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=project,  # current SDK executor uses cwd=working_dir
            env=env,
            timeout=120,
        )
        return proc.returncode, proc.stdout

    # The executor sends these exact fields (HookEvent); extra keys must not break us.
    stop_event = {
        "event_type": "Stop",
        "tool_name": None,
        "tool_input": None,
        "tool_response": None,
        "message": None,
        "session_id": "test-session",
        "working_dir": str(project),
        "metadata": {"reason": "agent_finished"},
    }
    code, out = run(stop_cmd, stop_event)
    check(code == 2, "finish attempt returns exit 2 (blocked)", str(code))
    payload = json.loads(out) if out.strip() else {}
    check(payload.get("decision") == "deny", "stdout decision is 'deny'")
    ctx = payload.get("additionalContext", "")
    check(bool(ctx), "additionalContext is set (the only text the agent sees)")
    check("Gates:" in ctx, "additionalContext carries gate results, not just prose")
    check(len(ctx) < 8000, "additionalContext is concise", f"{len(ctx)} chars")

    armed = stop_cmd
    disarm_payload = {
        "event_type": "UserPromptSubmit",
        "message": "stop",
        "session_id": "test-session",
        "working_dir": str(project),
    }
    user_cmd = config["user_prompt_submit"][0]["hooks"][0]["command"]
    run(user_cmd, disarm_payload)
    code, out = run(armed, stop_event)
    check(code == 0, "a real 'stop' message lets the finish through", str(code))

    pre_cmd = config["pre_tool_use"][0]["hooks"][0]["command"]
    check("--policy" in pre_cmd, "PreToolUse hook carries the immutable policy")
    prompt_cmd = config["user_prompt_submit"][0]["hooks"][0]["command"]
    check("--policy" in prompt_cmd, "UserPromptSubmit hook carries the immutable policy")
    deny_payload = {
        "event_type": "PreToolUse",
        "tool_name": "terminal",
        "tool_input": {"command": "python3 .openhands/guard/infinite_guard.py disarm"},
        "session_id": "test-session",
        "working_dir": str(project),
    }
    code, _ = run(pre_cmd, deny_payload)
    check(code == 2, "PreToolUse blocks disabling the guard", str(code))
    allow_payload = dict(deny_payload, tool_input={"command": "pytest -q"})
    code, _ = run(pre_cmd, allow_payload)
    check(code == 0, "PreToolUse allows ordinary commands", str(code))

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("all OpenHands conformance checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil

        for path in COMPAT_TMP:
            shutil.rmtree(path, ignore_errors=True)
