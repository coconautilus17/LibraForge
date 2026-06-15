# LibraForge

LibraForge is a Dockerized FastAPI application for Audible metadata matching,
manual review, M4B conversion, and Audiobookshelf-oriented library
organization.

It provides three pages:

- Metadata Forge (`/`)
- M4B Tool (`/m4b-tool`)
- Folder Forge (`/organizer`)

## Safety

Metadata and organizer operations default to dry-run. Review the generated
report or move preview before enabling an apply option.

- Back up media and metadata before the first write.
- Use a dedicated Audible account for metadata lookup.
- Mount Audible credentials read-only.
- Do not expose LibraForge directly to an untrusted network.
- Treat generated reports as private because they contain library paths and
  metadata.

## Features

- Streams fixer, conversion, and organizer progress.
- Shows output-driven task phases and downloadable JSON/text reports.
- Groups validated multipart MP3, Opus, M4A, and M4B books.
- Supports manual Audible candidate review and explicit edit modes.
- Loads and writes `m4b-tool` metadata sidecars.
- Caches read-only M4B discovery and audio probes.
- Converts or merges audio with configurable AAC settings.
- Preserves chapters and cover art while enforcing final M4B metadata.
- Previews metadata-derived library moves before apply.
- Reuses a persistent organizer structure cache.
- Provides system, dark, and light appearance settings with local browser
  persistence.
- Uses one shared, UI-managed title-noise policy for fixer matching clues and
  organizer folder naming.
- Places appearance and title-noise controls in a global header settings panel
  anchored to the settings button and available from every page.
- Uses dedicated artwork for each of the three Forge navigation cards.
- Makes explanatory notes individually collapsible, with a persistent header
  control to expand or collapse all explanations.
- Shows provenance-based Folder Forge review reasons for inferred or
  conflicting destination identity.

## Requirements

- Docker Engine with Docker Compose
- An audiobook directory mounted into the container
- An Audible auth JSON file for metadata searches

FFmpeg, FFprobe, Mutagen, FastAPI, Uvicorn, and `m4b-tool` are included in the
image.

## Setup

1. Copy the environment template:

   ```bash
   cp .env.example .env
   ```

2. Set these values in `.env`:

   ```dotenv
   UID=1000
   GID=1000
   AUDIOBOOKS_PATH=/path/to/audiobooks
   AUDIBLE_AUTH_PATH=/path/to/audible-auth
   ```

3. Build and start LibraForge:

   ```bash
   docker compose up -d --build
   ```

The included Compose file publishes LibraForge only on
`http://127.0.0.1:5056`. For a reverse proxy, attach the service to your proxy
network with a local `docker-compose.override.yml`; that file is intentionally
ignored by Git.

## Container Paths

| Purpose | Path |
|---|---|
| Audiobook library | `/audiobooks` |
| Audible auth directory | `/auth` |
| Maintained scripts | `/app/scripts` |
| Generated reports and caches | `/app/reports` |

The default auth file entered in the UI is:

```text
/auth/audible-metadata.json
```

Encrypted auth files are not supported by the web workflow because they
require an interactive password prompt.

## Metadata Forge

The maintained fixer is:

```text
scripts/audible-metadata-fixer-v4_15.py
```

The fixer:

- searches Audible using title, author, series, sequence, and duration clues;
- removes technical release labels without stripping ambiguous title words;
- rejects generic marketing subtitles as book identity;
- limits risky duration mismatches to conservative metadata modes;
- groups validated multipart chapter folders as one processing item;
- writes optional metadata backups and schema-version-2 reports.

Manual Review can load a supported file or browse a folder under
`/audiobooks`. Each candidate requires an explicit mode:

- `Full metadata` updates the selected title, author, narrator, series,
  sequence, year, summary, ASIN, and optional cover.
- `Series only` preserves local book identity and updates grouping-oriented
  metadata only.

## M4B Tool

The M4B page can load a fixer-created sidecar, search Audible, save edited
metadata, discover conversion candidates, and invoke `m4b-tool merge`.

Defaults:

- Codec: `libfdk_aac`
- Bitrate: `128k`
- Sample rate: `44100`
- Channels: preserve source
- Jobs: `4`

`No conversion` is recommended only when all detected source streams are
compatible AAC with matching sample rate and channel layout.

For serialized books, the sidecar title is authoritative. When its title does
not already contain the sidecar sequence, LibraForge adds an evidenced
`Vol. N` or `Volume N` label from the subtitle, otherwise `Book N`. The same
canonical title is used for the output filename, embedded title, and album.

Successful merges receive a final Mutagen metadata pass while preserving
chapters and cover art.

## Folder Forge

The maintained organizer is:

```text
scripts/organize-audiobooks-by-metadata-v3_7.py
```

The normal import workflow scans `/audiobooks/_unorganized` and targets
`/audiobooks`. It:

- plans author, series, and book folder destinations;
- uses fixer sidecars and embedded metadata;
- blocks unknown-author and ambiguous-structure moves by default;
- reserves targets to prevent duplicate plans;
- moves known companion files with loose audio;
- cleans release-junk filenames when the destination folder provides a safer
  canonical name;
- refreshes the structure cache after successful applies.

Run `Index library and exit` to build or refresh the destination structure
cache without planning moves.

## Title Noise Policy

Built-in generic subtitle patterns live in:

```text
config/title-noise.default.json
```

The global header settings panel can disable built-in patterns and add, enable,
disable, or remove custom regular expressions from any page. Local choices are
written to:

```text
config/title-noise.local.json
```

The local override is ignored by Git and excluded from the image build context.
Both maintained scripts reload the policy when it changes. Patterns are
case-insensitive and are used only for title cleanup; keep custom expressions
narrow enough that they cannot erase legitimate book titles.

## Reports And Local Data

Runtime files are written under `reports/`:

- `*.log.txt`
- `*.report.json`
- `m4b-discovery-cache.json`
- `organizer-structure-cache.json`

These files are intentionally ignored by Git and excluded from the Docker
build context. The directory contains a tracked `.gitkeep` only.

The following local/private files are also excluded:

- `.env`
- `config/title-noise.local.json`
- `archive/`
- Python bytecode and tool caches

## Development

Run the host-side regression suite:

```bash
python3 -m unittest discover -s app/tests -v
```

Compile maintained Python source:

```bash
python3 -m py_compile \
  app/main.py \
  app/m4b_naming.py \
  app/conversion_cache.py \
  app/conversion_discovery.py \
  app/progress_phases.py \
  scripts/audible-metadata-fixer-v4_15.py \
  scripts/organize-audiobooks-by-metadata-v3_7.py
```

Validate Compose:

```bash
docker compose config --quiet
```

Check the running container:

```bash
docker compose ps
docker compose exec -T libraforge python -c \
  'import app.main; print("import passed")'
```

Backend Python changes require a service restart. Static files are bind-mounted
by the included development-oriented Compose file.

## Repository Status

The maintained public scripts are fixer v4.15 and organizer v3.7. Experimental
fixer v5 files are excluded from Git and Docker builds until their concurrency
behavior is stable.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the shipped dependency
license summary.
