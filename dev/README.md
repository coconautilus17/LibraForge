# dev/ (dev branch only)

Tooling for developing LibraForge that a normal install never needs. It lives on the
long-lived `dev` branch, which is `main` plus this folder: features still go to `main`
through pull requests, and `main` is merged into `dev` to keep it current. Nothing here is
copied into the Docker image (the Dockerfile copies only `app/`, `scripts/`, `config/` and
`tools/`, and `.dockerignore` excludes `dev/` as well).

## benchmark/: matching accuracy on your own library

Every book whose `libraforge.json` kept its original tags (`backup.format_tags`, saved
before LibraForge first wrote anything) is a ready-made test case: the tags the file
arrived with, its duration, and, when a match was applied, the answer. The benchmark feeds
those original tags straight into the real matcher (no audio files, no copies) and scores
the picks against the applied matches.

```bash
# 1. Build the dataset from the NAS backups (all books, _unorganized included).
python3 dev/benchmark/collect.py --root /mnt/audiobooks            # data/full.json
python3 dev/benchmark/collect.py --root /mnt/audiobooks --sample 300   # + data/sample.json

# 2. Run the matcher from this checkout (public Audible catalog, or ABS).
dev/benchmark/run.sh full.json now_public audible
ABS_CONFIG=/home/tamir/dockers/libraforge/config dev/benchmark/run.sh full.json now_abs abs

# 3. Score one or more runs side by side (in the image: it reuses the fixer's placeholder authors).
docker run --rm --entrypoint /opt/venv/bin/python -v "$PWD/app:/app/app:ro" -v "$PWD/dev/benchmark:/bench" \
  -w /bench libraforge-libraforge score.py data/full.json data/scores.json \
  public=data/now_public.jsonl abs=data/now_abs.jsonl
```

A pick is **correct** when it is the reference ASIN, or another listing of the same
recording (runtime within 3% of the file or of the reference listing, and a shared
narrator). The reference is the library's own applied match, so it can be wrong too: a
"wrong" pick is worth a look before it counts as a regression. Books without an applied
ASIN are reported by outcome (applied / held / none) but not scored. Runs hit the live
providers, so results drift a little between days (an ABS search can stop returning a
listing); compare runs made close together.

To compare two versions, run each from its own worktree into a different tag and score
them together; to see what changed per book, diff the `class` fields of the score file.

Every runner writes its total wall time to `data/<tag>.time` (seconds); `score.py` saves
them under `_runtime` and the report shows them as each tool's Total runtime.

### Adding books from another library

A tag dump of someone else's files (before any matching) adds books your library doesn't
have. The dump is a JSON list of `{"path", "filename", "duration" (seconds), "tags"}`, one
per audio file: ffprobe's `format.filename`, `format.duration` and `format.tags`.

```bash
# keep the books your library doesn't already have (runs against your ABS)
docker run --rm --network homelab-proxy --entrypoint /opt/venv/bin/python -e ABS_URL=http://audiobookshelf \
  -v "$PWD/app:/app/app:ro" -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/config:/app/config:ro" \
  -v "$PWD/dev/benchmark:/bench" -w /app libraforge-libraforge \
  /bench/overlap.py /bench/data/dump.json /bench/data/import_kept.json /bench/data/import_overlap.json
# add them to the dataset
python3 dev/benchmark/collect.py --import dev/benchmark/data/import_kept.json \
  --merge dev/benchmark/data/complete.json --out dev/benchmark/data/combined.json
```

These books have no applied ASIN. Until one is confirmed (below), a file name curated as
`Author; Series; Book NN; Title` is the answer: a pick is correct when it is that book (same
author, and the same series and number or the same title), whichever recording. Library
and imported books are one list: each is a book in its original state.

### Confirming more answers

Books with no confirmed match (no applied ASIN, from either source) can be reviewed in a
throwaway LibraForge and applied there, the way a real library is matched:

```bash
# a writable copy of their mock files, each with a libraforge.json backup of its original
# tags and real duration (the fixer's write_original_metadata_backup)
docker run --rm --user 1000:1000 --entrypoint /opt/venv/bin/python -v "$PWD/app:/app/app:ro" \
  -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/dev/benchmark:/bench" -w /bench libraforge-libraforge \
  review_lib.py build data/combined.json data/abs_books data/review_books
# a LibraForge on it, with no ABS config so nothing reaches your real Audiobookshelf
docker run -d --name lf-review -p 5066:5056 --network homelab-proxy --user 1000:1000 \
  -v "$PWD/app:/app/app" -v "$PWD/scripts:/app/scripts" -v ~/dockers/libraforge-review/config:/app/config \
  -v ~/dockers/libraforge-review/reports:/app/reports -v ~/dockers/libraforge-review/auth:/auth \
  -v "$PWD/dev/benchmark/data/review_books:/audiobooks" -e SCRIPTS_DIR=/app/scripts \
  -e REPORTS_DIR=/app/reports -e AUDIOBOOKS_ROOT=/audiobooks libraforge-libraforge
```

Run a Metadata Forge dry run there, review its report and apply what is right. Then read
the applied matches back as confirmed answers (an applied ASIN, as in the real library):

```bash
docker run --rm --entrypoint /opt/venv/bin/python -v "$PWD/app:/app/app:ro" -v "$PWD/scripts:/app/scripts:ro" \
  -v "$PWD/dev/benchmark:/bench" -w /bench libraforge-libraforge \
  review_lib.py confirm data/combined.json data/review_books data/combined.json
```

**The dataset is your library.** `dev/benchmark/data/` holds titles, tags, ASINs and
folder paths, and is gitignored: never commit it, the repository is public.

### Optional: compare with BookOrbit

`bo_mock.py` writes a 1-second silent file per book carrying its original tags at its real
`Author/Title` path (about 10 KB each). Mount that folder read-only into a throwaway
BookOrbit stack, add it as a library, then run `python3 dev/benchmark/bookorbit.py fetch
<library id> dev/benchmark/data/bo.time` (a bulk metadata fetch, timed until its queue is
empty) and pass `bo=<library id>` to `score.py` (`bookorbit.py` reads `BOOKORBIT_URL` and
`BOOKORBIT_CREDS`). A library fetched before has BookOrbit's own metadata, not the
original tags, so a rerun needs a new library. BookOrbit fetches one book at a time with a 2 to 5 s pause between
books (longer while a provider throttles), so a full library takes about 12 hours.

### Optional: compare with Audiobookshelf Quick Match and beets-audible

Both read the same mock files. Never point either at your real library: Quick Match writes.

```bash
python3 dev/benchmark/bo_mock.py dev/benchmark/data/complete.json dev/benchmark/data/abs_books
# throwaway ABS on the mock (read-only), then Quick Match every book, one at a time
docker run -d --name abs-bench --network homelab-proxy -v /tmp/abs-bench/config:/config \
  -v /tmp/abs-bench/metadata:/metadata -v "$PWD/dev/benchmark/data/abs_books:/audiobooks:ro" \
  ghcr.io/advplyr/audiobookshelf:latest
docker run --rm --network homelab-proxy --entrypoint /opt/venv/bin/python -v "$PWD/dev/benchmark:/bench" \
  libraforge-libraforge /bench/abs_quickmatch.py http://abs-bench /bench/data/abs_quickmatch.jsonl

# beets reads tags with mutagen, so its mock uses standard iTunes atoms
python3 dev/benchmark/bo_mock.py dev/benchmark/data/complete.json dev/benchmark/data/beets_books --itunes
dev/benchmark/beets_run.sh complete.json beets 4     # 4 parallel imports -> data/beets.jsonl
```

Score them like any run (`absqm=...jsonl beets=...jsonl`). Quick Match on a fresh ABS each
time: it writes the match into ABS, so a second pass starts from its own answers.

### Books reviewed by hand

`curated=data/curation.json` on `score.py` overrides the rules for books reviewed one by
one: `{folder: {"verdict", "note", "accept": [ASIN], "titles": [title], "reject": [ASIN],
"others": [note]}}`. An accepted ASIN (or, for a Goodreads pick, title) is correct for every
tool that picked it, and a rejected one wrong, so a wrong library answer can be set aside.
Settle a library book's recording with `tools/chapter_match.py` on its real file; runtime
decides when the file's chapters were redone. The report shows each note on its book.

### The HTML report

`report.py` builds one standalone page: every book's original tags, the clues the matcher
parsed, the searches it ran, its candidates, the decision and the fields against the
library's answer, plus a summary, a table of how each tool matches with our notes on it, and
one comparison table per other tool. Each book also lists every other tool's outcome and pick,
and the filters (kept in the address, so a view can be linked) combine LibraForge's outcome
with another tool's.

```bash
python3 dev/benchmark/report.py dev/benchmark/data/complete.json dev/benchmark/data/scores.json \
    public dev/benchmark/data/public.jsonl dev/benchmark/data/report.html \
    --commit "$(git rev-parse --short HEAD)" --compare "absqm=Audiobookshelf Quick Match" \
    --compare "bo=BookOrbit" --compare "beets=beets-audible"
```

The page carries the whole library's titles, paths and tags: it stays in `data/` unless you
decide to publish it. Per-tool notes live in `TOOLS` in report.py; add an entry with each new tool.

### The public page

`publish_pages.sh` rebuilds the page with `--public` (only the tags a matcher reads: no
comments, descriptions, encoder or store fields) into a worktree of the `gh-pages` branch and
commits it there. GitHub Pages serves that branch as is. Look at the page, then push the branch.

```bash
git worktree add ../pages gh-pages   # once per machine
dev/benchmark/publish_pages.sh combined_4044.json scores_nov2.json public_gr nov2_public_gr.jsonl "$(git -C <main checkout> rev-parse --short HEAD)"
git -C ../pages push origin gh-pages
```

## tools/

- `chapter_match.py <file> <ASIN>...`: which listing is this audio? Compares the file's
  chapter lengths with each ASIN's chapter list from Audible's public catalog. Two
  recordings of one book rarely share a chapter layout, so this settles cases where tags
  and runtime disagree.
