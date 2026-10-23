# Testing

The suite is plain `unittest`: about 2,100 tests in about 190 files under `app/tests/`, and it
runs in roughly ten seconds.

## Running tests

Run tests where all the dependencies are installed, which means inside the container:

```bash
make test                                    # the whole suite
docker compose exec libraforge python -m unittest app.tests.test_fixer_v5_scoring   # one module
docker compose exec libraforge python -m unittest app.tests.test_fixer_v5_scoring.SplitSeriesTrailingNumberTests   # one class
```

`make test` runs `python -m unittest discover -s app/tests -p "test_*.py"` in the container's
virtualenv. CI (`.github/workflows/tests.yml`) runs the same discovery with `-t .` on a plain
Python 3.12 runner with `requirements.txt` and ffmpeg installed, then byte-compiles `app/main.py`,
a few other modules and every file in `scripts/`. Use dotted module names (`app.tests.test_x`)
when naming a single module.

The Settings page JavaScript tests (`app/tests/test_settings_pattern_ui.py`) run the real UI
code in QuickJS and are skipped when the optional `quickjs` package is not installed. It
installs from a prebuilt wheel on the glibc-based `Dockerfile.unified` image
(`pip install --target /tmp/pyjs quickjs`, then run the tests with `PYTHONPATH=/tmp/pyjs`);
the default Alpine image has no wheel and no compiler, so those tests skip there.

## How tests load the code

The two big scripts have hyphens in their names, so they cannot be imported. Tests load them
by path with `app/tests/script_loader.py`:

```python
from app.tests.script_loader import load_script

FIXER = load_script("fixer_my_tests", "audible-metadata-fixer-v5.py")
```

`load_script(name, filename)` loads a file from `scripts/`; `load_module(name, relative_path)`
loads any file by repo-relative path. Importing the helper also installs a stub for the
optional `audible` package when it is missing, so the fixer script can be imported anywhere.
Give each file its own module `name` so loaded copies do not share state.

## Conventions

These came out of an audit that removed or fixed tests which could not fail for the right
reason. Keep to them when adding tests.

- **Pin the exact result.** `assertEqual(parse(x), {"series": "Blight", "number": "1"})`, not
  `assertNotEqual(parse(x).get("series"), "Some Title")`. A test that only says what must not
  happen also passes when the function returns nothing.
- **A negative assertion needs a positive twin.** `assertNotIn("flag", cmd)` for the default
  is only meaningful next to a test that the flag appears when it is requested.
- **Same-shape examples go in one table.** One test with a `for ... in (...)` loop and
  `with self.subTest(...)` per row, instead of one near-identical test function per example.
  Every example is still checked, and a failure names the row.
- **Do not restate a constant.** A test that rebuilds the definition of a list or set only
  fails when someone edits the list, never when behaviour changes.
- **Do not patch `threading.Thread`.** `patch.object(main.threading, "Thread")` also stops the
  web server's worker threads from starting and the request hangs. Replace only the name the
  module under test uses, for example `patch.object(main_module, "threading", SimpleNamespace(**{**vars(threading), "Thread": fake}))`.
- **Tests must pass in any order and on their own.** A test that only passes because an earlier
  test left something behind will hang or fail when run alone. Shuffle the order occasionally
  to check.
- **Use temporary paths.** Never point a test at `/audiobooks`; use `tempfile.TemporaryDirectory()`.
- **Add a regression test with every fix** to matching, planning, grouping or report parsing
  (see [CONTRIBUTING](../../CONTRIBUTING.md)).

## Known defects

A confirmed bug that is not fixed yet gets a test marked `@unittest.expectedFailure` with the
issue number in a comment, so it is recorded and the suite stays green. When the fix lands
the test starts passing, which `unittest` reports as an unexpected success: remove the
decorator in the same change. `app/tests/test_audit_found_defects.py` holds the regression
tests for the defects the test audit found (#373 to #379), now fixed.
