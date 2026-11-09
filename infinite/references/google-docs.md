# Google Docs deliverables — the user's own Google API

The fixed prompt requires the research output to live in **Google Documents**,
not only local Markdown:

| Document | Local source (generated) | Google Doc title |
| --- | --- | --- |
| FOR | `research/book-of-mormon-for.md` | Book of Mormon Evidence — FOR |
| AGAINST | `research/book-of-mormon-against.md` | Book of Mormon Evidence — AGAINST |
| COMPARISON (both against each other) | `research/book-of-mormon-comparison.md` | Book of Mormon Evidence — FOR vs AGAINST (Comparison) |

`scripts/google_docs.py` (Python 3 standard library) creates the three documents
with the user's credentials and mirrors the compiled reports into them after
every `compile`. **Final validation is coded to fail** until all three Google
Docs are synced at the final ledger digest in `final` mode — so the run cannot
finish on local files alone.

## Where to create the Google API (the user does this once)

All steps happen in the Google Cloud Console:

1. **Create (or pick) a project:**
   <https://console.cloud.google.com/projectcreate>
2. **Enable the Google Docs API:**
   <https://console.cloud.google.com/apis/library/docs.googleapis.com>
3. **Enable the Google Drive API** (used to share/verify the documents):
   <https://console.cloud.google.com/apis/library/drive.googleapis.com>
4. **Create credentials:**
   <https://console.cloud.google.com/apis/credentials>
5. OAuth consent screen (only for the OAuth option, step 2 below):
   <https://console.cloud.google.com/apis/credentials/consent>

Two credential types work. Pick **one**.

### Option A — OAuth refresh token (recommended; pure standard library)

1. In *APIs & Services → OAuth consent screen*, configure the app (External is
   fine) and add your Google account under **Test users**.
2. In *APIs & Services → Credentials → Create credentials*, choose
   **OAuth client ID → Desktop app**. Copy the client ID and client secret.
3. Get a refresh token without writing any code — use the OAuth 2.0 Playground:
   <https://developers.google.com/oauthplayground>
   - Click the gear ⚙ → check **Use your own OAuth credentials** → paste the
     client ID/secret.
   - In step 1, request these scopes:
     `https://www.googleapis.com/auth/documents` and
     `https://www.googleapis.com/auth/drive`
   - Authorize, then in step 2 click **Exchange authorization code for tokens**
     and copy the **refresh token**.
4. Save the credentials where the helper finds them (project workspace):

   ```json
   // .infinite/gdocs-oauth.json
   {
     "client_id": "....apps.googleusercontent.com",
     "client_secret": "...",
     "refresh_token": "1//..."
   }
   ```

   Or point `INFINITE_GDOCS_OAUTH_FILE` at the file. `.infinite/` is gitignored —
   credentials never enter the repository.

### Option B — Service account key

1. In *Credentials → Create credentials*, choose **Service account**; then open
   the service account → **Keys → Add key → Create new key → JSON**. Download it.
2. Save it as `.infinite/gdocs-sa.json` in the workspace (or set
   `INFINITE_GDOCS_SA_FILE` / `GOOGLE_APPLICATION_CREDENTIALS`).
3. RS256 JWT signing needs one package: `pip install cryptography`.
4. Because documents are owned by the service account, run setup with
   `--share your@gmail.com` so you can see them:

   ```bash
   python3 scripts/google_docs.py --dir . setup --share your@gmail.com
   ```

## Commands

```bash
G="python3 infinite/scripts/google_docs.py --dir ."   # or .agents/skills/infinite/scripts after install

$G setup [--share EMAIL]   # validate credentials, create the three docs, write the receipt
$G sync                    # push compiled reports (interim; runs automatically after compile)
$G sync --mode final       # only after the user says stop (guard-enforced)
$G status                  # document URLs + staleness vs the ledger digest
$G token                   # diagnose credential resolution (prints no secrets)
```

The receipt `.infinite/gdocs.json` records the three document IDs/URLs and the
last sync (timestamp, mode, ledger SHA-256). It is written **only** by this
helper; the PreToolUse hook blocks the agent from hand-editing the receipt, the
credential files, or this helper.

## Enforcement summary (code, not prose)

- `infinite_research.py compile` auto-syncs all three docs when credentials
  exist (best-effort for interim compiles).
- `infinite_research.py validate --final` — the same validator the Stop hook
  runs — **fails** while any of the three Google Docs is missing, stale (digest
  mismatch), or last synced in interim mode. The run cannot finish on local
  Markdown alone.
- The guard blocks `google_docs.py sync --mode final` before a real user stop.
- The user-only escape hatch: run validation with `INFINITE_GDOCS=off` from your
  own terminal, or `--disarm`. Hooks never set that variable, so the agent
  cannot use it to pass the Stop gate.

## Failure handling

- No credentials yet: interim compiles still produce the three local reports;
  the validator warns. Fix: complete setup above.
- Network/API failure during a final sync: `compile --final` reports the failure
  and final validation stays red until a retry succeeds. Record the blocker
  honestly; never claim a sync that did not happen.
- Quota/permission errors: check that BOTH APIs are enabled for the project that
  issued the credentials, and (OAuth) that your account is a test user.

## Security

- Credential files live under `.infinite/` (gitignored) and are user-owned; the
  agent is blocked from writing them.
- Never paste client secrets, refresh tokens, or private keys into chat, the
  ledger, reports, or commits.
- The documents contain research output only; the receipt contains IDs/URLs and
  sync metadata, no secrets.
