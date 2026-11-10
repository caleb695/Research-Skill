# Google Docs Integration for Infinite Skill

## Purpose
Enable the Infinite skill agent to edit and view Google Docs while maintaining deterministic enforcement of the fixed Book of Mormon research task.

## Integration Design
The integration is implemented as a helper module that the agent can call via the standard helper commands (`infinite_research.py` or `infinite_state.py`) or via a new `google_docs` sub-command that logs the Google Doc access in the ledger without bypassing enforcement.

## Implementation
1. **Google Docs API Client** (`infinite/scripts/google_docs_client.py`)
   - Uses `google-api-python-client` and `google-auth`
   - Reads credentials from a JSON key file specified by the user
   - Supports viewing and editing Google Docs content

2. **Integration with Research Helper** (`infinite/scripts/infinite_research.py`)
   - Adds `google-docs` sub-command for logging Google Doc access in the ledger
   - Supports `view` and `edit` operations
   - Records the Google Doc URL, operation, and verification in the ledger

3. **Enforcement Compatibility**
   - All Google Doc operations are logged in the append-only ledger
   - The integration respects the deterministic enforcement rules
   - Google Doc content is treated as a source and must be authenticated and contextualized

## Usage
1. **Provide Credentials**
   Place your Google Workspace service account JSON key in the workspace (e.g., `.google/credentials.json`) or specify the path in the environment variable `GOOGLE_APPLICATION_CREDENTIALS`.

2. **View a Google Doc**
   ```bash
   python3 infinite/scripts/infinite_research.py --dir . google-docs view --doc-id "DOC_ID" --url "https://docs.google.com/document/d/DOC_ID/edit"
   ```

3. **Edit a Google Doc**
   ```bash
   python3 infinite/scripts/infinite_research.py --dir . google-docs edit --doc-id "DOC_ID" --url "https://docs.google.com/document/d/DOC_ID/edit" --content "New content"
   ```

4. **Log in Ledger**
   The operation is automatically logged in `.infinite/ledger.jsonl` as a `search` or `note` event with the Google Doc URL and verification details.

## Where to Add Credentials
Add your Google Workspace service account JSON key to:
- `.google/credentials.json` (recommended, will be automatically picked up)
- Or set the environment variable `GOOGLE_APPLICATION_CREDENTIALS` to the path of your JSON key file

## Enforcement Notes
- The integration does not bypass the deterministic enforcement engine
- All Google Doc operations must be logged in the ledger
- The agent must still authenticate, contextualize, and score any evidence from Google Docs
- The integration respects the `STOP_REQUESTED` marker and will not perform edits after a stop

## Dependencies
- `google-api-python-client`
- `google-auth`
- `google-auth-httplib2`
- `google-auth-oauthlib`

Install dependencies:
```bash
pip install google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib
```

## Security
- Credentials are stored in the workspace and excluded from Git snapshots
- The integration only accesses Google Docs specified by the user
- All operations are logged in the append-only ledger
