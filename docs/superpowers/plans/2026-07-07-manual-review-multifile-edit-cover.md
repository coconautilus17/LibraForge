# Manual Review: Multi-file Visibility, Direct-Edit Dialog, Cover Swap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface "this is a multi-file/grouped book" everywhere a book can be inspected in Manual Review and the match report (with a filter), and add a standalone "Edit Book" dialog that lets a user directly edit a book's fields and swap its cover without going through the search/match flow.

**Architecture:** Extend the existing `is_grouped`/`group_search.applied` signal (already computed everywhere) into two places that currently lack it (report items, the log-parsed category system) and three frontend surfaces that currently lack a badge. Extract the write sequence inside `apply_manual_review_result` into a shared `_write_book_metadata()` helper, then build a new `/api/manual-review/edit` endpoint on top of it. Add a small `/api/manual-review/cover-upload` endpoint that stores an uploaded image as a temp file and returns a `file://` URL — the existing `download_cover_bytes()` writer code already knows how to fetch any URL, including `file://`, so no new embed code path is needed. Frontend work for the new dialog goes in a new file (`app/static/manual-review-edit.js`) rather than growing `app.js` (already ~1600 lines) further; it's loaded after `app.js` in `index.html` and freely references `app.js`'s existing top-level globals (`manualContext`, `$`, `escapeHtml`, `manualCurrentCoverUrl`), the same way every script on this page already does — none of them use module scoping or an IIFE boundary between each other.

**Tech Stack:** Python 3 / FastAPI backend (`app/main.py`), a CPython-loaded fixer module (`scripts/audible-metadata-fixer-v5.py`) invoked in-process via `load_fixer_module()`, vanilla JS frontend (`app/static/*.js`, `app/static/index.html`), `unittest` for backend tests.

## Global Constraints

- Never use long/em dashes in any code comment, docstring, log message, commit message, or UI copy — use a hyphen or restructure the sentence instead.
- All existing tests must keep passing after every task; run the full suite (`docker compose exec libraforge /opt/venv/bin/python -m unittest discover -s app/tests -p "test_*.py"`) before each commit, not just the new test file.
- `field_policy="legacy"` (the default on every CLI call site) must remain byte-identical after any refactor — this is a hard regression bar already enforced by existing tests (`Mp4FieldPolicyTests.test_legacy_reproduces_historical_split`, `M4bToolSidecarAsinFieldPolicyTests.test_legacy_preserves_current_asin_when_blank`).
- Grouped/multi-file books never get per-chapter embedded tags from Manual Review (neither the existing apply flow nor the new edit flow) — only the JSON sidecar + `metadata.json`. Do not add per-chapter tag writes.
- The new Edit dialog is a separate, dedicated `<dialog>` element — do not reuse `manualApplyEditDialog`'s markup/IDs for it.
- The Edit dialog has one Save button; a blank field always clears that tag (`field_policy="overwrite"` always, no Fill/Overwrite choice).
- All commits use `git commit -m "$(cat <<'EOF' ... EOF)"` with a `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` trailer, and are made only on `feat/manual-review-multifile-edit-cover` (already checked out, cut from `main`).

---

## Task 1: `is_grouped` on report items

**Files:**
- Modify: `scripts/audible-metadata-fixer-v5.py` (`_build_report_item`, currently starting at line 4120)
- Test: `app/tests/test_report_item_is_grouped.py` (new)

**Interfaces:**
- Produces: `_build_report_item(result: ItemResult) -> dict` now includes `"is_grouped": bool` in its returned dict, derived from `result.clues.get("group_search", {}).get("applied")`.

- [ ] **Step 1: Write the failing test**

Create `app/tests/test_report_item_is_grouped.py`:

```python
"""_build_report_item must expose is_grouped so the match report can badge
and filter multi-file/grouped books -- same source of truth already used by
discover_manual_review_targets and inspect_manual_review_target
(app/main.py), just missing from the report item dict. See
docs/superpowers/specs/2026-07-07-manual-review-multifile-edit-cover-design.md.
"""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    audible_stub = types.ModuleType("audible")
    audible_stub.Client = type("Client", (), {})
    audible_stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = audible_stub

import importlib.util


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = load_module("fixer_v5_report_item_is_grouped", "scripts/audible-metadata-fixer-v5.py")


class ReportItemIsGroupedTests(unittest.TestCase):
    def _result(self, group_search_applied: bool) -> "FIXER.ItemResult":
        result = FIXER.ItemResult(
            index=1,
            file_path=Path("/lib/Book/book.m4b"),
            display_path="/lib/Book",
            log_lines=[],
        )
        result.status = "matched"
        result.clues = {"group_search": {"applied": group_search_applied}}
        result.metadata = {"title": "Book", "author": "Author"}
        return result

    def test_grouped_book_reports_is_grouped_true(self):
        item = FIXER._build_report_item(self._result(True))
        self.assertTrue(item["is_grouped"])

    def test_single_file_book_reports_is_grouped_false(self):
        item = FIXER._build_report_item(self._result(False))
        self.assertFalse(item["is_grouped"])

    def test_missing_group_search_defaults_to_false(self):
        result = self._result(False)
        result.clues = {}
        item = FIXER._build_report_item(result)
        self.assertFalse(item["is_grouped"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest app.tests.test_report_item_is_grouped -v`
Expected: FAIL with `KeyError: 'is_grouped'`

- [ ] **Step 3: Add the field**

In `scripts/audible-metadata-fixer-v5.py`, find the `item: dict = {...}` block inside `_build_report_item` (currently lines 4182-4194):

```python
    item: dict = {
        "path": str(result.file_path),
        "status": result.status,
        "skip_reason": result.skip_reason,
        "score": result.score,
        "mode": result.edit_mode,
        "duration_status": result.duration_status,
        "provider": result.source_provider,
        "goodreads_rate_limited": result.goodreads_rate_limited,
        "used_query": result.used_query or "",
        "was_manually_applied": result.was_manually_applied,
        "local": local,
    }
```

Add `is_grouped` right after `"local": local,`:

```python
    item: dict = {
        "path": str(result.file_path),
        "status": result.status,
        "skip_reason": result.skip_reason,
        "score": result.score,
        "mode": result.edit_mode,
        "duration_status": result.duration_status,
        "provider": result.source_provider,
        "goodreads_rate_limited": result.goodreads_rate_limited,
        "used_query": result.used_query or "",
        "was_manually_applied": result.was_manually_applied,
        "local": local,
        "is_grouped": bool((clues.get("group_search") or {}).get("applied")),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest app.tests.test_report_item_is_grouped -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full suite**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest discover -s app/tests -p "test_*.py"`
Expected: all tests pass (baseline was 572 before this task; expect 575)

- [ ] **Step 6: Commit**

```bash
git add scripts/audible-metadata-fixer-v5.py app/tests/test_report_item_is_grouped.py
git commit -m "$(cat <<'EOF'
feat(report): expose is_grouped on match report items

Same group_search.applied source of truth already used by Manual
Review's discovery list and load endpoint -- report items were
missing it, so there was no way to badge or filter multi-file books
in the match report.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `group:multi-file` category during a live scan

**Files:**
- Modify: `scripts/audible-metadata-fixer-v5.py` (`process_file`, log-line emission after clues are resolved, currently around line 3151)
- Modify: `app/main.py` (regex definitions around line 436-457, `parse_line` around line 1460-1467)
- Test: `app/tests/test_report_parser_categories.py` (extend existing file)

**Interfaces:**
- Produces: a new `"group:multi-file"` key in `state.files_by_category` (via `add_category(state, "group", "multi-file", path)`), populated for every processed item whose `group_search.applied` is true. Appears automatically in the existing "browse by category" dropdown -- no separate frontend change.

- [ ] **Step 1: Write the failing test**

In `app/tests/test_report_parser_categories.py`, add a new test method to `ReportParserCategoryTests` (after `test_ga_source_category_and_provider_breakdown`, before `test_goodreads_header_counts_as_matched_with_provider`):

```python
    def test_grouped_book_category(self):
        lines = [
            "[1/2] Processing: /lib/Grouped Book/book.m4b",
            "AUDIBLE MATCH:",
            "  Mode:     full",
            "  Grouped: 12 files",
            "[2/2] Processing: /lib/Single Book/book.m4b",
            "AUDIBLE MATCH:",
            "  Mode:     full",
        ]
        state = run_lines(lines)
        self.assertEqual(
            self._paths(state, "group:multi-file"),
            ["/lib/Grouped Book/book.m4b"],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest app.tests.test_report_parser_categories.ReportParserCategoryTests.test_grouped_book_category -v`
Expected: FAIL, `self.assertEqual([], ["/lib/Grouped Book/book.m4b"])`

- [ ] **Step 3: Add the regex and parse_line handling in `app/main.py`**

Find the regex block (currently lines 436-450):

```python
MODE_RE = re.compile(r"^\s+Mode:\s+([A-Za-z_]+)\s*$")
DURATION_STATUS_RE = re.compile(r"^\s+Status:\s+([A-Za-z_]+)\s*$")
```

Add `GROUPED_RE` right after `MODE_RE`:

```python
MODE_RE = re.compile(r"^\s+Mode:\s+([A-Za-z_]+)\s*$")
GROUPED_RE = re.compile(r"^\s+Grouped:\s+(\d+)\s+files?\s*$")
DURATION_STATUS_RE = re.compile(r"^\s+Status:\s+([A-Za-z_]+)\s*$")
```

Find the `MODE_RE` handling block in `parse_line` (currently lines 1460-1467):

```python
    m = MODE_RE.match(line)
    if m and state.current_file:
        mode = m.group(1)
        if mode in {"full", "series_only", "none"}:
            state.stats["mode_breakdown"].setdefault(mode, 0)
            state.stats["mode_breakdown"][mode] += 1
            add_category(state, "mode", mode, state.current_file)
        return
```

Add the `GROUPED_RE` handling right after it:

```python
    m = MODE_RE.match(line)
    if m and state.current_file:
        mode = m.group(1)
        if mode in {"full", "series_only", "none"}:
            state.stats["mode_breakdown"].setdefault(mode, 0)
            state.stats["mode_breakdown"][mode] += 1
            add_category(state, "mode", mode, state.current_file)
        return

    m = GROUPED_RE.match(line)
    if m and state.current_file:
        add_category(state, "group", "multi-file", state.current_file)
        return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest app.tests.test_report_parser_categories -v`
Expected: PASS (all tests in the file, including the new one)

- [ ] **Step 5: Emit the log line from the fixer script**

In `scripts/audible-metadata-fixer-v5.py`, find the clues-resolution block in `process_file` (currently lines 3134-3154):

```python
        match_cache_key = get_search_context_cache_key(file_path, multi_part_group_map)
        with search_context_lock:
            cached_ctx = search_context_cache.get(match_cache_key)
        if cached_ctx is not None:
            queries, clues = cached_ctx
        else:
            queries, clues, _ = build_search_context(
                file_path,
                multi_part_group_map,
                use_backup_tags=args.force_original,
                reprobe=args.reprobe,
                save_probe_cache=args.backup,
            )
            with search_context_lock:
                search_context_cache.setdefault(match_cache_key, (queries, clues))
                queries, clues = search_context_cache[match_cache_key]

        local_duration_minutes = clues.get("local_duration_minutes")

        result.queries = queries
        result.clues = clues
```

Add the log line right after `result.clues = clues`:

```python
        match_cache_key = get_search_context_cache_key(file_path, multi_part_group_map)
        with search_context_lock:
            cached_ctx = search_context_cache.get(match_cache_key)
        if cached_ctx is not None:
            queries, clues = cached_ctx
        else:
            queries, clues, _ = build_search_context(
                file_path,
                multi_part_group_map,
                use_backup_tags=args.force_original,
                reprobe=args.reprobe,
                save_probe_cache=args.backup,
            )
            with search_context_lock:
                search_context_cache.setdefault(match_cache_key, (queries, clues))
                queries, clues = search_context_cache[match_cache_key]

        local_duration_minutes = clues.get("local_duration_minutes")

        result.queries = queries
        result.clues = clues

        group_search = clues.get("group_search", {}) or {}
        if group_search.get("applied"):
            log.append(f"  Grouped: {group_search.get('file_count', 0)} files")
```

- [ ] **Step 6: Run the full suite**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest discover -s app/tests -p "test_*.py"`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add scripts/audible-metadata-fixer-v5.py app/main.py app/tests/test_report_parser_categories.py
git commit -m "$(cat <<'EOF'
feat(scan): categorize grouped/multi-file books during a live run

Adds a "Grouped: N files" log line (parsed into the existing
files_by_category system as group:multi-file), so multi-file books
show up in Manual Review's browse-by-category dropdown like every
other category already does.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Frontend badges (active target card, match report card, match report filter)

**Files:**
- Modify: `app/static/app.js` (`loadManualTarget` around line 578-589, `buildMatchCard` around line 1309-1344, `buildMatchReportCards` around line 1246-1264)
- Modify: `app/static/index.html` (target path field area around line 330-335, `matchReportFilter` select options)
- Modify: `app/static/style.css` (new `.match-grouped-badge` rule near the existing `.match-*-badge` block, currently around line 2990-3009)

**Interfaces:**
- Consumes: `manualContext.is_grouped` (already returned by `/api/manual-review/load`, `app/main.py:2629`), `item.is_grouped` (added in Task 1).

- [ ] **Step 1: Add the badge CSS**

In `app/static/style.css`, find the badge color rules (currently lines 3004-3009):

```css
.match-score-badge      { background: var(--accent-soft);           color: var(--accent);  }
.match-mode-badge       { background: var(--warning-soft);          color: var(--warning); }
.match-provider-badge   { background: rgb(120 80 200 / 15%);        color: #b09eff;        }
.match-manual-badge     { background: rgb(0 160 100 / 15%);         color: #00c878;        }
.match-write-badge      { background: var(--accent-soft);           color: var(--accent);  }
.match-gr-limited-badge { background: var(--danger-soft);           color: var(--danger);  }
```

Add a new rule after `.match-gr-limited-badge` and register the selector in the shared badge block just above it (currently lines 2990-2995):

```css
.match-score-badge,
.match-mode-badge,
.match-provider-badge,
.match-manual-badge,
.match-write-badge,
.match-gr-limited-badge,
.match-grouped-badge {
```

(only the last line changes -- add `,\n.match-grouped-badge` before the closing `{`), then add:

```css
.match-grouped-badge    { background: rgb(80 140 220 / 15%);        color: #6ea8f0;        }
```

- [ ] **Step 2: Badge on the active/loaded target card**

In `app/static/index.html`, find the target path field (currently lines 330-332):

```html
        <label>Selected target
          <input id="manualTargetPath" readonly />
        </label>
```

Add a badge span right after the closing `</label>`:

```html
        <label>Selected target
          <input id="manualTargetPath" readonly />
        </label>
        <span id="manualGroupedBadge" class="reason-badge" hidden>Multi-file book</span>
```

In `app/static/app.js`, find `loadManualTarget` (currently lines 578-589):

```javascript
  manualContext = data;
  await loadManualCurrentCover();
  $('manualTargetPath').value = data.display_path || data.path || '';
  $('manualSourcePath').value = data.source_path || '';
```

Add the badge toggle right after `manualContext = data;`:

```javascript
  manualContext = data;
  $('manualGroupedBadge').hidden = !data.is_grouped;
  await loadManualCurrentCover();
  $('manualTargetPath').value = data.display_path || data.path || '';
  $('manualSourcePath').value = data.source_path || '';
```

- [ ] **Step 3: Badge on match report cards**

In `app/static/app.js`, find the `summary.innerHTML` block inside `buildMatchCard` (currently lines 1332-1343):

```javascript
  summary.innerHTML = `
    <span class="match-status-badge ${statusClass}">${escapeHtml(statusLabel)}</span>
    ${item.was_manually_applied ? '<span class="match-manual-badge">Manually Applied</span>' : ''}
    <span class="mrep-title">${escapeHtml(bookName)}</span>
    <div class="mrep-badges">
      ${scorePct != null ? `<span class="match-score-badge">${scorePct}%</span>` : ''}
      ${mode ? `<span class="match-mode-badge">${escapeHtml(mode)}</span>` : ''}
      ${item.provider ? `<span class="match-provider-badge">${providerLabel}</span>` : ''}
      ${item.goodreads_rate_limited ? '<span class="match-gr-limited-badge" title="Goodreads was tried for this book but the abs-tract circuit breaker was open (rate-limited by Goodreads), so it was skipped instead of counted as a real no-match.">GR LIMITED</span>' : ''}
      ${writeAction && item.write_action !== 'smart_skipped' ? `<span class="match-write-badge"${writeNote}>${escapeHtml(writeAction)}</span>` : ''}
    </div>
  `;
```

Add the grouped badge inside `mrep-badges`:

```javascript
  summary.innerHTML = `
    <span class="match-status-badge ${statusClass}">${escapeHtml(statusLabel)}</span>
    ${item.was_manually_applied ? '<span class="match-manual-badge">Manually Applied</span>' : ''}
    <span class="mrep-title">${escapeHtml(bookName)}</span>
    <div class="mrep-badges">
      ${scorePct != null ? `<span class="match-score-badge">${scorePct}%</span>` : ''}
      ${mode ? `<span class="match-mode-badge">${escapeHtml(mode)}</span>` : ''}
      ${item.provider ? `<span class="match-provider-badge">${providerLabel}</span>` : ''}
      ${item.is_grouped ? '<span class="match-grouped-badge">Multi-file</span>' : ''}
      ${item.goodreads_rate_limited ? '<span class="match-gr-limited-badge" title="Goodreads was tried for this book but the abs-tract circuit breaker was open (rate-limited by Goodreads), so it was skipped instead of counted as a real no-match.">GR LIMITED</span>' : ''}
      ${writeAction && item.write_action !== 'smart_skipped' ? `<span class="match-write-badge"${writeNote}>${escapeHtml(writeAction)}</span>` : ''}
    </div>
  `;
```

- [ ] **Step 4: Filter option**

In `app/static/index.html`, find the match report filter `<select id="matchReportFilter">` and its `<option>` list (search for `id="matchReportFilter"`). Add a new option, e.g. right after the "manually applied" option:

```html
<option value="multi_file">Multi-file books</option>
```

In `app/static/app.js`, find the filter logic inside `buildMatchReportCards` (currently lines 1250-1263):

```javascript
    if (statusFilter) {
      const s = (item.status || '').toLowerCase();
      const writeAction = (item.write_action || '').toLowerCase();
      const hasMatch = !!item.match;
      if (statusFilter === 'matched' && !hasMatch) continue;
      if (statusFilter === 'goodreads' && (item.provider || '').toLowerCase() !== 'goodreads') continue;
      if (statusFilter === 'gr_limited' && !item.goodreads_rate_limited) continue;
      if (statusFilter === 'smart_skipped' && writeAction !== 'smart_skipped') continue;
      if (statusFilter === 'would_write' && writeAction !== 'would_write') continue;
      if (statusFilter === 'written' && writeAction !== 'written') continue;
      if (statusFilter === 'unmatched' && (hasMatch || s === 'skipped' || s === 'error')) continue;
      if (statusFilter === 'skipped' && s !== 'skipped') continue;
      if (statusFilter === 'error' && s !== 'error') continue;
      if (statusFilter === 'manually_applied' && !item.was_manually_applied) continue;
    }
```

Add the new filter branch:

```javascript
    if (statusFilter) {
      const s = (item.status || '').toLowerCase();
      const writeAction = (item.write_action || '').toLowerCase();
      const hasMatch = !!item.match;
      if (statusFilter === 'matched' && !hasMatch) continue;
      if (statusFilter === 'goodreads' && (item.provider || '').toLowerCase() !== 'goodreads') continue;
      if (statusFilter === 'gr_limited' && !item.goodreads_rate_limited) continue;
      if (statusFilter === 'smart_skipped' && writeAction !== 'smart_skipped') continue;
      if (statusFilter === 'would_write' && writeAction !== 'would_write') continue;
      if (statusFilter === 'written' && writeAction !== 'written') continue;
      if (statusFilter === 'unmatched' && (hasMatch || s === 'skipped' || s === 'error')) continue;
      if (statusFilter === 'skipped' && s !== 'skipped') continue;
      if (statusFilter === 'error' && s !== 'error') continue;
      if (statusFilter === 'manually_applied' && !item.was_manually_applied) continue;
      if (statusFilter === 'multi_file' && !item.is_grouped) continue;
    }
```

- [ ] **Step 5: Manual browser verification**

This task has no backend logic to unit test (pure rendering). Verify in-browser per Task 12's checklist once the container is restarted (deferred to the end of this plan, alongside the other frontend tasks, to avoid restarting mid-plan repeatedly).

- [ ] **Step 6: Commit**

```bash
git add app/static/app.js app/static/index.html app/static/style.css
git commit -m "$(cat <<'EOF'
feat(manual-review): show multi-file badge on active target and report cards

Badges the active Manual Review target and match report cards with
"Multi-file book"/"Multi-file" when is_grouped is true, plus a new
match report filter option -- same signal already shown in the
discovery list (app.js), now visible everywhere a book can be
inspected.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Extract `_write_book_metadata()` shared write helper

**Files:**
- Modify: `app/main.py` (`apply_manual_review_result`, currently lines 2718-2856)
- Test: `app/tests/test_manual_review_apply.py` (existing tests must all still pass unmodified -- this task is a pure refactor with no behavior change)

**Interfaces:**
- Produces:
  ```python
  def _write_book_metadata(
      *,
      source_path: Path,
      metadata: dict[str, Any],
      clues: dict[str, Any],
      score: float,
      fixer_module,
      write_policy: str,
      marker_mode: str,
      writer: str = "auto",
      cover_if_missing: bool = False,
      replace_cover: bool = False,
      backup: bool = False,
  ) -> dict[str, Any]:
      """Returns {"output_kind": str, "output_path": str,
      "metadata_json_path": str, "warning": str}."""
  ```
- Consumed by: `apply_manual_review_result` (this task) and the new edit endpoint (Task 5).

- [ ] **Step 1: Confirm the regression baseline**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest app.tests.test_manual_review_apply -v`
Expected: all tests PASS (this is the "before" snapshot -- the refactor must not change this outcome)

- [ ] **Step 2: Extract the helper**

In `app/main.py`, find `apply_manual_review_result` (currently lines 2718-2856). Replace the entire function with the extracted helper plus a slimmed-down `apply_manual_review_result` that calls it:

```python
def _write_book_metadata(
    *,
    source_path: Path,
    metadata: dict[str, Any],
    clues: dict[str, Any],
    score: float,
    fixer_module,
    write_policy: str,
    marker_mode: str,
    writer: str = "auto",
    cover_if_missing: bool = False,
    replace_cover: bool = False,
    backup: bool = False,
) -> dict[str, Any]:
    """Resolves alone/grouped placement and writes tags-or-JSON-sidecar,
    metadata.json, and the marker. Shared by apply_manual_review_result and
    edit_manual_review_book so the two flows can never diverge -- see
    docs/superpowers/specs/2026-07-07-manual-review-multifile-edit-cover-design.md.
    """
    # Full Overwrite can't be honestly honored on a file that falls back to
    # the ffmpeg writer (build_metadata_args never clears a tag -- see
    # docs/design/manual-review-apply-rewrite-rules.md). Detect this ahead of
    # time and apply anyway with fill-like behavior, surfacing why instead of
    # silently doing something other than what was asked.
    write_policy_warning = ""
    if write_policy == "overwrite" and writer != "mutagen":
        will_use_mutagen = (
            fixer_module.is_mutagen_mp4_candidate(source_path)
            or fixer_module.is_mutagen_mp3_candidate(source_path)
        )
        if not will_use_mutagen:
            write_policy_warning = (
                "Full Overwrite requested, but this file type only supports the "
                "ffmpeg writer, which cannot force-clear a tag; blank fields were "
                "left untouched instead of cleared."
            )

    output_kind = "tags"
    output_path = str(source_path)

    # Follow the same sidecar placement as the rest of the script: a single file
    # alone in its folder (or a grouped multi-file book) gets a folder-level
    # libraforge.json + metadata.json; a loose file sharing its folder gets per-file
    # companions. Grouped books are already routed folder-level via the group_search
    # clue; for a single file we detect "alone" by counting sibling audio files.
    grouped = bool((clues.get("group_search") or {}).get("applied"))
    if grouped:
        alone = False
    else:
        folder = source_path.parent
        try:
            alone = sum(1 for x in folder.iterdir() if x.is_file() and is_audio_file(x)) <= 1
        except OSError:
            alone = True

    if fixer_module.should_write_json_sidecar(source_path, clues):
        output_kind = "json_sidecar"
        sidecar_path = fixer_module.write_m4b_tool_metadata_sidecar(
            source_path, metadata, clues, score, field_policy=write_policy
        )
        output_path = str(sidecar_path)
    else:
        # Back up explicitly so the backup lands in the same (alone-aware)
        # libraforge.json the marker will use, instead of a split per-file copy.
        if backup:
            fixer_module.write_original_metadata_backup(source_path, alone=alone)
        fixer_module.write_tags(
            source_path,
            metadata,
            backup=False,
            writer=writer,
            cover_if_missing=cover_if_missing,
            replace_cover=replace_cover,
            field_policy=write_policy,
        )

    # Audiobookshelf metadata.json, placed by the same alone/group rules.
    metadata_json_path = fixer_module.write_audiobookshelf_metadata_json(
        source_path, metadata, clues, alone,
        skip_blank_fields=(write_policy == "fill"),
    )

    # Mirror the CLI path's written_fields computation (audible-metadata-fixer-v5.py,
    # around WRITE_ACTION_JSON emission): a field counts as "written" only when
    # tags were actually written (not a json-sidecar-only apply) and the resolved
    # value is non-blank. Without this, marker_skip_is_clean() sees an empty
    # written_fields list, believes the real ASIN was never recorded as written,
    # and routes the book into the recovery path on the next scan -- surfacing a
    # "would write" badge in the report for a book that was already applied.
    wrote_tags = output_kind == "tags"
    written_fields = (
        [f for f in fixer_module.FILL_FIELDS if str((metadata or {}).get(f) or "").strip()]
        if wrote_tags else None
    )
    fixer_module.write_marker(
        source=source_path,
        metadata=metadata,
        clues=clues,
        score=score,
        mode=marker_mode,
        aggressive=False,
        output_kind=output_kind,
        alone=alone,
        written_fields=written_fields,
        field_policy=write_policy,
    )

    return {
        "output_kind": output_kind,
        "output_path": output_path,
        "metadata_json_path": str(metadata_json_path),
        "warning": write_policy_warning,
    }


def apply_manual_review_result(req: ManualReviewApplyRequest) -> dict[str, Any]:
    if req.write_policy not in ("fill", "overwrite"):
        raise HTTPException(status_code=400, detail="write_policy must be 'fill' or 'overwrite'")

    context = inspect_manual_review_target(path=req.path, script_name=req.script_name)
    fixer_module = load_fixer_module(req.script_name)
    source_path = Path(context["source_path"])
    file_type = source_path.suffix.lower().lstrip(".")
    metadata = build_manual_metadata_from_result(
        req.selected_result,
        file_type,
        req.edit_mode,
    )

    for key in ("title", "subtitle", "author", "narrator", "series", "sequence", "year", "asin", "publisher", "genre", "summary"):
        if key in req.metadata_override and req.metadata_override[key] is not None:
            metadata[key] = req.metadata_override[key]

    metadata["write_summary"] = True

    if not metadata.get("title") or not metadata.get("author"):
        raise HTTPException(status_code=400, detail="Selected result does not include enough metadata to apply")

    clues = build_context_clues(fixer_module, context["metadata"])
    if context.get("is_grouped"):
        clues["group_search"] = context.get("group_search", {})
    # Required for write_marker's per-field survivor-fallback to work on this
    # path at all -- context["metadata"] is already exactly the right "current
    # tag state" shape (inspect_manual_review_target prefers sidecar/marker
    # over a live probe, same rule as the CLI path). Without this,
    # clues.get("current") is always {} here, so marker.audible silently
    # misreports any field the match didn't supply as blank even when the
    # real tag survives on disk. See docs/design/manual-review-apply-rewrite-rules.md.
    clues["current"] = dict(context["metadata"])

    score = float(req.selected_result.get("score", 1.0) or 1.0)

    write_result = _write_book_metadata(
        source_path=source_path,
        metadata=metadata,
        clues=clues,
        score=score,
        fixer_module=fixer_module,
        write_policy=req.write_policy,
        marker_mode=f"manual_{req.edit_mode}",
        writer=req.writer,
        cover_if_missing=req.cover_if_missing,
        replace_cover=req.replace_cover,
        backup=req.backup,
    )

    result = {
        "status": "applied",
        "target_path": context["display_path"],
        "source_path": context["source_path"],
        "output_kind": write_result["output_kind"],
        "output_path": write_result["output_path"],
        "metadata_json_path": write_result["metadata_json_path"],
        "edit_mode": req.edit_mode,
        "write_policy": req.write_policy,
        "metadata_preview": metadata,
    }
    if write_result["warning"]:
        result["warning"] = write_result["warning"]
    return result
```

- [ ] **Step 3: Run the existing test suite to confirm zero behavior change**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest app.tests.test_manual_review_apply -v`
Expected: all tests PASS, identical to Step 1's baseline (same test names, same pass count) -- this is the regression proof for the refactor.

- [ ] **Step 4: Run the full suite**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest discover -s app/tests -p "test_*.py"`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add app/main.py
git commit -m "$(cat <<'EOF'
refactor(manual-review): extract _write_book_metadata from apply_manual_review_result

Pure extraction, no behavior change (existing test_manual_review_apply
suite passes unmodified). Prepares for the new direct-edit endpoint
(edit_manual_review_book) to share this exact write sequence instead
of duplicating it -- two copies of this sequence is exactly the kind
of drift that caused this session's grouped-book ASIN bug.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `POST /api/manual-review/edit` endpoint

**Files:**
- Modify: `app/main.py` (new `ManualReviewEditRequest` model near `ManualReviewApplyRequest`, currently lines 1043-1057; new `edit_manual_review_book` function near `apply_manual_review_result`; new route near line 6194)
- Test: `app/tests/test_manual_review_edit.py` (new)

**Interfaces:**
- Produces: `POST /api/manual-review/edit` -> `edit_manual_review_book(req: ManualReviewEditRequest) -> dict[str, Any]`, response shape `{"status": "applied", "target_path": str, "source_path": str, "output_kind": str, "output_path": str, "metadata_json_path": str, "metadata_preview": dict, "warning"?: str}` (same shape family as apply's response, minus `edit_mode`/`write_policy` which don't apply here).
- Consumes: `_write_book_metadata` (Task 4), `inspect_manual_review_target`, `build_context_clues`.

- [ ] **Step 1: Write the failing test**

Create `app/tests/test_manual_review_edit.py`:

```python
"""POST /api/manual-review/edit -- direct field editing without a prior
match/search. Reuses _write_book_metadata (shared with
apply_manual_review_result) with write_policy always "overwrite" (blank
field always clears that tag -- there is no match value to fall back to)
and score always 1.0 (a direct user edit is definitionally full-confidence).
See docs/superpowers/specs/2026-07-07-manual-review-multifile-edit-cover-design.md.
"""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import main


class ManualReviewEditTests(unittest.TestCase):
    def _context(self, is_grouped=False, group_search=None):
        return {
            "source_path": "/library/Book/book.m4b",
            "display_path": "/library/Book",
            "is_grouped": is_grouped,
            "group_search": group_search or {},
            "metadata": {
                "title": "Old Title",
                "author": "Old Author",
                "asin": "B0OLDASIN01",
            },
        }

    def _fixer(self, written: dict, mutagen_candidate: bool = True):
        return SimpleNamespace(
            FILL_FIELDS=("title", "author", "series", "sequence", "narrator", "year", "asin", "genre", "subtitle"),
            clean_text=lambda value: value,
            clean_author_value=lambda value: value,
            normalize_book_number=lambda value: value,
            should_write_json_sidecar=lambda source, clues: bool(
                (clues.get("group_search") or {}).get("applied")
            ),
            is_mutagen_mp4_candidate=lambda source: mutagen_candidate,
            is_mutagen_mp3_candidate=lambda source: False,
            write_audiobookshelf_metadata_json=lambda source, metadata, clues, alone, fill_missing=False, skip_blank_fields=False: (
                written.setdefault("meta_json_skip_blank", skip_blank_fields),
                Path("/library/Book/metadata.json"),
            )[1],
            write_tags=lambda source, metadata, **kwargs: written.update(
                tags_metadata=metadata, tags_field_policy=kwargs.get("field_policy")
            ),
            write_m4b_tool_metadata_sidecar=lambda source, metadata, clues, score, field_policy="legacy": (
                written.update(sidecar_metadata=metadata, sidecar_field_policy=field_policy),
                Path("/library/Book/libraforge.json"),
            )[1],
            write_marker=lambda **kwargs: written.update(marker_kwargs=kwargs),
        )

    def _request(self, **overrides) -> "main.ManualReviewEditRequest":
        fields = {
            "path": "/library/Book",
            "title": "New Title",
            "author": "New Author",
            "subtitle": "",
            "narrator": "",
            "series": "",
            "sequence": "",
            "year": "",
            "asin": "",
            "isbn": "",
            "publisher": "",
            "genre": "",
            "summary": "",
            "cover_url": "",
        }
        fields.update(overrides)
        return main.ManualReviewEditRequest(**fields)

    def test_requires_title_and_author(self):
        req = self._request(title="")
        with patch.object(main, "inspect_manual_review_target", return_value=self._context()):
            with self.assertRaises(main.HTTPException) as ctx:
                main.edit_manual_review_book(req)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_blank_field_clears_tag_single_file(self):
        written = {}
        req = self._request(title="New Title", author="New Author", asin="")
        with (
            patch.object(main, "inspect_manual_review_target", return_value=self._context()),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            result = main.edit_manual_review_book(req)

        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["output_kind"], "tags")
        self.assertEqual(written["tags_field_policy"], "overwrite")
        self.assertEqual(written["tags_metadata"]["asin"], "")
        self.assertEqual(written["tags_metadata"]["title"], "New Title")
        self.assertFalse(written["meta_json_skip_blank"])
        self.assertEqual(written["marker_kwargs"]["field_policy"], "overwrite")
        self.assertEqual(written["marker_kwargs"]["score"], 1.0)
        self.assertEqual(written["marker_kwargs"]["mode"], "manual_edit")

    def test_grouped_book_writes_sidecar_only(self):
        written = {}
        req = self._request(title="New Title", author="New Author")
        ctx = self._context(
            is_grouped=True,
            group_search={"applied": True, "folder": "/library/Book", "file_count": 12},
        )
        with (
            patch.object(main, "inspect_manual_review_target", return_value=ctx),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            result = main.edit_manual_review_book(req)

        self.assertEqual(result["output_kind"], "json_sidecar")
        self.assertNotIn("tags_metadata", written)
        self.assertEqual(written["sidecar_field_policy"], "overwrite")

    def test_ffmpeg_fallback_surfaces_warning(self):
        written = {}
        req = self._request(title="New Title", author="New Author")
        with (
            patch.object(main, "inspect_manual_review_target", return_value=self._context()),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written, mutagen_candidate=False)),
        ):
            result = main.edit_manual_review_book(req)

        self.assertIn("warning", result)
        self.assertIn("Full Overwrite", result["warning"])

    def test_cover_url_threads_replace_cover(self):
        written = {}
        req = self._request(title="New Title", author="New Author", cover_url="file:///tmp/cover.jpg")
        with (
            patch.object(main, "inspect_manual_review_target", return_value=self._context()),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            main.edit_manual_review_book(req)

        self.assertEqual(written["tags_metadata"]["cover_url"], "file:///tmp/cover.jpg")

    def test_no_cover_url_does_not_touch_cover(self):
        written = {}
        req = self._request(title="New Title", author="New Author")
        with (
            patch.object(main, "inspect_manual_review_target", return_value=self._context()),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            main.edit_manual_review_book(req)

        self.assertEqual(written["tags_metadata"]["cover_url"], "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest app.tests.test_manual_review_edit -v`
Expected: FAIL with `AttributeError: module 'app.main' has no attribute 'ManualReviewEditRequest'`

- [ ] **Step 3: Add the request model**

In `app/main.py`, find `ManualReviewApplyRequest` (currently lines 1043-1057):

```python
class ManualReviewApplyRequest(BaseModel):
    path: str
    script_name: str = Field(default_factory=default_fixer_script)
    selected_result: dict[str, Any]
    edit_mode: str
    backup: bool = False
    cover_if_missing: bool = False
    replace_cover: bool = False
    writer: str = "auto"
    metadata_override: dict[str, Any] = Field(default_factory=dict)
    # "fill": only write fields with a value; blank fields are left untouched.
    # "overwrite": write every field exactly as shown, including blanks (a
    # blank clears that tag). See docs/design/manual-review-apply-rewrite-rules.md.
    write_policy: str = "fill"
```

Add a new model right after it:

```python
class ManualReviewEditRequest(BaseModel):
    """Direct field editing, no match/search involved -- see
    docs/superpowers/specs/2026-07-07-manual-review-multifile-edit-cover-design.md.
    Always writes with field_policy="overwrite" (a blank field here always
    clears that tag) and score=1.0 (no match to carry a confidence score
    from).
    """
    path: str
    script_name: str = Field(default_factory=default_fixer_script)
    title: str
    subtitle: str = ""
    author: str
    narrator: str = ""
    series: str = ""
    sequence: str = ""
    year: str = ""
    asin: str = ""
    isbn: str = ""
    publisher: str = ""
    genre: str = ""
    summary: str = ""
    cover_url: str = ""
```

- [ ] **Step 4: Add `edit_manual_review_book`**

In `app/main.py`, find the end of `apply_manual_review_result` (right after the extraction in Task 4, ends with `return result`). Add the new function right after it:

```python
def edit_manual_review_book(req: ManualReviewEditRequest) -> dict[str, Any]:
    if not req.title or not req.author:
        raise HTTPException(status_code=400, detail="Title and author are required")

    context = inspect_manual_review_target(path=req.path, script_name=req.script_name)
    fixer_module = load_fixer_module(req.script_name)
    source_path = Path(context["source_path"])

    metadata = {
        "title": req.title,
        "subtitle": req.subtitle,
        "author": req.author,
        "narrator": req.narrator,
        "series": req.series,
        "sequence": req.sequence,
        "year": req.year,
        "asin": req.asin,
        "isbn": req.isbn,
        "publisher": req.publisher,
        "genre": req.genre,
        "summary": req.summary,
        "write_summary": True,
        "edit_mode": "full",
        "cover_url": req.cover_url,
    }

    clues = build_context_clues(fixer_module, context["metadata"])
    if context.get("is_grouped"):
        clues["group_search"] = context.get("group_search", {})
    clues["current"] = dict(context["metadata"])

    write_result = _write_book_metadata(
        source_path=source_path,
        metadata=metadata,
        clues=clues,
        score=1.0,
        fixer_module=fixer_module,
        write_policy="overwrite",
        marker_mode="manual_edit",
        writer="auto",
        cover_if_missing=False,
        replace_cover=bool(req.cover_url),
        backup=False,
    )

    result = {
        "status": "applied",
        "target_path": context["display_path"],
        "source_path": context["source_path"],
        "output_kind": write_result["output_kind"],
        "output_path": write_result["output_path"],
        "metadata_json_path": write_result["metadata_json_path"],
        "metadata_preview": metadata,
    }
    if write_result["warning"]:
        result["warning"] = write_result["warning"]
    return result
```

- [ ] **Step 5: Add the route**

In `app/main.py`, find the apply route (currently lines 6194-6196):

```python
@app.post("/api/manual-review/apply")
def apply_manual_review(req: ManualReviewApplyRequest) -> dict[str, Any]:
    return apply_manual_review_result(req)
```

Add the new route right after it:

```python
@app.post("/api/manual-review/edit")
def edit_manual_review(req: ManualReviewEditRequest) -> dict[str, Any]:
    return edit_manual_review_book(req)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest app.tests.test_manual_review_edit -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Run the full suite**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest discover -s app/tests -p "test_*.py"`
Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add app/main.py app/tests/test_manual_review_edit.py
git commit -m "$(cat <<'EOF'
feat(manual-review): add direct field-edit endpoint

POST /api/manual-review/edit lets a user save a book's fields
directly (title/author/.../summary + cover_url) without going through
the search/match flow. Always writes with field_policy="overwrite" --
a blank field always clears that tag, since there's no match value to
fall back to. Reuses _write_book_metadata, so grouped/multi-file books
correctly route to the JSON sidecar exactly like the existing apply
flow, with no separate write path to drift.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `POST /api/manual-review/cover-upload` endpoint

**Files:**
- Modify: `app/main.py` (imports around line 22-24, new endpoint near the cover routes around line 6180-6192)
- Test: `app/tests/test_manual_review_cover_upload.py` (new)

**Interfaces:**
- Produces: `POST /api/manual-review/cover-upload` (multipart form, field name `file`) -> `{"cover_url": "file:///.../<uuid>.<ext>"}`. The returned `file://` URL is directly usable as `ManualReviewEditRequest.cover_url` / `ManualReviewApplyRequest`'s underlying `metadata["cover_url"]`, since `download_cover_bytes()` (`scripts/audible-metadata-fixer-v5.py`) already fetches arbitrary URLs via `urllib.request.urlopen`, which handles `file://` natively.

- [ ] **Step 1: Write the failing test**

Create `app/tests/test_manual_review_cover_upload.py`:

```python
"""POST /api/manual-review/cover-upload -- stores an uploaded cover image
as a temp file and returns a file:// URL. That URL is used directly as
metadata["cover_url"] by the edit/apply write path -- download_cover_bytes
(scripts/audible-metadata-fixer-v5.py) already fetches arbitrary URLs via
urllib, which handles file:// with no extra code. See
docs/superpowers/specs/2026-07-07-manual-review-multifile-edit-cover-design.md.
"""
import unittest
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi.testclient import TestClient

from app.main import app

# Smallest possible valid 1x1 JPEG (magic bytes only matter for sniffing).
_JPEG_BYTES = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300"
    + "01" * 64
    + "ffd9"
)


class CoverUploadTests(unittest.TestCase):
    def test_upload_returns_file_url_and_file_exists_with_correct_bytes(self):
        client = TestClient(app)
        res = client.post(
            "/api/manual-review/cover-upload",
            files={"file": ("cover.jpg", _JPEG_BYTES, "image/jpeg")},
        )
        self.assertEqual(res.status_code, 200)
        cover_url = res.json()["cover_url"]
        self.assertTrue(cover_url.startswith("file://"))

        stored_path = Path(unquote(urlparse(cover_url).path))
        self.assertTrue(stored_path.is_file())
        self.assertEqual(stored_path.read_bytes(), _JPEG_BYTES)
        self.assertEqual(stored_path.suffix, ".jpg")

    def test_rejects_non_image_upload(self):
        client = TestClient(app)
        res = client.post(
            "/api/manual-review/cover-upload",
            files={"file": ("notes.txt", b"not an image", "text/plain")},
        )
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest app.tests.test_manual_review_cover_upload -v`
Expected: FAIL with 404 (route does not exist yet)

- [ ] **Step 3: Add the `UploadFile`/`File` import**

In `app/main.py`, find the fastapi import (currently line 22):

```python
from fastapi import FastAPI, HTTPException
```

Change to:

```python
from fastapi import FastAPI, File, HTTPException, UploadFile
```

- [ ] **Step 4: Add the endpoint**

In `app/main.py`, find the `current-cover` route (currently lines 6180-6191):

```python
@app.get("/api/manual-review/current-cover")
def current_manual_review_cover(
    path: str,
    script_name: str = "",
) -> Response:
    context = inspect_manual_review_target(path=path, script_name=script_name or default_fixer_script())
    cover_bytes, media_type = extract_current_cover(Path(context["source_path"]))
    return Response(
        content=cover_bytes,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )
```

Add the new route right after it:

```python
COVER_UPLOAD_DIR = Path(tempfile.gettempdir()) / "libraforge-cover-uploads"


@app.post("/api/manual-review/cover-upload")
async def upload_manual_review_cover(file: UploadFile = File(...)) -> dict[str, str]:
    data = await file.read()
    if data.startswith(b"\xff\xd8\xff"):
        suffix = ".jpg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix = ".png"
    else:
        raise HTTPException(status_code=400, detail="Uploaded file is not a JPEG or PNG image")

    COVER_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = COVER_UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(data)
    return {"cover_url": dest.as_uri()}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest app.tests.test_manual_review_cover_upload -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full suite**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest discover -s app/tests -p "test_*.py"`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add app/main.py app/tests/test_manual_review_cover_upload.py
git commit -m "$(cat <<'EOF'
feat(manual-review): add cover-upload endpoint for the edit dialog's Cover tab

Stores an uploaded JPEG/PNG as a temp file and returns a file:// URL,
which download_cover_bytes (scripts/audible-metadata-fixer-v5.py)
already knows how to fetch via urllib -- no new embed code path
needed, the upload just becomes a normal cover_url.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Edit dialog skeleton + Fields tab (frontend)

**Files:**
- Create: `app/static/manual-review-edit.js`
- Modify: `app/static/index.html` (add "Edit Book" button near `manualReloadCoverBtn`, load the new script)
- Modify: `app/static/style.css` (tab CSS)

**Interfaces:**
- Produces: `window.ManualReviewEdit.open()` -- opens the Edit dialog pre-filled from `manualContext.metadata`, with a Fields tab (Save wired to `POST /api/manual-review/edit`) and an initially-empty Cover tab placeholder (populated in Task 8/9).
- Consumes (from `app.js`, already global, no import needed): `manualContext`, `$`, `escapeHtml`, `manualCurrentCoverUrl`.

- [ ] **Step 1: Add the button and script tag**

In `app/static/index.html`, find the actions bar (currently lines 359-362):

```html
      <div class="actions">
        <button id="manualSearchBtn" class="secondary">Search For Selected Target</button>
        <button id="manualReloadCoverBtn" class="secondary">Reload Current Cover</button>
      </div>
```

Add the Edit button:

```html
      <div class="actions">
        <button id="manualSearchBtn" class="secondary">Search For Selected Target</button>
        <button id="manualReloadCoverBtn" class="secondary">Reload Current Cover</button>
        <button id="manualEditBtn" class="secondary">Edit Book</button>
      </div>
```

Find the script tags at the bottom of the file (currently lines 375-376):

```html
  <script src="/static/ui-common.js?v=20260705-2"></script>
  <script src="/static/app.js?v=20260705-3"></script>
```

Add the new script after `app.js`:

```html
  <script src="/static/ui-common.js?v=20260705-2"></script>
  <script src="/static/app.js?v=20260705-3"></script>
  <script src="/static/manual-review-edit.js?v=20260707-1"></script>
```

- [ ] **Step 2: Add tab CSS**

In `app/static/style.css`, find the `.manual-apply-edit-fields` block (currently lines 2790-2815) and add new rules right after it:

```css
.mre-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--border);
}

.mre-tab-btn {
  background: none;
  border: none;
  padding: 8px 16px;
  cursor: pointer;
  color: var(--muted);
  border-bottom: 2px solid transparent;
}

.mre-tab-btn.active {
  color: var(--text);
  border-bottom-color: var(--accent);
}

.mre-tab-panel {
  display: none;
}

.mre-tab-panel.active {
  display: block;
}
```

- [ ] **Step 3: Create `app/static/manual-review-edit.js` with the dialog skeleton and Fields tab**

```javascript
// Standalone "Edit Book" dialog for Manual Review: directly edit a book's
// fields (pre-filled from current tags/sidecar) without going through the
// search/match flow. A dedicated dialog, not a reuse of the match-apply
// dialog (manualApplyEditDialog in app.js) -- see
// docs/superpowers/specs/2026-07-07-manual-review-multifile-edit-cover-design.md.
//
// Relies on globals already defined by app.js, loaded before this file:
// manualContext, $, escapeHtml, manualCurrentCoverUrl.

let mrePendingCoverUrl = '';

function mreBuildDialog() {
  if ($('mreDialog')) return;

  const dlg = document.createElement('dialog');
  dlg.id = 'mreDialog';
  dlg.className = 'manual-apply-dialog';
  dlg.innerHTML = `
    <h3 class="manual-apply-title">Edit Book</h3>
    <p id="mreContext" class="manual-apply-body"></p>
    <div class="mre-tabs">
      <button type="button" id="mreTabFieldsBtn" class="mre-tab-btn active">Fields</button>
      <button type="button" id="mreTabCoverBtn" class="mre-tab-btn">Cover</button>
    </div>
    <div id="mreFieldsPanel" class="mre-tab-panel active">
      <p class="manual-apply-write-policy-note">
        A blank field is saved as blank and clears that tag. Separate multiple
        genres with a comma (e.g. "Fantasy, LitRPG") &mdash; each is saved as
        its own genre tag, not one combined genre.
      </p>
      <div class="manual-apply-edit-fields">
        <label>Title<input id="mreTitle" /></label>
        <label>Subtitle<input id="mreSubtitle" /></label>
        <label>Author<input id="mreAuthor" /></label>
        <label>Narrator<input id="mreNarrator" /></label>
        <label>Series<input id="mreSeries" /></label>
        <label>Sequence<input id="mreSequence" /></label>
        <label>Year<input id="mreYear" /></label>
        <label>ASIN<input id="mreAsin" /></label>
        <label>ISBN<input id="mreIsbn" /></label>
        <label>Publisher<input id="mrePublisher" /></label>
        <label>Genre<input id="mreGenre" placeholder="e.g. Fantasy, LitRPG" /></label>
        <label class="mae-full-width">Comment / Summary<textarea id="mreSummary" rows="4"></textarea></label>
      </div>
    </div>
    <div id="mreCoverPanel" class="mre-tab-panel"></div>
    <p id="mreResult" class="manual-apply-body" hidden></p>
    <p id="mreWarning" class="manual-apply-warning" hidden></p>
    <div class="manual-apply-actions">
      <button id="mreCancelBtn" class="secondary">Cancel</button>
      <button id="mreSaveBtn">Save</button>
    </div>`;
  document.body.appendChild(dlg);

  $('mreTabFieldsBtn').addEventListener('click', () => mreSwitchTab('fields'));
  $('mreTabCoverBtn').addEventListener('click', () => mreSwitchTab('cover'));
}

function mreSwitchTab(name) {
  const fieldsActive = name === 'fields';
  $('mreTabFieldsBtn').classList.toggle('active', fieldsActive);
  $('mreTabCoverBtn').classList.toggle('active', !fieldsActive);
  $('mreFieldsPanel').classList.toggle('active', fieldsActive);
  $('mreCoverPanel').classList.toggle('active', !fieldsActive);
}

function mreFillFieldsFromCurrent() {
  const m = (manualContext && manualContext.metadata) || {};
  $('mreTitle').value = m.title || '';
  $('mreSubtitle').value = m.subtitle || '';
  $('mreAuthor').value = m.author || '';
  $('mreNarrator').value = m.narrator || '';
  $('mreSeries').value = m.series || '';
  $('mreSequence').value = m.sequence || '';
  $('mreYear').value = m.year || '';
  $('mreAsin').value = m.asin || '';
  $('mreIsbn').value = m.isbn || '';
  $('mrePublisher').value = m.publisher || '';
  $('mreGenre').value = m.genre || '';
  $('mreSummary').value = m.summary || '';
}

async function mreSave() {
  const saveBtn = $('mreSaveBtn');
  saveBtn.disabled = true;
  saveBtn.textContent = 'Saving...';
  $('mreResult').hidden = true;
  $('mreWarning').hidden = true;

  try {
    const res = await fetch('/api/manual-review/edit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: manualContext.path,
        script_name: $('script').value,
        title: $('mreTitle').value.trim(),
        subtitle: $('mreSubtitle').value.trim(),
        author: $('mreAuthor').value.trim(),
        narrator: $('mreNarrator').value.trim(),
        series: $('mreSeries').value.trim(),
        sequence: $('mreSequence').value.trim(),
        year: $('mreYear').value.trim(),
        asin: $('mreAsin').value.trim(),
        isbn: $('mreIsbn').value.trim(),
        publisher: $('mrePublisher').value.trim(),
        genre: $('mreGenre').value.trim(),
        summary: $('mreSummary').value.trim(),
        cover_url: mrePendingCoverUrl,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      $('mreResult').hidden = false;
      $('mreResult').textContent = data.detail || 'Save failed';
      return;
    }
    $('mreResult').hidden = false;
    $('mreResult').textContent = `Saved (${data.output_kind === 'json_sidecar' ? 'multi-file sidecar' : 'embedded tags'}).`;
    if (data.warning) {
      $('mreWarning').hidden = false;
      $('mreWarning').textContent = data.warning;
    }
    mrePendingCoverUrl = '';
    await loadManualTarget(manualContext.path);
  } catch (e) {
    $('mreResult').hidden = false;
    $('mreResult').textContent = 'Error: ' + e.message;
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = 'Save';
  }
}

function mreOpen() {
  if (!manualContext?.path) {
    alert('Load a manual review target first.');
    return;
  }
  mreBuildDialog();
  mrePendingCoverUrl = '';
  mreSwitchTab('fields');
  $('mreContext').textContent = `Editing: ${manualContext.display_path || manualContext.path}`;
  $('mreResult').hidden = true;
  $('mreWarning').hidden = true;
  mreFillFieldsFromCurrent();

  const dlg = $('mreDialog');

  function onCancel() { dlg.close(); }
  function onSave() { mreSave(); }

  $('mreCancelBtn').addEventListener('click', onCancel, { once: true });
  $('mreSaveBtn').addEventListener('click', onSave);
  dlg.addEventListener('cancel', onCancel, { once: true });
  dlg.showModal();
}

window.ManualReviewEdit = { open: mreOpen };

document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('manualEditBtn');
  if (btn) btn.addEventListener('click', mreOpen);
});
```

Note: `$('mreSaveBtn').addEventListener('click', onSave)` is intentionally not `{ once: true }` and not removed on cancel/close, since `mreBuildDialog()` only creates the dialog once (guarded by `if ($('mreDialog')) return;`) but `mreOpen()` runs on every click of "Edit Book" -- re-adding the same `onSave` reference would double-fire. Guard against this by removing any previously attached listener before adding a new one:

```javascript
  const dlg = $('mreDialog');

  function onCancel() { dlg.close(); }
  function onSave() { mreSave(); }

  $('mreCancelBtn').addEventListener('click', onCancel, { once: true });
  $('mreSaveBtn').replaceWith($('mreSaveBtn').cloneNode(true));
  $('mreSaveBtn').addEventListener('click', onSave);
  dlg.addEventListener('cancel', onCancel, { once: true });
  dlg.showModal();
```

(`cloneNode` strips any previously attached listeners cheaply, matching the fact this button has no other state to preserve.) Replace the `onSave` wiring lines in the `mreOpen` function above with this corrected version.

- [ ] **Step 4: Manual browser verification**

No backend logic in this task to unit test. Verify per Task 12's checklist once the container is restarted.

- [ ] **Step 5: Commit**

```bash
git add app/static/manual-review-edit.js app/static/index.html app/static/style.css
git commit -m "$(cat <<'EOF'
feat(manual-review): add Edit Book dialog with Fields tab

New dedicated dialog (app/static/manual-review-edit.js), triggered by
a new "Edit Book" button next to Reload Current Cover. Pre-fills from
manualContext.metadata (already loaded, no new fetch) and saves via
the new POST /api/manual-review/edit endpoint. Cover tab is a
placeholder here, filled in by the next two tasks.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Cover tab -- search sub-feature

**Files:**
- Modify: `app/static/manual-review-edit.js` (populate `#mreCoverPanel`)

**Interfaces:**
- Consumes: the existing provider search dispatch already in `app.js`'s `searchManualTarget()` -- rather than re-implementing per-provider dispatch, this task factors the provider-dispatch body of `searchManualTarget()` into a small reusable function in `app.js` that both the existing search flow and this new Cover-tab search can call.

- [ ] **Step 1: Factor out the provider search call in `app.js`**

In `app/static/app.js`, find `searchManualTarget` (currently lines 810-884). Extract the provider-dispatch body (everything that builds `res`) into a new function `runManualProviderSearch()`, and have `searchManualTarget` call it:

```javascript
async function runManualProviderSearch() {
  const provider = $('manualProvider').value;
  let res;

  if (provider === 'abs') {
    res = await fetch('/api/abs/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: $('manualQuery').value.trim(),
        provider: $('manualAbsProvider').value || 'audible',
        limit: 10,
      }),
    });
  } else if (provider === 'abs-agg') {
    res = await searchAbsAgg({
      query: $('manualQuery').value.trim(),
      provider: $('manualAbsAggProvider').value,
      providerParams: $('manualAbsAggParams').value.trim(),
      baseUrl: $('manualAbsAggUrl').value.trim(),
      limit: 10,
    });
  } else if (provider === 'graphicaudio' || provider === 'soundbooththeater') {
    res = await searchAbsAgg({
      query: $('manualTitle').value.trim() || $('manualQuery').value.trim(),
      author: $('manualAuthor').value.trim(),
      provider,
      limit: 10,
    });
  } else if (provider === 'goodreads' || provider === 'kindle') {
    res = await fetch('/api/abs-tract/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: $('manualTitle').value.trim() || $('manualQuery').value.trim(),
        author: $('manualAuthor').value.trim(),
        provider,
        limit: 10,
      }),
    });
  } else {
    const payload = {
      query: $('manualQuery').value.trim(),
      auth_file: $('authFile').value.trim(),
      metadata: collectManualMetadata(),
      limit: 10,
      script_name: $('script').value,
    };
    res = await fetch('/api/m4b/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }

  return res;
}

async function searchManualTarget() {
  if (!manualContext?.path) {
    alert('Load a manual review target first.');
    return;
  }

  // When "search from original backup" is active, reload the displayed metadata
  // from pre-apply backup tags before running the search so the form reflects
  // what the file contained before the fixer ever touched it.
  if ($('force').checked && $('forceOriginal').checked) {
    await loadManualTarget(manualContext.path, true);
  }

  const res = await runManualProviderSearch();
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Search failed');
    return;
  }
  $('manualMeta').textContent = data.queries?.length ? `Search queries tried: ${data.queries.join(' | ')}` : 'No search queries were produced.';
  renderManualSearchResults(data.results || []);
}
```

This is a pure extraction (same logic, same order, same branches) -- no behavior change for the existing search flow.

- [ ] **Step 2: Manual verification of the extraction**

Run the app locally (or via the container) and confirm the existing "Search For Selected Target" button still works exactly as before for at least one provider (e.g. Audible, the default `else` branch). This is a JS-only change with no unit test harness in this repo for frontend code; verify at the same time as Task 12's full checklist to avoid a mid-plan container restart.

- [ ] **Step 3: Add the Cover tab's search UI**

In `app/static/manual-review-edit.js`, replace the placeholder panel:

```javascript
    <div id="mreCoverPanel" class="mre-tab-panel"></div>
```

with a populated one:

```javascript
    <div id="mreCoverPanel" class="mre-tab-panel">
      <div class="cover-comparison">
        <div>
          <strong>Current</strong>
          <img id="mreCurrentCoverImg" class="cover-thumb" alt="Current book cover" />
          <p id="mreCurrentCoverNote" class="note" hidden>No current cover</p>
        </div>
        <div>
          <strong>Pending</strong>
          <img id="mrePendingCoverImg" class="cover-thumb" alt="Pending cover" hidden />
          <p id="mrePendingCoverNote" class="note">No new cover selected -- current cover is kept.</p>
        </div>
      </div>
      <div class="actions">
        <input id="mreCoverQuery" placeholder="Title Author" />
        <select id="mreCoverProvider">
          <option value="audible">Audible</option>
          <option value="goodreads">Goodreads</option>
          <option value="kindle">Kindle</option>
        </select>
        <button id="mreCoverSearchBtn" class="secondary" type="button">Search Covers</button>
      </div>
      <div id="mreCoverResults" class="results-grid"></div>
      <hr />
      <div class="actions">
        <input id="mreCoverUrlInput" placeholder="https://... or paste an image URL" />
        <button id="mreCoverUrlUseBtn" class="secondary" type="button">Use URL</button>
      </div>
      <div class="actions">
        <input id="mreCoverFileInput" type="file" accept="image/jpeg,image/png" />
      </div>
    </div>
```

Add the search wiring after `mreSwitchTab`:

```javascript
async function mreSearchCovers() {
  const query = $('mreCoverQuery').value.trim();
  if (!query) {
    alert('Enter a search query first.');
    return;
  }
  const provider = $('mreCoverProvider').value;
  const btn = $('mreCoverSearchBtn');
  btn.disabled = true;
  btn.textContent = 'Searching...';
  try {
    let res;
    if (provider === 'audible') {
      res = await fetch('/api/m4b/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          auth_file: $('authFile').value.trim(),
          metadata: {},
          limit: 10,
          script_name: $('script').value,
        }),
      });
    } else {
      res = await fetch('/api/abs-tract/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, provider, limit: 10 }),
      });
    }
    const data = await res.json();
    if (!res.ok) {
      alert(data.detail || 'Cover search failed');
      return;
    }
    mreRenderCoverResults(data.results || []);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Search Covers';
  }
}

function mreRenderCoverResults(results) {
  const withCovers = results.filter((r) => r.cover_url);
  $('mreCoverResults').innerHTML = withCovers.length
    ? withCovers.map((r, i) => `
        <article class="result-card">
          <img class="cover-thumb" src="${escapeHtml(r.cover_url)}" alt="${escapeHtml(r.title || 'Cover option')}" />
          <p>${escapeHtml(r.title || '')}</p>
          <button type="button" class="secondary" data-mre-cover-pick="${i}">Use this cover</button>
        </article>
      `).join('')
    : '<p class="note">No covers found for this query.</p>';

  for (const button of $('mreCoverResults').querySelectorAll('button[data-mre-cover-pick]')) {
    button.addEventListener('click', () => {
      const index = Number(button.getAttribute('data-mre-cover-pick'));
      mreSetPendingCover(withCovers[index].cover_url);
    });
  }
}

function mreSetPendingCover(url) {
  mrePendingCoverUrl = url;
  $('mrePendingCoverImg').src = url;
  $('mrePendingCoverImg').hidden = false;
  $('mrePendingCoverNote').hidden = true;
}
```

Wire the search button in `mreBuildDialog`, right after the tab button listeners:

```javascript
  $('mreTabFieldsBtn').addEventListener('click', () => mreSwitchTab('fields'));
  $('mreTabCoverBtn').addEventListener('click', () => mreSwitchTab('cover'));
  $('mreCoverSearchBtn').addEventListener('click', mreSearchCovers);
```

- [ ] **Step 4: Show the current cover when the dialog opens**

In `mreOpen()`, after `mreFillFieldsFromCurrent();`, add:

```javascript
  if (manualCurrentCoverUrl) {
    $('mreCurrentCoverImg').src = manualCurrentCoverUrl;
    $('mreCurrentCoverImg').hidden = false;
    $('mreCurrentCoverNote').hidden = true;
  } else {
    $('mreCurrentCoverImg').hidden = true;
    $('mreCurrentCoverNote').hidden = false;
  }
  $('mrePendingCoverImg').hidden = true;
  $('mrePendingCoverImg').src = '';
  $('mrePendingCoverNote').hidden = false;
```

- [ ] **Step 5: Commit**

```bash
git add app/static/app.js app/static/manual-review-edit.js
git commit -m "$(cat <<'EOF'
feat(manual-review): Cover tab search (Audible/Goodreads/Kindle thumbnails)

Factors runManualProviderSearch out of app.js's searchManualTarget
(pure extraction, existing search flow unchanged) and reuses it for
the new Edit dialog's Cover tab, which shows only cover thumbnails
from the results -- picking one sets the dialog's pending cover_url,
applied together with the Fields tab on Save.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Cover tab -- URL and upload sub-feature

**Files:**
- Modify: `app/static/manual-review-edit.js`

**Interfaces:**
- Consumes: `POST /api/manual-review/cover-upload` (Task 6).

- [ ] **Step 1: Wire the URL input**

In `app/static/manual-review-edit.js`, add after `mreSetPendingCover`:

```javascript
function mreUseCoverUrl() {
  const url = $('mreCoverUrlInput').value.trim();
  if (!url) {
    alert('Enter a cover image URL first.');
    return;
  }
  mreSetPendingCover(url);
}

async function mreUploadCoverFile(file) {
  const previewUrl = URL.createObjectURL(file);
  $('mrePendingCoverImg').src = previewUrl;
  $('mrePendingCoverImg').hidden = false;
  $('mrePendingCoverNote').hidden = true;

  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch('/api/manual-review/cover-upload', { method: 'POST', body: formData });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Cover upload failed');
    return;
  }
  mrePendingCoverUrl = data.cover_url;
}
```

Wire both controls in `mreBuildDialog`, right after `$('mreCoverSearchBtn').addEventListener('click', mreSearchCovers);`:

```javascript
  $('mreCoverUrlUseBtn').addEventListener('click', mreUseCoverUrl);
  $('mreCoverFileInput').addEventListener('change', () => {
    const file = $('mreCoverFileInput').files[0];
    if (file) mreUploadCoverFile(file);
  });
```

- [ ] **Step 2: Reset the file/URL inputs on dialog open**

In `mreOpen()`, after the pending-cover-reset block added in Task 8 Step 4, add:

```javascript
  $('mreCoverQuery').value = '';
  $('mreCoverResults').innerHTML = '';
  $('mreCoverUrlInput').value = '';
  $('mreCoverFileInput').value = '';
```

- [ ] **Step 3: Manual browser verification**

No backend logic in this task beyond the already-tested upload endpoint. Verify per Task 12's checklist.

- [ ] **Step 4: Commit**

```bash
git add app/static/manual-review-edit.js
git commit -m "$(cat <<'EOF'
feat(manual-review): Cover tab URL/upload option

Completes the Cover tab: a pasted URL is used as-is, an uploaded file
goes through the new cover-upload endpoint and its returned file://
URL becomes the pending cover_url. Either path updates the same
preview and pending-cover state the search sub-feature (previous
task) already established.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Design doc + full verification pass

**Files:**
- Create: `docs/design/manual-review-multifile-edit-cover.md`
- No code changes -- this task restarts the container and does the full manual verification checklist from the spec's Testing section.

- [ ] **Step 1: Write the design doc**

Create `docs/design/manual-review-multifile-edit-cover.md`, mirroring the structure of `docs/design/manual-review-apply-rewrite-rules.md` (header with date/status, what changed and why, conformance notes):

```markdown
# Manual Review: Multi-file Visibility, Direct Edit, Cover Swap

Date: 2026-07-07
Status: Implemented

## What changed

Three additions to Manual Review, all built on infrastructure that already
existed:

1. **Multi-file/grouped-book visibility.** `is_grouped` (already computed
   everywhere via `clues["group_search"]["applied"]`) is now on match report
   items (`_build_report_item`), in a new `group:multi-file` browse-by-category
   entry (a new "Grouped: N files" log line, parsed the same way every other
   category already is), and shown as a badge on the active target card and
   match report cards, with a matching filter option in the match report.

2. **Direct field editing.** A new "Edit Book" button opens a dedicated
   dialog (`app/static/manual-review-edit.js`, not a reuse of the
   match-apply dialog) pre-filled from the book's current tags/sidecar
   (already loaded, no new fetch). A single Save button always uses
   `field_policy="overwrite"` -- a blank field always clears that tag, since
   there's no match value to fall back to. `POST /api/manual-review/edit`
   handles it, sharing the exact write sequence
   (`_write_book_metadata`, extracted from `apply_manual_review_result`) the
   existing match-apply flow already uses, so grouped books correctly write
   the JSON sidecar only, exactly like the existing apply flow.

3. **Cover tab.** Two ways to pick a cover: search (reuses the same
   provider search dispatch the main search flow uses, factored into
   `runManualProviderSearch` in `app.js`, showing only thumbnails), or a
   direct URL/upload. An uploaded file goes through the new
   `POST /api/manual-review/cover-upload` endpoint, which stores it as a
   temp file and returns a `file://` URL -- `download_cover_bytes` already
   fetches arbitrary URLs via `urllib`, which handles `file://` natively, so
   no new embed code path was needed.

## Why `_write_book_metadata` was extracted

Before this change, `apply_manual_review_result` had the entire
tags-or-sidecar + metadata.json + marker write sequence inline. Duplicating
that for the new edit endpoint would have created two copies of the exact
class of logic that caused this session's earlier grouped-book ASIN bug
(two write paths silently drifting apart). The extraction has zero behavior
change for the existing apply flow (proven by the pre-refactor test suite
passing unmodified against the post-refactor code).

## Conformance

| Scenario | Behavior |
|---|---|
| Edit a single-file book, leave a field blank | Tag is cleared (`field_policy="overwrite"` always) |
| Edit a grouped/multi-file book | Only the JSON sidecar is written, no per-chapter tags -- same as the existing match-apply flow |
| Edit a book whose file falls back to the ffmpeg writer | Save succeeds, response includes a `warning` that blank fields could not be cleared |
| Pick a cover via search | `cover_url` set from the picked result, `replace_cover=True` on save |
| Pick a cover via upload | File stored under a temp dir, `cover_url` is its `file://` URI |
| Cover tab left untouched | `cover_url=""`, `replace_cover=False` -- existing cover is never re-downloaded/re-embedded |
```

- [ ] **Step 2: Commit the design doc**

```bash
git add docs/design/manual-review-multifile-edit-cover.md
git commit -m "$(cat <<'EOF'
docs: design notes for multi-file visibility, direct edit, cover swap

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Restart the container**

Run: `docker compose restart libraforge`
Then wait and confirm health: `docker compose ps libraforge` shows `healthy`.

- [ ] **Step 4: Full backend test suite one more time, post-restart sanity**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest discover -s app/tests -p "test_*.py"`
Expected: all tests pass.

- [ ] **Step 5: Manual browser verification checklist**

Using a real book in the library (prefer one single-file book and one grouped/multi-file book, e.g. a book from `_unorganized`):

1. Open Manual Review, load the single-file book. Confirm no "Multi-file book" badge appears.
2. Load a grouped/multi-file book (e.g. a chapter-split book folder). Confirm the "Multi-file book" badge appears next to the target path.
3. Run a scan over a folder containing at least one grouped book. Open the match report. Confirm the "Multi-file" badge appears on that book's card, and the new "Multi-file books" filter option correctly isolates it.
4. In Manual Review's "browse by category" dropdown, confirm a `group:multi-file (N)` entry appears after the scan and lists the grouped book(s).
5. Click "Edit Book" on the loaded single-file book. Confirm the Fields tab is pre-filled with its current tags. Clear one field (e.g. Genre), fill in a different one, click Save. Confirm success, then reload the target and confirm the cleared field is genuinely blank and the changed field reflects the new value (cross-check with `ffprobe` as done earlier this session).
6. Repeat Save on the grouped/multi-file book. Confirm the response's `output_kind` is `json_sidecar` and no per-chapter tags were touched.
7. Open the Cover tab, search a query against Audible. Confirm thumbnails render (not full match cards) and clicking one updates the Pending preview.
8. Paste an image URL into the Cover tab's URL field, click "Use URL". Confirm the Pending preview updates.
9. Upload a local image file via the file picker. Confirm the Pending preview updates immediately (client-side preview) and does not error.
10. Click Save with a pending cover set. Confirm the book's actual embedded/sidecar cover changes to the picked one.
11. Click Save with the Cover tab left untouched (no pending cover). Confirm the existing cover is unchanged (not re-downloaded, no error).

- [ ] **Step 6: Report results**

If all steps pass, the feature is complete -- proceed to `superpowers:finishing-a-development-branch` to decide push/PR. If any step fails, fix inline and re-run the specific failing step (do not re-run the whole checklist unless the fix could have affected earlier steps).
