# Development

```bash
# Run tests (inside the container, where dependencies are installed)
make test

# Restart after backend (app/main.py) changes
make restart

# Rebuild after Dockerfile or dependency changes
make rebuild
```

Static files (`app/static`, `scripts/`) are bind-mounted - HTML, CSS, and JS edits are
live without a restart.

Run `make help` for the full list of commands (`make up`, `make down`, `make logs`, and
more).

LibraForge is licensed under [AGPL-3.0-or-later](../LICENSE). See
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for dependency licence information.
