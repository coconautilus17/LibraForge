# Development

```bash
# Run tests (inside the container, where dependencies are installed)
make test

# Restart after backend (app/main.py) changes
make restart

# Rebuild after Dockerfile or dependency changes
make rebuild
```

The Settings page JavaScript tests (`app/tests/test_settings_pattern_ui.py`) run the real
UI code in QuickJS and are skipped when the optional `quickjs` package is not installed.
It installs from a prebuilt wheel on the glibc-based `Dockerfile.unified` image
(`pip install --target /tmp/pyjs quickjs`, then run the tests with `PYTHONPATH=/tmp/pyjs`);
the default Alpine image has no wheel and no compiler, so those tests skip there.

Static files (`app/static`, `scripts/`) are bind-mounted - HTML, CSS, and JS edits are
live without a restart.

Run `make help` for the full list of commands (`make up`, `make down`, `make logs`, and
more).

LibraForge is licensed under [AGPL-3.0-or-later](../LICENSE). See
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for dependency licence information.
