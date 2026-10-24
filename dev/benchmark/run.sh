#!/bin/bash
# Run the matcher from this checkout over a mock dataset.
#
# usage: dev/benchmark/run.sh <books.json> <tag> <audible|abs> [workers]
#   books.json   a file in dev/benchmark/data (from collect.py)
#   tag          output name: data/<tag>.jsonl and data/<tag>.log
#
# Environment:
#   LIBRAFORGE_IMAGE  image to run in (default libraforge-libraforge)
#   BENCH_NETWORK     docker network that reaches ABS / abs-agg (default homelab-proxy)
#   ABS_CONFIG        directory holding abs.json, for abs mode (default ./config)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
books="$1"; tag="$2"; provider="$3"; workers="${4:-4}"
config="$(cd "${ABS_CONFIG:-$repo/config}" && pwd)"

docker run --rm --name "bench-$tag" --network "${BENCH_NETWORK:-homelab-proxy}" \
  --entrypoint /opt/venv/bin/python \
  -v "$repo/app:/app/app:ro" -v "$repo/scripts:/app/scripts:ro" -v "$config:/app/config:ro" \
  -v "$here:/bench" -e REPORTS_DIR=/tmp/reports -w /app \
  "${LIBRAFORGE_IMAGE:-libraforge-libraforge}" \
  /bench/lf_bench.py "/bench/data/$books" "/bench/data/$tag.jsonl" "$provider" "$workers" \
  > "$here/data/$tag.log" 2>&1
echo "$tag: exit $? ($(wc -l < "$here/data/$tag.jsonl") books)"
