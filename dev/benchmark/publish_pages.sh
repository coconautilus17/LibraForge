#!/bin/bash
# Rebuild the public comparison page and its downloads, and commit them to the gh-pages branch
# (GitHub Pages serves the branch as committed, no build). Push it yourself after looking at the page.
#
# usage: dev/benchmark/publish_pages.sh [manifest.json]
#   everything comes from the manifest (bench_data.py): the dataset, every run, the final
#   audit (audit_check.py --write), the geo summary (geo.py summary) and the LibraForge build.
#
# The page and its downloads list only the tags a matcher reads (report.py --public):
#   index.html                  the page
#   benchmark-books.json        every book: its tags, the right answer, each tool's verdict, pick and result
#   benchmark-mock-files.tar.gz every book as one second of silence carrying those tags, at its folder path
#
# Environment:
#   PAGES_DIR  worktree of the gh-pages branch (default ../pages next to this worktree), made with
#              git worktree add --orphan -b gh-pages <dir>   (first time; later: git worktree add <dir> gh-pages)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
pages="${PAGES_DIR:-$(cd "$here/../../.." && pwd)/pages}"
manifest="${1:-manifest.json}"
books="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['books'])" "$here/data/$manifest")"
commit="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('commit',''))" "$here/data/$manifest")"

# The mock, rebuilt from scratch so it holds exactly this dataset.
mock="$here/data/public_mock"
rm -rf "$mock"
python3 "$here/bo_mock.py" "$here/data/$books" "$mock" --public
tar -C "$here/data" -cf - public_mock | gzip -9n > "$pages/benchmark-mock-files.tar.gz"

(cd "$here" && python3 report.py "$pages/index.html" --manifest "$manifest" --public \
  --mock-url benchmark-mock-files.tar.gz)
touch "$pages/.nojekyll"  # serve the files as they are
git -C "$pages" add index.html .nojekyll benchmark-books.json benchmark-mock-files.tar.gz
git -C "$pages" commit -q -m "Benchmark page: LibraForge $commit, $(date +%F)" && git -C "$pages" log --oneline -1
