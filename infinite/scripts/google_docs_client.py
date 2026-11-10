#!/usr/bin/env python3
"""Google Docs client for the Infinite skill.

Standard library + google-api-python-client. This helper supports viewing and
editing Google Docs content while maintaining deterministic enforcement.

Commands:
  view  --doc-id ID  --url URL  [--credentials PATH]
  edit  --doc-id ID  --url URL  --content TEXT  [--credentials PATH]

State is logged in <project>/.infinite/ledger.jsonl as a search or note event.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    GOOGLE_CLIENT_AVAILABLE = True
except ImportError:
    GOOGLE_CLIENT_AVAILABLE = False


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def project_dir(explicit: str | None) -> Path:
    path = Path(explicit or ".").expanduser().resolve()
    return path.parent if path.name == ".infinite" else path


def ledger_path(project: Path) -> Path:
    return project / ".infinite" / "ledger.jsonl"


def append_event(project: Path, event: str, **fields) -> None:
    path = ledger_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": now(), "event": event, **fields}, ensure_ascii=False) + "\n")


def get_credentials(path: str | None) -> str:
    """Resolve credentials path.

    Priority:
    1. Explicit path argument
    2. GOOGLE_APPLICATION_CREDENTIALS environment variable
    3. .google/credentials.json in the project directory
    """
    if path:
        return path
    env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if env_path:
        return env_path
    project = project_dir(None)
    default_path = project / ".google" / "credentials.json"
    if default_path.exists():
        return str(default_path)
    raise FileNotFoundError(
        "Google credentials not found. Provide --credentials, set "
        "GOOGLE_APPLICATION_CREDENTIALS, or place credentials in .google/credentials.json"
    )


def build_service(credentials_path: str):
    """Build the Google Docs service."""
    if not GOOGLE_CLIENT_AVAILABLE:
        raise ImportError(
            "google-api-python-client and google-auth are required. "
            "Install with: pip install google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib"
        )
    scopes = ["https://www.googleapis.com/auth/documents"]
    credentials = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=scopes
    )
    return build("docs", "v1", credentials=credentials)


def cmd_view(args) -> int:
    project = project_dir(args.dir)
    credentials_path = get_credentials(args.credentials)
    
    try:
        service = build_service(credentials_path)
        document = service.documents().get(documentId=args.doc_id).execute()
        title = document.get("title", "Untitled")
        content = "\n".join(
            [
                "".join([element.get("textRun", {}).get("content", "") for element in paragraph.get("elements", [])])
                for paragraph in document.get("body", {}).get("content", [])
                if "paragraph" in paragraph
            ]
        )
        
        # Log in ledger as a search event
        append_event(
            project,
            "search",
            side="for",  # Default to for; agent will categorize based on content
            round=0,  # Will be updated by state helper
            query=f"Google Doc view: {args.doc_id}",
            outcome="accepted",
            notes=f"Viewed Google Doc '{title}' (ID: {args.doc_id}, URL: {args.url}). Content length: {len(content)} characters.",
            url=[args.url],
        )
        
        print(f"viewed Google Doc '{title}' (ID: {args.doc_id})")
        print(f"content length: {len(content)} characters")
        # Print first 500 characters for verification
        print(f"preview: {content[:500]}...")
        return 0
        
    except Exception as e:
        print(f"error viewing Google Doc: {e}", file=sys.stderr)
        # Log failed search
        append_event(
            project,
            "search",
            side="for",
            round=0,
            query=f"Google Doc view: {args.doc_id}",
            outcome="blocked",
            notes=f"Failed to view Google Doc (ID: {args.doc_id}, URL: {args.url}): {str(e)}",
            url=[args.url],
        )
        return 1


def cmd_edit(args) -> int:
    project = project_dir(args.dir)
    credentials_path = get_credentials(args.credentials)
    
    try:
        service = build_service(credentials_path)
        
        # Create requests to insert content at the end
        requests = [
            {
                "insertText": {
                    "location": {
                        "index": 1,  # Insert at beginning (index 1, 0 is newline)
                    },
                    "text": args.content + "\n",
                }
            }
        ]
        
        result = service.documents().batchUpdate(
            documentId=args.doc_id, body={"requests": requests}
        ).execute()
        
        # Log in ledger as a note event
        append_event(
            project,
            "note",
            side="for",  # Default to for; agent will categorize based on content
            kind="original-synthesis",
            text=f"Edited Google Doc (ID: {args.doc_id}, URL: {args.url}). Added content: {args.content[:100]}...",
        )
        
        print(f"edited Google Doc (ID: {args.doc_id})")
        print(f"result: {result.get('replies', [])}")
        return 0
        
    except Exception as e:
        print(f"error editing Google Doc: {e}", file=sys.stderr)
        # Log failed note
        append_event(
            project,
            "note",
            side="for",
            kind="method-limit",
            text=f"Failed to edit Google Doc (ID: {args.doc_id}, URL: {args.url}): {str(e)}",
        )
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", help="project workspace (default: current directory)")
    parser.add_argument("--credentials", help="path to Google service account JSON key")
    sub = parser.add_subparsers(dest="command", required=True)
    
    view = sub.add_parser("view", help="view a Google Doc")
    view.add_argument("--doc-id", required=True, help="Google Doc ID")
    view.add_argument("--url", required=True, help="Google Doc URL")
    view.set_defaults(func=cmd_view)
    
    edit = sub.add_parser("edit", help="edit a Google Doc")
    edit.add_argument("--doc-id", required=True, help="Google Doc ID")
    edit.add_argument("--url", required=True, help="Google Doc URL")
    edit.add_argument("--content", required=True, help="Content to insert")
    edit.set_defaults(func=cmd_edit)
    
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"google docs error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
