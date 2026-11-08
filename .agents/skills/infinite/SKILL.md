---
name: infinite
description: >-
  Project entry point for the Infinite Book of Mormon evidence-research skill.
  Use when asked to research evidence for and against the Book of Mormon
  indefinitely, or when the user says /infinite, never stop, keep going, or
  until I say stop. Loads the canonical repository skill and its verification,
  scoring, alternating-round, durable-ledger, and two-report stop protocol.
triggers:
- /infinite
- /forever
- /never-stop
- never stop
- don't stop
- do not stop
- keep going
- keep improving
- infinite mode
- work forever
- until I say stop
- indefinitely research
- Book of Mormon
license: MIT
compatibility: OpenHands Cloud project-skill discovery; canonical resources live in the repository's infinite/ directory.
metadata:
  author: caleb695
  version: "1.1.0"
---

# Infinite repository launcher

This file exists at the standard project-skill discovery path so OpenHands
Cloud can find the skill when this repository is the conversation workspace.
It is a launcher, not the complete portable package.

Before doing any work:

1. The repository root is `../../../` relative to the directory containing this file.
2. Read `<repository-root>/infinite/SKILL.md` in full and follow it.
3. Read the references it names from `<repository-root>/infinite/references/`.
4. Run helpers from `<repository-root>/infinite/scripts/` with the conversation
   workspace as `--dir`.

For Book of Mormon research, initialize the research ledger if needed, alternate
for/against rounds, verify and score every item, and maintain the two reports.
On an explicit user stop, cease research and compile both final reports. For an
unrelated task, follow the canonical skill's generic audit/improve/verify loop.

To install the complete self-contained skill into another workspace, use
`infinite/scripts/install-openhands-hooks.sh --install-skill`; to load it directly
from GitHub in Cloud, select the `infinite/` directory (see the repository
README and `infinite/references/openhands-cloud.md`). Do not treat this launcher
alone as a portable copy of the scripts and references.
