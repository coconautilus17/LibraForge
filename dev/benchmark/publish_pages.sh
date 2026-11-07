#!/bin/bash
# Rebuild the public comparison page and commit it to the gh-pages branch (GitHub Pages
# serves the branch as committed, no build). Push it yourself after looking at the page.
#
# usage: dev/benchmark/publish_pages.sh <books.json> <scores.json> <run-name> <run.jsonl> <commit>
#   the same inputs as report.py (files in dev/benchmark/data), run-name being the
#   LibraForge public catalog + Goodreads run; <commit> is the LibraForge commit it ran.
#
# Environment:
#   PAGES_DIR  worktree of the gh-pages branch (default ../pages next to this worktree), made with
#              git worktree add --orphan -b gh-pages <dir>   (first time; later: git worktree add <dir> gh-pages)
#   COMPARE    the --compare runs, space separated name=label (labels without spaces use _ for a space)
#   GEO        geo summary json (how many confirmed listings Audible's search hid from the runs)
#   AUDIT      audit_final.json from audit_check.py --write (default when it exists): score from the hand verdicts
#
# The page is built with --public: only the tags a matcher reads are listed.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
pages="${PAGES_DIR:-$(cd "$here/../../.." && pwd)/pages}"
books="$1"; scores="$2"; run_name="$3"; run="$4"; commit="$5"
compare="${COMPARE:-audiosilo=AudioSilo absqm=Audiobookshelf_Quick_Match bo=BookOrbit grimmory=Grimmory rmab=ReadMeABook beets=beets_(audible_plugin)}"

args=()
audit="${AUDIT:-audit_final.json}"
[ -f "$here/data/$audit" ] && args+=(--audit "$here/data/$audit")
[ -n "${GEO:-}" ] && [ -f "$here/data/$GEO" ] && args+=(--geo "$here/data/$GEO")
for spec in $compare; do label="${spec#*=}"; args+=(--compare "${spec%%=*}=${label//_/ }"); done
python3 "$here/report.py" "$here/data/$books" "$here/data/$scores" "$run_name" "$here/data/$run" "$pages/index.html" \
  --public --commit "$commit" \
  --provider "Audible public catalog (no login), US marketplace, Goodreads fallback" "${args[@]}"
touch "$pages/.nojekyll"  # serve the files as they are
git -C "$pages" add index.html .nojekyll
git -C "$pages" commit -q -m "Benchmark page: LibraForge $commit, $(date +%F)" && git -C "$pages" log --oneline -1
