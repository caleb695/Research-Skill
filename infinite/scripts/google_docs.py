#!/usr/bin/env python3
"""Google Docs mirror for the Infinite skill's three research reports.

The fixed prompt requires the deliverables to be Google Documents: one FOR, one
AGAINST, and one head-to-head COMPARISON. This helper creates and syncs those
three documents with two interchangeable transports:

1. the Google Workspace CLI (`gws`, https://github.com/googleworkspace/cli)
   when it is installed — it owns authentication (encrypted store, keyring,
   service accounts); the helper shells out to `gws docs documents
   create|get|batchUpdate` and `gws drive permissions create`; or
2. a built-in direct REST transport (Python standard library only) that needs
   no CLI at all — it uses user credentials (client_id/client_secret/
   refresh_token) to call the Google Docs + Drive APIs over HTTPS. Ideal for
   hosted sandboxes (OpenHands Cloud) and phone-only users.

Getting credentials without a computer: create a free Google Cloud project and
an OAuth client for "TVs and Limited Input devices" in a phone browser, then run

    python3 google_docs.py --dir . login

which starts Google's device-code flow: it prints a short code and a URL, the
user approves it from any browser (their phone), and the refresh token is saved
to .infinite/gws-credentials.json (mode 0600, gitignored, guard-protected).
Alternatively store exported credentials (gws auth export --unmasked) in the
GOOGLE_WORKSPACE_CLI_CREDENTIALS_JSON / GWS_CREDENTIALS_JSON secret, or point
GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE at a file. GDOCS_TRANSPORT=auto|gws|rest
forces a transport (default auto: gws when installed, else REST).

It is the only writer of the sync receipt `.infinite/gdocs.json`, and
`infinite_research.py validate --final` refuses to pass until that receipt shows
all three documents synced at the current ledger digest in final mode — so the
run cannot finish on local Markdown alone.

Commands:
  login                   device-code OAuth login (phone-friendly, no browser here)
  setup [--share EMAIL]   check auth, create the three docs, write receipt
  sync [--mode M]         push the compiled reports into the three docs (M=interim|final)
  status                  show receipt, document URLs, and staleness
  doctor                  diagnose transport, installation, and authentication

Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DOC_NAMES = ("for", "against", "comparison")
TITLES = {
    "for": "Book of Mormon Evidence — FOR",
    "against": "Book of Mormon Evidence — AGAINST",
    "comparison": "Book of Mormon Evidence — FOR vs AGAINST (Comparison)",
}
REPORT_PATHS = {
    "for": Path("research/book-of-mormon-for.md"),
    "against": Path("research/book-of-mormon-against.md"),
    "comparison": Path("research/book-of-mormon-comparison.md"),
}
RECEIPT_REL = Path(".infinite/gdocs.json")

MAX_INSERT_CHARS = 3500          # per insertText request
MAX_REQUESTS_PER_BATCH = 400     # per batchUpdate call
MAX_BATCH_BYTES = 250_000        # serialized payload safety margin (argv limit)
MAX_CELL_CHARS = 800             # table cell truncation guard
GWS_TIMEOUT = 180                # seconds per gws invocation (discovery fetch can be slow)
RETRY_EXIT_CODES = {1, 4, 5}     # API / discovery / internal errors may be transient
RETRY_HTTP_CODES = {429, 500, 502, 503, 504}

INSTALL_HINT = (
    "install the Google Workspace CLI: npm install -g @googleworkspace/cli "
    "(or brew install googleworkspace-cli, or a binary from "
    "https://github.com/googleworkspace/cli/releases), then authenticate with "
    "'gws auth login' (or 'gws auth setup', or export credentials for headless "
    "use). No computer? Run 'google_docs.py login' instead (device-code flow "
    "you approve from your phone). Full walkthrough: references/google-docs.md"
)

# --------------------------------------------------------------------------- #
# direct REST transport (stdlib only; used when gws is not installed)
# --------------------------------------------------------------------------- #
REST_TIMEOUT = 120               # seconds per HTTPS call
DOCS_SCOPES = ("https://www.googleapis.com/auth/documents",
               "https://www.googleapis.com/auth/drive.file")
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
PROJECT_CREDS_REL = ".infinite/gws-credentials.json"   # written by login/prepare_credentials
NO_CREDS_HINT = (
    "no Google credentials found. Options: run 'google_docs.py login' "
    "(device-code flow — works from a phone, needs an OAuth client for "
    "'TVs and Limited Input devices'), or install the gws CLI "
    "(npm install -g @googleworkspace/cli) and authenticate, or set "
    "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE / the "
    "GOOGLE_WORKSPACE_CLI_CREDENTIALS_JSON secret. Walkthrough: references/google-docs.md"
)


def _rest_url(service: str, path: str) -> str:
    """Absolute REST URL; GDOCS_REST_ORIGIN overrides every endpoint (tests)."""
    override = os.environ.get("GDOCS_REST_ORIGIN")
    if override:
        return override.rstrip("/") + path
    bases = {
        "oauth": "https://oauth2.googleapis.com",
        "docs": "https://docs.googleapis.com",
        "drive": "https://drive.googleapis.com",
    }
    return bases[service] + path


def _http_json(method: str, url: str, payload: dict | None = None,
               form: dict | None = None, headers: dict | None = None,
               retries: int = 3) -> dict:
    """One HTTPS JSON call with retry/backoff on transient failures."""
    hdrs = dict(headers or {})
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    elif payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    last_error = ""
    for attempt in range(retries):
        request = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(request, timeout=REST_TIMEOUT) as response:
                body = response.read().decode("utf-8", "replace").strip()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            body = (exc.read() or b"").decode("utf-8", "replace")[:800]
            if exc.code in RETRY_HTTP_CODES and attempt < retries - 1:
                last_error = f"HTTP {exc.code}: {body}"
                time.sleep(min(2 ** attempt, 16))
                continue
            if exc.code in (401, 403):
                raise GDocsError(
                    f"Google rejected the credentials (HTTP {exc.code}): {body}. "
                    "The refresh token may be revoked or the OAuth app missing your "
                    "account as a test user — re-run 'google_docs.py login' (or re-export "
                    "credentials). See references/google-docs.md") from None
            raise GDocsError(f"{method} {url} failed (HTTP {exc.code}): {body}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt, 16))
                continue
            raise GDocsError(f"{method} {url} failed after retries — {last_error}") from None
    raise GDocsError(f"{method} {url} failed after retries — {last_error}")


class RestCredentials:
    """User credentials for the direct REST transport, with token refresh.

    Resolution order: GOOGLE_WORKSPACE_CLI_TOKEN (raw access token) →
    GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE → .infinite/gws-credentials.json in
    the project (written by `login` or materialized from the JSON secret).
    Service-account keys are rejected here (JWT signing needs the gws CLI).
    """

    def __init__(self, project: Path):
        self._static = os.environ.get("GOOGLE_WORKSPACE_CLI_TOKEN") or None
        self.source = "GOOGLE_WORKSPACE_CLI_TOKEN"
        self.client_id = self.client_secret = self.refresh_token = None
        self._token: str | None = None
        self._expiry = 0.0
        if self._static:
            return
        creds = self._load(project)
        if creds.get("type") == "service_account":
            raise GDocsError(
                "the built-in REST transport supports user credentials (authorized_user); "
                "service-account keys need the gws CLI. Either install gws, or run "
                "'google_docs.py login' / export user credentials instead "
                "(see references/google-docs.md)")
        self.client_id = creds.get("client_id")
        self.client_secret = creds.get("client_secret")
        self.refresh_token = creds.get("refresh_token")
        missing = [key for key, value in (("client_id", self.client_id),
                                          ("client_secret", self.client_secret),
                                          ("refresh_token", self.refresh_token)) if not value]
        if missing:
            raise GDocsError(
                f"credentials ({self.source}) are missing: {', '.join(missing)}. "
                "Expected the JSON from 'google_docs.py login' or 'gws auth export --unmasked'.")

    def _load(self, project: Path) -> dict:
        candidates: list[tuple[Path, str]] = []
        env_path = os.environ.get("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE")
        if env_path:
            candidates.append((Path(env_path).expanduser(), f"GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE ({env_path})"))
        project_path = Path(project) / PROJECT_CREDS_REL
        candidates.append((project_path, str(project_path)))
        for path, label in candidates:
            if path.is_file():
                self.source = label
                try:
                    parsed = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise GDocsError(f"could not read credentials at {label}: {exc}") from exc
                if not isinstance(parsed, dict):
                    raise GDocsError(f"credentials at {label} are not a JSON object")
                return parsed
        raise GDocsError(NO_CREDS_HINT)

    def access_token(self) -> str:
        if self._static:
            return self._static
        if self._token and time.time() < self._expiry - 60:
            return self._token
        response = _http_json("POST", _rest_url("oauth", "/token"), form={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "refresh_token": self.refresh_token, "grant_type": "refresh_token",
        })
        token = response.get("access_token")
        if not token:
            raise GDocsError(f"token refresh returned no access_token: {str(response)[:300]} — "
                             "re-run 'google_docs.py login' if this persists")
        self._token = str(token)
        self._expiry = time.time() + int(response.get("expires_in", 3600))
        return self._token


class RestDocs:
    """Google Docs REST surface matching the GwsDocs interface."""

    def __init__(self, document_id: str, creds: RestCredentials):
        self.document_id = document_id
        self.creds = creds

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.creds.access_token()}"}

    def get(self) -> dict:
        return _http_json("GET", _rest_url("docs", f"/v1/documents/{self.document_id}"),
                          headers=self._headers())

    def batch_update(self, requests: list[dict]) -> dict:
        if not requests:
            return {}
        return _http_json("POST", _rest_url("docs", f"/v1/documents/{self.document_id}:batchUpdate"),
                          payload={"requests": requests}, headers=self._headers())

    @staticmethod
    def create(title: str, creds: RestCredentials) -> str:
        response = _http_json("POST", _rest_url("docs", "/v1/documents"),
                              payload={"title": title},
                              headers={"Authorization": f"Bearer {creds.access_token()}"})
        document_id = response.get("documentId")
        if not document_id:
            raise GDocsError(f"documents.create for '{title}' returned no documentId: {str(response)[:300]}")
        return str(document_id)


def rest_share(creds: RestCredentials, file_id: str, email: str) -> None:
    _http_json("POST",
               _rest_url("drive", f"/v3/files/{file_id}/permissions?sendNotificationEmail=false"),
               payload={"role": "writer", "type": "user", "emailAddress": email},
               headers={"Authorization": f"Bearer {creds.access_token()}"})


class Transport:
    """Chooses between the gws CLI and the direct REST transport."""

    def __init__(self, project: Path):
        mode = (os.environ.get("GDOCS_TRANSPORT") or "auto").strip().lower()
        if mode not in ("auto", "gws", "rest"):
            raise GDocsError(f"unknown GDOCS_TRANSPORT '{mode}' (expected auto, gws, or rest)")
        binary = gws_bin()
        if mode == "gws" and binary is None:
            raise GDocsError(f"GDOCS_TRANSPORT=gws but {INSTALL_HINT}")
        if mode == "rest" or (mode == "auto" and binary is None):
            self.mode = "rest"
            self.creds = RestCredentials(project)   # raises with NO_CREDS_HINT when unavailable
        else:
            self.mode = "gws"
            self.creds = None

    def create(self, title: str) -> str:
        if self.mode == "gws":
            return GwsDocs.create(title)
        return RestDocs.create(title, self.creds)

    def docs(self, document_id: str):
        return GwsDocs(document_id) if self.mode == "gws" else RestDocs(document_id, self.creds)

    def share(self, file_id: str, email: str) -> None:
        if self.mode == "gws":
            run_gws(["drive", "permissions", "create",
                     "--params", json.dumps({"fileId": file_id, "sendNotificationEmail": False}),
                     "--json", json.dumps({"role": "writer", "type": "user", "emailAddress": email})])
        else:
            rest_share(self.creds, file_id, email)

    def label(self, detail: str) -> str:
        return f"gws-cli:{detail}" if self.mode == "gws" else f"direct-rest:{self.creds.source}"


class GDocsError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def project_dir(explicit: str | None) -> Path:
    path = Path(explicit or ".").expanduser().resolve()
    return path.parent if path.name == ".infinite" else path


def read_json(path: Path, default: dict) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)
    return value if isinstance(value, dict) else dict(default)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def ledger_digest(project: Path) -> str:
    path = project / ".infinite" / "ledger.jsonl"
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


# --------------------------------------------------------------------------- #
# gws CLI transport
# --------------------------------------------------------------------------- #
def gws_bin() -> str | None:
    override = os.environ.get("GWS_BIN")
    if override:
        candidate = shutil.which(override) or (override if Path(override).is_file() else None)
        return candidate
    return shutil.which("gws")


def run_gws(args: list[str], retries: int = 3) -> dict:
    """Run one gws command and return its parsed JSON output.

    Retries transient failures (429/5xx API errors, discovery fetch errors,
    timeouts) with backoff. Raises GDocsError with actionable text otherwise.
    """
    binary = gws_bin()
    if binary is None:
        raise GDocsError(f"gws CLI not found on PATH; {INSTALL_HINT}")
    label = " ".join(args[:4])
    last_error = ""
    for attempt in range(retries):
        try:
            proc = subprocess.run([binary, *args], capture_output=True, text=True, timeout=GWS_TIMEOUT)
        except subprocess.TimeoutExpired:
            last_error = f"timeout after {GWS_TIMEOUT}s"
            if attempt == retries - 1:
                raise GDocsError(f"gws {label} failed — {last_error}") from None
            time.sleep(min(2 ** attempt, 16))
            continue
        except OSError as exc:
            raise GDocsError(f"gws {label} could not be executed: {exc}") from exc
        stdout = (proc.stdout or "").strip()
        if proc.returncode == 0:
            if not stdout:
                return {}
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise GDocsError(f"gws {label} returned non-JSON output: {stdout[:300]}") from exc
            return parsed if isinstance(parsed, dict) else {"result": parsed}
        detail = (proc.stderr or stdout)[:800].strip()
        http_code = None
        try:
            http_code = json.loads(stdout).get("error", {}).get("code")
        except (json.JSONDecodeError, AttributeError):
            pass
        if proc.returncode == 2:
            raise GDocsError(
                f"gws authentication failed (exit 2): {detail}. Run 'gws auth login' "
                "(or point GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE at exported credentials). "
                "See references/google-docs.md"
            )
        if proc.returncode == 3:
            raise GDocsError(f"gws rejected the command (exit 3, validation): {detail}")
        transient = proc.returncode in RETRY_EXIT_CODES and (http_code in RETRY_HTTP_CODES or http_code is None)
        if transient and attempt < retries - 1:
            last_error = f"exit {proc.returncode}" + (f" (HTTP {http_code})" if http_code else "") + f": {detail}"
            time.sleep(min(2 ** attempt, 16))
            continue
        raise GDocsError(f"gws {label} failed (exit {proc.returncode}): {detail}")
    raise GDocsError(f"gws {label} failed after retries — {last_error}")


CREDENTIALS_JSON_ENVS = ("GOOGLE_WORKSPACE_CLI_CREDENTIALS_JSON", "GWS_CREDENTIALS_JSON")
MATERIALIZED_CREDS_REL = PROJECT_CREDS_REL


def prepare_credentials(project: Path) -> None:
    """Materialize an inline credentials secret into a private file for gws.

    Hosted sandboxes (e.g. OpenHands Cloud) deliver user secrets as environment
    variables, but gws takes credentials through GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE.
    When one of CREDENTIALS_JSON_ENVS holds a full credentials JSON (the output of
    `gws auth export --unmasked`, or a service-account key), write it to
    `.infinite/gws-credentials.json` (mode 0600, guard-protected) and point the
    env var at it — so no secret ever has to pass through the agent's shell.
    """
    if os.environ.get("GOOGLE_WORKSPACE_CLI_TOKEN"):
        return
    existing = os.environ.get("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE")
    if existing and Path(existing).expanduser().is_file():
        return
    for name in CREDENTIALS_JSON_ENVS:
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GDocsError(f"{name} is set but is not valid JSON ({exc}); it must hold the "
                             f"contents of 'gws auth export --unmasked' (or a service-account key)")
        if not isinstance(parsed, dict) or not parsed:
            raise GDocsError(f"{name} must hold a credentials JSON object")
        path = Path(project) / MATERIALIZED_CREDS_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current != raw + "\n":
            path.write_text(raw + "\n", encoding="utf-8")
            os.chmod(path, 0o600)
        os.environ["GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"] = str(path)
        return
    fallback = Path(project) / PROJECT_CREDS_REL
    if fallback.is_file():
        # login (or a previous run) already stored credentials in the project;
        # expose them to gws subprocesses through the standard env var.
        os.environ["GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"] = str(fallback)


def auth_probe(project: Path | None = None) -> tuple[bool, str]:
    """Cheap, local check that some transport holds credentials for the user."""
    if os.environ.get("GOOGLE_WORKSPACE_CLI_TOKEN"):
        return True, "GOOGLE_WORKSPACE_CLI_TOKEN"
    creds_file = os.environ.get("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE")
    if creds_file and Path(creds_file).expanduser().is_file():
        return True, "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"
    if project and (Path(project) / PROJECT_CREDS_REL).is_file():
        return True, str(Path(project) / PROJECT_CREDS_REL)
    binary = gws_bin()
    if binary is None:
        return False, f"no gws CLI on PATH and {NO_CREDS_HINT}"
    try:
        status = run_gws(["auth", "status"], retries=1)
    except GDocsError as exc:
        return False, str(exc)
    if status.get("auth_method") not in (None, "none") or status.get("credential_source") not in (None, "none"):
        source = status.get("credential_source") or status.get("auth_method")
        return True, f"gws auth ({source})"
    return False, ("gws is installed but not authenticated; run 'gws auth login' "
                   "(or 'gws auth setup', or export credentials headlessly). "
                   "See references/google-docs.md")


# --------------------------------------------------------------------------- #
# markdown -> Google Docs conversion (transport-independent)
# --------------------------------------------------------------------------- #
INLINE_RE = re.compile(r"(\*\*.+?\*\*|\[[^\]]+\]\([^)\s]+\)|`[^`]+`)")
HEADING_STYLES = {1: "TITLE", 2: "HEADING_1", 3: "HEADING_2", 4: "HEADING_3", 5: "HEADING_3", 6: "HEADING_3"}


def render_inline(text: str) -> tuple[str, list[tuple[int, int, dict, str]]]:
    """Flatten markdown inline markup into plain text plus styled ranges.

    Returns (plain, [(start, end, textStyle, fields), ...]).
    """
    plain_parts: list[str] = []
    ranges: list[tuple[int, int, dict, str]] = []
    position = 0
    for piece in INLINE_RE.split(text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**") and len(piece) > 4:
            body = piece[2:-2]
            plain_parts.append(body)
            ranges.append((position, position + len(body), {"bold": True}, "bold"))
            position += len(body)
        elif piece.startswith("[") and "](" in piece and piece.endswith(")"):
            anchor, _, url = piece[1:-1].partition("](")
            plain_parts.append(anchor)
            ranges.append((position, position + len(anchor), {"link": {"url": url}}, "link"))
            position += len(anchor)
        elif piece.startswith("`") and piece.endswith("`") and len(piece) > 2:
            body = piece[1:-1]
            plain_parts.append(body)
            ranges.append((position, position + len(body), {"fontFamily": "Courier New"}, "fontFamily"))
            position += len(body)
        else:
            plain_parts.append(piece)
            position += len(piece)
    return "".join(plain_parts), ranges


def clean_cell(text: str) -> str:
    return text.replace("<br>", "; ").replace("\\|", "|").strip()


def parse_blocks(markdown: str) -> list[dict]:
    """Parse the report markdown subset into ordered blocks."""
    blocks: list[dict] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or re.fullmatch(r"<!--.*-->", stripped):
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            blocks.append({"type": "heading", "level": len(heading.group(1)), "text": heading.group(2).strip()})
            index += 1
            continue
        bullet = re.match(r"^(\s*)-\s+(.*)$", line)
        if bullet:
            indent = min(len(bullet.group(1)) // 2, 3)
            blocks.append({"type": "bullet", "indent": indent, "text": bullet.group(2).strip()})
            index += 1
            continue
        if stripped.startswith("|"):
            rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                body = lines[index].strip()
                body = body[1:] if body.startswith("|") else body
                body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
                # Split only on UNESCAPED pipes; the reports escape literal
                # pipes inside cells as \| (see md() in infinite_research.py).
                cells = [clean_cell(c) for c in re.split(r"(?<!\\)\|", body)]
                if cells and not all(re.fullmatch(r":?-{2,}:?", c.strip()) for c in cells if c.strip() != ""):
                    rows.append(cells)
                index += 1
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                blocks.append({"type": "table", "rows": rows})
            continue
        blocks.append({"type": "para", "text": stripped})
        index += 1
    return blocks


def paragraph_requests(cursor: int, text: str, style: str, indent: int = 0) -> tuple[list[dict], int]:
    plain, ranges = render_inline(text)
    body = plain + "\n"
    requests: list[dict] = []
    position = cursor
    remaining = body
    while remaining:
        chunk, remaining = remaining[:MAX_INSERT_CHARS], remaining[MAX_INSERT_CHARS:]
        requests.append({"insertText": {"location": {"index": position}, "text": chunk}})
        position += len(chunk)
    end = cursor + len(body)
    paragraph_style = {"namedStyleType": style}
    fields = "namedStyleType"
    if indent:
        paragraph_style["indentStartLevel"] = indent
        fields += ",indentStartLevel"
    requests.append({"updateParagraphStyle": {
        "range": {"startIndex": cursor, "endIndex": end},
        "paragraphStyle": paragraph_style, "fields": fields}})
    for start, stop, style_body, style_fields in ranges:
        if start >= stop or stop > len(plain):
            continue
        requests.append({"updateTextStyle": {
            "range": {"startIndex": cursor + start, "endIndex": cursor + stop},
            "textStyle": style_body, "fields": style_fields}})
    return requests, end


def document_end_index(document: dict) -> int:
    content = document.get("body", {}).get("content") or []
    if not content:
        return 1
    return int(content[-1].get("endIndex", 1))


def find_table_at(document: dict, start_index: int) -> dict | None:
    for element in document.get("body", {}).get("content") or []:
        table = element.get("table")
        if table and int(element.get("startIndex", -1)) == start_index:
            return element
    return None


class GwsDocs:
    """Thin wrapper over the gws Docs surface."""

    def __init__(self, document_id: str):
        self.document_id = document_id

    def get(self) -> dict:
        return run_gws(["docs", "documents", "get",
                        "--params", json.dumps({"documentId": self.document_id})])

    def batch_update(self, requests: list[dict]) -> dict:
        if not requests:
            return {}
        return run_gws(["docs", "documents", "batchUpdate",
                        "--params", json.dumps({"documentId": self.document_id}),
                        "--json", json.dumps({"requests": requests})])

    @staticmethod
    def create(title: str) -> str:
        response = run_gws(["docs", "documents", "create", "--json", json.dumps({"title": title})])
        document_id = response.get("documentId")
        if not document_id:
            raise GDocsError(f"docs.documents.create for '{title}' returned no documentId: {str(response)[:300]}")
        return str(document_id)


class Batcher:
    """Accumulates Docs requests and flushes them in size-bounded batchUpdates."""

    def __init__(self, docs: GwsDocs):
        self.docs = docs
        self.pending: list[dict] = []

    def add(self, requests: list[dict]) -> None:
        for request in requests:
            self.pending.append(request)
            if len(self.pending) >= MAX_REQUESTS_PER_BATCH or self._bytes() > MAX_BATCH_BYTES:
                self.flush()

    def _bytes(self) -> int:
        return len(json.dumps(self.pending))

    def flush(self) -> None:
        if not self.pending:
            return
        batch, self.pending = self.pending, []
        self.docs.batch_update(batch)


def sync_document(docs, markdown: str, title: str) -> None:
    """Replace the document's content with the rendered markdown report.

    `docs` is a GwsDocs or RestDocs handle (same get/batch_update interface).
    """
    document = docs.get()
    end = document_end_index(document)
    batcher = Batcher(docs)
    if end > 2:
        batcher.add([{"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end - 1}}}])
    batcher.flush()
    cursor = 1
    for block in parse_blocks(markdown):
        if block["type"] == "heading":
            requests, cursor = paragraph_requests(cursor, block["text"], HEADING_STYLES.get(block["level"], "HEADING_3"))
            batcher.add(requests)
        elif block["type"] == "bullet":
            requests, cursor = paragraph_requests(cursor, block["text"], "BULLET", block.get("indent", 0))
            batcher.add(requests)
        elif block["type"] == "para":
            requests, cursor = paragraph_requests(cursor, block["text"], "NORMAL_TEXT")
            batcher.add(requests)
        elif block["type"] == "table":
            batcher.flush()
            rows = block["rows"]
            if not rows or not rows[0]:
                continue
            docs.batch_update([{"insertTable": {
                "location": {"index": cursor}, "rows": len(rows), "columns": len(rows[0])}}])
            document = docs.get()
            table = find_table_at(document, cursor)
            if table is None:
                raise GDocsError(f"could not locate inserted table at index {cursor}")
            cells: list[tuple[int, bool]] = []
            for row_index, row in enumerate(table.get("table", {}).get("tableRows", [])):
                for cell in row.get("tableCells", []):
                    content = cell.get("content") or [{}]
                    start = int(content[0].get("startIndex", cursor))
                    cells.append((start, row_index == 0))
            flat = [c for row in rows for c in row]
            if len(flat) != len(cells):
                flat = (flat + [""] * len(cells))[:len(cells)]
            cell_requests: list[dict] = []
            inserted = 0
            for (start, header), text in reversed(list(zip(cells, flat))):
                text = text.replace("\n", " ").strip()
                if not text:
                    continue
                truncated = text[:MAX_CELL_CHARS]
                plain, ranges = render_inline(truncated)
                position = start
                remaining = plain
                while remaining:
                    chunk, remaining = remaining[:MAX_INSERT_CHARS], remaining[MAX_INSERT_CHARS:]
                    cell_requests.append({"insertText": {"location": {"index": position}, "text": chunk}})
                    position += len(chunk)
                if header:
                    cell_requests.append({"updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": start + len(plain)},
                        "textStyle": {"bold": True}, "fields": "bold"}})
                inserted += len(plain)
            # Cells were processed in reverse document order, so every recorded
            # index stays valid while the batch applies sequentially.
            for chunk_start in range(0, len(cell_requests), MAX_REQUESTS_PER_BATCH):
                docs.batch_update(cell_requests[chunk_start:chunk_start + MAX_REQUESTS_PER_BATCH])
            table_element_end = int(table.get("endIndex", cursor + 1))
            cursor = table_element_end + inserted
    batcher.flush()
    docs.batch_update([{"updateDocumentProperties": {"properties": {"title": title}, "fields": "title"}}])


# --------------------------------------------------------------------------- #
# receipt, setup, sync
# --------------------------------------------------------------------------- #
def receipt_path(project: Path) -> Path:
    return project / RECEIPT_REL


def create_missing_documents(project: Path, receipt: dict, transport: Transport | None = None) -> dict:
    documents = receipt.get("documents") if isinstance(receipt.get("documents"), dict) else {}
    if any(not (isinstance(documents.get(name), dict) and documents.get(name, {}).get("id"))
           for name in DOC_NAMES):
        transport = transport or Transport(project)
    for name in DOC_NAMES:
        entry = documents.get(name) if isinstance(documents.get(name), dict) else {}
        if entry.get("id"):
            continue
        document_id = transport.create(TITLES[name])
        entry = {"id": document_id, "title": TITLES[name],
                 "url": f"https://docs.google.com/document/d/{document_id}/edit"}
        documents[name] = entry
    receipt["documents"] = documents
    write_json(receipt_path(project), receipt)
    return receipt


def share_documents(project: Path, receipt: dict, email: str, transport: Transport | None = None) -> None:
    transport = transport or Transport(project)
    for name in DOC_NAMES:
        entry = receipt.get("documents", {}).get(name, {})
        if not entry.get("id"):
            continue
        transport.share(entry["id"], email)


def sync_all(project: Path, mode: str) -> dict:
    """Sync the three compiled reports to Google Docs and update the receipt."""
    prepare_credentials(project)
    ok, detail = auth_probe(project)
    if not ok:
        raise GDocsError(detail)
    transport = Transport(project)
    receipt = read_json(receipt_path(project), {})
    receipt = create_missing_documents(project, receipt, transport)
    for name in DOC_NAMES:
        report = project / REPORT_PATHS[name]
        if not report.is_file():
            raise GDocsError(f"report {report} is missing; run infinite_research.py compile first")
        sync_document(transport.docs(receipt["documents"][name]["id"]),
                      report.read_text(encoding="utf-8"), TITLES[name])
    receipt["auth"] = transport.label(detail)
    receipt["last_sync"] = {"ts": now(), "mode": mode, "digest": ledger_digest(project),
                            "documents_synced": list(DOC_NAMES)}
    write_json(receipt_path(project), receipt)
    return receipt


def maybe_sync(project: Path, mode: str = "interim") -> tuple[str, str]:
    """Best-effort entry point used by infinite_research.py compile.

    Returns (status, message) with status in {"synced", "skipped", "failed"};
    never raises, so a missing gws install or network failure cannot break the
    local compile. Final enforcement lives in validate --final, which requires
    a current final-mode receipt.
    """
    project = Path(project)
    try:
        prepare_credentials(project)
        ok, detail = auth_probe(project)
        if not ok:
            return "skipped", detail
        receipt = sync_all(project, mode)
    except GDocsError as exc:
        return "failed", str(exc)
    except (OSError, ValueError) as exc:
        return "failed", f"unexpected error: {exc}"
    urls = ", ".join(receipt.get("documents", {}).get(name, {}).get("url", "?") for name in DOC_NAMES)
    return "synced", f"all three Google Docs updated via gws ({mode} mode): {urls}"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def cmd_login(args) -> int:
    """Device-code OAuth login — the phone-friendly path.

    The sandbox has no browser; Google's device flow shows the user a short
    code + URL to approve from any device. Requires an OAuth client of type
    'TVs and Limited Input devices' (free; creatable from a phone browser in
    the Google Cloud Console — see references/google-docs.md).
    """
    project = project_dir(args.dir)
    client_id = args.client_id or os.environ.get("GOOGLE_WORKSPACE_CLI_CLIENT_ID")
    client_secret = args.client_secret or os.environ.get("GOOGLE_WORKSPACE_CLI_CLIENT_SECRET")
    if not client_id or not client_secret:
        print(
            "device login needs OAuth client credentials for a 'TVs and Limited Input devices' client:\n"
            "  1. open https://console.cloud.google.com/apis/credentials in any browser (phone is fine)\n"
            "  2. create project if needed, enable the Google Docs API and Google Drive API,\n"
            "     add yourself as a Test user on the OAuth consent screen\n"
            "  3. Create credentials -> OAuth client ID -> TVs and Limited Input devices\n"
            "  4. save the client ID + secret as OpenHands secrets GOOGLE_WORKSPACE_CLI_CLIENT_ID\n"
            "     and GOOGLE_WORKSPACE_CLI_CLIENT_SECRET (or pass --client-id/--client-secret)\n"
            "  step-by-step: references/google-docs.md (phone-only setup)", file=sys.stderr)
        return 1
    try:
        start = _http_json("POST", _rest_url("oauth", "/device/code"),
                           form={"client_id": client_id, "scope": " ".join(DOCS_SCOPES)})
    except GDocsError as exc:
        print(f"device login could not start: {exc}", file=sys.stderr)
        return 1
    device_code = start.get("device_code")
    user_code = start.get("user_code")
    if not device_code or not user_code:
        print(f"unexpected device-code response: {str(start)[:300]}", file=sys.stderr)
        return 1
    verification = start.get("verification_url") or "https://www.google.com/device"
    interval = max(int(start.get("interval", 5)), 1)
    expires = int(start.get("expires_in", 1800))
    print("=" * 64)
    print("ON YOUR PHONE (or any browser), open:")
    print(f"    {verification}")
    print("and enter this code:")
    print(f"    {user_code}")
    print("then sign in with your Google account and approve access.")
    print("Waiting for approval...", flush=True)
    print("=" * 64, flush=True)
    deadline = time.time() + min(args.timeout, expires)
    while time.time() < deadline:
        time.sleep(interval)
        try:
            response = _http_json("POST", _rest_url("oauth", "/token"), form={
                "client_id": client_id, "client_secret": client_secret,
                "device_code": device_code, "grant_type": DEVICE_GRANT,
            }, retries=1)
        except GDocsError as exc:
            message = str(exc)
            if "authorization_pending" in message:
                continue
            if "slow_down" in message:
                interval += 5
                continue
            if "access_denied" in message:
                print("login denied by the user or the OAuth app; re-run and approve.", file=sys.stderr)
                return 1
            if "expired_token" in message:
                print("the device code expired; re-run login and approve promptly.", file=sys.stderr)
                return 1
            print(f"device login failed: {message}", file=sys.stderr)
            return 1
        refresh_token = response.get("refresh_token")
        if not refresh_token:
            print(
                "Google returned no refresh_token (access was likely granted before). Revoke this app at "
                "https://myaccount.google.com/permissions, then re-run login.", file=sys.stderr)
            return 1
        path = project / PROJECT_CREDS_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "type": "authorized_user", "client_id": client_id,
            "client_secret": client_secret, "refresh_token": refresh_token,
        }, indent=2) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
        os.environ["GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"] = str(path)
        print(f"login complete. Credentials saved to {path} (mode 0600; gitignored; guard-protected).")
        print("next: python3 google_docs.py --dir . setup")
        return 0
    print(f"timed out after {min(args.timeout, expires)}s waiting for approval; re-run login.", file=sys.stderr)
    return 1


def cmd_setup(args) -> int:
    project = project_dir(args.dir)
    try:
        prepare_credentials(project)
    except GDocsError as exc:
        print(f"google docs setup blocked: {exc}", file=sys.stderr)
        return 1
    ok, detail = auth_probe(project)
    if not ok:
        print(f"google docs setup blocked: {detail}", file=sys.stderr)
        return 1
    transport = Transport(project)
    receipt = create_missing_documents(project, read_json(receipt_path(project), {}), transport)
    if args.share:
        share_documents(project, receipt, args.share, transport)
        print(f"shared all three documents with {args.share} (writer)")
    receipt["auth"] = transport.label(detail)
    receipt["setup_at"] = now()
    write_json(receipt_path(project), receipt)
    print(f"authentication ({transport.mode}): {detail}")
    for name in DOC_NAMES:
        entry = receipt["documents"][name]
        print(f"  {name:10s} {entry['url']}")
    print("next: python3 google_docs.py --dir . sync   (runs automatically after each compile when gws is authenticated)")
    return 0


def cmd_sync(args) -> int:
    project = project_dir(args.dir)
    if args.mode == "final" and not (project / ".openhands/guard/STOP_REQUESTED").exists():
        # Mirrors the guard rule: a final sync only follows a real user stop.
        print("note: no user STOP_REQUESTED marker found; the guard blocks a premature final "
              "sync when hooks are installed. Use --mode final only after the user says stop.",
              file=sys.stderr)
    status, message = maybe_sync(project, args.mode)
    if status == "skipped":
        print(f"google docs sync SKIPPED: {message}", file=sys.stderr)
        return 1
    if status == "failed":
        print(f"google docs sync FAILED: {message}", file=sys.stderr)
        return 1
    print(f"google docs: {message}")
    return 0


def cmd_status(args) -> int:
    project = project_dir(args.dir)
    receipt = read_json(receipt_path(project), {})
    if not receipt:
        print("no Google Docs receipt yet; run: python3 google_docs.py --dir . setup")
        print("(gws walkthrough: references/google-docs.md)")
        return 0
    digest = ledger_digest(project)
    synced = receipt.get("last_sync", {})
    print(f"auth        : {receipt.get('auth', '?')}")
    for name in DOC_NAMES:
        entry = receipt.get("documents", {}).get(name, {})
        print(f"document {name:10s}: {entry.get('url', '(not created)')}")
    print(f"last sync   : {synced.get('ts', 'never')} (mode {synced.get('mode', '?')})")
    state = "current" if synced.get("digest") == digest else "STALE — recompile and sync"
    print(f"ledger match: {state}")
    return 0


def cmd_doctor(args) -> int:
    project = project_dir(args.dir)
    try:
        prepare_credentials(project)
    except GDocsError as exc:
        print(f"credential secret problem: {exc}")
    binary = gws_bin()
    print(f"gws binary  : {binary or 'not found (REST fallback can still work with credentials)'}")
    if binary:
        try:
            proc = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30)
            print(f"gws version : {(proc.stdout or proc.stderr).strip()[:120] or 'unknown'}")
        except (OSError, subprocess.TimeoutExpired):
            print("gws version : (could not run --version)")
    ok, detail = auth_probe(project)
    print(f"auth probe  : {'OK' if ok else 'NOT AUTHENTICATED'} — {detail}")
    try:
        transport = Transport(project)
        print(f"transport   : {transport.mode}" + (f" (credentials: {transport.creds.source})"
                                                   if transport.mode == "rest" else ""))
    except GDocsError as exc:
        print(f"transport   : unavailable — {exc}")
    receipt = read_json(receipt_path(project), {})
    if receipt:
        synced = receipt.get("last_sync", {})
        current = synced.get("digest") == ledger_digest(project)
        print(f"receipt     : {len(receipt.get('documents', {}))} documents; last sync {synced.get('ts', 'never')} ({synced.get('mode', '?')}); {'current' if current else 'STALE'}")
    else:
        print("receipt     : none (run setup)")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", help="project workspace (default: current directory)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("login", help="device-code OAuth login (approve from your phone; no browser needed here)")
    p.add_argument("--client-id", help="OAuth client ID (default: GOOGLE_WORKSPACE_CLI_CLIENT_ID)")
    p.add_argument("--client-secret", help="OAuth client secret (default: GOOGLE_WORKSPACE_CLI_CLIENT_SECRET)")
    p.add_argument("--timeout", type=int, default=600, help="seconds to wait for approval (default 600)")
    p.set_defaults(func=cmd_login)
    p = sub.add_parser("setup", help="check auth, create the three documents")
    p.add_argument("--share", metavar="EMAIL", help="share the documents with this Google account (writer)")
    p.set_defaults(func=cmd_setup)
    p = sub.add_parser("sync", help="push the compiled reports into the three documents")
    p.add_argument("--mode", choices=["interim", "final"], default="interim")
    p.set_defaults(func=cmd_sync)
    p = sub.add_parser("status", help="show receipt, URLs, and staleness")
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("doctor", help="diagnose the gws installation and authentication")
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except GDocsError as exc:
        print(f"google docs error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
