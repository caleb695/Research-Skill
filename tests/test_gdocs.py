#!/usr/bin/env python3
"""Offline tests for the Google Docs mirror (scripts/google_docs.py).

These exercise the markdown-to-Docs conversion, the gws CLI transport (via a
fake `gws` executable — no network), and the receipt logic. Fixtures are
synthetic; nothing here asserts a historical or religious conclusion.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GDOCS = REPO / "infinite" / "scripts" / "google_docs.py"
RESEARCH = REPO / "infinite" / "scripts" / "infinite_research.py"
spec = importlib.util.spec_from_file_location("infinite_google_docs", GDOCS)
assert spec and spec.loader
gdocs = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gdocs
spec.loader.exec_module(gdocs)

FAKE_GWS = r'''#!/usr/bin/env python3
"""Fake `gws` for offline tests: models docs create/get/batchUpdate + auth status.

State lives in $FAKE_GWS_STATE (JSON). Set FAKE_GWS_UNAUTH=1 to report no
credentials, or FAKE_GWS_FAIL_AUTH=1 to exit 2 (auth error) on API calls.
"""
import json, os, sys

state_path = os.environ.get("FAKE_GWS_STATE", "/tmp/fake-gws-state.json")

def load():
    try:
        with open(state_path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"docs": {}, "counter": 0, "batches": 0, "shares": 0}

def save(state):
    with open(state_path, "w") as f:
        json.dump(state, f)

def flag(name, *args):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
    return None

args = sys.argv[1:]
state = load()

if args[:1] == ["--version"]:
    print("gws 0.0.0-fake")
    sys.exit(0)

if args[:2] == ["auth", "status"]:
    if os.environ.get("FAKE_GWS_UNAUTH"):
        print(json.dumps({"auth_method": "none", "credential_source": "none"}))
    else:
        print(json.dumps({"auth_method": "oauth2", "credential_source": "client_secret.json"}))
    sys.exit(0)

if os.environ.get("FAKE_GWS_FAIL_AUTH"):
    print("missing credentials; run gws auth login", file=sys.stderr)
    sys.exit(2)

if args[:3] == ["docs", "documents", "create"]:
    body = json.loads(flag("--json", *args) or "{}")
    state["counter"] += 1
    doc_id = "fake-doc-%d" % state["counter"]
    state["docs"][doc_id] = {"end": 2, "title": body.get("title", ""), "tables": {}}
    save(state)
    print(json.dumps({"documentId": doc_id, "title": body.get("title", "")}))
    sys.exit(0)

if args[:3] == ["docs", "documents", "get"]:
    params = json.loads(flag("--params", *args) or "{}")
    doc = state["docs"].get(params.get("documentId", ""))
    if doc is None:
        print(json.dumps({"error": {"code": 404, "message": "not found"}}))
        sys.exit(1)
    content = []
    for start_str, table in sorted(doc["tables"].items(), key=lambda kv: int(kv[0])):
        start = int(start_str)
        rows = []
        for r in range(table["rows"]):
            cells = []
            for c in range(table["cols"]):
                k = r * table["cols"] + c
                cells.append({"content": [{"startIndex": start + 1 + 2 * k}]})
            rows.append({"tableCells": cells})
        content.append({"startIndex": start, "endIndex": table["end"], "table": {"tableRows": rows}})
    content.append({"endIndex": doc["end"]})
    print(json.dumps({"documentId": params.get("documentId"), "title": doc["title"],
                      "body": {"content": content}}))
    sys.exit(0)

if args[:3] == ["docs", "documents", "batchUpdate"]:
    params = json.loads(flag("--params", *args) or "{}")
    body = json.loads(flag("--json", *args) or "{}")
    doc = state["docs"].get(params.get("documentId", ""))
    if doc is None:
        print(json.dumps({"error": {"code": 404, "message": "not found"}}))
        sys.exit(1)
    replies = []
    for request in body.get("requests", []):
        state["batches"] += 1
        if "insertText" in request:
            doc["end"] += len(request["insertText"].get("text", ""))
        elif "deleteContentRange" in request:
            rng = request["deleteContentRange"].get("range", {})
            doc["end"] = max(2, doc["end"] - (rng.get("endIndex", 0) - rng.get("startIndex", 0)))
            doc["tables"] = {}
        elif "insertTable" in request:
            spec_t = request["insertTable"]
            start = spec_t["location"]["index"]
            rows, cols = spec_t["rows"], spec_t["columns"]
            length = 1 + rows * cols * 2
            doc["tables"][str(start)] = {"rows": rows, "cols": cols, "end": start + length}
            doc["end"] += length
        elif "updateDocumentProperties" in request:
            doc["title"] = request["updateDocumentProperties"]["properties"].get("title", doc["title"])
        replies.append({})
    save(state)
    print(json.dumps({"documentId": params.get("documentId"), "replies": replies, "revisionId": "rev-1"}))
    sys.exit(0)

if args[:3] == ["drive", "permissions", "create"]:
    state["shares"] += 1
    save(state)
    print(json.dumps({"id": "perm-%d" % state["shares"], "role": "writer", "type": "user"}))
    sys.exit(0)

print(json.dumps({"error": {"code": 400, "message": "unsupported fake command: %s" % " ".join(args)}}))
sys.exit(3)
'''


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
        table = next(b for b in blocks if b["type"] == "table")
        self.assertEqual(table["rows"], [["a", "b"], ["c|d", "e; f"]])
        nested = blocks[4]
        self.assertEqual(nested["indent"], 1)

    def test_parse_blocks_on_real_compiled_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = subprocess.run([sys.executable, str(RESEARCH), "--dir", str(root), "init"],
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
                            for cell in row:
                                self.assertNotIn("<br>", cell)
                                self.assertNotIn("\\|", cell)


class FakeGwsTestCase(unittest.TestCase):
    """Base class that installs a fake `gws` binary and a clean environment."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="infinite-gdocs-test-")
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.fake = self.root / "gws"
        self.fake.write_text(FAKE_GWS, encoding="utf-8")
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IEXEC)
        self.state_file = self.root / "gws-state.json"
        self._saved_env = {}
        for key in ("GWS_BIN", "FAKE_GWS_STATE", "FAKE_GWS_UNAUTH", "FAKE_GWS_FAIL_AUTH",
                    "GOOGLE_WORKSPACE_CLI_TOKEN", "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE",
                    "GOOGLE_WORKSPACE_CLI_CREDENTIALS_JSON", "GWS_CREDENTIALS_JSON",
                    "GOOGLE_WORKSPACE_CLI_CLIENT_ID", "GOOGLE_WORKSPACE_CLI_CLIENT_SECRET",
                    "GDOCS_TRANSPORT", "GDOCS_REST_ORIGIN", "INFINITE_GDOCS"):
            self._saved_env[key] = os.environ.pop(key, None)
        os.environ["GWS_BIN"] = str(self.fake)
        os.environ["FAKE_GWS_STATE"] = str(self.state_file)

    def tearDown(self):
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def fake_state(self) -> dict:
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def init_project(self):
        proc = subprocess.run([sys.executable, str(RESEARCH), "--dir", str(self.project), "init"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class TransportTests(FakeGwsTestCase):
    def test_auth_probe_uses_gws_status(self):
        ok, detail = gdocs.auth_probe()
        self.assertTrue(ok)
        self.assertIn("gws auth", detail)
        os.environ["FAKE_GWS_UNAUTH"] = "1"
        ok, detail = gdocs.auth_probe()
        self.assertFalse(ok)
        self.assertIn("gws auth login", detail)
        del os.environ["FAKE_GWS_UNAUTH"]
        os.environ["GOOGLE_WORKSPACE_CLI_TOKEN"] = "ya29.fake"
        ok, detail = gdocs.auth_probe()
        self.assertTrue(ok)
        self.assertEqual(detail, "GOOGLE_WORKSPACE_CLI_TOKEN")

    def test_missing_binary_and_credentials_skips_sync_with_hints(self):
        os.environ["GWS_BIN"] = str(self.root / "definitely-not-here")
        self.init_project()
        status, message = gdocs.maybe_sync(self.project, "interim")
        self.assertEqual(status, "skipped")
        self.assertIn("google_docs.py login", message)
        self.assertIn("npm install -g @googleworkspace/cli", message)

    def test_auth_error_surfaces_actionable_failure(self):
        self.init_project()
        os.environ["FAKE_GWS_FAIL_AUTH"] = "1"
        status, message = gdocs.maybe_sync(self.project, "interim")
        self.assertEqual(status, "failed")
        self.assertIn("gws auth login", message)

    def test_sync_end_to_end_creates_three_docs_and_receipt(self):
        self.init_project()
        status, message = gdocs.maybe_sync(self.project, "interim")
        self.assertEqual(status, "synced", message)
        state = self.fake_state()
        self.assertEqual(state["counter"], 3)
        titles = sorted(doc["title"] for doc in state["docs"].values())
        self.assertEqual(titles, sorted(gdocs.TITLES.values()))
        for doc in state["docs"].values():
            self.assertGreater(doc["end"], 2, "document content was written")
        receipt = json.loads((self.project / ".infinite/gdocs.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(receipt["documents"]), ["against", "comparison", "for"])
        for name in gdocs.DOC_NAMES:
            entry = receipt["documents"][name]
            self.assertTrue(entry["id"].startswith("fake-doc-"))
            self.assertIn(entry["id"], entry["url"])
        self.assertEqual(receipt["last_sync"]["mode"], "interim")
        self.assertEqual(receipt["last_sync"]["digest"], gdocs.ledger_digest(self.project))
        self.assertEqual(receipt["last_sync"]["documents_synced"], list(gdocs.DOC_NAMES))

    def test_resync_is_idempotent_and_reuses_documents(self):
        self.init_project()
        self.assertEqual(gdocs.maybe_sync(self.project, "interim")[0], "synced")
        first = self.fake_state()
        self.assertEqual(gdocs.maybe_sync(self.project, "final")[0], "synced")
        second = self.fake_state()
        self.assertEqual(second["counter"], 3, "no duplicate documents created on resync")
        self.assertGreater(second["batches"], first["batches"])
        receipt = json.loads((self.project / ".infinite/gdocs.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["last_sync"]["mode"], "final")

    def test_setup_cli_shares_and_writes_receipt(self):
        self.init_project()
        proc = subprocess.run(
            [sys.executable, str(GDOCS), "--dir", str(self.project), "setup", "--share", "user@example.com"],
            capture_output=True, text=True,
            env=dict(os.environ))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("shared all three documents with user@example.com", proc.stdout)
        self.assertEqual(self.fake_state()["shares"], 3)
        self.assertTrue((self.project / ".infinite/gdocs.json").is_file())

    def test_sync_cli_fails_cleanly_when_unauthenticated(self):
        self.init_project()
        os.environ["FAKE_GWS_UNAUTH"] = "1"
        proc = subprocess.run(
            [sys.executable, str(GDOCS), "--dir", str(self.project), "sync"],
            capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("SKIPPED", proc.stderr)
        self.assertIn("gws auth login", proc.stderr)

    def test_doctor_reports_binary_auth_and_receipt(self):
        self.init_project()
        proc = subprocess.run(
            [sys.executable, str(GDOCS), "--dir", str(self.project), "doctor"],
            capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("gws binary", proc.stdout)
        self.assertIn("auth probe  : OK", proc.stdout)
        os.environ["FAKE_GWS_UNAUTH"] = "1"
        proc = subprocess.run(
            [sys.executable, str(GDOCS), "--dir", str(self.project), "doctor"],
            capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("NOT AUTHENTICATED", proc.stdout)

    def test_credentials_json_secret_is_materialized_privately(self):
        """OpenHands Cloud delivers secrets as env vars; gws needs a file."""
        secret = json.dumps({"type": "authorized_user", "client_id": "cid.apps.googleusercontent.com",
                             "client_secret": "sec", "refresh_token": "rt"})
        os.environ["GOOGLE_WORKSPACE_CLI_CREDENTIALS_JSON"] = secret
        self.init_project()
        status, message = gdocs.maybe_sync(self.project, "interim")
        self.assertEqual(status, "synced", message)
        path = self.project / ".infinite/gws-credentials.json"
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_text(encoding="utf-8").strip(), secret)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(os.environ.get("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"), str(path))
        ok, detail = gdocs.auth_probe()
        self.assertTrue(ok)
        self.assertEqual(detail, "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE")

    def test_invalid_credentials_json_secret_fails_cleanly(self):
        self.init_project()
        os.environ["GWS_CREDENTIALS_JSON"] = "this is not json"
        status, message = gdocs.maybe_sync(self.project, "interim")
        self.assertEqual(status, "failed")
        self.assertIn("GWS_CREDENTIALS_JSON", message)
        self.assertIn("not valid JSON", message)

    def test_compile_auto_syncs_through_gws(self):
        """infinite_research.py compile must mirror via maybe_sync when gws works."""
        self.init_project()
        proc = subprocess.run(
            [sys.executable, str(RESEARCH), "--dir", str(self.project), "compile"],
            capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("google docs: all three Google Docs updated via gws", proc.stdout)
        receipt = json.loads((self.project / ".infinite/gdocs.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["last_sync"]["digest"], gdocs.ledger_digest(self.project))


class FakeGoogleAPI(http.server.BaseHTTPRequestHandler):
    """In-process fake of oauth2.googleapis.com + Docs/Drive REST (via GDOCS_REST_ORIGIN)."""

    def log_message(self, *args):  # silence request logging
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        if "application/x-www-form-urlencoded" in (self.headers.get("Content-Type") or ""):
            return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
        return json.loads(raw) if raw else {}

    def _doc_content(self, doc):
        content = []
        for start_str, table in sorted(doc["tables"].items(), key=lambda kv: int(kv[0])):
            start = int(start_str)
            rows = []
            for r in range(table["rows"]):
                cells = [{"content": [{"startIndex": start + 1 + 2 * (r * table["cols"] + c)}]}
                         for c in range(table["cols"])]
                rows.append({"tableCells": cells})
            content.append({"startIndex": start, "endIndex": table["end"],
                            "table": {"tableRows": rows}})
        content.append({"endIndex": doc["end"]})
        return content

    def _apply(self, doc, requests):
        for request in requests:
            self.server.state["batches"] += 1
            if "insertText" in request:
                doc["end"] += len(request["insertText"].get("text", ""))
            elif "deleteContentRange" in request:
                rng = request["deleteContentRange"].get("range", {})
                doc["end"] = max(2, doc["end"] - (rng.get("endIndex", 0) - rng.get("startIndex", 0)))
                doc["tables"] = {}
            elif "insertTable" in request:
                spec = request["insertTable"]
                start, rows, cols = spec["location"]["index"], spec["rows"], spec["columns"]
                length = 1 + rows * cols * 2
                doc["tables"][str(start)] = {"rows": rows, "cols": cols, "end": start + length}
                doc["end"] += length
            elif "updateDocumentProperties" in request:
                doc["title"] = request["updateDocumentProperties"]["properties"].get("title", doc["title"])

    def do_POST(self):
        state = self.server.state
        path = self.path.split("?")[0]
        body = self._body()
        if path == "/device/code":
            self._send(200, {"device_code": "dev-code-1", "user_code": "ABCD-EFGH",
                             "verification_url": "https://www.google.com/device",
                             "expires_in": 600, "interval": 1})
            return
        if path == "/token":
            grant = body.get("grant_type", "")
            if grant == gdocs.DEVICE_GRANT:
                if state.get("device_pending", 0) > 0:
                    state["device_pending"] -= 1
                    self._send(400, {"error": "authorization_pending"})
                else:
                    state["device_approved"] = True
                    self._send(200, {"access_token": "rest-access-token", "expires_in": 3600,
                                     "refresh_token": "rest-refresh-token"})
                return
            if grant == "refresh_token":
                if body.get("refresh_token") in ("rt", "rest-refresh-token") and body.get("client_id"):
                    state["refreshes"] = state.get("refreshes", 0) + 1
                    self._send(200, {"access_token": "rest-access-token", "expires_in": 3600})
                else:
                    self._send(400, {"error": "invalid_grant", "error_description": "bad refresh token"})
                return
            self._send(400, {"error": "unsupported_grant_type"})
            return
        auth = self.headers.get("Authorization", "")
        if auth != "Bearer rest-access-token":
            self._send(401, {"error": {"code": 401, "message": "invalid credentials"}})
            return
        if path == "/v1/documents":
            state["counter"] += 1
            doc_id = "rest-doc-%d" % state["counter"]
            state["docs"][doc_id] = {"end": 2, "title": body.get("title", ""), "tables": {}}
            self._send(200, {"documentId": doc_id, "title": body.get("title", "")})
            return
        if path.startswith("/v1/documents/") and path.endswith(":batchUpdate"):
            doc = state["docs"].get(path.split("/v1/documents/")[1].split(":")[0])
            if doc is None:
                self._send(404, {"error": {"code": 404, "message": "not found"}})
                return
            self._apply(doc, body.get("requests", []))
            self._send(200, {"replies": [], "revisionId": "rev-1"})
            return
        if path.startswith("/v3/files/") and path.endswith("/permissions"):
            state["shares"] += 1
            self._send(200, {"id": "perm-%d" % state["shares"], "role": "writer", "type": "user"})
            return
        self._send(400, {"error": {"code": 400, "message": "unsupported path %s" % path}})

    def do_GET(self):
        state = self.server.state
        path = self.path.split("?")[0]
        if path.startswith("/v1/documents/"):
            doc = state["docs"].get(path.split("/v1/documents/")[1])
            if doc is None or self.headers.get("Authorization") != "Bearer rest-access-token":
                self._send(404 if doc is None else 401, {"error": {"code": 404}})
                return
            self._send(200, {"documentId": path.rsplit("/", 1)[-1], "title": doc["title"],
                             "body": {"content": self._doc_content(doc)}})
            return
        self._send(400, {"error": {"code": 400, "message": "unsupported path %s" % path}})


class RestTransportTests(FakeGwsTestCase):
    """Direct REST fallback: no gws binary, credentials only."""

    def setUp(self):
        super().setUp()
        os.environ["GWS_BIN"] = str(self.root / "no-gws-here")   # force the REST transport
        self.api_state = {"docs": {}, "counter": 0, "batches": 0, "shares": 0}
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeGoogleAPI)
        self.server.state = self.api_state
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        os.environ["GDOCS_REST_ORIGIN"] = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.creds_file = self.root / "creds.json"
        self.creds_file.write_text(json.dumps({
            "type": "authorized_user", "client_id": "cid.apps.googleusercontent.com",
            "client_secret": "sec", "refresh_token": "rt"}), encoding="utf-8")
        os.environ["GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"] = str(self.creds_file)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def test_rest_sync_end_to_end_without_any_cli(self):
        self.init_project()
        status, message = gdocs.maybe_sync(self.project, "interim")
        self.assertEqual(status, "synced", message)
        self.assertEqual(self.api_state["counter"], 3)
        titles = sorted(doc["title"] for doc in self.api_state["docs"].values())
        self.assertEqual(titles, sorted(gdocs.TITLES.values()))
        for doc in self.api_state["docs"].values():
            self.assertGreater(doc["end"], 2)
        self.assertGreater(self.api_state["refreshes"], 0)
        receipt = json.loads((self.project / ".infinite/gdocs.json").read_text(encoding="utf-8"))
        self.assertTrue(receipt["auth"].startswith("direct-rest:"), receipt["auth"])
        for name in gdocs.DOC_NAMES:
            self.assertTrue(receipt["documents"][name]["id"].startswith("rest-doc-"))

    def test_rest_final_sync_and_share_via_setup(self):
        self.init_project()
        proc = subprocess.run(
            [sys.executable, str(GDOCS), "--dir", str(self.project), "setup", "--share", "user@example.com"],
            capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("authentication (rest)", proc.stdout)
        self.assertEqual(self.api_state["shares"], 3)
        status, message = gdocs.maybe_sync(self.project, "final")
        self.assertEqual(status, "synced", message)
        receipt = json.loads((self.project / ".infinite/gdocs.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["last_sync"]["mode"], "final")
        self.assertEqual(receipt["last_sync"]["digest"], gdocs.ledger_digest(self.project))

    def test_rest_credentials_from_project_login_file(self):
        """Credentials written by `login` at .infinite/gws-credentials.json are picked up."""
        del os.environ["GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"]
        self.init_project()
        path = self.project / ".infinite/gws-credentials.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": "authorized_user", "client_id": "cid",
                                    "client_secret": "sec", "refresh_token": "rt"}), encoding="utf-8")
        os.chmod(path, 0o600)
        status, message = gdocs.maybe_sync(self.project, "interim")
        self.assertEqual(status, "synced", message)
        self.assertEqual(os.environ.get("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"), str(path))

    def test_device_login_command_writes_credentials(self):
        self.init_project()
        del os.environ["GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"]
        self.api_state["device_pending"] = 1   # one authorization_pending poll, then success
        env = dict(os.environ)
        env["GOOGLE_WORKSPACE_CLI_CLIENT_ID"] = "cid.apps.googleusercontent.com"
        env["GOOGLE_WORKSPACE_CLI_CLIENT_SECRET"] = "sec"
        proc = subprocess.run(
            [sys.executable, str(GDOCS), "--dir", str(self.project), "login", "--timeout", "30"],
            capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ABCD-EFGH", proc.stdout)
        self.assertIn("www.google.com/device", proc.stdout)
        path = self.project / ".infinite/gws-credentials.json"
        self.assertTrue(path.is_file())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["refresh_token"], "rest-refresh-token")
        self.assertEqual(saved["type"], "authorized_user")
        self.assertTrue(self.api_state["device_approved"])

    def test_device_login_without_client_explains_console_steps(self):
        self.init_project()
        env = {k: v for k, v in os.environ.items()
               if k not in ("GOOGLE_WORKSPACE_CLI_CLIENT_ID", "GOOGLE_WORKSPACE_CLI_CLIENT_SECRET")}
        proc = subprocess.run(
            [sys.executable, str(GDOCS), "--dir", str(self.project), "login"],
            capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("TVs and Limited Input devices", proc.stderr)
        self.assertIn("console.cloud.google.com", proc.stderr)

    def test_service_account_key_rejected_on_rest_with_guidance(self):
        self.creds_file.write_text(json.dumps({
            "type": "service_account", "client_id": "x"}), encoding="utf-8")
        self.init_project()
        status, message = gdocs.maybe_sync(self.project, "interim")
        self.assertEqual(status, "failed")
        self.assertIn("service-account keys need the gws CLI", message)

    def test_bad_refresh_token_fails_actionably(self):
        self.creds_file.write_text(json.dumps({
            "type": "authorized_user", "client_id": "cid",
            "client_secret": "sec", "refresh_token": "revoked"}), encoding="utf-8")
        self.init_project()
        status, message = gdocs.maybe_sync(self.project, "interim")
        self.assertEqual(status, "failed")
        self.assertIn("invalid_grant", message)

    def test_gws_still_preferred_when_binary_exists(self):
        os.environ["GWS_BIN"] = str(self.fake)   # auto must pick gws over REST
        self.init_project()
        status, _ = gdocs.maybe_sync(self.project, "interim")
        self.assertEqual(status, "synced")
        receipt = json.loads((self.project / ".infinite/gdocs.json").read_text(encoding="utf-8"))
        self.assertTrue(receipt["auth"].startswith("gws-cli:"), receipt["auth"])
        self.assertEqual(self.api_state["counter"], 0, "REST endpoints must not be used")

    def test_transport_override_env(self):
        os.environ["GWS_BIN"] = str(self.fake)
        os.environ["GDOCS_TRANSPORT"] = "rest"
        self.init_project()
        status, _ = gdocs.maybe_sync(self.project, "interim")
        self.assertEqual(status, "synced")
        receipt = json.loads((self.project / ".infinite/gdocs.json").read_text(encoding="utf-8"))
        self.assertTrue(receipt["auth"].startswith("direct-rest:"), receipt["auth"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
