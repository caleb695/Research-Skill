# Google Docs deliverables — via the Google Workspace CLI (`gws`)

The fixed prompt requires the research output to live in **Google Documents**,
not only local Markdown:

| Document | Local source (generated) | Google Doc title |
| --- | --- | --- |
| FOR | `research/book-of-mormon-for.md` | Book of Mormon Evidence — FOR |
| AGAINST | `research/book-of-mormon-against.md` | Book of Mormon Evidence — AGAINST |
| COMPARISON (both against each other) | `research/book-of-mormon-comparison.md` | Book of Mormon Evidence — FOR vs AGAINST (Comparison) |

`scripts/google_docs.py` has **two interchangeable transports** (Python
standard library only):

1. **Google Workspace CLI** ([github.com/googleworkspace/cli](https://github.com/googleworkspace/cli))
   when installed — the helper shells out to `gws docs documents
   create|get|batchUpdate` (and `gws drive permissions create` for sharing),
   and **`gws` owns all authentication** (encrypted store, OS keyring,
   service accounts).
2. **Direct REST fallback** — when `gws` is not on PATH, the helper calls the
   Google Docs + Drive REST APIs itself using user credentials
   (`client_id`/`client_secret`/`refresh_token`). Nothing to install; ideal for
   hosted sandboxes and **phone-only users** (see below).

`GDOCS_TRANSPORT=auto|gws|rest` forces a transport (default `auto`: gws when
installed, else REST). Either way the skill never displays or transmits
secrets; credential files are mode 0600, gitignored, and guard-protected.

**Final validation is coded to fail** until all three Google Docs are synced at
the final ledger digest in `final` mode (`.infinite/gdocs.json` receipt) — so
the run cannot finish on local files alone.

## Phone-only setup (no computer needed)

If you have no computer — only a phone/tablet — skip the CLI entirely. Google's
**device-code flow** lets the sandbox show a short code that you approve from
your phone's browser, and the built-in REST transport does the rest.

1. In your **phone browser**, open the Google Cloud Console
   (sign in with your Google account; it's free, no credit card):
   - Create a project: <https://console.cloud.google.com/projectcreate>
   - Enable the Google Docs API:
     <https://console.cloud.google.com/apis/library/docs.googleapis.com>
   - Enable the Google Drive API:
     <https://console.cloud.google.com/apis/library/drive.googleapis.com>
   - OAuth consent screen:
     <https://console.cloud.google.com/apis/credentials/consent> — App type
     **External** (testing mode is fine) and **add your own Google account as a
     Test user** (required, or the login is rejected).
   - Credentials: <https://console.cloud.google.com/apis/credentials> →
     **+ Create credentials → OAuth client ID → TVs and Limited Input devices**
     (device flow only works with this client type). Note the **Client ID** and
     **Client secret** shown on the page.
2. In OpenHands Cloud → **Settings → Secrets**, add two secrets:
   - `GOOGLE_WORKSPACE_CLI_CLIENT_ID` = the client ID
   - `GOOGLE_WORKSPACE_CLI_CLIENT_SECRET` = the client secret
   Then **start a new conversation** (secrets only reach conversations started
   after the save).
3. In the conversation, the agent runs:
   ```bash
   python3 infinite/scripts/google_docs.py --dir . login
   ```
   It prints a URL (`https://www.google.com/device`) and a code like
   `ABCD-EFGH`. Open that URL on your phone, enter the code, sign in, and
   approve. The sandbox receives a refresh token and saves it to
   `.infinite/gws-credentials.json` (mode 0600, gitignored, guard-protected).
4. Done — `setup`/`sync` now work with no CLI anywhere:
   ```bash
   python3 infinite/scripts/google_docs.py --dir . setup
   ```

If Google returns no refresh token (you approved this app before), revoke it at
<https://myaccount.google.com/permissions> and run `login` again.

## Setup with a computer (gws CLI)

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

### OpenHands Cloud (hosted sandbox, no browser)

Cloud sandboxes have no browser and don't come with `gws` — and with the
built-in REST transport, **they don't need it**. OpenHands Cloud exports
**Settings → Secrets** entries as environment variables in the agent runtime,
and the helper understands credential secrets directly, so nothing sensitive
passes through the agent's shell or the chat. Pick ONE of these two routes:

**Route 1 — no computer at all (device-code login).** Follow the
[Phone-only setup](#phone-only-setup-no-computer-needed) above: create a
'TVs and Limited Input devices' OAuth client from your phone browser, store
`GOOGLE_WORKSPACE_CLI_CLIENT_ID`/`_CLIENT_SECRET` as secrets, and have the
agent run `google_docs.py login` — you approve the printed code from your
phone. Credentials land in `.infinite/gws-credentials.json` and the REST
transport uses them.

**Route 2 — exported credentials secret** (if you have any machine with a
browser, a Cloud shell works too):

1. Install `gws` there, run `gws auth setup` + `gws auth login`, then
   `gws auth export --unmasked > gws-credentials.json`.
2. In OpenHands Cloud: **Settings → Secrets → Add a new secret** with
   - Name: `GOOGLE_WORKSPACE_CLI_CREDENTIALS_JSON` (or `GWS_CREDENTIALS_JSON`)
   - Value: the **entire contents** of `gws-credentials.json`
   Secrets are masked in the UI and never appear in the conversation. Start a
   **new conversation** after saving (secrets reach conversations started
   afterwards).
3. When `scripts/google_docs.py` runs (setup/sync/doctor, or the automatic
   post-compile mirror) it detects the secret env var, writes it to
   `.infinite/gws-credentials.json` (mode 0600, guard-protected against agent
   tampering), and uses it — via the REST transport, or via
   `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` for `gws` when installed.

Installing `gws` inside the sandbox is optional (only needed for
service-account keys or if you prefer the CLI):
`npm install -g @googleworkspace/cli` (Node 18+) or a release binary from
<https://github.com/googleworkspace/cli/releases>.

Notes: `GOOGLE_WORKSPACE_CLI_TOKEN` also works as a secret but holds a raw
access token that expires (~1 h), so prefer the refresh-token routes above.
Both transports need outbound HTTPS to `googleapis.com`, which Cloud sandboxes
have; `gws` additionally fetches Discovery documents (cached 24 h). In a
locked-down sandbox the user can run the sync from their own terminal against
the same workspace instead.

### 3. Create the three documents

```bash
python3 infinite/scripts/google_docs.py --dir . setup
# service-account or exported-credential setups: add --share your@gmail.com
```

`setup` verifies authentication (gws or credentials file), creates the three
Google Docs, and writes the receipt `.infinite/gdocs.json` with their IDs and
URLs.

## Commands

```bash
G="python3 infinite/scripts/google_docs.py --dir ."   # or .agents/skills/infinite/scripts after install

$G login [--timeout N]     # device-code OAuth: prints a URL + code to approve from your phone
$G setup [--share EMAIL]   # check auth, create the three docs, write the receipt
$G sync                    # push compiled reports (interim; runs automatically after compile)
$G sync --mode final       # only after the user says stop (guard-enforced)
$G status                  # document URLs + staleness vs the ledger digest
$G doctor                  # diagnose: gws binary, auth probe, chosen transport, receipt state
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

- No transport authenticated (no gws and no credentials): interim compiles
  still produce the three local reports; the validator warns with the login /
  install / secret instructions. Final validation stays red until setup
  succeeds.
- Network/API failure during a sync: on gws, exit codes are structured
  (2 = auth, 1 = API, 4 = discovery); on REST, HTTP statuses drive the same
  logic. Transient 429/5xx are retried with backoff on both. A failed final
  sync leaves validation red until a retry succeeds — record the blocker
  honestly; never claim a sync that did not happen.
- HTTP 401/403 on REST: the refresh token was revoked or the OAuth app is
  missing your account as a Test user — re-run `google_docs.py login` (or
  re-export credentials) and check
  <https://console.cloud.google.com/apis/credentials/consent>.
- Device login returns no refresh token: the app was approved before; revoke
  at <https://myaccount.google.com/permissions> and log in again.
- `gws`-specific: Discovery documents are fetched at runtime (cached 24 h), so
  `gws` needs access to `googleapis.com`; unverified OAuth apps cap at ~25
  scopes in testing mode — `gws auth login -s drive,docs`. Service-account
  keys work only via `gws` (JWT signing); the REST transport supports user
  credentials.

## Security

- Credentials are user-owned. Either `gws` manages them (encrypted store, OS
  keyring) or the helper stores them in `.infinite/gws-credentials.json`
  (mode 0600, gitignored, written only by `login`/secret materialization). No
  secrets live in this repository, the ledger, the reports, the receipt, or
  the chat: secrets arrive as OpenHands environment variables and are never
  echoed.
- The agent is blocked from `gws auth export`/`logout`/`reset`, from writing
  `~/.config/gws`, `.infinite/gdocs*.json`, or `.infinite/gws-credentials.json`,
  and from printing/copying/transmitting credential env vars or files
  (`echo $GOOGLE_WORKSPACE_CLI_CLIENT_SECRET`, `cat .infinite/gws-credentials.json`,
  and friends are denied).
- The device-code flow never exposes the client secret in chat; only the
  short-lived user code and verification URL are shown.
- The documents contain research output only; the receipt contains IDs/URLs and
  sync metadata, no secrets.
- `gws` is not an officially supported Google product; the REST fallback uses
  the same public Google Docs/Drive APIs. Both are user-chosen tools for these
  deliverables.
