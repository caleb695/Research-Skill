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


def source(sid="S1", group="fixture-chain-a", slug="fixture-a", locator="fixture line 1", role="evidence"):
    return {
        "id": sid, "title": f"Synthetic primary fixture {sid}",
        "reference": f"Test suite fixture {sid}, edition 1, published by the test harness for structural checks",
        "url": f"https://example.org/{slug}", "locator": locator, "accessed": "2026-11-07",
        "kind": "test-fixture", "role": role, "independence_group": group,
        "bias": "none; synthetic fixture created for schema testing only",
        "verification": "Created and compared by this test suite; not an online historical check.",
    }


def evidence(eid="F001", side="for", identity="A distinct checked observation", verdict="verified", opposing=None, category="bible"):
    return {
        "id": eid, "side": side, "category": category, "title": f"Fixture {eid}",
        "identity": identity, "aliases": [],
        "proposition": "A synthetic observation used only to test the ledger mechanics, not a historical claim.",
        "inference": "This fixture exercises the six-step schema validation rather than any conclusion about the Book of Mormon.",
        "assumptions": ["Synthetic test fixture; not evidence about the Book of Mormon."],
        "dependence": "Two synthetic independent fixture chains with no shared manuscript or author.",
        "uncertainty": "Not a real research finding; structure only, and this is stated explicitly.",
        "authenticity": {"verdict": verdict, "checks": [
            "Earliest accessible edition located and bibliographically described in full",
            "Exact wording and locator compared against the fixture original line by line",
            "Correction/retraction/forgery search performed with recorded negative results"],
            "limitations": "Illustrative fixture only; no real provenance exists behind it."},
        "context": {
            "textual": "Whole synthetic literary unit reviewed including neighboring verses and the chapter argument.",
            "historical": "Synthetic test context with dates, actors, and sequence fully described for the fixture.",
            "pov": "Test author with no religious POV; incentives and audience documented as part of the fixture.",
            "missing_facts": "No real-world facts are asserted; this notes what would change interpretation if real."},
        "sources": [source("S1"), source("S2", "fixture-chain-b", "fixture-b", "fixture line 2")],
        "corroboration": {
            "cross_checks": "Fixture A and fixture B were compared line by line; they agree on the synthetic observation and no discrepancies were found.",
            "cited_evidence": [
                {"source_id": "S1", "piece": "fixture line 1 exact wording", "what_it_shows": "Establishes the synthetic observation in chain A."},
                {"source_id": "S2", "piece": "fixture line 2 exact wording", "what_it_shows": "Independently repeats the observation in chain B."}]},
        "scores": {"credibility": 80, "accuracy": 90, "relevance": 70, "usefulness": 60},
        "score_reasons": {d: f"Fixture rationale for {d} with enough substance to satisfy the coded minimum." for d in research.DIMENSIONS},
        "counter_evaluation": {"analysis": "The strongest synthetic alternative is considered in full, including its effect on the item and the residual uncertainty that remains after the comparison; this is not a real evidential judgment.", "opposing_ids": opposing or [], "source_ids": ["S1"]},
        "investigation": {
            "queries": ["fixture schema validation", "fixture independence group test"],
            "sources_consulted": 2,
            "rejected_leads": "A third fixture chain was considered and rejected as an exact duplicate of chain A.",
            "depth": "Both fixtures were read in full, traced to their generating test code, and cross-checked against each other."},
    }


def claim(cid="C001", side="for", eids=None, opposing=None, category="bible"):
    return {
        "id": cid, "side": side, "category": category, "title": f"Fixture claim {cid}",
        "statement": "A synthetic claim for testing report organization and ranking mechanics.",
        "synthesis": "The fixture demonstrates how evidence is grouped under claims without counting duplicates as independent support, and it explains the whole argument rather than summing parts.",
        "evidence_ids": eids or ["F001"], "assumptions": ["Synthetic fixture."],
        "dependence": "One fixture chain pair.", "uncertainty": "No historical conclusion is drawn from this fixture.",
        "scores": {"credibility": 75, "accuracy": 85, "relevance": 65, "usefulness": 55},
        "score_reasons": {d: f"Fixture claim rationale for {d} with enough substance to satisfy the coded minimum." for d in research.DIMENSIONS},
        "counter_evaluation": {"analysis": "The strongest synthetic alternative is acknowledged in full for testing, including its effect on the claim and the residual uncertainty that remains after the comparison.", "opposing_ids": opposing or [], "source_ids": []},
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

    def write_receipt(self, mode="final"):
        """Simulate a successful google_docs.py sync at the current ledger digest."""
        digest = research.ledger_digest(self.project)
        receipt = {
            "auth": "oauth-refresh",
            "documents": {name: {"id": f"doc-{name}", "title": name,
                                 "url": f"https://docs.google.com/document/d/doc-{name}/edit"}
                          for name in ("for", "against", "comparison")},
            "last_sync": {"ts": "2026-11-09T00:00:00+00:00", "mode": mode, "digest": digest,
                          "documents_synced": ["for", "against", "comparison"]},
        }
        (self.project / ".infinite/gdocs.json").write_text(json.dumps(receipt), encoding="utf-8")

    def add_evidence(self, record, revise=False, ok=True):
        return self.run_py(RESEARCH, "revise" if revise else "evidence", "--file", self.write_record(record), ok=ok)

    def add_claim(self, record, ok=True):
        return self.run_py(RESEARCH, "claim", "--file", self.write_record(record), ok=ok)

    def log(self, side, outcome="accepted", eid=None, ok=True):
        args = ["log", "--target", "fixture target", "--verification", "fixture checks passed", "--next", "opposite-side fixture", "--side", side, "--outcome", outcome]
        if eid:
            args += ["--evidence-id", eid]
        return self.run_py(STATE, *args, ok=ok)

    def test_init_is_idempotent_and_creates_three_reports(self):
        self.init()
        self.log("for", "no-new")
        before = json.loads((self.project / ".infinite/state.json").read_text())
        self.init()
        after = json.loads((self.project / ".infinite/state.json").read_text())
        self.assertEqual(after["round"], before["round"])
        self.assertEqual(after["next_side"], "against")
        self.assertEqual(after["dry_rounds"], 1)
        for name in ("for", "against", "comparison"):
            path = self.project / f"research/book-of-mormon-{name}.md"
            self.assertTrue(path.is_file())
            self.assertIn("INTERIM", path.read_text())
        proc = self.run_py(RESEARCH, "validate")
        self.assertIn("Google Docs", proc.stdout + proc.stderr)  # warning until configured

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
        self.write_receipt("final")
        self.run_py(RESEARCH, "validate", "--final")
        for side in ("for", "against"):
            content = (self.project / f"research/book-of-mormon-{side}.md").read_text()
            self.assertIn("FINAL snapshot", content)
            self.assertIn("Category ranking", content)
            self.assertIn("Opposing-evidence evaluation", content)
            self.assertIn("Overall claim ranking", content)
        comparison = (self.project / "research/book-of-mormon-comparison.md").read_text()
        self.assertIn("FINAL snapshot", comparison)
        self.assertIn("F001 (for) vs A001 (against)", comparison)
        self.assertIn("Category face-offs", comparison)
        self.assertIn("Complete ranked evidence register", comparison)
        self.run_py(RESEARCH, "search", "--side", "against", "--query", "later fixture", "--outcome", "no-new", "--notes", "Makes reports stale.")
        proc = self.run_py(RESEARCH, "validate", ok=False)
        self.assertIn("stale", proc.stderr)
        self.run_py(RESEARCH, "compile", "--final")
        self.write_receipt("final")
        self.run_py(RESEARCH, "validate", "--final")

    def test_final_requires_usable_evidence_to_be_organized(self):
        self.init()
        self.add_evidence(evidence())
        self.run_py(RESEARCH, "compile", "--final")
        self.write_receipt("final")
        proc = self.run_py(RESEARCH, "validate", "--final", ok=False)
        self.assertIn("not organized under a claim", proc.stderr)
        self.add_claim(claim())
        self.run_py(RESEARCH, "compile", "--final")
        self.write_receipt("final")
        self.run_py(RESEARCH, "validate", "--final")

    def test_six_prompt_steps_are_code_enforced(self):
        """Each numbered step of the fixed prompt rejects partial work."""
        self.init()

        def rejected(mutate, eid, needle):
            item = evidence(eid, identity=f"distinct identity {eid}")
            mutate(item)
            proc = self.add_evidence(item, ok=False)
            self.assertIn(needle, proc.stderr)

        # Step 1: at least three substantive authenticity checks.
        rejected(lambda i: i["authenticity"]["checks"].pop(), "F101", "prompt step 1")
        # Step 2: full context, not one-liners.
        rejected(lambda i: i["context"].update(pov="biased"), "F102", "prompt step 2")
        # Step 3: multiple sources, multiple independence groups, multiple cited pieces.
        rejected(lambda i: i["sources"].pop(), "F103", "prompt step 3")
        rejected(lambda i: i["sources"][1].update(independence_group="fixture-chain-a"), "F104", "prompt step 3")
        rejected(lambda i: i["corroboration"]["cited_evidence"].pop(), "F105", "prompt step 3")
        rejected(lambda i: i.pop("corroboration"), "F106", "prompt step 3")
        # Biased/lead-only sources cannot carry a verified item.
        rejected(lambda i: i["sources"][1].update(role="lead-only"), "F107", "prompt step 3")
        # Step 4: substantive counter analysis.
        rejected(lambda i: i["counter_evaluation"].update(analysis="Critics disagree."), "F108", "prompt step 4")
        # Step 5: every dimension needs a specific reason.
        rejected(lambda i: i["score_reasons"].update(credibility="solid"), "F109", "prompt step 5")
        # Step 6: extensive research record.
        rejected(lambda i: i.pop("investigation"), "F110", "prompt step 6")
        rejected(lambda i: i["investigation"].update(queries=["one"]), "F111", "prompt step 6")
        rejected(lambda i: i["investigation"].update(sources_consulted=1), "F112", "prompt step 6")
        # A complete item still passes, and quarantined leads may use one source.
        self.add_evidence(evidence("F100", identity="A complete six-step fixture"))
        lead = evidence("F200", identity="A quarantined single-source lead", verdict="unverified")
        lead["sources"].pop()
        lead["corroboration"]["cited_evidence"].pop()
        self.add_evidence(lead)
        self.assertEqual(research.store(self.project)["evidence"]["F200"]["overall_score"], 49.0)

    def test_witnesses_category_is_capped_weighed_less(self):
        self.init()
        item = evidence("F300", identity="A witnesses-category fixture", category="witnesses")
        self.add_evidence(item)
        stored = research.store(self.project)["evidence"]["F300"]
        self.assertEqual(stored["overall_score"], 69.0)  # capped, not 76.8
        item = evidence("F301", identity="Another witnesses fixture with disputed verdict",
                        category="witnesses", verdict="disputed")
        self.add_evidence(item)
        self.assertEqual(research.store(self.project)["evidence"]["F301"]["overall_score"], 69.0)
        claim_item = claim("C300", category="witnesses", eids=["F300"])
        self.add_claim(claim_item)
        # Uncapped the claim would score 71.7; the witnesses ceiling brings it to 69.
        self.assertEqual(research.store(self.project)["claims"]["C300"]["overall_score"], 69.0)

    def test_final_requires_synced_google_docs(self):
        self.init()
        self.add_evidence(evidence())
        self.add_claim(claim())
        self.run_py(RESEARCH, "compile", "--final")
        proc = self.run_py(RESEARCH, "validate", "--final", ok=False)
        self.assertIn("Google Docs deliverables are missing", proc.stderr)
        self.assertIn("googleworkspace/cli", proc.stderr)
        self.assertIn("gws auth login", proc.stderr)
        self.write_receipt("interim")
        proc = self.run_py(RESEARCH, "validate", "--final", ok=False)
        self.assertIn("interim mode", proc.stderr)
        self.write_receipt("final")
        self.run_py(RESEARCH, "validate", "--final")
        # A later ledger change makes the Google Docs stale too.
        self.run_py(RESEARCH, "note", "--side", "for", "--kind", "method-limit", "--text", "later change")
        proc = self.run_py(RESEARCH, "validate", "--final", ok=False)
        self.assertIn("stale", proc.stderr)
        self.run_py(RESEARCH, "compile", "--final")
        self.write_receipt("final")
        self.run_py(RESEARCH, "validate", "--final")
        # The user-only escape hatch skips the requirement.
        env_backup = os.environ.get("INFINITE_GDOCS")
        os.environ["INFINITE_GDOCS"] = "off"
        try:
            (self.project / ".infinite/gdocs.json").unlink()
            self.run_py(RESEARCH, "validate", "--final")
        finally:
            if env_backup is None:
                os.environ.pop("INFINITE_GDOCS", None)
            else:
                os.environ["INFINITE_GDOCS"] = env_backup

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
            ("terminal", {"command": "sed -i 's/FINAL/INTERIM/' research/book-of-mormon-comparison.md"}),
            ("file_editor", {"path": "research/book-of-mormon-against.md", "command": "str_replace", "old_str": "a", "new_str": "b"}),
            ("file_editor", {"path": ".agents/skills/infinite/scripts/infinite_research.py", "command": "str_replace", "old_str": "a", "new_str": "b"}),
            ("file_editor", {"path": ".agents/skills/infinite/scripts/google_docs.py", "command": "str_replace", "old_str": "a", "new_str": "b"}),
            ("terminal", {"command": "python3 .agents/skills/infinite/scripts/infinite_research.py --dir . compile --final"}),
            ("terminal", {"command": "python3 .agents/skills/infinite/scripts/google_docs.py --dir . sync --mode final"}),
            ("terminal", {"command": "python3 .agents/skills/infinite/scripts/infinite_state.py --dir . disarm"}),
            ("terminal", {"command": "echo '{\"documents\":{}}' > .infinite/gdocs.json"}),
            ("file_editor", {"path": ".infinite/gdocs.json", "command": "create", "file_text": "{}"}),
            ("file_editor", {"path": ".infinite/gdocs-oauth.json", "command": "create", "file_text": "{}"}),
            ("terminal", {"command": "gws auth export --unmasked > creds.json"}),
            ("terminal", {"command": "echo '{}' > .infinite/gws-credentials.json"}),
            ("file_editor", {"path": ".infinite/gws-credentials.json", "command": "str_replace", "old_str": "a", "new_str": "b"}),
            ("terminal", {"command": "gws auth logout"}),
            ("terminal", {"command": "rm -rf ~/.config/gws"}),
            ("file_editor", {"path": "~/.config/gws/credentials.json", "command": "str_replace", "old_str": "a", "new_str": "b"}),
        ]
        for tool_name, tool_input in attacks:
            result = self.hook(self.project, "pretool", tool_name=tool_name, tool_input=tool_input)
            self.assertEqual(result.returncode, 2, f"{tool_input}: {result.stdout + result.stderr}")
        allowed = [
            ("read_file", {"path": ".infinite/ledger.jsonl"}),
            ("terminal", {"command": "python3 .agents/skills/infinite/scripts/infinite_research.py --dir . status"}),
            ("terminal", {"command": "python3 .agents/skills/infinite/scripts/infinite_research.py --dir . validate"}),
            ("terminal", {"command": "python3 .agents/skills/infinite/scripts/infinite_state.py --dir . status"}),
            ("terminal", {"command": "python3 .agents/skills/infinite/scripts/google_docs.py --dir . status"}),
            ("terminal", {"command": "python3 .agents/skills/infinite/scripts/google_docs.py --dir . sync"}),
            ("terminal", {"command": "python3 .agents/skills/infinite/scripts/google_docs.py --dir . doctor"}),
            ("terminal", {"command": "gws auth status"}),
            ("terminal", {"command": "gws docs documents get --params '{\"documentId\": \"abc\"}'"}),
        ]
        for tool_name, tool_input in allowed:
            result = self.hook(self.project, "pretool", tool_name=tool_name, tool_input=tool_input)
            self.assertEqual(result.returncode, 0, f"{tool_input}: {result.stdout + result.stderr}")
        # A real user stop switches the helper from research to finalization.
        self.hook(self.project, "prompt", "stop")
        result = self.hook(self.project, "pretool", tool_name="terminal", tool_input={"command": "python3 .agents/skills/infinite/scripts/infinite_research.py --dir . compile --final"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.hook(self.project, "pretool", tool_name="terminal", tool_input={"command": "python3 .agents/skills/infinite/scripts/google_docs.py --dir . sync --mode final"})
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
        self.write_receipt("final")
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
        self.write_receipt("final")
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
        self.write_receipt("final")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
