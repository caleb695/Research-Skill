# Google Docs deliverables — via the Google Workspace CLI (`gws`)

The fixed prompt requires the research output to live in **Google Documents**,
not only local Markdown:

| Document | Local source (generated) | Google Doc title |
| --- | --- | --- |
| FOR | `research/book-of-mormon-for.md` | Book of Mormon Evidence — FOR |
| AGAINST | `research/book-of-mormon-against.md` | Book of Mormon Evidence — AGAINST |
| COMPARISON (both against each other) | `research/book-of-mormon-comparison.md` | Book of Mormon Evidence — FOR vs AGAINST (Comparison) |

All Google access goes through the **Google Workspace CLI**
([github.com/googleworkspace/cli](https://github.com/googleworkspace/cli)) —
one command-line tool for Drive, Docs, and the rest of Workspace, built for
humans and AI agents, with structured JSON output. `scripts/google_docs.py`
shells out to `gws docs documents create|get|batchUpdate` (and `gws drive
permissions create` for sharing); **`gws` owns all authentication** — the skill
never sees, stores, or handles tokens or client secrets itself.

**Final validation is coded to fail** until all three Google Docs are synced at
the final ledger digest in `final` mode (`.infinite/gdocs.json` receipt) — so
the run cannot finish on local files alone.

## Setup (the user does this once)

### 1. Install the CLI

```bash
npm install -g @googleworkspace/cli        # needs Node.js 18+
# or: brew install googleworkspace-cli     # macOS / Linux
# or: download a binary from https://github.com/googleworkspace/cli/releases
```

### 2. Authenticate

Fastest (with `gcloud` installed):

```bash
gws auth setup     # creates the Cloud project, enables the APIs, logs you in
gws auth login     # subsequent logins / scope changes
```

Manual Google Cloud Console route (no `gcloud`):

1. OAuth consent screen:
   `https://console.cloud.google.com/apis/credentials/consent` — App type
   **External** (testing mode is fine); **add yourself under Test users**.
2. Credentials: `https://console.cloud.google.com/apis/credentials` — create an
   **OAuth client ID → Desktop app**, download the client JSON to
   `~/.config/gws/client_secret.json`.
3. `gws auth login` and approve in the browser. If the app is unverified,
   choose individual services (`gws auth login -s drive,docs`) — the
   `recommended` preset exceeds the ~25-scope testing-mode limit.

Headless / CI (agent sandboxes without a browser):

```bash
# on a machine with a browser:
gws auth export --unmasked > credentials.json
# on the headless machine:
export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/path/to/credentials.json
```

Also supported by `gws`: a service-account key via the same
`GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE`, or a raw access token via
`GOOGLE_WORKSPACE_CLI_TOKEN` (e.g. `$(gcloud auth print-access-token)`).
Credentials from `gws auth login` are encrypted at rest (AES-256-GCM, key in
the OS keyring; `GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file` for headless).

### 3. Create the three documents

```bash
python3 infinite/scripts/google_docs.py --dir . setup
# service-account or exported-credential setups: add --share your@gmail.com
```

`setup` verifies authentication (`gws auth status`), creates the three Google
Docs, and writes the receipt `.infinite/gdocs.json` with their IDs and URLs.

## Commands

```bash
G="python3 infinite/scripts/google_docs.py --dir ."   # or .agents/skills/infinite/scripts after install

$G setup [--share EMAIL]   # check gws + auth, create the three docs, write the receipt
$G sync                    # push compiled reports (interim; runs automatically after compile)
$G sync --mode final       # only after the user says stop (guard-enforced)
$G status                  # document URLs + staleness vs the ledger digest
$G doctor                  # diagnose: gws binary, version, auth probe, receipt state
```

Useful `gws` commands directly (the CLI is general-purpose):

```bash
gws auth status                                  # local, no network: shows auth method/source
gws docs documents get --params '{"documentId": "ID"}'
gws docs +write --document ID --text 'appended plain text'
gws schema docs.documents.batchUpdate            # introspect any method
```

Optional: install the CLI's own agent skills for interactive Workspace work —
`npx skills add https://github.com/googleworkspace/cli/tree/main/skills/gws-docs`.

The receipt `.infinite/gdocs.json` records the three document IDs/URLs and the
last sync (timestamp, mode, ledger SHA-256). It is written **only** by this
helper; the PreToolUse hook blocks the agent from hand-editing the receipt or
this helper, from touching the `gws` credential store (`~/.config/gws`), from
running `gws auth export`/`logout`, and from a final-mode sync before a real
user stop.

## Enforcement summary (code, not prose)

- `infinite_research.py compile` auto-syncs all three docs through `gws`
  whenever it is installed and authenticated (best-effort for interim compiles).
- `infinite_research.py validate --final` — the same validator the Stop hook
  runs — **fails** while any of the three Google Docs is missing, stale (digest
  mismatch), or last synced in interim mode. The run cannot finish on local
  Markdown alone.
- The guard blocks `google_docs.py sync --mode final` before a real user stop
  and blocks agent-side tampering with `gws` credentials.
- The user-only escape hatch: run validation with `INFINITE_GDOCS=off` from your
  own terminal, or `--disarm`. Hooks never set that variable, so the agent
  cannot use it to pass the Stop gate.

## Failure handling

- `gws` not installed or not authenticated: interim compiles still produce the
  three local reports; the validator warns with install/auth instructions.
  Final validation stays red until setup succeeds.
- Network/API failure during a sync: `gws` exit codes are structured
  (2 = auth, 1 = API, 4 = discovery); transient 429/5xx are retried with
  backoff. A failed final sync leaves validation red until a retry succeeds —
  record the blocker honestly; never claim a sync that did not happen.
- Discovery documents are fetched at runtime (cached 24 h), so `gws` needs
  access to `googleapis.com`; in restricted sandboxes the user can run the sync
  from their own terminal against the same workspace.
- Scope/consent errors: unverified OAuth apps cap at ~25 scopes in testing
  mode — log in with `-s drive,docs` instead of the full preset, and confirm
  your account is a Test user.

## Security

- Authentication is entirely `gws`'s job: encrypted credential store or
  environment-provided credentials owned by the user. No secrets live in this
  repository, the ledger, the reports, or the receipt.
- The agent is blocked from `gws auth export`/`logout` and from writing
  `~/.config/gws` or `.infinite/gdocs*.json`.
- The documents contain research output only; the receipt contains IDs/URLs and
  sync metadata, no secrets.
- `gws` is not an officially supported Google product; it is the user-chosen
  tool for these deliverables.
