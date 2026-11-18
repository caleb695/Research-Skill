#!/usr/bin/env bash
# OpenHands repository setup script (runs automatically in OpenHands Cloud sandboxes).
# Ensures hook/helper scripts are executable and best-effort installs optional
# Google Docs API Python packages across venv and PEP-668 system Python runtimes.

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd || pwd)"

chmod +x \
    "$REPO_ROOT"/.openhands/hooks/*.sh \
    "$REPO_ROOT"/.openhands/hooks/*.py \
    "$REPO_ROOT"/infinite/scripts/*.sh \
    "$REPO_ROOT"/infinite/scripts/*.py 2>/dev/null || true

if command -v python3 >/dev/null 2>&1; then
    if ! python3 -c "import googleapiclient, google.oauth2" >/dev/null 2>&1; then
        PKGS=(google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib)
        python3 -m pip install --quiet "${PKGS[@]}" >/dev/null 2>&1 \
            || python3 -m pip install --quiet --user --break-system-packages "${PKGS[@]}" >/dev/null 2>&1 \
            || python3 -m pip install --quiet --break-system-packages "${PKGS[@]}" >/dev/null 2>&1 \
            || true
    fi
fi

exit 0
