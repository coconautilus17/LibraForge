#!/bin/bash
# Run beets-audible over the --itunes mock (bo_mock.py), split across parallel imports.
#
# usage: dev/benchmark/beets_run.sh <books.json> <tag> [shards]
#   books.json   a file in dev/benchmark/data (from collect.py)
#   tag          output name: data/<tag>.jsonl and data/<tag>.time (total runtime)
#
# Each shard is its own python:3.12-slim container with its own beets database
# (data/<tag>_shard<N>.db), importing with -q -C -W: quiet, nothing copied or
# written. beets matches one book at a time, so shards are what make a full
# library finish in hours. The mock must be at data/beets_books.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
books="$1"; tag="$2"; shards="${3:-4}"
data="$here/data"

python3 - "$data/$books" "$data/$tag" "$shards" <<'EOF'
import json, sys
books, prefix, shards = json.load(open(sys.argv[1])), sys.argv[2], int(sys.argv[3])
for i in range(shards):
    open(f"{prefix}_shard{i}.txt", "w").write("".join(b["folder"] + "\n" for b in books[i::shards]))
EOF

start=$(date +%s)
for i in $(seq 0 $((shards - 1))); do
  mkdir -p "$data/${tag}_beetsdir$i"
  sed "s#/tmp/beets.db#/bench/data/${tag}_shard$i.db#; s#/bench/data/beets_import.log#/bench/data/${tag}_shard$i.log#" \
    "$here/beets/config.yaml" > "$data/${tag}_beetsdir$i/config.yaml"
  docker rm -f "beets-bench-$i" >/dev/null 2>&1 || true
  docker run -d --name "beets-bench-$i" --network "${BENCH_NETWORK:-homelab-proxy}" \
    -e BEETSDIR="/bench/data/${tag}_beetsdir$i" -e BENCH_BOOKS="/bench/data/$books" \
    -v "$here:/bench" -v "$data/beets_books:/audiobooks:ro" python:3.12-slim \
    sh -c "pip install -q beets beets-audible >/dev/null 2>&1; cd /audiobooks && tr '\n' '\0' < /bench/data/${tag}_shard$i.txt | xargs -0 -n 50 beet import -q -C -W > /bench/data/${tag}_shard$i.out 2>&1" >/dev/null
done
for i in $(seq 0 $((shards - 1))); do docker wait "beets-bench-$i" >/dev/null; docker rm "beets-bench-$i" >/dev/null; done
took=$(( $(date +%s) - start ))
echo "$took" > "$data/$tag.time"  # total runtime in seconds (pip install included), read by score.py

python3 "$here/beets_rows.py" "$data/$books" "$data/$tag.jsonl" $(for i in $(seq 0 $((shards - 1))); do echo "$data/${tag}_shard$i.db"; done)
echo "$tag: $(( took / 60 )) min"
