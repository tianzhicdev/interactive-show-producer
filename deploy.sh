#!/usr/bin/env bash
set -euo pipefail
BASEDIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASEDIR/workers"
pnpm wrangler deploy --env production
cd "$BASEDIR/web"
pnpm run build
pnpm wrangler deploy --env production
