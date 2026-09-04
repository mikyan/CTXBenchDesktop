#!/usr/bin/env bash
set -euo pipefail

archive="${1:?Usage: images-import.sh <ctxbench-images.tar>}"
if [[ -f "$archive.sha256" ]]; then
  sha256sum --check "$archive.sha256"
fi
docker load --input "$archive"
echo "CTXBench images imported."
