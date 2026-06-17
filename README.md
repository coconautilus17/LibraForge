# LibraForge

Self-hosted Audible metadata matching, M4B conversion, and Audiobookshelf library organisation — three tools in one Docker container.

---

## Recent Updates

- **Backup and cache** — `Backup and cache original metadata` now runs independently of apply, creating per-file `.metadata-backup.json` and per-group sidecar caches on the first run. Subsequent force re-runs skip all ffprobe calls by reading from cache. `Force original tags` and `Re-probe audio files` options control cache behaviour explicitly.
- **Audiobookshelf metadata.json export** — `Write Audiobookshelf metadata.json` writes a sidecar at the book folder root instead of embedding tags in the audio file, for Audiobookshelf to pick up automatically.
- **Dynamic script selection** — the fixer and organizer default to the latest versioned script found in `scripts/`, no configuration needed on upgrade.
- **Manual review cleanup** — pattern-matched and already-processed skips are no longer included in the manual review list; only items that genuinely need attention appear.
- **Multipart group extraction fix** — "Author - Title" folder names now correctly extract author and title even when chapter file tags carry the narrator as artist. Track numbers on chapter files are no longer mistaken for book sequence numbers.

## Planned

- Configurable concurrent workers for faster metadata search and write.
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

**Manual Review** lets you load any book and search Audible manually. Requires an explicit `Full metadata` or `Series only` mode before applying.

### M4B Tool (`/m4b-tool`)

Converts or merges audio into a single M4B file.

1. Load a source file or folder. Existing fixer sidecars are loaded automatically.
2. Search Audible or edit metadata manually.
3. Use **Find conversion candidates** to scan for multipart or non-M4B books.
4. Set codec, bitrate, and jobs, then convert.

`No conversion` is recommended only when all source streams are AAC with matching sample rate and channel layout.

### Folder Forge (`/organizer`)

Plans and applies `Author/Series/Book N - Title` destination moves.

1. Set source (`/audiobooks/_unorganized`) and destination (`/audiobooks`).
2. Run a dry-run preview.
3. Review move plans — items flagged for review show structured reasons.
4. Enable **Apply** and run to execute moves.

Run **Index library and exit** to rebuild the destination structure cache independently.

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
