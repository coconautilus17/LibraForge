# Installing LibraForge

The [README](../README.md) has the two quickest ways to start. This page has the rest:
running from a clone, the two published images, the optional companion services, and the
paths inside the container.

## From a clone

Requires Docker with the Compose plugin.

```bash
git clone https://github.com/coconautilus17/LibraForge.git
cd LibraForge
make up
```

Then open **http://127.0.0.1:5056**. `make up` builds the image, creates the first-boot
data folders, and runs the container as your user so mounted files stay writable. Without
`make`, `docker compose up -d --build` works too (it falls back to a repo-local `./data/`
library and UID/GID `1000`).

**Point it at your library.** By default LibraForge mounts the empty `./data/audiobooks`
and `./data/auth` folders. To use your real library, copy the env file and set the paths:

```bash
cp .env.example .env      # then edit AUDIOBOOKS_PATH / AUDIBLE_AUTH_PATH, and UID/GID if not 1000
make up                   # re-run to apply
```

For HTTPS, attach the container to your reverse proxy network in
`docker-compose.override.yml` (git-ignored).

Common commands: `make up`, `make down`, `make logs`, `make restart`, `make test`
(`make help` lists them all).

## The published image

The image on GitHub Container Registry is self-contained: the only thing you provide is
the path to your library. Audible sign-ins, run reports and the settings you save in the UI
(patterns, Audiobookshelf connection, retention) live in named volumes.

```bash
docker run -d --name libraforge \
  --user "$(id -u):$(id -g)" \
  -p 127.0.0.1:5056:5056 \
  -v /path/to/your/audiobooks:/audiobooks \
  -v libraforge-auth:/auth \
  -v libraforge-reports:/app/reports \
  -v libraforge-settings:/app/settings \
  -e LIBRAFORGE_SETTINGS_DIR=/app/settings \
  ghcr.io/coconautilus17/libraforge:latest
```

Or with Compose: download [`docker-compose.dist.yml`](../docker-compose.dist.yml) and run

```bash
AUDIOBOOKS_PATH=/path/to/your/audiobooks \
  docker compose -f docker-compose.dist.yml up -d
```

Upgrade later with `docker pull ghcr.io/coconautilus17/libraforge:latest`.

> **Upgrading from 0.2.4 or earlier?** Earlier run commands and compose files had no
> volume for saved settings, so anything saved in the UI lived inside the container and was
> lost when it was recreated. Add the `libraforge-settings` volume and the
> `LIBRAFORGE_SETTINGS_DIR` variable shown above (or download the new
> `docker-compose.dist.yml`) once; settings you save from then on survive upgrades.
> New in 0.2.5: **Settings → Author names** (a universal author-name scheme). It is on for
> new installs and off after an upgrade, so an existing organized library is not affected
> unless you turn it on.

### Two images

| Tag | Base | Chapter Forge speech recognition (Hybrid / Full transcription) |
|---|---|---|
| `ghcr.io/coconautilus17/libraforge:latest` | lean (`Dockerfile`) | not included |
| `ghcr.io/coconautilus17/libraforge:latest-chaptering` | `Dockerfile.unified` | included |

Chapter Forge's **Audible chapters** method (Audible's own chapter list) works in either
image. **Hybrid** and **Full transcription** transcribe audio locally with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), about 825 MB on its own, so
they ship only in the `-chaptering` tag. `latest` has everything else, is smaller, and also
supports `linux/arm64` (`-chaptering` is `linux/amd64` only for now).

To use it, swap the tag in the `docker run` command above, or with Compose:

```bash
LIBRAFORGE_IMAGE_TAG=latest-chaptering AUDIOBOOKS_PATH=/path/to/your/audiobooks \
  docker compose -f docker-compose.dist.yml up -d
```

## Optional companion services

| Service | Purpose |
|---|---|
| [Audiobookshelf](https://www.audiobookshelf.org/) | Metadata provider through ABS's search API, owned-book detection, and Enrichment Forge. Create an API key in ABS Settings → Users → API Keys and add it under Settings → Accounts. |
| [abs-agg](https://github.com/Vito0912/abs-agg) | More metadata sources: GraphicAudio, SoundBooth Theater, LibriVox, Storytel, BookBeat, Big Finish and others. Deploy on the same Docker network and set its URL in provider settings. |
| [audiosilo-meta](https://github.com/KodeStar/audiosilo-meta) | A local copy of AudioSilo's community database (`ghcr.io/kodestar/audiosilo-meta`), used instead of the public meta.audiosilo.app for the matcher's fallback. Set its URL under Settings → AudioSilo. |
| [abs-tract](https://github.com/ahobsonsayers/abs-tract) | Kindle cover art after a Goodreads match (Goodreads itself is read directly). Deploy on the same Docker network and set its URL in provider settings. |

None is required: matching works out of the box through the public Audible catalog.

## Paths inside the container

| Purpose | Path |
|---|---|
| Audiobook library | `/audiobooks` |
| Audible sign-ins | `/auth` (active account `/auth/audible-metadata.json`, saved accounts `/auth/accounts/`) |
| Scripts | `/app/scripts` |
| Reports and caches | `/app/reports` |
| Saved settings | `/app/settings` when `LIBRAFORGE_SETTINGS_DIR` is set (as in the published image's compose file), otherwise `/app/config` |
