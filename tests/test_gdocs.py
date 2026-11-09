#!/usr/bin/env python3
"""Offline tests for the Google Docs mirror (scripts/google_docs.py).

These exercise the markdown-to-Docs conversion, credential resolution, and the
receipt logic without any network access. Fixtures are synthetic.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GDOCS = REPO / "infinite" / "scripts" / "google_docs.py"
spec = importlib.util.spec_from_file_location("infinite_google_docs", GDOCS)
assert spec and spec.loader
gdocs = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gdocs
spec.loader.exec_module(gdocs)


class ConverterTests(unittest.TestCase):
    def test_render_inline_flattens_markup_and_records_ranges(self):
        plain, ranges = gdocs.render_inline("Score **76.8** via [link](https://example.org) and `code`.")
        self.assertEqual(plain, "Score 76.8 via link and code.")
        kinds = [tuple(sorted(style.keys())) for _, _, style, _ in ranges]
        self.assertIn(("bold",), kinds)
        self.assertIn(("link",), kinds)
        self.assertIn(("fontFamily",), kinds)
        for start, end, _, _ in ranges:
            self.assertLess(start, end)
            self.assertLessEqual(end, len(plain))
        link_range = next((start, end) for start, end, style, _ in ranges if "link" in style)
        self.assertEqual(plain[link_range[0]:link_range[1]], "link")

    def test_paragraph_requests_track_the_cursor(self):
        requests, end = gdocs.paragraph_requests(1, "Hello **world**", "HEADING_1")
        insert = requests[0]["insertText"]
        self.assertEqual(insert["location"]["index"], 1)
        self.assertEqual(insert["text"], "Hello world\n")
        style = requests[1]["updateParagraphStyle"]
        self.assertEqual(style["paragraphStyle"]["namedStyleType"], "HEADING_1")
        self.assertEqual(style["range"], {"startIndex": 1, "endIndex": 1 + len("Hello world\n")})
        self.assertEqual(end, 1 + len("Hello world\n"))
        bold = [r for r in requests if "updateTextStyle" in r]
        self.assertEqual(len(bold), 1)
        self.assertEqual(bold[0]["updateTextStyle"]["range"], {"startIndex": 7, "endIndex": 12})

    def test_long_paragraphs_are_chunked(self):
        text = "word " * 2000  # > MAX_INSERT_CHARS
        requests, end = gdocs.paragraph_requests(5, text.strip(), "NORMAL_TEXT")
        inserts = [r for r in requests if "insertText" in r]
        self.assertGreater(len(inserts), 1)
        for insert in inserts:
            self.assertLessEqual(len(insert["insertText"]["text"]), gdocs.MAX_INSERT_CHARS)
        self.assertEqual(end, 5 + len(text.strip()) + 1)

    def test_parse_blocks_classifies_the_report_subset(self):
        markdown = "\n".join([
            "<!-- infinite-research-mode: final -->",
            "# Title",
            "",
            "## Section",
            "",
            "A paragraph with **bold** text.",
            "",
            "- bullet one",
            "  - nested bullet",
            "",
            "| a | b |",
            "| ---: | --- |",
            "| c\\|d | e<br>f |",
            "",
            "### Sub",
        ])
        blocks = gdocs.parse_blocks(markdown)
        kinds = [b["type"] for b in blocks]
        self.assertEqual(kinds, ["heading", "heading", "para", "bullet", "bullet", "table", "heading"])
        self.assertNotIn("comment", kinds)  # HTML markers are stripped
        table = next(b for b in blocks if b["type"] == "table")
        self.assertEqual(table["rows"], [["a", "b"], ["c|d", "e; f"]])
        nested = blocks[4]
        self.assertEqual(nested["indent"], 1)

    def test_parse_blocks_on_a_real_compiled_report(self):
        project = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            import subprocess
            research = REPO / "infinite" / "scripts" / "infinite_research.py"
            proc = subprocess.run([sys.executable, str(research), "--dir", str(root), "init"],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            for name in ("for", "against", "comparison"):
                content = (root / f"research/book-of-mormon-{name}.md").read_text(encoding="utf-8")
                blocks = gdocs.parse_blocks(content)
                self.assertTrue(blocks)
                for block in blocks:
                    if block["type"] == "table":
                        self.assertTrue(block["rows"])
                        width = len(block["rows"][0])
                        for row in block["rows"]:
                            self.assertEqual(len(row), width)
                        for row in block["rows"]:
                            for cell in row:
                                self.assertNotIn("<br>", cell)
                                self.assertNotIn("\\|", cell)


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in
                       ("INFINITE_GDOCS_OAUTH_FILE", "INFINITE_GDOCS_SA_FILE", "GOOGLE_APPLICATION_CREDENTIALS")}

    def tearDown(self):
        for key, value in self._saved.items():
            if value is not None:
                os.environ[key] = value

    def test_no_credentials_resolves_none_and_sync_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.assertIsNone(gdocs.resolve_credentials(project))
            status, message = gdocs.maybe_sync(project, "interim")
            self.assertEqual(status, "skipped")
            self.assertIn("references/google-docs.md", message)

    def test_oauth_refresh_file_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".infinite").mkdir()
            (project / ".infinite/gdocs-oauth.json").write_text(
                json.dumps({"client_id": "x", "client_secret": "y", "refresh_token": "z"}), encoding="utf-8")
            kind, config = gdocs.resolve_credentials(project)
            self.assertEqual(kind, "oauth-refresh")
            self.assertEqual(config["refresh_token"], "z")

    def test_service_account_file_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".infinite").mkdir()
            (project / ".infinite/gdocs-sa.json").write_text(
                json.dumps({"client_email": "a@b.iam", "private_key": "-----BEGIN PRIVATE KEY-----\nx"}),
                encoding="utf-8")
            kind, _ = gdocs.resolve_credentials(project)
            self.assertEqual(kind, "service-account")

    def test_incomplete_oauth_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".infinite").mkdir()
            (project / ".infinite/gdocs-oauth.json").write_text(json.dumps({"client_id": "x"}), encoding="utf-8")
            self.assertIsNone(gdocs.resolve_credentials(project))


class ReceiptTests(unittest.TestCase):
    def test_receipt_round_trip_and_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".infinite").mkdir()
            (project / ".infinite/ledger.jsonl").write_text('{"event":"x"}\n', encoding="utf-8")
            digest = gdocs.ledger_digest(project)
            self.assertEqual(len(digest), 64)
            receipt_path = project / ".infinite/gdocs.json"
            gdocs.write_json(receipt_path, {"documents": {}, "last_sync": {"digest": digest, "mode": "final"}})
            receipt = gdocs.read_json(receipt_path, {})
            self.assertEqual(receipt["last_sync"]["digest"], digest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
