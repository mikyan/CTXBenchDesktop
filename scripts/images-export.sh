#!/usr/bin/env bash
set -euo pipefail

destination="${1:-ctxbench-images-0.1.0.tar}"
docker compose -f docker/compose.yaml --profile build-only build
docker save \
  ctxbench/worker:0.1.0 \
  ctxbench/agent-pi:0.1.0 \
  ctxbench/egress-proxy:0.1.0 \
  ctxbench/official-harness:0.1.0 \
  --output "$destination"
sha256sum "$destination" >"$destination.sha256"
echo "Exported $destination and $destination.sha256"
