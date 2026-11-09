#!/usr/bin/env python3
"""Google Docs mirror for the Infinite skill's three research reports.

The fixed prompt requires the deliverables to be Google Documents: one FOR, one
AGAINST, and one head-to-head COMPARISON. This helper creates and syncs those
three documents through the Google Workspace CLI (`gws`,
https://github.com/googleworkspace/cli), which the user installs and
authenticates once:

    npm install -g @googleworkspace/cli     # or brew install googleworkspace-cli
    gws auth setup                          # creates the Cloud project + OAuth client (needs gcloud)
    gws auth login                          # or: manual Console setup / exported credentials
    # headless: gws auth export --unmasked > credentials.json
    #           export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/path/to/credentials.json

`gws` owns all authentication (encrypted credential store, OS keyring, service
accounts, raw tokens); this helper never sees or stores secrets. It shells out
to `gws docs documents create|get|batchUpdate` (and `gws drive permissions
create` for sharing) and parses the CLI's structured JSON output.

It is the only writer of the sync receipt `.infinite/gdocs.json`, and
`infinite_research.py validate --final` refuses to pass until that receipt shows
all three documents synced at the current ledger digest in final mode — so the
run cannot finish on local Markdown alone.

Commands:
  setup [--share EMAIL]   check gws + auth, create the three docs, write receipt
  sync [--mode M]         push the compiled reports into the three docs (M=interim|final)
  status                  show receipt, document URLs, and staleness
  doctor                  diagnose gws installation and authentication

Standard library only; requires the `gws` binary on PATH (override: GWS_BIN).
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
    "use). Full walkthrough: references/google-docs.md"
)


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


def auth_probe() -> tuple[bool, str]:
    """Cheap, local check that gws exists and holds credentials for the user."""
    if os.environ.get("GOOGLE_WORKSPACE_CLI_TOKEN"):
        return True, "GOOGLE_WORKSPACE_CLI_TOKEN"
    creds_file = os.environ.get("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE")
    if creds_file and Path(creds_file).expanduser().is_file():
        return True, "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"
    binary = gws_bin()
    if binary is None:
        return False, f"gws CLI not found on PATH; {INSTALL_HINT}"
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


def sync_document(document_id: str, markdown: str, title: str) -> None:
    """Replace the document's content with the rendered markdown report."""
    docs = GwsDocs(document_id)
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


def create_missing_documents(project: Path, receipt: dict) -> dict:
    documents = receipt.get("documents") if isinstance(receipt.get("documents"), dict) else {}
    for name in DOC_NAMES:
        entry = documents.get(name) if isinstance(documents.get(name), dict) else {}
        if entry.get("id"):
            continue
        document_id = GwsDocs.create(TITLES[name])
        entry = {"id": document_id, "title": TITLES[name],
                 "url": f"https://docs.google.com/document/d/{document_id}/edit"}
        documents[name] = entry
    receipt["documents"] = documents
    write_json(receipt_path(project), receipt)
    return receipt


def share_documents(receipt: dict, email: str) -> None:
    for name in DOC_NAMES:
        entry = receipt.get("documents", {}).get(name, {})
        if not entry.get("id"):
            continue
        run_gws(["drive", "permissions", "create",
                 "--params", json.dumps({"fileId": entry["id"], "sendNotificationEmail": False}),
                 "--json", json.dumps({"role": "writer", "type": "user", "emailAddress": email})])


def sync_all(project: Path, mode: str) -> dict:
    """Sync the three compiled reports to Google Docs and update the receipt."""
    ok, detail = auth_probe()
    if not ok:
        raise GDocsError(detail)
    receipt = read_json(receipt_path(project), {})
    receipt = create_missing_documents(project, receipt)
    for name in DOC_NAMES:
        report = project / REPORT_PATHS[name]
        if not report.is_file():
            raise GDocsError(f"report {report} is missing; run infinite_research.py compile first")
        sync_document(receipt["documents"][name]["id"],
                      report.read_text(encoding="utf-8"), TITLES[name])
    receipt["auth"] = f"gws-cli:{detail}"
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
    ok, detail = auth_probe()
    if not ok:
        return "skipped", detail
    try:
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
def cmd_setup(args) -> int:
    project = project_dir(args.dir)
    ok, detail = auth_probe()
    if not ok:
        print(f"google docs setup blocked: {detail}", file=sys.stderr)
        return 1
    receipt = create_missing_documents(project, read_json(receipt_path(project), {}))
    if args.share:
        share_documents(receipt, args.share)
        print(f"shared all three documents with {args.share} (writer)")
    receipt["auth"] = f"gws-cli:{detail}"
    receipt["setup_at"] = now()
    write_json(receipt_path(project), receipt)
    print(f"gws authentication: {detail}")
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
    binary = gws_bin()
    print(f"gws binary  : {binary or 'NOT FOUND — ' + INSTALL_HINT}")
    if binary:
        try:
            proc = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30)
            print(f"gws version : {(proc.stdout or proc.stderr).strip()[:120] or 'unknown'}")
        except (OSError, subprocess.TimeoutExpired):
            print("gws version : (could not run --version)")
    ok, detail = auth_probe()
    print(f"auth probe  : {'OK' if ok else 'NOT AUTHENTICATED'} — {detail}")
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
    p = sub.add_parser("setup", help="check gws + auth, create the three documents")
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
