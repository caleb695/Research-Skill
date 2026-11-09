#!/usr/bin/env python3
"""Google Docs mirror for the Infinite skill's three research reports.

The fixed prompt requires the deliverables to be Google Documents: one FOR, one
AGAINST, and one head-to-head COMPARISON. This helper creates and syncs those
three documents with the USER's own Google API credentials. It is the only
writer of the sync receipt `.infinite/gdocs.json`, and `infinite_research.py
validate --final` refuses to pass until that receipt shows all three documents
synced at the current ledger digest in final mode.

Credentials (user-owned; the agent is blocked from writing them):
  1. OAuth refresh token (recommended, pure standard library):
     .infinite/gdocs-oauth.json  or  INFINITE_GDOCS_OAUTH_FILE
     {"client_id": "...", "client_secret": "...", "refresh_token": "..."}
  2. Service account key JSON:
     .infinite/gdocs-sa.json  or  INFINITE_GDOCS_SA_FILE  or
     GOOGLE_APPLICATION_CREDENTIALS
     (requires `pip install cryptography` for RS256 JWT signing)

Setup walkthrough and the Google Cloud Console links: references/google-docs.md.

Commands:
  setup [--share EMAIL]   validate credentials, create the three docs, write receipt
  sync [--mode M]         push the compiled reports into the three docs (M=interim|final)
  status                  show receipt, document URLs, and staleness
  token                   diagnose credential resolution (prints no secrets)

Standard library only (service-account signing additionally needs `cryptography`).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
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
OAUTH_FILE_REL = Path(".infinite/gdocs-oauth.json")
SA_FILE_REL = Path(".infinite/gdocs-sa.json")
SCOPES = "https://www.googleapis.com/auth/documents https://www.googleapis.com/auth/drive"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DOCS_BASE = "https://docs.googleapis.com/v1/documents"
DRIVE_BASE = "https://www.googleapis.com/drive/v3/files"

MAX_INSERT_CHARS = 3500          # per insertText request
MAX_REQUESTS_PER_BATCH = 400     # per batchUpdate call
MAX_BATCH_BYTES = 300_000        # serialized payload safety margin
MAX_CELL_CHARS = 800             # table cell truncation guard
HTTP_TIMEOUT = 60
RETRY_STATUSES = {429, 500, 502, 503, 504}


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
# credentials and tokens
# --------------------------------------------------------------------------- #
def resolve_credentials(project: Path) -> tuple[str, dict] | None:
    """Return (kind, config) for the first usable credential source, or None."""
    oauth_env = os.environ.get("INFINITE_GDOCS_OAUTH_FILE")
    for candidate in ([Path(oauth_env).expanduser()] if oauth_env else []) + [project / OAUTH_FILE_REL]:
        if candidate.is_file():
            config = read_json(candidate, {})
            if config.get("client_id") and config.get("refresh_token"):
                return "oauth-refresh", config
    sa_env = os.environ.get("INFINITE_GDOCS_SA_FILE") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    for candidate in ([Path(sa_env).expanduser()] if sa_env else []) + [project / SA_FILE_REL]:
        if candidate.is_file():
            config = read_json(candidate, {})
            if config.get("client_email") and config.get("private_key"):
                return "service-account", config
    return None


def http_json(url: str, method: str = "GET", payload=None, token: str | None = None,
              form: dict | None = None, retries: int = 5):
    data = None
    headers = {"Accept": "application/json"}
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_error = ""
    for attempt in range(retries):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:800]
            last_error = f"HTTP {exc.code}: {body}"
            if exc.code not in RETRY_STATUSES or attempt == retries - 1:
                raise GDocsError(f"{method} {url} failed — {last_error}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            if attempt == retries - 1:
                raise GDocsError(f"{method} {url} failed — {last_error}") from exc
        time.sleep(min(2 ** attempt, 16))
    raise GDocsError(f"{method} {url} failed — {last_error}")


def oauth_refresh_token(config: dict) -> str:
    form = {
        "client_id": config["client_id"],
        "refresh_token": config["refresh_token"],
        "grant_type": "refresh_token",
    }
    if config.get("client_secret"):
        form["client_secret"] = config["client_secret"]
    try:
        response = http_json(TOKEN_URL, method="POST", form=form)
    except GDocsError as exc:
        raise GDocsError(
            f"OAuth refresh failed: {exc}. Check client_id/client_secret/refresh_token "
            "and that the Google Docs + Drive APIs are enabled for the project "
            "(https://console.cloud.google.com/apis/library/docs.googleapis.com)."
        ) from exc
    token = response.get("access_token")
    if not token:
        raise GDocsError("OAuth refresh response contained no access_token")
    return token


def service_account_token(config: dict) -> str:
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as exc:
        raise GDocsError(
            "service-account auth needs RS256 signing: run `pip install cryptography`, "
            "or use the OAuth refresh-token credentials instead (references/google-docs.md)"
        ) from exc

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    issued = int(time.time())
    header = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = b64(json.dumps({
        "iss": config["client_email"],
        "scope": SCOPES,
        "aud": config.get("token_uri", TOKEN_URL),
        "iat": issued,
        "exp": issued + 3600,
    }).encode())
    signing_input = f"{header}.{claims}".encode("ascii")
    key = serialization.load_pem_private_key(config["private_key"].encode(), password=None)
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    assertion = signing_input.decode("ascii") + "." + b64(signature)
    response = http_json(config.get("token_uri", TOKEN_URL), method="POST",
                         form={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                               "assertion": assertion})
    token = response.get("access_token")
    if not token:
        raise GDocsError("service-account token response contained no access_token")
    return token


def get_token(project: Path) -> tuple[str, str]:
    resolved = resolve_credentials(project)
    if resolved is None:
        raise GDocsError(
            "no Google credentials found. Create them (user-owned) at "
            "https://console.cloud.google.com/apis/credentials after enabling the Docs and Drive "
            "APIs, then place .infinite/gdocs-oauth.json or .infinite/gdocs-sa.json — full "
            "walkthrough in references/google-docs.md"
        )
    kind, config = resolved
    token = oauth_refresh_token(config) if kind == "oauth-refresh" else service_account_token(config)
    return kind, token


# --------------------------------------------------------------------------- #
# markdown -> Google Docs conversion
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


class Batcher:
    """Accumulates Docs requests and flushes them in size-bounded batchUpdates."""

    def __init__(self, document_id: str, token: str):
        self.document_id = document_id
        self.token = token
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
        http_json(f"{DOCS_BASE}/{self.document_id}:batchUpdate", method="POST",
                  payload={"requests": batch}, token=self.token)


def sync_document(document_id: str, token: str, markdown: str, title: str) -> None:
    """Replace the document's content with the rendered markdown report."""
    document = http_json(f"{DOCS_BASE}/{document_id}", token=token)
    end = document_end_index(document)
    batcher = Batcher(document_id, token)
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
            http_json(f"{DOCS_BASE}/{document_id}:batchUpdate", method="POST", token=token,
                      payload={"requests": [{"insertTable": {
                          "location": {"index": cursor}, "rows": len(rows), "columns": len(rows[0])}}]})
            document = http_json(f"{DOCS_BASE}/{document_id}", token=token)
            table = find_table_at(document, cursor)
            if table is None:
                raise GDocsError(f"could not locate inserted table at index {cursor}")
            cells: list[tuple[int, str, bool]] = []
            for row_index, row in enumerate(table.get("table", {}).get("tableRows", [])):
                for cell in row.get("tableCells", []):
                    content = cell.get("content") or [{}]
                    start = int(content[0].get("startIndex", cursor))
                    cells.append((start, "", row_index == 0))
            flat = [c for row in rows for c in row]
            if len(flat) != len(cells):
                flat = (flat + [""] * len(cells))[:len(cells)]
            cell_requests: list[dict] = []
            inserted = 0
            for (start, _unused, header), text in reversed(list(zip(cells, flat))):
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
                chunk = cell_requests[chunk_start:chunk_start + MAX_REQUESTS_PER_BATCH]
                http_json(f"{DOCS_BASE}/{document_id}:batchUpdate", method="POST",
                          payload={"requests": chunk}, token=token)
            table_element_end = int(table.get("endIndex", cursor + 1))
            cursor = table_element_end + inserted
    batcher.flush()
    http_json(f"{DOCS_BASE}/{document_id}:batchUpdate", method="POST", token=token,
              payload={"requests": [{"updateDocumentProperties": {
                  "properties": {"title": title}, "fields": "title"}}]})


# --------------------------------------------------------------------------- #
# receipt, setup, sync
# --------------------------------------------------------------------------- #
def receipt_path(project: Path) -> Path:
    return project / RECEIPT_REL


def create_missing_documents(project: Path, token: str, receipt: dict) -> dict:
    documents = receipt.get("documents") if isinstance(receipt.get("documents"), dict) else {}
    for name in DOC_NAMES:
        entry = documents.get(name) if isinstance(documents.get(name), dict) else {}
        if entry.get("id"):
            continue
        created = http_json(DOCS_BASE, method="POST", payload={"title": TITLES[name]}, token=token)
        document_id = created.get("documentId")
        if not document_id:
            raise GDocsError(f"documents.create for '{name}' returned no documentId")
        entry = {"id": document_id, "title": TITLES[name],
                 "url": f"https://docs.google.com/document/d/{document_id}/edit"}
        documents[name] = entry
    receipt["documents"] = documents
    write_json(receipt_path(project), receipt)
    return receipt


def share_documents(receipt: dict, token: str, email: str) -> None:
    for name in DOC_NAMES:
        entry = receipt.get("documents", {}).get(name, {})
        if not entry.get("id"):
            continue
        http_json(f"{DRIVE_BASE}/{entry['id']}/permissions?sendNotificationEmail=false",
                  method="POST", token=token,
                  payload={"role": "writer", "type": "user", "emailAddress": email})


def sync_all(project: Path, mode: str) -> dict:
    """Sync the three compiled reports to Google Docs and update the receipt."""
    kind, token = get_token(project)
    receipt = read_json(receipt_path(project), {})
    receipt = create_missing_documents(project, token, receipt)
    for name in DOC_NAMES:
        report = project / REPORT_PATHS[name]
        if not report.is_file():
            raise GDocsError(f"report {report} is missing; run infinite_research.py compile first")
        sync_document(receipt["documents"][name]["id"], token,
                      report.read_text(encoding="utf-8"), TITLES[name])
    receipt["auth"] = kind
    receipt["last_sync"] = {"ts": now(), "mode": mode, "digest": ledger_digest(project),
                            "documents_synced": list(DOC_NAMES)}
    write_json(receipt_path(project), receipt)
    return receipt


def maybe_sync(project: Path, mode: str = "interim") -> tuple[str, str]:
    """Best-effort entry point used by infinite_research.py compile.

    Returns (status, message) with status in {"synced", "skipped", "failed"};
    never raises, so a missing credential or network failure cannot break the
    local compile. Final enforcement lives in validate --final, which requires
    a current final-mode receipt.
    """
    project = Path(project)
    if resolve_credentials(project) is None:
        return "skipped", ("no Google credentials found (.infinite/gdocs-oauth.json, "
                           ".infinite/gdocs-sa.json, INFINITE_GDOCS_OAUTH_FILE, "
                           "INFINITE_GDOCS_SA_FILE, or GOOGLE_APPLICATION_CREDENTIALS); "
                           "see references/google-docs.md")
    try:
        receipt = sync_all(project, mode)
    except GDocsError as exc:
        return "failed", str(exc)
    except (OSError, ValueError) as exc:
        return "failed", f"unexpected error: {exc}"
    urls = ", ".join(receipt.get("documents", {}).get(name, {}).get("url", "?") for name in DOC_NAMES)
    return "synced", f"all three Google Docs updated ({mode} mode): {urls}"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def cmd_setup(args) -> int:
    project = project_dir(args.dir)
    kind, token = get_token(project)
    receipt = create_missing_documents(project, token, read_json(receipt_path(project), {}))
    if args.share:
        share_documents(receipt, token, args.share)
        print(f"shared all three documents with {args.share} (writer)")
    receipt["auth"] = kind
    receipt["setup_at"] = now()
    write_json(receipt_path(project), receipt)
    print(f"credentials: {kind}")
    for name in DOC_NAMES:
        entry = receipt["documents"][name]
        print(f"  {name:10s} {entry['url']}")
    print("next: python3 google_docs.py --dir . sync   (runs automatically after each compile when credentials exist)")
    return 0


def cmd_sync(args) -> int:
    project = project_dir(args.dir)
    mode = args.mode
    if mode == "final" and not (project / ".openhands/guard/STOP_REQUESTED").exists():
        # Mirrors the guard rule: a final sync only follows a real user stop.
        print("note: no user STOP_REQUESTED marker found; recording final mode anyway is blocked by the "
              "guard when hooks are installed. Use --mode final only after the user says stop.", file=sys.stderr)
    status, message = maybe_sync(project, mode)
    if status == "failed":
        print(f"google docs sync FAILED: {message}", file=sys.stderr)
        return 1
    print(f"google docs: {message}")
    if status == "skipped":
        return 1
    return 0


def cmd_status(args) -> int:
    project = project_dir(args.dir)
    receipt = read_json(receipt_path(project), {})
    if not receipt:
        print("no Google Docs receipt yet; run: python3 google_docs.py --dir . setup")
        print("(credentials walkthrough: references/google-docs.md)")
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


def cmd_token(args) -> int:
    project = project_dir(args.dir)
    resolved = resolve_credentials(project)
    if resolved is None:
        print("no credentials resolved; see references/google-docs.md")
        return 1
    kind, _config = resolved
    try:
        get_token(project)
    except GDocsError as exc:
        print(f"{kind}: token request failed — {exc}", file=sys.stderr)
        return 1
    print(f"{kind}: token OK (scopes: {SCOPES})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", help="project workspace (default: current directory)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("setup", help="validate credentials and create the three documents")
    p.add_argument("--share", metavar="EMAIL", help="share the documents with this Google account (writer)")
    p.set_defaults(func=cmd_setup)
    p = sub.add_parser("sync", help="push the compiled reports into the three documents")
    p.add_argument("--mode", choices=["interim", "final"], default="interim")
    p.set_defaults(func=cmd_sync)
    p = sub.add_parser("status", help="show receipt, URLs, and staleness")
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("token", help="diagnose credential resolution")
    p.set_defaults(func=cmd_token)
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
