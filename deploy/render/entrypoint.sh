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
# concurrent SSE and export requests. Raise --workers if the plan allows it.
exec gunicorn \
  --bind "0.0.0.0:${PORT:-10000}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout 180 \
  --access-logfile - \
  "backend.app:create_app()"
