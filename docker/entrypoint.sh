#!/bin/sh
# Stable JWT secret per data dir: generated once, reused across container
# recreations (an explicit OW_JWT_SECRET always wins). Without this, every
# recreate would mint a fresh secret in the ephemeral backend/.env and all
# issued tokens would die with the old container.
set -e

if [ -z "$OW_JWT_SECRET" ]; then
  secret_file="$OW_DATA_DIR/jwt-secret"
  if [ ! -f "$secret_file" ]; then
    mkdir -p "$OW_DATA_DIR"
    (umask 077; head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$secret_file")
  fi
  OW_JWT_SECRET=$(cat "$secret_file")
  export OW_JWT_SECRET
fi

exec "$@"
