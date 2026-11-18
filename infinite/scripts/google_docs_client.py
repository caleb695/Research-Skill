#!/usr/bin/env python3
"""Google Docs client for the Infinite skill.

Standard library + optional google-api-python-client / google-auth runtime.
Supports viewing and editing Google Docs content while maintaining deterministic
enforcement and valid `.infinite/ledger.jsonl` records.

Commands:
  view  --doc-id ID  --url URL  [--side for|against] [--credentials PATH]
  edit  --doc-id ID  --url URL  --content TEXT  [--side for|against] [--kind KIND] [--credentials PATH]

Credential resolution order:
  1. --credentials PATH (file path or inline/base64 service-account JSON)
  2. GOOGLE_APPLICATION_CREDENTIALS (file path or inline/base64 JSON)
  3. GOOGLE_SERVICE_ACCOUNT_JSON / GOOGLE_CREDENTIALS_JSON (OpenHands Cloud secrets)
  4. <project>/.google/credentials.json (when .google/ is a directory)
  5. <project>/.google (when .google is a JSON file)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    GOOGLE_CLIENT_AVAILABLE = True
except ImportError:
    service_account = None  # type: ignore[assignment]
    build = None  # type: ignore[assignment]
    GOOGLE_CLIENT_AVAILABLE = False

SIDES = ("for", "against")
NOTE_KINDS = ("method-limit", "original-synthesis", "closing-analysis")
STOP_MARKER = Path(".openhands") / "guard" / "STOP_REQUESTED"
DOC_ID_RE = re.compile(r"/document/d/([A-Za-z0-9_-]+)")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def project_dir(explicit: str | None) -> Path:
    path = Path(explicit or os.environ.get("OPENHANDS_PROJECT_DIR") or ".").expanduser().resolve()
    return path.parent if path.name == ".infinite" else path


def ledger_path(project: Path) -> Path:
    return project / ".infinite" / "ledger.jsonl"


def read_state(project: Path) -> dict:
    path = project / ".infinite" / "state.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def stop_requested(project: Path) -> bool:
    if (project / STOP_MARKER).exists():
        return True
    return bool(read_state(project).get("stop_requested"))


def append_event(project: Path, event: str, **fields) -> None:
    path = ledger_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": now(), "event": event, **fields}, ensure_ascii=False) + "\n")
    _refresh_interim_reports_if_present(project)


def _refresh_interim_reports_if_present(project: Path) -> None:
    """Keep compiled interim report digests in sync if reports already exist."""
    for_report = project / "research" / "book-of-mormon-for.md"
    against_report = project / "research" / "book-of-mormon-against.md"
    if not (for_report.is_file() and against_report.is_file()):
        return
    if stop_requested(project):
        return
    try:
        text = for_report.read_text(encoding="utf-8")
    except OSError:
        return
    if "<!-- infinite-research-mode: interim -->" not in text:
        return
    try:
        scripts_dir = Path(__file__).resolve().parent
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import infinite_research

        infinite_research.compile_reports(project, final=False)
    except Exception:
        # Never mask the primary Google Docs result if state is not initialized yet.
        pass


def _parse_json_candidate(raw: str) -> dict | None:
    stripped = raw.strip()
    if not stripped:
        return None
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    try:
        decoded = base64.b64decode(stripped + "=" * (-len(stripped) % 4)).decode("utf-8")
        if decoded.lstrip().startswith("{"):
            parsed = json.loads(decoded)
            return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None
    return None


def _validate_service_account_dict(data: dict, source_label: str) -> dict:
    if not isinstance(data, dict) or not data.get("client_email") or not data.get("private_key"):
        raise ValueError(
            f"Invalid Google service-account credentials in {source_label}: "
            "expected JSON object with 'client_email' and 'private_key'."
        )
    return data


def get_credentials(path: str | None = None, project: Path | None = None) -> str:
    """Resolve a credentials file path or inline secret value.

    Priority:
    1. Explicit --credentials argument
    2. GOOGLE_APPLICATION_CREDENTIALS environment variable
    3. GOOGLE_SERVICE_ACCOUNT_JSON / GOOGLE_CREDENTIALS_JSON environment variables
    4. <project>/.google/credentials.json (when .google is a directory)
    5. <project>/.google (when .google is a file)
    """
    if path:
        return path
    for env_name in (
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        "GOOGLE_CREDENTIALS_JSON",
    ):
        env_val = os.environ.get(env_name, "").strip()
        if env_val:
            return env_val
    proj = project or project_dir(None)
    dot_google = proj / ".google"
    if dot_google.is_dir():
        cred_file = dot_google / "credentials.json"
        if cred_file.is_file():
            return str(cred_file)
    elif dot_google.is_file():
        return str(dot_google)
    raise FileNotFoundError(
        "Google credentials not found. Provide --credentials, set "
        "GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_JSON, or place "
        "service-account JSON in .google/credentials.json (or .google)."
    )


def load_credentials_info(path: str | None = None, project: Path | None = None) -> dict:
    """Load and validate Google service-account credentials as a dict."""
    raw = get_credentials(path, project=project)
    inline = _parse_json_candidate(raw)
    if inline is not None:
        return _validate_service_account_dict(inline, "environment/inline secret")
    cred_path = Path(raw).expanduser()
    if not cred_path.is_absolute() and project is not None and (project / cred_path).is_file():
        cred_path = project / cred_path
    if not cred_path.is_file():
        raise FileNotFoundError(f"Google credentials file not found: {cred_path}")
    try:
        data = json.loads(cred_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Google credentials file {cred_path} is not valid JSON: {exc}") from exc
    return _validate_service_account_dict(data, str(cred_path))


def build_service(credentials_source: str | dict | None = None, project: Path | None = None):
    """Build the Google Docs v1 API service."""
    if not GOOGLE_CLIENT_AVAILABLE:
        raise ImportError(
            "google-api-python-client and google-auth are required. "
            "Install with: pip install google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib"
        )
    scopes = ["https://www.googleapis.com/auth/documents"]
    info = (
        _validate_service_account_dict(credentials_source, "dict")
        if isinstance(credentials_source, dict)
        else load_credentials_info(credentials_source, project=project)
    )
    credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    return build("docs", "v1", credentials=credentials, cache_discovery=False)


def extract_document_text(document: dict) -> str:
    """Extract plain text from paragraphs, tables, and nested structural elements."""
    chunks: list[str] = []

    def walk(elements: list) -> None:
        for element in elements:
            if not isinstance(element, dict):
                continue
            if "paragraph" in element:
                para = element["paragraph"]
                line = "".join(
                    el.get("textRun", {}).get("content", "")
                    for el in para.get("elements", [])
                    if isinstance(el, dict)
                )
                if line:
                    chunks.append(line.rstrip("\n"))
            elif "table" in element:
                for row in element["table"].get("tableRows", []):
                    cell_texts: list[str] = []
                    for cell in row.get("tableCells", []):
                        sub_chunks: list[str] = []
                        for sub in cell.get("content", []):
                            if "paragraph" in sub:
                                txt = "".join(
                                    el.get("textRun", {}).get("content", "")
                                    for el in sub["paragraph"].get("elements", [])
                                    if isinstance(el, dict)
                                ).strip()
                                if txt:
                                    sub_chunks.append(txt)
                        cell_texts.append(" ".join(sub_chunks))
                    if any(cell_texts):
                        chunks.append(" | ".join(cell_texts))
            elif "tableOfContents" in element:
                walk(element["tableOfContents"].get("content", []))

    walk(document.get("body", {}).get("content", []))
    return "\n".join(chunks)


def resolve_doc_target(doc_id: str | None, url: str | None) -> tuple[str, str]:
    resolved_id = (doc_id or "").strip()
    resolved_url = (url or "").strip()
    if not resolved_id and resolved_url:
        match = DOC_ID_RE.search(resolved_url)
        if match:
            resolved_id = match.group(1)
    if resolved_id and not resolved_url:
        resolved_url = f"https://docs.google.com/document/d/{resolved_id}/edit"
    if not resolved_id or not resolved_url:
        raise ValueError("Both --doc-id and --url (or a standard Google Docs URL containing /document/d/<ID>) are required.")
    return resolved_id, resolved_url


def resolve_side(project: Path, explicit_side: str | None) -> tuple[str, int]:
    state = read_state(project)
    side = explicit_side if explicit_side in SIDES else str(state.get("next_side") or "for")
    if side not in SIDES:
        side = "for"
    round_num = int(state.get("round", 0)) + 1
    return side, round_num


def cmd_view(args) -> int:
    project = project_dir(getattr(args, "dir", None))
    if stop_requested(project):
        print(
            "Blocked: research is stopped (STOP_REQUESTED). Do not view new sources; "
            "reconcile the existing ledger and compile final reports.",
            file=sys.stderr,
        )
        return 1

    doc_id, url = resolve_doc_target(args.doc_id, args.url)
    side, round_num = resolve_side(project, getattr(args, "side", None))
    credentials_raw = get_credentials(getattr(args, "credentials", None), project=project)

    try:
        service = build_service(credentials_raw, project=project)
        document = service.documents().get(documentId=doc_id).execute()
        title = document.get("title", "Untitled")
        content = extract_document_text(document)

        append_event(
            project,
            "search",
            side=side,
            round=round_num,
            query=f"Google Doc view: {doc_id}",
            outcome="accepted",
            notes=f"Viewed Google Doc '{title}' (ID: {doc_id}, URL: {url}). Content length: {len(content)} characters.",
            urls=[url],
        )

        print(f"viewed Google Doc '{title}' (ID: {doc_id})")
        print(f"content length: {len(content)} characters")
        preview = content[:500]
        print(f"preview: {preview}{'...' if len(content) > 500 else ''}")
        return 0
    except Exception as exc:
        print(f"error viewing Google Doc: {exc}", file=sys.stderr)
        append_event(
            project,
            "search",
            side=side,
            round=round_num,
            query=f"Google Doc view: {doc_id}",
            outcome="blocked",
            notes=f"Failed to view Google Doc (ID: {doc_id}, URL: {url}): {exc}",
            urls=[url],
        )
        return 1


def cmd_edit(args) -> int:
    project = project_dir(getattr(args, "dir", None))
    if stop_requested(project):
        print(
            "Blocked: research is stopped (STOP_REQUESTED). Google Doc edits are "
            "not permitted after user stop; compile and validate final local reports.",
            file=sys.stderr,
        )
        return 1

    doc_id, url = resolve_doc_target(args.doc_id, args.url)
    side, _ = resolve_side(project, getattr(args, "side", None))
    note_kind = getattr(args, "kind", None) or "original-synthesis"
    if note_kind not in NOTE_KINDS:
        note_kind = "original-synthesis"
    credentials_raw = get_credentials(getattr(args, "credentials", None), project=project)

    try:
        service = build_service(credentials_raw, project=project)
        text_to_insert = args.content if args.content.endswith("\n") else args.content + "\n"
        requests = [
            {
                "insertText": {
                    "endOfSegmentLocation": {"segmentId": ""},
                    "text": text_to_insert,
                }
            }
        ]
        result = service.documents().batchUpdate(
            documentId=doc_id, body={"requests": requests}
        ).execute()

        snippet = args.content[:100].replace("\n", " ")
        append_event(
            project,
            "research_note",
            side=side,
            kind=note_kind,
            text=f"Edited Google Doc (ID: {doc_id}, URL: {url}). Added content: {snippet}{'...' if len(args.content) > 100 else ''}",
        )

        print(f"edited Google Doc (ID: {doc_id})")
        print(f"result: {result.get('replies', [])}")
        return 0
    except Exception as exc:
        print(f"error editing Google Doc: {exc}", file=sys.stderr)
        append_event(
            project,
            "research_note",
            side=side,
            kind="method-limit",
            text=f"Failed to edit Google Doc (ID: {doc_id}, URL: {url}): {exc}",
        )
        return 1


def register_subcommands(subparsers, *, include_common: argparse.ArgumentParser | None = None) -> None:
    """Register `view` and `edit` parsers (shared with `infinite_research.py google-docs`)."""
    parents = [include_common] if include_common is not None else []

    view = subparsers.add_parser("view", parents=parents, help="view a Google Doc and log in ledger")
    view.add_argument("--doc-id", default=None, help="Google Doc ID (optional if --url has /document/d/<ID>)")
    view.add_argument("--url", default=None, help="Google Doc URL (optional if --doc-id is provided)")
    view.add_argument("--side", choices=SIDES, default=None, help="research side (defaults to state.next_side)")
    view.add_argument("--credentials", default=argparse.SUPPRESS, help="path to Google service account JSON key")
    view.set_defaults(func=cmd_view)

    edit = subparsers.add_parser("edit", parents=parents, help="edit a Google Doc and log in ledger")
    edit.add_argument("--doc-id", default=None, help="Google Doc ID (optional if --url has /document/d/<ID>)")
    edit.add_argument("--url", default=None, help="Google Doc URL (optional if --doc-id is provided)")
    edit.add_argument("--content", required=True, help="content to append to the Google Doc")
    edit.add_argument("--side", choices=SIDES, default=None, help="research side (defaults to state.next_side)")
    edit.add_argument("--kind", choices=NOTE_KINDS, default="original-synthesis", help="research note kind")
    edit.add_argument("--credentials", default=argparse.SUPPRESS, help="path to Google service account JSON key")
    edit.set_defaults(func=cmd_edit)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", default=argparse.SUPPRESS, help="project workspace (default: current directory)")
    parser = argparse.ArgumentParser(description=__doc__, parents=[common])
    parser.add_argument("--credentials", default=None, help="path to Google service account JSON key")
    sub = parser.add_subparsers(dest="command", required=True)
    register_subcommands(sub, include_common=common)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "dir"):
        args.dir = None
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"google docs error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
