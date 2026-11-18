# Google Docs Integration for Infinite Skill

## Purpose
Enable the Infinite skill agent to view and edit Google Docs while maintaining deterministic enforcement of the fixed Book of Mormon research task and valid `.infinite/ledger.jsonl` state.

## Integration Design
The integration is implemented in `infinite/scripts/google_docs_client.py` and exposed directly as a subcommand of `infinite/scripts/infinite_research.py` (`google-docs` / `google_docs`), so all Google Doc access is logged in the append-only ledger and keeps compiled interim report digests synchronized without bypassing enforcement.

## Implementation
1. **Google Docs API Client** (`infinite/scripts/google_docs_client.py`)
   - Uses `google-api-python-client` and `google-auth` when installed (auto-installed on OpenHands Cloud startup by `.openhands/setup.sh`)
   - Resolves service-account credentials from CLI flags, OpenHands Cloud Secrets / environment variables, `.google/credentials.json`, or a `.google` JSON file
   - Extracts text from both paragraphs and tables on `view`, and appends content at the end of the document body on `edit`

2. **Integration with Research Helper** (`infinite/scripts/infinite_research.py`)
   - Exposes `google-docs view` and `google-docs edit`
   - Logs `view` as a schema-valid `search` event (`urls`, `side`, `round`, `outcome`, `notes`) and `edit` as a schema-valid `research_note` event (`side`, `kind`, `text`)
   - Refreshes compiled interim reports if already initialized so `validate` never fails on stale report digests

3. **Enforcement Compatibility**
   - Protected by `PreToolUse` (`infinite_guard.py`): helper scripts cannot be hand-edited by the agent
   - Respects `.openhands/guard/STOP_REQUESTED`: both `PreToolUse` and `google_docs_client.py` block Google Doc edits and new views once the user says `stop`
   - Google Doc content is treated as an untrusted/candidate source until authenticated, contextualized, and scored like any other evidence

## Usage
1. **Provide Credentials**
   Supported credential sources (checked in order):
   - `--credentials /path/to/key.json`
   - `GOOGLE_APPLICATION_CREDENTIALS` (file path, inline JSON, or base64-encoded JSON)
   - `GOOGLE_SERVICE_ACCOUNT_JSON` or `GOOGLE_CREDENTIALS_JSON` (recommended for OpenHands Cloud Secrets: paste raw or base64 service-account JSON)
   - `.google/credentials.json` in the workspace
   - `.google` (service-account JSON file directly at workspace root)

2. **View a Google Doc**
   ```bash
   python3 infinite/scripts/infinite_research.py --dir . google-docs view \
     --doc-id "DOC_ID" \
     --url "https://docs.google.com/document/d/DOC_ID/edit"
   ```

3. **Edit a Google Doc**
   ```bash
   python3 infinite/scripts/infinite_research.py --dir . google-docs edit \
     --doc-id "DOC_ID" \
     --url "https://docs.google.com/document/d/DOC_ID/edit" \
     --content "New content"
   ```

## Dependencies
- `google-api-python-client`
- `google-auth`
- `google-auth-httplib2`
- `google-auth-oauthlib`

Install manually if needed outside `.openhands/setup.sh`:
```bash
pip install google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib
```

## Security
- `.google` and `.google/` are listed in `.gitignore` and `infinite/assets/project.gitignore.fragment` to prevent accidental credential commits in target workspaces; in OpenHands Cloud, prefer storing service-account JSON in Cloud Secrets (`GOOGLE_SERVICE_ACCOUNT_JSON`).
- Share target Google Docs explicitly with the service account's `client_email`.
