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

    def hook(self, project, event, message=None):
        config = json.loads((project / ".openhands/hooks.json").read_text())
        key = {"stop": "stop", "prompt": "user_prompt_submit"}[event]
        command = config[key][0]["hooks"][0]["command"]
        payload = {"event_type": "Stop" if event == "stop" else "UserPromptSubmit", "working_dir": str(project), "session_id": "test"}
        if message is not None:
            payload["message"] = message
        env = dict(os.environ, OPENHANDS_PROJECT_DIR=str(project))
        return subprocess.run(command, shell=True, cwd=project, env=env, input=json.dumps(payload), capture_output=True, text=True, timeout=60)

    def test_research_hooks_stop_finalization_and_cloud_relocation(self):
        proc = subprocess.run(["bash", str(INSTALL), "--dir", str(self.project), "--research", "--install-skill"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue((self.project / ".agents/skills/infinite/scripts/infinite_research.py").is_file())
        config = json.loads((self.project / ".openhands/hooks.json").read_text())
        stop_cmd = config["stop"][0]["hooks"][0]["command"]
        self.assertTrue(stop_cmd.startswith("bash .openhands/hooks/"))
        self.assertNotIn(str(self.project), stop_cmd)
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
        self.hook(self.project, "prompt", "/infinite continue")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
