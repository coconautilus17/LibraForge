# LibraForge

Self-hosted Audible metadata matching, M4B conversion, and Audiobookshelf library organisation — three tools in one Docker container.

---

## Recent Updates

- **Concurrent workers (v5)** — parallel Audible API search with `--workers N`; per-thread client pool, per-query dedup, and a persistent chapter-count cache that makes discovery near-instant on repeat runs. ASIN conflict detection prevents wrong matches from being written even when scoring passes.
- **Scoring improvements** — fixer now rejects candidates whose Audible title carries a different explicit series number than the local title (e.g. "Series 4" vs "Series 6"), and candidates where the local title has an explicit number but the Audible series title does not yet the sequence disagrees. Fixes wrong-book matches that previously scored 1.0 due to high title similarity and matching duration.
- **Manual review loads original tags** — the manual book-load form now reads pre-apply original tags from the backup, not the (possibly wrong) Audible-written values, so suggested queries and scored results reflect the real book.
- **Organizer: broadcaster prefix strip** — `BBC -`, `BBC Radio -`, etc. are removed from author tags before folder construction so books are filed under the actual author, not the broadcaster.
- **metadata.json sidecar naming** — written as `<file>.metadata.json` so books in flat unorganised folders don't overwrite each other; the organizer renames it to `metadata.json` post-move.
- **Backup and cache** — `Backup and cache original metadata` runs independently of apply, creating per-file `.metadata-backup.json` and per-group sidecar caches on the first run. Subsequent runs skip ffprobe by reading from cache.
- **Dynamic script selection** — the fixer and organizer default to the latest versioned script found in `scripts/`, no configuration needed on upgrade.

## Planned

- Local agent advisory review: send a generated report to a local LLM endpoint and display its suggestions (read-only, no automatic writes).
- Chapter detection via speech recognition before M4B conversion.
- Unraid Community Apps package.

---

## Install

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
UID=1000
GID=1000
AUDIOBOOKS_PATH=/path/to/audiobooks
AUDIBLE_AUTH_PATH=/path/to/audible-auth
```

```bash
docker compose up -d --build
```

LibraForge listens on `127.0.0.1:5056`. For HTTPS, attach to your reverse proxy network via `docker-compose.override.yml` (git-ignored).

---

## Usage

### Metadata Forge (`/`)

Searches Audible and writes matched metadata to your audiobook files.

1. Select your root folder (e.g. `/audiobooks/_unorganized`).
2. Run a **dry run** first — review the report and manual review items.
3. Enable **Backup and cache** on the first apply run to preserve originals and speed up future runs.
4. Enable **Apply changes** and re-run to write tags.

Key options:

| Option | When to use |
|---|---|
| Backup and cache | Always on first apply; caches probes for future runs |
| Force / ignore markers | Re-process already-matched files |
| Force original tags | Re-search using pre-apply embedded tags instead of post-apply Audible values |
| Re-probe audio files | Ignore cache and probe files fresh |
| Write Audiobookshelf metadata.json | Write a sidecar instead of embedding tags |
| Workers (v5) | Number of parallel Audible search workers; recommended 5, max 10 |

**Manual Review** lets you load any book and search Audible manually. Requires an explicit `Full metadata` or `Series only` mode before applying.
<img width="1215" height="1073" alt="image" src="https://github.com/user-attachments/assets/7702662c-d3d8-47cf-945d-777f86e4cbbd" />

### M4B Tool (`/m4b-tool`)

Converts or merges audio into a single M4B file.

1. Load a source file or folder. Existing fixer sidecars are loaded automatically.
2. Search Audible or edit metadata manually.
3. Use **Find conversion candidates** to scan for multipart or non-M4B books.
4. Set codec, bitrate, and jobs, then convert.

`No conversion` is recommended only when all source streams are AAC with matching sample rate and channel layout.
<img width="1201" height="1160" alt="image" src="https://github.com/user-attachments/assets/258208dc-0ddb-4642-9541-7c47378e24f8" />

### Folder Forge (`/organizer`)

Plans and applies `Author/Series/Book N - Title` destination moves.

1. Set source (`/audiobooks/_unorganized`) and destination (`/audiobooks`).
2. Run a dry-run preview.
3. Review move plans — items flagged for review show structured reasons.
4. Enable **Apply** and run to execute moves.

Run **Index library and exit** to rebuild the destination structure cache independently.
<img width="1198" height="1197" alt="image" src="https://github.com/user-attachments/assets/024a57ca-333f-445a-bf33-4a5c512f3159" />

---

## Container paths

| Purpose | Path |
|---|---|
| Audiobook library | `/audiobooks` |
| Audible auth directory | `/auth` (default file: `/auth/audible-metadata.json`) |
| Scripts | `/app/scripts` |
| Reports and caches | `/app/reports` |

## Safety

- All operations default to dry-run. Review before applying.
- Back up media before the first write.
- Use a dedicated Audible account for metadata lookup.
- Mount Audible credentials read-only.
- Do not expose LibraForge to an untrusted network.

## Development

```bash
# Run tests
python3 -m unittest discover -s app/tests -v

# Restart after backend changes
docker compose restart libraforge

# Rebuild after Dockerfile or dependency changes
docker compose up -d --build
```

Static files (`app/`, `scripts/`) are bind-mounted — HTML, CSS, and JS edits are live without restart.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for dependency licence information.
