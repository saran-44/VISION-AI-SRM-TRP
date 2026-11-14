#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Read-only local audit for VISION AI - SRM TRP.
#
#   bash scripts/audit_local.sh              # fast checks
#   bash scripts/audit_local.sh --with-tests # also run the pytest suite
#
# Nothing here writes to the repository, the database or the network. It only
# reads files and prints a report you can paste into a chat or an issue.
# It never prints the contents of .env or any secret value.
# ---------------------------------------------------------------------------
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
ROOT="$PWD"
WITH_TESTS=0
[ "${1:-}" = "--with-tests" ] && WITH_TESTS=1

# Prefer the project virtualenv. On Windows Git Bash that is
# .venv/Scripts/python.exe; running the system interpreter by mistake is the
# usual reason "pytest failed" shows up in an otherwise healthy tree.
PY="python"
if [ -x ".venv/Scripts/python.exe" ]; then PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"
elif [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/Scripts/python.exe" ]; then PY="$VIRTUAL_ENV/Scripts/python.exe"
elif [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then PY="$VIRTUAL_ENV/bin/python"
fi
PY_OK=0
if "$PY" -c "import sys" >/dev/null 2>&1; then PY_OK=1; fi

section() { printf '\n===== %s =====\n' "$1"; }
ok()      { printf '  [ok]   %s\n' "$1"; }
warn()    { printf '  [warn] %s\n' "$1"; }
fail()    { printf '  [FAIL] %s\n' "$1"; }

section "1. Environment"
printf '  repo      : %s\n' "$ROOT"
printf '  date      : %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
printf '  python    : %s  (%s)\n' "$("$PY" --version 2>&1 | head -1)" "$PY"
printf '  node      : %s\n' "$(node --version 2>/dev/null || echo 'not installed')"
NODE_MAJOR=$(node --version 2>/dev/null | sed 's/^v//' | cut -d. -f1)
case "${NODE_MAJOR:-0}" in
  2[4-9]|3[0-9]) warn "Node ${NODE_MAJOR} breaks firebase-tools under MSYS path mangling; use Node LTS 22 for 'firebase deploy'" ;;
esac
printf '  git       : %s\n' "$(git --version)"

section "2. Git state"
printf '  branch    : %s\n' "$(git rev-parse --abbrev-ref HEAD)"
printf '  commit    : %s\n' "$(git rev-parse --short HEAD)"
printf '  tracking  : %s\n' "$(git status -sb | head -1)"
if [ -n "$(git status --porcelain)" ]; then
  warn "uncommitted changes:"; git status --porcelain | head -20
else
  ok "working tree clean"
fi

section "3. Ignored-but-present local files (never committed)"
for f in .env .env.local; do
  if [ -f "$f" ]; then
    if git check-ignore -q "$f"; then ok "$f exists and is ignored"; else fail "$f exists and is NOT ignored"; fi
    printf '         permissions: %s\n' "$(stat -c '%a %U' "$f" 2>/dev/null || stat -f '%Lp %Su' "$f" 2>/dev/null)"
  else
    printf '  [--]   %s not present\n' "$f"
  fi
done
if git ls-files --error-unmatch .env >/dev/null 2>&1; then fail ".env is TRACKED in git"; else ok ".env is not tracked"; fi

section "4. Secret scan (tracked files only)"
if "$PY" scripts/scan_secrets.py; then ok "built-in scanner found nothing"; else fail "built-in scanner reported a problem"; fi

section "5. Tracked data files that should stay out of git"
data_files=$(git ls-files | grep -Ei '\.(csv|xlsx|xls|pdf|mp4|mov|avi|mkv|webm|jpe?g|gif|heic|pt|onnx|pem|key|p12|dump)$' \
  | grep -vE '^frontend/assets/(logo-emblem|logo-wordmark|favicon)\.png$' || true)
if [ -z "$data_files" ]; then
  ok "no data, media or key files tracked"
else
  printf '%s\n' "$data_files" | sed 's/^/  [review] /'
  warn "each line above must be deliberate (best.pt is the shipped model; branding PNGs are allowed)"
fi

section "6. Route authentication coverage"
"$PY" - "$ROOT" <<'PY'
import re, sys, pathlib
root = pathlib.Path(sys.argv[1])
src = (root / "backend" / "app.py").read_text().splitlines()
guards = ("@require_roles", "@require_page_roles", "@require_device_key")
# Public by design: the login surface, health probe and the public Firebase
# web configuration (identifiers only, no secrets).
public = {"/", "/login", "/api/health", "/api/auth/login", "/api/auth/config",
          "/api/auth/firebase", "/api/config/firebase",
          # Static files: HTML, CSS, JS modules and vendored libraries. They
          # contain no data; every page that shows data is guarded.
          "/assets/<path:filename>", "/js/<path:filename>", "/vendor/<path:filename>"}
rows, pending = [], None
for line in src:
    m = re.search(r'@app\.(get|post|put|patch|delete)\("([^"]+)"\)', line)
    if m:
        pending = (m.group(1).upper(), m.group(2))
        continue
    if pending and line.strip().startswith(guards):
        rows.append((pending[0], pending[1], "guarded"))
        pending = None
    elif pending and line.strip().startswith("def "):
        rows.append((pending[0], pending[1], "PUBLIC"))
        pending = None
unguarded = [r for r in rows if r[2] == "PUBLIC"]
for method, path, state in rows:
    if state == "PUBLIC":
        tag = "public (expected)" if path in public else "PUBLIC (UNEXPECTED)"
        print(f"  [{tag:18}] {method:6} {path}")
print(f"  total routes: {len(rows)} · guarded: {len(rows) - len(unguarded)} · public: {len(unguarded)}")
unexpected = [r for r in unguarded if r[1] not in public]
print("  RESULT:", "no unexpected public route" if not unexpected else f"{len(unexpected)} UNEXPECTED")
PY

section "7. Configuration hardening signals"
for key in LEGACY_PASSWORD_LOGIN_ENABLED DEMO_MODE ALLOW_LEGACY_LOGIN_IN_PRODUCTION; do
  value=$(grep -E "^$key=" .env 2>/dev/null | cut -d= -f2- | tr -d '"')
  printf '  %-38s %s\n' "$key" "$( [ -n "${value}" ] && echo "set (value hidden)" || echo 'not set in .env')"
done
printf '  %-38s %s\n' "render.yaml LEGACY_PASSWORD_LOGIN" "$(grep -A1 'LEGACY_PASSWORD_LOGIN_ENABLED' render.yaml | grep value | tr -d ' "')"
demo_keys=$(grep -cE '^[[:space:]]*-[[:space:]]*key:[[:space:]]*DEMO_MODE' render.yaml 2>/dev/null || true)
if [ "${demo_keys:-0}" = "0" ]; then
  printf '  %-38s %s\n' "render.yaml DEMO_MODE" "absent (correct; only a comment mentions it)"
else
  printf '  %-38s %s\n' "render.yaml DEMO_MODE" "$demo_keys KEY LINE(S) — remove them"
fi
if grep -qE '^[[:space:]]*DATABASE_URL=' .env 2>/dev/null; then
  printf '  %-38s %s\n' ".env DATABASE_URL" "set (hidden) — the preview ignores it; it uses in-memory SQLite"
fi

section "8. Frontend and documentation checks"
if node scripts/check_frontend.mjs >/tmp/audit_frontend.txt 2>&1; then ok "$(tail -1 /tmp/audit_frontend.txt)"; else fail "frontend checks failed"; tail -5 /tmp/audit_frontend.txt; fi
if grep -rq "__SRM_DEVICE_KEY__" frontend/ 2>/dev/null; then fail "a device API key placeholder is shipped to the browser"; else ok "no device API key in frontend/"; fi
if grep -rq "transparenttextures.com" frontend/assets/*.css 2>/dev/null; then fail "remote texture reference (CSP/offline)"; else ok "no remote texture references in CSS"; fi

section "9. Dependency audit (optional)"
if "$PY" -m pip_audit --version >/dev/null 2>&1; then
  "$PY" -m pip_audit -r backend/requirements.txt 2>&1 | tail -15
else
  warn "pip-audit not installed — run: $PY -m pip install pip-audit && $PY -m pip_audit -r backend/requirements.txt"
fi

if [ "$WITH_TESTS" = "1" ]; then
  section "10. Test suite"
  if [ "$PY_OK" != "1" ]; then
    warn "no usable Python interpreter found; activate the virtualenv and re-run"
  elif ! "$PY" -m pytest --version >/dev/null 2>&1; then
    warn "pytest is not installed in $PY — this is an environment gap, not a code failure"
    printf '         fix: %s -m pip install -r backend/requirements.txt\n' "$PY"
    printf '         or : source .venv/Scripts/activate   (Git Bash, Windows)\n'
  else
    if "$PY" -m pytest -o addopts="" -q 2>&1 | tail -3; then ok "pytest finished"; else fail "pytest failed"; fi
  fi
fi

section "Done"
printf '  Paste this whole output when asking for a review.\n'
printf '  No writes were made, no secrets were printed.\n'
