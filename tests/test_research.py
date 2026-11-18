#!/usr/bin/env python3
"""Standard-library tests for the Book of Mormon research profile.

These test mechanics (schema, scoring, deduplication, alternation, reports,
resume, and Cloud-style hook relocation). They do not assert any historical or
religious conclusion; fixture sources are illustrative, not research findings.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "infinite" / "scripts"
RESEARCH = SCRIPTS / "infinite_research.py"
STATE = SCRIPTS / "infinite_state.py"
INSTALL = SCRIPTS / "install-openhands-hooks.sh"
spec = importlib.util.spec_from_file_location("infinite_research", RESEARCH)
assert spec and spec.loader
research = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = research
spec.loader.exec_module(research)


def evidence(eid="F001", side="for", identity="A distinct checked observation", verdict="verified", opposing=None):
    return {
        "id": eid, "side": side, "category": "bible", "title": f"Fixture {eid}",
        "identity": identity, "aliases": [],
        "proposition": "A synthetic observation used only to test the ledger.",
        "inference": "This fixture tests structure, not a historical conclusion.",
        "assumptions": ["Synthetic test fixture; not evidence about the Book of Mormon."],
        "dependence": "Single synthetic source chain.",
        "uncertainty": "Not a real research finding.",
        "authenticity": {"verdict": verdict, "checks": ["Structural fixture created by the test suite."], "limitations": "Illustrative only."},
        "context": {"textual": "Whole synthetic unit reviewed.", "historical": "Synthetic test context.", "pov": "Test author; no religious POV.", "missing_facts": "No real-world facts are asserted."},
        "sources": [{"id": "S1", "title": "Synthetic primary fixture", "reference": "Test suite fixture, not a publication", "url": "https://example.org/fixture", "locator": "fixture line 1", "accessed": "2026-11-07", "kind": "test-fixture", "independence_group": "fixture", "bias": "none; synthetic", "verification": "Created by this test; not an online historical check."}],
        "scores": {"credibility": 80, "accuracy": 90, "relevance": 70, "usefulness": 60},
        "score_reasons": {d: f"Fixture rationale for {d}." for d in research.DIMENSIONS},
        "counter_evaluation": {"analysis": "A synthetic alternative is considered; this is not a real evidential judgment.", "opposing_ids": opposing or [], "source_ids": ["S1"]},
    }


def claim(cid="C001", side="for", eids=None, opposing=None):
    return {
        "id": cid, "side": side, "category": "bible", "title": f"Fixture claim {cid}",
        "statement": "A synthetic claim for testing report organization.",
        "synthesis": "The fixture demonstrates how evidence is grouped without counting duplicates as independent support.",
        "evidence_ids": eids or ["F001"], "assumptions": ["Synthetic fixture."],
        "dependence": "One fixture chain.", "uncertainty": "No historical conclusion.",
        "scores": {"credibility": 75, "accuracy": 85, "relevance": 65, "usefulness": 55},
        "score_reasons": {d: f"Fixture claim rationale for {d}." for d in research.DIMENSIONS},
        "counter_evaluation": {"analysis": "The strongest synthetic alternative is acknowledged for testing.", "opposing_ids": opposing or [], "source_ids": []},
    }


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="infinite-research-test-")
        self.project = Path(self.tmp.name) / "project"
        self.project.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_py(self, script, *args, ok=True, cwd=None):
        proc = subprocess.run([sys.executable, str(script), "--dir", str(self.project), *args], capture_output=True, text=True, cwd=cwd or self.project)
        if ok:
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        elif ok is False:
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def write_record(self, record):
        path = self.project / "record.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        return str(path)

    def init(self):
        self.run_py(RESEARCH, "init")

    def add_evidence(self, record, revise=False, ok=True):
        return self.run_py(RESEARCH, "revise" if revise else "evidence", "--file", self.write_record(record), ok=ok)

    def add_claim(self, record, ok=True):
        return self.run_py(RESEARCH, "claim", "--file", self.write_record(record), ok=ok)

    def log(self, side, outcome="accepted", eid=None, ok=True):
        args = ["log", "--target", "fixture target", "--verification", "fixture checks passed", "--next", "opposite-side fixture", "--side", side, "--outcome", outcome]
        if eid:
            args += ["--evidence-id", eid]
        return self.run_py(STATE, *args, ok=ok)

    def test_init_is_idempotent_and_creates_two_reports(self):
        self.init()
        self.log("for", "no-new")
        before = json.loads((self.project / ".infinite/state.json").read_text())
        self.init()
        after = json.loads((self.project / ".infinite/state.json").read_text())
        self.assertEqual(after["round"], before["round"])
        self.assertEqual(after["next_side"], "against")
        self.assertEqual(after["dry_rounds"], 1)
        for side in ("for", "against"):
            path = self.project / f"research/book-of-mormon-{side}.md"
            self.assertTrue(path.is_file())
            self.assertIn("INTERIM", path.read_text())
        self.run_py(RESEARCH, "validate")

    def test_score_formula_and_provenance_caps(self):
        item = evidence()
        item["overall_score"] = research.score(item, "test", [])
        self.assertEqual(item["overall_score"], 76.8)
        for verdict, cap in (("unverified", 49.0), ("disputed", 69.0), ("fabricated", 0.0)):
            item = evidence(verdict=verdict)
            self.assertEqual(research.score(item, "test", [], research.CAPS[verdict]), cap)
        item = evidence()
        item["scores"]["credibility"] = 0
        self.assertEqual(research.score(item, "test", []), 0.0)

    def test_helper_computes_score_and_rejects_bad_sources_context(self):
        self.init()
        item = evidence()
        self.assertNotIn("overall_score", item)
        self.add_evidence(item)
        stored = research.store(self.project)["evidence"]["F001"]
        self.assertEqual(stored["overall_score"], 76.8)
        bad = evidence("F002", identity="Another observation")
        bad["sources"][0]["url"] = "https://en.wikipedia.org/wiki/Example"
        self.add_evidence(bad, ok=False)
        bad = evidence("F003", identity="Third observation")
        del bad["context"]["pov"]
        self.add_evidence(bad, ok=False)

    def test_deduplication_and_revision_do_not_create_new_items(self):
        self.init()
        self.add_evidence(evidence())
        self.add_evidence(evidence("F002", identity="  A   DISTINCT checked observation! "), ok=False)
        alias = evidence("F003", identity="Different wording")
        alias["aliases"] = ["A distinct checked observation"]
        self.add_evidence(alias, ok=False)
        revised = evidence()
        revised["uncertainty"] = "Updated after a deeper fixture check."
        self.add_evidence(revised, revise=True)
        data = research.store(self.project)
        self.assertEqual(len(data["evidence"]), 1)
        self.assertEqual(data["evidence"]["F001"]["revision"], 2)
        self.assertIn("Updated after", data["evidence"]["F001"]["uncertainty"])
        out = self.run_py(RESEARCH, "lookup", "distinct checked").stdout
        self.assertIn("F001", out)

    def test_alternation_dry_rounds_and_resume(self):
        self.init()
        self.add_evidence(evidence("A001", "against", "A distinct opposing fixture"))
        self.log("against", ok=False)
        self.log("for", "no-new")
        self.log("for", "no-new", ok=False)
        self.log("against", "blocked")
        self.log("for", "blocked")
        state = json.loads((self.project / ".infinite/state.json").read_text())
        self.assertEqual(state["dry_rounds"], 3)
        self.assertEqual(state["next_side"], "against")
        self.run_py(RESEARCH, "compile", "--final")
        self.log("against", ok=False)
        self.run_py(STATE, "resume")
        self.log("against", "deepened", "A001")
        state = json.loads((self.project / ".infinite/state.json").read_text())
        self.assertEqual(state["round"], 4)
        self.assertEqual(state["dry_rounds"], 0)
        self.assertEqual(state["next_side"], "for")

    def test_claims_cross_links_final_reports_and_staleness(self):
        self.init()
        self.add_evidence(evidence())
        self.add_evidence(evidence("A001", "against", "A distinct opposing observation"))
        revised = evidence(opposing=["A001"])
        self.add_evidence(revised, revise=True)
        self.add_claim(claim())
        self.add_claim(claim("C002", "against", ["A001"], ["F001"]))
        self.add_claim(claim("C003", "for", ["A001"]), ok=False)
        self.log("for", "accepted", "F001")
        self.log("against", "accepted", "A001")
        self.run_py(RESEARCH, "search", "--side", "for", "--query", "fixture primary text", "--outcome", "accepted", "--notes", "Synthetic search log.")
        self.run_py(RESEARCH, "note", "--side", "against", "--kind", "method-limit", "--text", "Fixture coverage limit.")
        self.run_py(RESEARCH, "compile")
        self.run_py(RESEARCH, "validate")
        proc = self.run_py(RESEARCH, "validate", "--final", ok=False)
        self.assertIn("not final", proc.stderr)
        self.run_py(RESEARCH, "compile", "--final")
        self.run_py(RESEARCH, "validate", "--final")
        for side in ("for", "against"):
            content = (self.project / f"research/book-of-mormon-{side}.md").read_text()
            self.assertIn("FINAL snapshot", content)
            self.assertIn("Category ranking", content)
            self.assertIn("Opposing-evidence evaluation", content)
            self.assertIn("Overall claim ranking", content)
        self.run_py(RESEARCH, "search", "--side", "against", "--query", "later fixture", "--outcome", "no-new", "--notes", "Makes reports stale.")
        proc = self.run_py(RESEARCH, "validate", ok=False)
        self.assertIn("stale", proc.stderr)
        self.run_py(RESEARCH, "compile", "--final")
        self.run_py(RESEARCH, "validate", "--final")

    def test_final_requires_usable_evidence_to_be_organized(self):
        self.init()
        self.add_evidence(evidence())
        self.run_py(RESEARCH, "compile", "--final")
        proc = self.run_py(RESEARCH, "validate", "--final", ok=False)
        self.assertIn("not organized under a claim", proc.stderr)
        self.add_claim(claim())
        self.run_py(RESEARCH, "compile", "--final")
        self.run_py(RESEARCH, "validate", "--final")

    def test_rejected_lead_is_preserved_with_zero_score(self):
        self.init()
        item = evidence("F900", identity="A debunked fixture", verdict="fabricated")
        self.add_evidence(item)
        self.log("for", "rejected", "F900")
        self.run_py(RESEARCH, "compile")
        content = (self.project / "research/book-of-mormon-for.md").read_text()
        self.assertIn("Quarantined and rejected leads", content)
        self.assertIn("fabricated", content)
        self.assertEqual(research.store(self.project)["evidence"]["F900"]["overall_score"], 0.0)

    def hook(self, project, event, message=None, tool_name=None, tool_input=None):
        config = json.loads((project / ".openhands/hooks.json").read_text())
        key = {"stop": "stop", "prompt": "user_prompt_submit", "pretool": "pre_tool_use"}[event]
        command = config[key][0]["hooks"][0]["command"]
        payload = {"event_type": {"stop": "Stop", "prompt": "UserPromptSubmit", "pretool": "PreToolUse"}[event],
                   "working_dir": str(project), "session_id": "test"}
        if message is not None:
            payload["message"] = message
        if tool_name is not None:
            payload["tool_name"] = tool_name
            payload["tool_input"] = tool_input or {}
        env = dict(os.environ, OPENHANDS_PROJECT_DIR=str(project))
        return subprocess.run(command, shell=True, cwd=project, env=env, input=json.dumps(payload), capture_output=True, text=True, timeout=60)

    def test_research_pretool_blocks_faking_the_mormon_side(self):
        proc = subprocess.run(["bash", str(INSTALL), "--dir", str(self.project), "--install-skill", "--no-gates"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        attacks = [
            ("terminal", {"command": "echo '{}' > .infinite/ledger.jsonl"}),
            ("terminal", {"command": "python3 -c \"open('.infinite/state.json','w').write('{}')\""}),
            ("terminal", {"command": "sed -i 's/FINAL/INTERIM/' research/book-of-mormon-for.md"}),
            ("file_editor", {"path": "research/book-of-mormon-against.md", "command": "str_replace", "old_str": "a", "new_str": "b"}),
            ("file_editor", {"path": ".agents/skills/infinite/scripts/infinite_research.py", "command": "str_replace", "old_str": "a", "new_str": "b"}),
            ("terminal", {"command": "python3 .agents/skills/infinite/scripts/infinite_research.py --dir . compile --final"}),
            ("terminal", {"command": "python3 .agents/skills/infinite/scripts/infinite_state.py --dir . disarm"}),
        ]
        for tool_name, tool_input in attacks:
            result = self.hook(self.project, "pretool", tool_name=tool_name, tool_input=tool_input)
            self.assertEqual(result.returncode, 2, f"{tool_input}: {result.stdout + result.stderr}")
        allowed = [
            ("read_file", {"path": ".infinite/ledger.jsonl"}),
            ("terminal", {"command": "python3 .agents/skills/infinite/scripts/infinite_research.py --dir . status"}),
            ("terminal", {"command": "python3 .agents/skills/infinite/scripts/infinite_research.py --dir . validate"}),
            ("terminal", {"command": "python3 .agents/skills/infinite/scripts/infinite_state.py --dir . status"}),
        ]
        for tool_name, tool_input in allowed:
            result = self.hook(self.project, "pretool", tool_name=tool_name, tool_input=tool_input)
            self.assertEqual(result.returncode, 0, f"{tool_input}: {result.stdout + result.stderr}")
        # A real user stop switches the helper from research to finalization.
        self.hook(self.project, "prompt", "stop")
        result = self.hook(self.project, "pretool", tool_name="terminal", tool_input={"command": "python3 .agents/skills/infinite/scripts/infinite_research.py --dir . compile --final"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.hook(self.project, "pretool", tool_name="terminal", tool_input={"command": "python3 .agents/skills/infinite/scripts/infinite_research.py --dir . search --side for --query x --outcome no-new --notes y"})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.hook(self.project, "prompt", "continue")
        self.assertFalse((self.project / ".openhands/guard/STOP_REQUESTED").exists())
        result = self.hook(self.project, "pretool", tool_name="terminal", tool_input={"command": "python3 .agents/skills/infinite/scripts/infinite_state.py --dir . resume"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_standby_hooks_arm_only_on_a_real_fixed_invocation(self):
        proc = subprocess.run(["bash", str(INSTALL), "--dir", str(self.project), "--install-skill", "--no-arm"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        config = json.loads((self.project / ".openhands/guard/config.json").read_text())
        self.assertEqual(config["mode"], "standby")
        self.assertEqual(config["profile"], "book-of-mormon")
        self.assertEqual(self.hook(self.project, "stop").returncode, 0)
        self.hook(self.project, "prompt", "do not use this skill")
        self.assertEqual(self.hook(self.project, "stop").returncode, 0)
        self.hook(self.project, "prompt", "use this skill")
        self.assertTrue((self.project / ".openhands/guard/ARMED").is_file())
        result = self.hook(self.project, "stop")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("next for round", result.stdout)
        self.hook(self.project, "prompt", "stop")
        self.run_py(RESEARCH, "compile", "--final")
        result = self.hook(self.project, "stop")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.project / ".openhands/guard/ARMED").exists())
        self.assertFalse((self.project / ".openhands/guard/STOP_REQUESTED").exists())

    def test_research_validator_is_builtin_even_with_no_gates(self):
        proc = subprocess.run(["bash", str(INSTALL), "--dir", str(self.project), "--install-skill", "--no-gates"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        config = json.loads((self.project / ".openhands/guard/config.json").read_text())
        self.assertEqual(config["profile"], "book-of-mormon")
        self.assertEqual(config["gates"], [])
        self.hook(self.project, "prompt", "stop")
        result = self.hook(self.project, "stop")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("research-validator", result.stdout)
        self.assertIn("final reports are not ready", result.stdout)
        self.run_py(RESEARCH, "compile", "--final")
        result = self.hook(self.project, "stop")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_research_hooks_stop_finalization_and_cloud_relocation(self):
        # The fixed skill installs Book of Mormon enforcement by default; no
        # separate --research flag is required for the Mormon side.
        proc = subprocess.run(["bash", str(INSTALL), "--dir", str(self.project), "--install-skill"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue((self.project / ".agents/skills/infinite/scripts/infinite_research.py").is_file())
        self.assertTrue((self.project / ".agents/skills/infinite/references/fixed-task.md").is_file())
        config = json.loads((self.project / ".openhands/hooks.json").read_text())
        stop_cmd = config["stop"][0]["hooks"][0]["command"]
        self.assertTrue(stop_cmd.startswith("bash .openhands/hooks/"))
        self.assertNotIn(str(self.project), stop_cmd)
        pre_cmd = config["pre_tool_use"][0]["hooks"][0]["command"]
        self.assertIn("--policy", pre_cmd)
        result = self.hook(self.project, "stop")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("next for round", result.stdout)
        self.hook(self.project, "prompt", "I want you to indefinitely research evidence until I say stop.")
        self.assertFalse((self.project / ".openhands/guard/STOP_REQUESTED").exists())
        # The embedded policy, not the editable mirrors, controls research stop.
        state_path = self.project / ".infinite/state.json"
        saved_state = state_path.read_text()
        state = json.loads(saved_state); state["profile"] = "generic"; state_path.write_text(json.dumps(state))
        config_path = self.project / ".openhands/guard/config.json"
        saved_config = config_path.read_text()
        config = json.loads(saved_config); config["mode"] = "disabled"; config_path.write_text(json.dumps(config))
        result = self.hook(self.project, "prompt", "stop researching and compile the final reports")
        self.assertEqual(result.returncode, 0)
        self.assertTrue((self.project / ".openhands/guard/STOP_REQUESTED").exists())
        self.assertFalse((self.project / ".openhands/guard/DISARMED").exists())
        state_path.write_text(saved_state)
        config_path.write_text(saved_config)
        result = self.hook(self.project, "stop")
        self.assertEqual(result.returncode, 2)
        self.assertIn("final reports are not ready", result.stdout)
        self.run_py(RESEARCH, "compile", "--final")
        result = self.hook(self.project, "stop")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.hook(self.project, "prompt", "use this skill")
        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.project / ".openhands/guard/STOP_REQUESTED").exists())
        self.run_py(STATE, "resume")
        # Simulate a Cloud clone at a different checkout path: no installed command
        # or gate may depend on the original machine's absolute project path.
        relocated = Path(self.tmp.name) / "cloud checkout"
        shutil.copytree(self.project, relocated)
        result = self.hook(relocated, "stop")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Book of Mormon research protocol", result.stdout)
        proc = subprocess.run(["bash", str(INSTALL), "--dir", str(relocated), "--disarm"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.hook(relocated, "stop").returncode, 0)
        self.hook(relocated, "prompt", "do not use this skill")
        self.assertEqual(self.hook(relocated, "stop").returncode, 0)
        self.hook(relocated, "prompt", "use this skill")
        self.assertEqual(self.hook(relocated, "stop").returncode, 2)

    def plugin_hook(self, project: Path, plugin_root: Path, event: str, message=None, tool_name=None, tool_input=None):
        config = json.loads((plugin_root / "hooks/hooks.json").read_text(encoding="utf-8"))
        key = {"stop": "stop", "prompt": "user_prompt_submit", "pretool": "pre_tool_use"}[event]
        command = config[key][0]["hooks"][0]["command"]
        payload = {
            "event_type": {"stop": "Stop", "prompt": "UserPromptSubmit", "pretool": "PreToolUse"}[event],
            "working_dir": str(project),
            "session_id": "cloud-plugin-test",
        }
        if message is not None:
            payload["message"] = message
        if tool_name is not None:
            payload["tool_name"] = tool_name
            payload["tool_input"] = tool_input or {}
        env = dict(os.environ, OPENHANDS_PROJECT_DIR=str(project), PLUGIN_ROOT=str(plugin_root))
        return subprocess.run(command, shell=True, cwd=project, env=env, input=json.dumps(payload), capture_output=True, text=True, timeout=60)

    def test_cloud_plugin_hooks_work_in_empty_workspace_via_plugin_root(self):
        # Simulate OpenHands Cloud caching the plugin under ~/.openhands/plugins/installed/infinite
        # and running a conversation in a clean workspace that has NO .openhands/hooks.json.
        fake_home = Path(self.tmp.name) / "cloud_home"
        cached_plugin = fake_home / ".openhands" / "plugins" / "installed" / "infinite"
        shutil.copytree(REPO / "infinite", cached_plugin)
        empty_ws = Path(self.tmp.name) / "empty_cloud_workspace"
        empty_ws.mkdir()

        # Standby before invocation: allows normal work & finish without creating .openhands/guard
        self.assertEqual(self.plugin_hook(empty_ws, cached_plugin, "stop").returncode, 0)
        self.assertFalse((empty_ws / ".openhands/guard").exists())
        self.assertEqual(
            self.plugin_hook(empty_ws, cached_plugin, "pretool", tool_name="terminal", tool_input={"command": "pytest -q"}).returncode,
            0,
        )

        # User invokes the skill via "use this skill" (or /infinite:infinite)
        res = self.plugin_hook(empty_ws, cached_plugin, "prompt", message="use this skill")
        self.assertEqual(res.returncode, 0)
        self.assertTrue((empty_ws / ".openhands/guard/ARMED").is_file())

        # Agent can run helpers & read references from ~/.openhands/plugins/... (not falsely blocked as .openhands/guard)
        init_cmd = f"python3 {cached_plugin / 'scripts/infinite_research.py'} --dir . init"
        self.assertEqual(
            self.plugin_hook(empty_ws, cached_plugin, "pretool", tool_name="terminal", tool_input={"command": init_cmd}).returncode,
            0,
        )
        subprocess.run(["python3", str(cached_plugin / "scripts/infinite_research.py"), "--dir", str(empty_ws), "init"], check=True, capture_output=True)

        # Agent tampering is blocked, and premature finish is denied by the plugin's Stop hook
        self.assertEqual(
            self.plugin_hook(empty_ws, cached_plugin, "pretool", tool_name="terminal", tool_input={"command": "echo '{}' > .infinite/ledger.jsonl"}).returncode,
            2,
        )
        stop_res = self.plugin_hook(empty_ws, cached_plugin, "stop")
        self.assertEqual(stop_res.returncode, 2)
        self.assertIn("next for round", stop_res.stdout)

        # User says stop -> finalization allowed -> clean exit
        self.plugin_hook(empty_ws, cached_plugin, "prompt", message="stop")
        self.assertTrue((empty_ws / ".openhands/guard/STOP_REQUESTED").is_file())
        subprocess.run(["python3", str(cached_plugin / "scripts/infinite_research.py"), "--dir", str(empty_ws), "compile", "--final"], check=True, capture_output=True)
        final_stop = self.plugin_hook(empty_ws, cached_plugin, "stop")
        self.assertEqual(final_stop.returncode, 0, final_stop.stdout + final_stop.stderr)
        self.assertFalse((empty_ws / ".openhands/guard/ARMED").exists())

    def test_prewired_repo_standby_hooks_work_in_fresh_cloud_clone(self):
        clone = Path(self.tmp.name) / "fresh_cloud_clone"
        clone.mkdir()
        shutil.copytree(REPO / ".openhands", clone / ".openhands")
        shutil.copytree(REPO / ".agents", clone / ".agents")
        shutil.copytree(REPO / "infinite", clone / "infinite")
        shutil.copy2(REPO / "SKILL.md", clone / "SKILL.md")
        self.assertFalse((clone / ".openhands/guard").exists())

        # Ordinary prompt finishes cleanly in standby mode
        self.hook(clone, "prompt", "explain how scoring caps work")
        self.assertEqual(self.hook(clone, "stop").returncode, 0)
        self.assertFalse((clone / ".openhands/guard").exists())

        # Invoking the skill arms enforcement in the same Cloud conversation
        self.hook(clone, "prompt", "/infinite")
        self.assertTrue((clone / ".openhands/guard/ARMED").is_file())
        subprocess.run(["python3", str(clone / "infinite/scripts/infinite_research.py"), "--dir", str(clone), "init"], check=True, capture_output=True)
        self.assertEqual(self.hook(clone, "stop").returncode, 2)
        self.hook(clone, "prompt", "stop")
        subprocess.run(["python3", str(clone / "infinite/scripts/infinite_research.py"), "--dir", str(clone), "compile", "--final"], check=True, capture_output=True)
        self.assertEqual(self.hook(clone, "stop").returncode, 0)

    def test_google_docs_credentials_subcommand_ledger_and_stop_guard(self):
        import base64
        from unittest import mock
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        import google_docs_client as gdocs

        # 1. Existing repo .google file (when present) and synthetic .google file / dir / Cloud secret env vars
        ws_file = Path(self.tmp.name) / "ws_dot_google_file"
        ws_file.mkdir()
        fake_key = {
            "type": "service_account",
            "project_id": "test-proj",
            "client_email": "bot@test-proj.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----\n",
        }
        (ws_file / ".google").write_text(json.dumps(fake_key), encoding="utf-8")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
            os.environ.pop("GOOGLE_SERVICE_ACCOUNT_JSON", None)
            os.environ.pop("GOOGLE_CREDENTIALS_JSON", None)
            loaded = gdocs.load_credentials_info(project=ws_file)
            self.assertEqual(loaded["client_email"], fake_key["client_email"])
            if (REPO / ".google").is_file():
                repo_creds = gdocs.load_credentials_info(project=REPO)
                self.assertIn("client_email", repo_creds)

        ws_dir = Path(self.tmp.name) / "ws_dot_google_dir"
        (ws_dir / ".google").mkdir(parents=True)
        (ws_dir / ".google" / "credentials.json").write_text(json.dumps(fake_key), encoding="utf-8")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
            os.environ.pop("GOOGLE_SERVICE_ACCOUNT_JSON", None)
            self.assertEqual(gdocs.load_credentials_info(project=ws_dir)["project_id"], "test-proj")

        b64_secret = base64.b64encode(json.dumps(fake_key).encode("utf-8")).decode("ascii")
        with mock.patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": b64_secret}, clear=False):
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
            self.assertEqual(gdocs.load_credentials_info(project=self.project)["project_id"], "test-proj")

        # 2. End-to-end google-docs view & edit via infinite_research.py with mocked Google Docs API
        self.init()
        (self.project / ".google").write_text(json.dumps(fake_key), encoding="utf-8")
        fake_doc = {
            "title": "Book of Mormon Witness Notes",
            "body": {
                "content": [
                    {"paragraph": {"elements": [{"textRun": {"content": "Oliver Cowdery statement.\n"}}]}},
                    {"table": {"tableRows": [{"tableCells": [
                        {"content": [{"paragraph": {"elements": [{"textRun": {"content": "Witness"}}]}}]},
                        {"content": [{"paragraph": {"elements": [{"textRun": {"content": "1830"}}]}}]},
                    ]}]}},
                ]
            },
        }
        fake_service = mock.MagicMock()
        fake_service.documents.return_value.get.return_value.execute.return_value = fake_doc
        fake_service.documents.return_value.batchUpdate.return_value.execute.return_value = {"replies": [{}]}

        with mock.patch.object(gdocs, "build_service", return_value=fake_service):
            rc_view = research.main([
                "--dir", str(self.project),
                "google-docs", "view",
                "--doc-id", "doc123",
                "--url", "https://docs.google.com/document/d/doc123/edit",
            ])
            self.assertEqual(rc_view, 0)
            rc_edit = research.main([
                "--dir", str(self.project),
                "google-docs", "edit",
                "--doc-id", "doc123",
                "--url", "https://docs.google.com/document/d/doc123/edit",
                "--content", "Appended synthesis note.",
            ])
            self.assertEqual(rc_edit, 0)

        # Ledger entries are schema-valid and interim reports stay fresh for `validate`
        self.run_py(RESEARCH, "validate")
        parsed = research.store(self.project)
        self.assertEqual(len(parsed["searches"]), 1)
        self.assertEqual(parsed["searches"][0]["urls"], ["https://docs.google.com/document/d/doc123/edit"])
        self.assertEqual(len(parsed["notes"]), 1)
        self.assertEqual(parsed["notes"][0]["kind"], "original-synthesis")

        # STOP_REQUESTED blocks both google_docs_client operations and PreToolUse invocations
        proc = subprocess.run(["bash", str(INSTALL), "--dir", str(self.project), "--install-skill", "--no-gates"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.hook(self.project, "prompt", "stop")
        with mock.patch.object(gdocs, "build_service", return_value=fake_service):
            self.assertEqual(
                research.main([
                    "--dir", str(self.project),
                    "google-docs", "edit",
                    "--doc-id", "doc123",
                    "--url", "https://docs.google.com/document/d/doc123/edit",
                    "--content", "Should be blocked after stop",
                ]),
                1,
            )
        pretool_gd = self.hook(
            self.project,
            "pretool",
            tool_name="terminal",
            tool_input={"command": "python3 infinite/scripts/infinite_research.py --dir . google-docs edit --doc-id d1 --url https://docs.google.com/document/d/d1/edit --content x"},
        )
        self.assertEqual(pretool_gd.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
