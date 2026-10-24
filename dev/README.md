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

# 3. Score one or more runs side by side.
python3 dev/benchmark/score.py dev/benchmark/data/full.json dev/benchmark/data/scores.json \
    public=dev/benchmark/data/now_public.jsonl abs=dev/benchmark/data/now_abs.jsonl
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

**The dataset is your library.** `dev/benchmark/data/` holds titles, tags, ASINs and
folder paths, and is gitignored: never commit it, the repository is public.

### Optional: compare with BookOrbit

`bo_mock.py` writes a 1-second silent file per book carrying its original tags at its real
`Author/Title` path (about 10 KB each). Mount that folder read-only into a throwaway
BookOrbit stack, add it as a library, start a bulk metadata fetch, then pass
`bo=<library id>` to `score.py` (`bookorbit.py` reads `BOOKORBIT_URL` and
`BOOKORBIT_CREDS`). BookOrbit fetches one book at a time with a 2 to 5 s pause between
books (longer while a provider throttles), so a full library takes about 12 hours.

## tools/

- `chapter_match.py <file> <ASIN>...`: which listing is this audio? Compares the file's
  chapter lengths with each ASIN's chapter list from Audible's public catalog. Two
  recordings of one book rarely share a chapter layout, so this settles cases where tags
  and runtime disagree.
