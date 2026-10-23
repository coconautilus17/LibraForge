# Developer documentation

For people changing LibraForge. The user-facing guide is [../features.md](../features.md),
and the install instructions are in the [project README](../../README.md).

| Page | What it covers |
|---|---|
| [Architecture](architecture.md) | How the web app, the scripts and the front end fit together, what a run does, where decisions live. |
| [Data and files](data-and-files.md) | Every file LibraForge writes (sidecars, reports, caches, settings), environment variables, what is safe to delete. |
| [Testing](testing.md) | Running the suite, how tests load the scripts, and the conventions for writing tests. |
| [Contributing](../../CONTRIBUTING.md) | Branches, what not to commit, code guidelines. |

## Working locally

```bash
# Run tests (inside the container, where dependencies are installed)
make test

# Restart after backend (Python) changes
make restart

# Rebuild after Dockerfile or dependency changes
make rebuild

# Everything else
make help
```

With the repo's `docker-compose.yml`, the `app/`, `scripts/`, `config/` and `reports/` folders
are bind-mounted into the container. HTML, CSS and JS edits are live without a restart;
Python edits need `make restart`. The published image has no bind mounts, so none of this
applies to it.

LibraForge is licensed under [AGPL-3.0-or-later](../../LICENSE). See
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) for dependency licence information.
