# dev/

Tooling for developing LibraForge that a normal install never needs. Nothing here is copied
into the Docker image (the Dockerfile copies only `app/`, `scripts/`, `config/` and `tools/`,
and `.dockerignore` excludes `dev/` as well).

The benchmark is also mapped in the Product Model (`product-model/domains/benchmark.md` and
the capabilities it lists): what each step reads and writes, and the rules that keep its
results comparable. Read that first when changing it.

## benchmark/: matching tools compared on the same books

The same real audiobooks, in their original state, are given to every matching tool; every
result is then audited book by book, and the comparison page is built from that audit.

**The dataset is your library.** `dev/benchmark/data/` holds titles, tags, ASINs and folder
paths and is gitignored: never commit it, the repository is public. Only the published page
and its downloads carry any of it, and those list only the tags a matcher reads.

### The pipeline

| Step | Command | Reads | Writes |
| --- | --- | --- | --- |
| 1. Collect | `collect.py --root /mnt/audiobooks` | the library's `libraforge.json` backups | `data/full.json` |
| 1b. Import | `overlap.py`, `collect.py --import`, `dedupe.py` | another library's ffprobe dump | a merged dataset |
| 1c. Confirm answers | `review_lib.py build` / `confirm` | books with no confirmed answer | the dataset, answers filled in |
| 2. Mock files | `bo_mock.py <books> <out> [--itunes] [--runtime] [--public]` | the dataset | silent files carrying the tags |
| 3. Run each tool | `run.sh`, `audiosilo.py`, `abs_quickmatch.py`, `grimmory.py`, `readmeabook.py`, `bookorbit.py`, `beets_run.sh` | the dataset or the mock | `data/<run>.jsonl`, `data/<run>.time` |
| 4. Manifest | edit `data/manifest.json` (shape: `manifest.example.json`) | | which dataset, runs and audit make up this benchmark |
| 5. Hand audit | write `data/<audit>/verdicts_*.txt`, then `audit.py` | every tool's result per book | `audit.hand` |
| 6. Field checks | `audit_check.py --write` | the runs and the hand audit | `audit.final`, the verdicts the page shows |
| 7. Second audit | `reaudit_sample.py sample 300 <seed>`, judge the sheets, `findings.txt` | `audit.final` | the page's error rates |
| 8. Geo | `geo.py rights`, `geo.py summary --market XX` | confirmed answers | how many Audible's search hid |
| 9. Publish | `publish_pages.sh` | the manifest | `gh-pages`: the page, `benchmark-books.json`, `benchmark-mock-files.tar.gz` |

Steps 4 to 9 read everything through `bench_data.py` and the manifest, so they always agree
on which files make up the benchmark. `bench_data.result()` is the one statement of how
each tool writes; the field checks and the downloadable book list both use it.

### 1. The dataset

Every book whose `libraforge.json` kept its original tags (`backup.format_tags`, saved
before LibraForge first wrote anything) is a test case: the tags the file arrived with, its
duration and folder, and, when a match was applied, that match as the right answer (its ASIN
and the title, author, narrator, series and number it wrote then).

```bash
python3 dev/benchmark/collect.py --root /mnt/audiobooks            # data/full.json
```

Books from another library come as an ffprobe tag dump (a JSON list of `{"path",
"filename", "duration" (seconds), "tags"}` per audio file, see the "Add your books" issue
template). Keep the ones your library doesn't have, add them, then keep one of each search:

```bash
docker run --rm --network homelab-proxy --entrypoint /opt/venv/bin/python -e ABS_URL=http://audiobookshelf \
  -v "$PWD/app:/app/app:ro" -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/config:/app/config:ro" \
  -v "$PWD/dev/benchmark:/bench" -w /app libraforge-libraforge \
  /bench/overlap.py /bench/data/dump.json /bench/data/import_kept.json /bench/data/import_overlap.json
python3 dev/benchmark/collect.py --import dev/benchmark/data/import_kept.json \
  --merge dev/benchmark/data/full.json --out dev/benchmark/data/combined.json
# dedupe.py runs in the image the same way: dedupe.py <books.json> <out.json> [--dump ... --overlap ...]
```

An imported book has no applied match. A file name in `Author; Series; Book NN; Title` form
is its answer until one is confirmed: the right book is that author's, with that series and
number or that title, in any recording. Its answer names no narrator.

To confirm answers, build a throwaway library of those books (each with the backup a real
library book has), match and apply them in a throwaway LibraForge, and read the applied
matches back:

```bash
docker run --rm --user 1000:1000 --entrypoint /opt/venv/bin/python -v "$PWD/app:/app/app:ro" \
  -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/dev/benchmark:/bench" -w /bench libraforge-libraforge \
  review_lib.py build data/combined.json data/abs_books data/review_books
# a LibraForge on data/review_books with no ABS config; dry run, review, apply; then:
docker run --rm --entrypoint /opt/venv/bin/python -v "$PWD/app:/app/app:ro" -v "$PWD/scripts:/app/scripts:ro" \
  -v "$PWD/dev/benchmark:/bench" -w /bench libraforge-libraforge \
  review_lib.py confirm data/combined.json data/review_books data/combined.json
```

### 2 and 3. Mock files and runs

Every tool gets the same books. LibraForge's own run feeds the original tags straight into
the real matcher (no files); every other tool reads mock files: each book as silence
carrying its original tags at its real folder path, built by `bo_mock.py`:

- default: 1 s, tags as custom keys (ffprobe readers: BookOrbit, Audiobookshelf, ReadMeABook)
- `--itunes`: standard iTunes atoms (mutagen and jaudiotagger readers: beets, Grimmory)
- `--runtime`: as long as the book, for AudioSilo, which checks runtime (beets reads each
  book's real runtime from the dataset through `beets/benchplug` instead)

Each tool runs in a throwaway instance, never your real library (Quick Match and Grimmory
write), the way its own documentation suggests. Each runner's docstring has its setup:

```bash
dev/benchmark/run.sh combined.json lf_run audible 5            # LibraForge (GOODREADS=1 for the fallback)
python3 dev/benchmark/audiosilo.py match data/audiosilo.time   # then: rows <books> data/audiosilo.jsonl
docker run ... /bench/abs_quickmatch.py http://abs-bench /bench/data/absqm.jsonl
python3 dev/benchmark/grimmory.py refresh data/grimmory.time   # then: rows <books> data/grimmory.jsonl
python3 dev/benchmark/readmeabook.py scan <books> data/rmab.jsonl
python3 dev/benchmark/bookorbit.py fetch <library id> data/bo.time   # then: rows <library id> data/bo_rows.jsonl
dev/benchmark/beets_run.sh combined.json beets 4
```

Every runner writes the run's total wall time to `data/<run>.time` (seconds). Runs hit live
providers, so results drift a little between days: compare runs made close together.

### 4 to 7. The audit

`data/manifest.json` names the dataset, each tool's run, the audit files and the
LibraForge build (`manifest.example.json` has the shape).

Every book's result for every tool is judged by hand into verdict files, one line per book:
`<book index> LF AS ABS GRM RMAB BO BEETS | note`, one code per tool (C right book and every
field right, E right book from another recording, P right book with a field off, W wrong book,
S/s series-only write into the right/wrong series, H/h held for review with a right/wrong
pick, N nothing written). The hand verdict decides which book it is; `audit_check.py` then
rebuilds what each tool left on the book and checks every field, which decides C or P:

```bash
cd dev/benchmark
python3 audit.py                            # verdict files -> audit.hand
python3 audit_check.py --write --out data/disagreements.jsonl   # -> audit.final
```

Every book where the field checks and the hand verdict disagree goes to the disagreements
file for a second look. To measure the audit, draw a sample, judge its sheets again and
list every verdict that was wrong in `findings.txt` (`<index> <TOOL> <old>-><new> | why
(rule|hand)`); a rule error is fixed for every book. `validation` draws a fresh sample after
that. `audit_check.py --write` counts both into the page's error rates.

```bash
python3 reaudit_sample.py sample 300 20261102
python3 reaudit_sample.py validation 100 424242
```

A new LibraForge run is judged by carrying the audit forward: an unchanged result keeps its
verdict, a changed one is settled by rule where the evidence is plain (the confirmed answer's
ASIN, a pick another tool was judged right on, the book's own series), and the rest is listed
for hand review:

```bash
python3 reaudit_run.py old_run.jsonl new_run.jsonl data/audit_new
# review data/audit_new/to_review.tsv, then point the manifest's audit.verdicts at data/audit_new
```

### 8. Books Audible's search couldn't show

Audible's search returns a book only where Audible sells it; a lookup by ASIN works
everywhere. `geo.py rights` reads the sales rights of every confirmed answer, and `geo.py
summary --market XX` counts the answers sold only elsewhere. The market is never written
anywhere: the page never says where the runs were made.

### 9. The page

```bash
git worktree add ../pages gh-pages     # once per machine
dev/benchmark/publish_pages.sh         # commits to the gh-pages worktree
git -C ../pages push origin gh-pages   # after looking at it
```

It publishes the page, `benchmark-books.json` (every book with its tags, the right answer
and each tool's verdict, pick and result) and `benchmark-mock-files.tar.gz` (the 1 s mock
with only the tags a matcher reads: no comments, descriptions, cover art, store or encoder
fields). Per-tool notes live in `TOOLS` and `WRITES` in report.py; add one with each new tool.

## tools/

- `chapter_match.py <file> <ASIN>...`: which listing is this audio? Compares the file's
  chapter lengths with each ASIN's chapter list from Audible's public catalog. Two
  recordings of one book rarely share a chapter layout, so this settles cases where tags
  and runtime disagree.
- `build_guild_catalog.py`: rebuilds the Audiobook Guild catalog LibraForge ships.
