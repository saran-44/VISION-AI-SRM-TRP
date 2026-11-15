#!/bin/sh
# Entrypoint for platforms that inject $PORT and have no Secret Manager
# (Render, Railway, Koyeb, Hugging Face Spaces, a plain VM).
#
# The Supabase CA certificate is supplied base64-encoded in PGSSLROOTCERT_B64
# so it survives platforms that do not support mounted secret files. It is
# decoded into the container's writable temp directory at boot.
set -eu

if [ -n "${PGSSLROOTCERT_B64:-}" ]; then
  CERT_DIR=/tmp/srm-trp-certs
  mkdir -p "$CERT_DIR"
  printf '%s' "$PGSSLROOTCERT_B64" | base64 -d > "$CERT_DIR/supabase-ca.crt"
  chmod 600 "$CERT_DIR/supabase-ca.crt"
  # Apps using sslmode=verify-full read this path (see backend/config.py).
  export PGSSLROOTCERT="$CERT_DIR/supabase-ca.crt"
fi

# A single worker keeps memory inside a 512 MB free instance; threads carry the
# concurrent SSE, scan and export requests. `/api/stream` bounds its own
# lifetime (API_SSE_SECONDS, default 210 s) so a thread is never held by a tab
# that was closed — with 4 threads, four left-open dashboards used to hang the
# whole service.
#
# --max-requests recycles the worker periodically: a free instance runs for days
# without a restart, and this is the cheapest bound on slow memory growth.
exec gunicorn \
  --bind "0.0.0.0:${PORT:-10000}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --threads "${GUNICORN_THREADS:-8}" \
  --timeout 180 \
  --graceful-timeout 30 \
  --max-requests 800 \
  --max-requests-jitter 80 \
  --access-logfile - \
  --error-logfile - \
  "backend.app:create_app()"
