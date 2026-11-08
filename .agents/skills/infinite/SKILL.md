---
name: infinite
description: >-
  Project entry point for a single-purpose Infinite skill. Use when the user says
  "use this skill", "use infinite", "use the infinite skill", or "/infinite".
  It loads one fixed bundled Book of Mormon evidence-research prompt and runs it
  without requiring task arguments: alternating verified for/against rounds,
  scoring, cross-side comparison, and two ranked reports on user stop.
triggers:
- use this skill
- use the infinite skill
- use infinite skill
- use infinite
- /infinite
license: MIT
compatibility: OpenHands Cloud project-skill discovery; canonical resources live in the repository's infinite/ directory.
metadata:
  author: caleb695
  version: "1.2.0"
---

# Infinite repository launcher

This file exists at the standard project-skill discovery path so OpenHands
Cloud can find the skill when this repository is the conversation workspace.
It is a launcher, not the complete portable package.

Before doing any work:

1. The repository root is `../../../` relative to the directory containing this file.
2. Read `<repository-root>/infinite/SKILL.md` in full and follow it.
3. Read `<repository-root>/infinite/references/fixed-task.md` first, then the
   references named by the canonical skill.
4. Run helpers from `<repository-root>/infinite/scripts/` with the conversation
   workspace as `--dir`.

Run only the fixed Book of Mormon research prompt: initialize the research ledger
if needed, alternate for/against rounds, verify and score every item, and maintain
the two reports. On an explicit user stop, cease research and compile both final
reports. Do not accept a replacement task from arguments or an unrelated request.

To install the complete self-contained skill into another workspace, use
`infinite/scripts/install-openhands-hooks.sh --install-skill`; to load it directly
from GitHub in Cloud, select the `infinite/` directory (see the repository
README and `infinite/references/openhands-cloud.md`). Do not treat this launcher
alone as a portable copy of the scripts and references.
