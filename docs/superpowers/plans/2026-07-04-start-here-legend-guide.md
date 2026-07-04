# Start Here Legend/Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single collapsed-by-default reference section to the Start
Here page (`app/static/start-here.html`) that explains every write mode,
edit mode, match badge, report type, and the metadata.json/libraforge.json
relationship, so a user looking at a report understands exactly what
happened to a book and why.

**Architecture:** Pure static HTML + CSS, no backend or JS state changes. One
outer `<details>` block holds six content subsections in fixed order; one
inner nested `<details>` (inside the Write modes subsection) explains the
Smart-mode field comparison in depth. Badge samples reuse the exact CSS
classes real reports use, so what a user sees in the guide is pixel-identical
to what they'll see in an actual report.

**Tech Stack:** Vanilla HTML/CSS (`app/static/start-here.html`,
`app/static/style.css`). No new JS, no new API routes, no new dependencies.

## Global Constraints

- Never use em dashes (`—` or `&mdash;`) anywhere in this content. Use a
  period, comma, short hyphen, or restructure the sentence.
- This guide must NOT be swept into the existing `initializeExplanations()`
  candidate selector in `app/static/ui-preferences.js` (`.action-explanation,
  .note:not([id]), .audio-profile-help, .workflow-guide`). Do not give the
  outer `<details>` or any of its content the classes `action-explanation`,
  `note` (without an `id`), `audio-profile-help`, or `workflow-guide`.
- Content is static and factual, grounded in the approved spec at
  `docs/superpowers/specs/2026-07-04-start-here-legend-guide-design.md`. Do
  not paraphrase loosely; use the exact wording from that spec's Content
  section unless a step below says otherwise.
- Whenever `app/static/style.css` is modified, bump its cache-bust query
  string (`?v=YYYYMMDD-N`) in **all six** HTML files that reference it:
  `organizer.html`, `start-here.html`, `index.html`, `m4b-tool.html`,
  `settings.html`, `downloader.html`. They currently all share
  `?v=20260701-3`; bump all six to the same new value together.
- No backend restart is required for HTML/CSS-only changes (`app/static` is
  bind-mounted and served directly by FastAPI), but the browser cache-bust
  bump above is still required so real browsers pick up the CSS change.

---

### Task 1: Guide shell, CSS, and the Edit modes + Write modes content

**Files:**
- Modify: `app/static/start-here.html` (insert new section after the hero,
  before the folder-path picker)
- Modify: `app/static/style.css` (append new rules near the end of the file)
- Modify (cache-bust bump only): `app/static/organizer.html`,
  `app/static/index.html`, `app/static/m4b-tool.html`,
  `app/static/settings.html`, `app/static/downloader.html`

**Interfaces:**
- Produces: the outer `<details id="startHereGuide" class="start-here-guide">`
  container that Tasks 2-4 append content into, and the CSS classes
  `.start-here-guide`, `.guide-section`, `.guide-section h3`,
  `.guide-badge-row`, `.guide-badge-sample`, `.guide-smart-detail` that all
  later tasks reuse verbatim.

- [ ] **Step 1: Locate the insertion point**

Run: `grep -n "start-here-hero\|pick-row" app/static/start-here.html`

Expected output includes these lines (line numbers may drift slightly if the
file changed, but the surrounding text will match):

```
48:    <div class="start-here-hero">
49:      <h1>What needs attention</h1>
50:      <p>Point LibraForge at a folder and it'll tell you what's missing, what's ready, and what's already in shape - across tagging, conversion, and organization.</p>
51:    </div>
52:
53:    <div class="pick-row">
```

The new section is inserted between the closing `</div>` of
`start-here-hero` (line 51 above) and the opening `<div class="pick-row">`
(line 53 above).

- [ ] **Step 2: Insert the guide shell with Edit modes and Write modes content**

Using the Edit tool, replace this exact text in `app/static/start-here.html`:

```html
    <div class="start-here-hero">
      <h1>What needs attention</h1>
      <p>Point LibraForge at a folder and it'll tell you what's missing, what's ready, and what's already in shape - across tagging, conversion, and organization.</p>
    </div>

    <div class="pick-row">
```

with:

```html
    <div class="start-here-hero">
      <h1>What needs attention</h1>
      <p>Point LibraForge at a folder and it'll tell you what's missing, what's ready, and what's already in shape - across tagging, conversion, and organization.</p>
    </div>

    <details id="startHereGuide" class="start-here-guide">
      <summary>Guide: what the badges and modes mean</summary>

      <div class="guide-section">
        <h3>Edit modes</h3>
        <ul>
          <li><span class="match-mode-badge">Full metadata</span> writes everything the match provided: title, author, series, sequence, narrator, year, genre, ASIN.</li>
          <li><span class="match-mode-badge">Series only</span> writes only series/sequence and leaves title and other fields untouched. Used when the match confirms series and author confidently but title identity is uncertain, so a possibly-correct local title is never clobbered.</li>
        </ul>
      </div>

      <div class="guide-section">
        <h3>Write modes</h3>
        <ul>
          <li><strong>Smart</strong>: only writes if the current embedded tags differ from the match.</li>
          <li><strong>Fill missing fields only</strong>: never touches a field that already has a value, only fills blanks.</li>
          <li><strong>Overwrite</strong>: always writes every matched field, unconditionally.</li>
        </ul>

        <details class="guide-smart-detail">
          <summary>How does Smart mode decide what counts as "already matching"?</summary>
          <p>Smart mode compares each field the match would write against what's already embedded in the file: title, author, series, genre, and ASIN, plus sequence, narrator, and year when the edit mode is Full. It only marks the book <span class="match-status-badge status-smart-skipped">Smart-skipped</span> (nothing written) when every one of those checked fields already matches. If even one differs, the file is written normally.</p>
        </details>

        <p class="guide-force-note"><strong>Force reprocess</strong> only bypasses the "already processed" check, so the book is re-searched and re-matched from scratch. It does not override what the write mode decides once a fresh match is found:</p>
        <ul>
          <li><strong>Smart + Force</strong>: re-matches from scratch, but if the fresh match's fields are identical to what's already embedded, the book still shows <span class="match-status-badge status-smart-skipped">Smart-skipped</span>. Force restarts the search, not the write.</li>
          <li><strong>Fill missing + Force</strong>: still only fills currently-blank fields either way, a no-op if nothing's blank.</li>
          <li><strong>Overwrite + Force</strong>: the only combination that reliably rewrites everything, since Overwrite always writes the full fresh match regardless of what's already there.</li>
        </ul>
      </div>

    </details>

    <div class="pick-row">
```

- [ ] **Step 3: Add the CSS for the guide shell**

Using the Edit tool, append this block to the end of `app/static/style.css`:

```css

/* Start Here legend/guide */
.start-here-guide {
  margin: 18px 0;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.start-here-guide > summary {
  color: var(--accent);
  font-size: 13px;
  font-weight: 720;
  cursor: pointer;
}

.guide-section {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

.guide-section:first-of-type {
  border-top: none;
  padding-top: 8px;
}

.guide-section h3 {
  margin: 0 0 8px;
  font-size: 14px;
}

.guide-section ul {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: var(--text-soft);
}

.guide-section li {
  margin-bottom: 6px;
}

.guide-smart-detail {
  margin: 10px 0;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2, var(--surface));
}

.guide-smart-detail summary {
  font-size: 12.5px;
  font-weight: 620;
  cursor: pointer;
  color: var(--accent);
}

.guide-smart-detail p {
  margin: 8px 0 0;
  font-size: 12.5px;
  color: var(--text-soft);
}

.guide-force-note {
  margin: 10px 0 6px;
  font-size: 13px;
  color: var(--text-soft);
}

.guide-badge-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
  font-size: 13px;
  color: var(--text-soft);
}

.guide-badge-sample {
  flex-shrink: 0;
  min-width: 108px;
}
```

- [ ] **Step 4: Bump the style.css cache-bust version in all six HTML files**

Run: `grep -rn 'style.css?v=' app/static/*.html`

Expected: all six files show `?v=20260701-3`.

Using the Edit tool, replace `style.css?v=20260701-3` with
`style.css?v=20260704-1` in each of these six files:
`app/static/organizer.html`, `app/static/start-here.html`,
`app/static/index.html`, `app/static/m4b-tool.html`,
`app/static/settings.html`, `app/static/downloader.html`.

Run: `grep -rn 'style.css?v=' app/static/*.html`

Expected: all six files now show `?v=20260704-1`.

- [ ] **Step 5: Verify the HTML is well-formed and the container renders**

Run:
```bash
docker compose exec libraforge /opt/venv/bin/python3 -c "
from html.parser import HTMLParser
with open('/app/app/static/start-here.html') as f:
    content = f.read()
HTMLParser().feed(content)
print('parsed OK, length', len(content))
"
```

Expected: `parsed OK, length <some number>` with no exceptions. This only
checks the HTML tokenizes without error; `html.parser` does not validate tag
nesting, so also visually confirm balance by counting tags:

Run: `grep -o "<details" app/static/start-here.html | wc -l && grep -o "</details>" app/static/start-here.html | wc -l`

Expected: both counts equal (2 at this point: the outer guide details and
the nested Smart-mode details).

- [ ] **Step 6: Commit**

```bash
git add app/static/start-here.html app/static/style.css app/static/organizer.html app/static/index.html app/static/m4b-tool.html app/static/settings.html app/static/downloader.html
git commit -m "feat(start-here): add guide shell with Edit modes and Write modes content"
```

---

### Task 2: Match badges content (the main section)

**Files:**
- Modify: `app/static/start-here.html`

**Interfaces:**
- Consumes: `.guide-section` from Task 1's CSS; `.match-status-badge` +
  `.status-matched`/`.status-smart-skipped`/`.status-skipped`/
  `.status-unmatched`/`.status-error`, `.match-manual-badge`,
  `.match-score-badge`, `.match-mode-badge`, `.match-provider-badge`,
  `.match-write-badge`, `.reason-badge` + `.danger`/`.recommended` (all
  pre-existing classes defined in `app/static/style.css` lines 1516-1522,
  1622-1638, 2941-2977; verify with
  `grep -n "match-status-badge\|reason-badge" app/static/style.css` if
  unsure).
- Produces: the third `.guide-section` block, inserted directly after the
  Write modes section from Task 1.

- [ ] **Step 1: Locate the insertion point**

Run: `grep -n "guide-section\|</details>" app/static/start-here.html`

Find the `</div>` that closes the Write modes `.guide-section` (it is
immediately followed by a blank line and then `</details>`, the closing tag
of `#startHereGuide`).

- [ ] **Step 2: Insert the Match badges section**

Using the Edit tool, replace this exact text (the end of Task 1's insertion):

```html
      </div>

    </details>

    <div class="pick-row">
```

with:

```html
      </div>

      <div class="guide-section">
        <h3>Match badges</h3>
        <p>Every status and badge a book can show in a report, and what it means for that file.</p>

        <div class="guide-badge-row">
          <span class="guide-badge-sample"><span class="match-status-badge status-matched">Matched</span></span>
          <span>A confident match was found. Will write or wrote metadata per the active write/edit mode.</span>
        </div>
        <div class="guide-badge-row">
          <span class="guide-badge-sample"><span class="match-status-badge status-smart-skipped">Smart-skipped</span></span>
          <span>Write mode is Smart and every checked field already matched. Nothing written.</span>
        </div>
        <div class="guide-badge-row">
          <span class="guide-badge-sample"><span class="match-status-badge status-skipped">Skipped</span></span>
          <span>Explicitly excluded before matching (skip pattern, ignored folder). The badge also shows the reason.</span>
        </div>
        <div class="guide-badge-row">
          <span class="guide-badge-sample"><span class="match-status-badge status-unmatched">Not Matched</span></span>
          <span>No confident match found. Needs Manual Review.</span>
        </div>
        <div class="guide-badge-row">
          <span class="guide-badge-sample"><span class="match-status-badge status-error">Error</span></span>
          <span>Something failed while processing this file.</span>
        </div>
        <div class="guide-badge-row">
          <span class="guide-badge-sample"><span class="match-manual-badge">Manually Applied</span></span>
          <span>This book's metadata was set by hand via Manual Review, not the automatic run.</span>
        </div>
        <div class="guide-badge-row">
          <span class="guide-badge-sample"><span class="match-score-badge">87%</span></span>
          <span>Match confidence.</span>
        </div>
        <div class="guide-badge-row">
          <span class="guide-badge-sample"><span class="match-mode-badge">Full metadata</span></span>
          <span>Which edit mode was used for this book: Full metadata or Series only.</span>
        </div>
        <div class="guide-badge-row">
          <span class="guide-badge-sample"><span class="match-provider-badge">Audible</span></span>
          <span>Which source produced the match: Audible, ABS, abs-agg (LibriVox, Storytel, Audioteka, BookBeat, Big Finish, ARD Audiothek, Die drei ???), GraphicAudio, Soundbooth Theater, Goodreads, or Kindle.</span>
        </div>
        <div class="guide-badge-row">
          <span class="guide-badge-sample"><span class="match-write-badge">written</span></span>
          <span>What actually happened on disk: written, smart-skipped, no-op, skipped, or error.</span>
        </div>
        <div class="guide-badge-row">
          <span class="guide-badge-sample"><span class="reason-badge danger">no match</span></span>
          <span>Manual Review reason tag (red): no match, asin conflict, low score, missing metadata, unsafe match, no metadata, status:skipped, mode:none, or an N% duration-diff tag.</span>
        </div>
        <div class="guide-badge-row">
          <span class="guide-badge-sample"><span class="reason-badge recommended">manually applied</span></span>
          <span>Manual Review reason tag (green): manually applied.</span>
        </div>
      </div>

    </details>

    <div class="pick-row">
```

- [ ] **Step 3: Verify tag balance**

Run: `grep -o "<details" app/static/start-here.html | wc -l && grep -o "</details>" app/static/start-here.html | wc -l`

Expected: both counts equal 2 (unchanged from Task 1; this section adds no
new `<details>`).

Run:
```bash
docker compose exec libraforge /opt/venv/bin/python3 -c "
from html.parser import HTMLParser
with open('/app/app/static/start-here.html') as f:
    HTMLParser().feed(f.read())
print('parsed OK')
"
```

Expected: `parsed OK` with no exceptions.

- [ ] **Step 4: Commit**

```bash
git add app/static/start-here.html
git commit -m "feat(start-here): add Match badges content to the guide"
```

---

### Task 3: metadata.json content

**Files:**
- Modify: `app/static/start-here.html`

**Interfaces:**
- Consumes: `.guide-section` from Task 1.
- Produces: the fourth `.guide-section` block, inserted after the Match
  badges section from Task 2.

- [ ] **Step 1: Insert the metadata.json section**

Using the Edit tool, replace this exact text (the end of Task 2's
insertion):

```html
        <div class="guide-badge-row">
          <span class="guide-badge-sample"><span class="reason-badge recommended">manually applied</span></span>
          <span>Manual Review reason tag (green): manually applied.</span>
        </div>
      </div>

    </details>
```

with:

```html
        <div class="guide-badge-row">
          <span class="guide-badge-sample"><span class="reason-badge recommended">manually applied</span></span>
          <span>Manual Review reason tag (green): manually applied.</span>
        </div>
      </div>

      <div class="guide-section">
        <h3>metadata.json</h3>
        <p>An Audiobookshelf-native <code>metadata.json</code> sidecar is written for every matched book. It's LibraForge's one guaranteed, universal output, independent of audio format or whether embedded-tag writing is even possible or desired (<code>--metadata-json-only</code> skips tags entirely; metadata.json is written either way).</p>
        <p>On repeat runs it follows the same write-mode skip logic as tags, so there is no needless rewrite once nothing's changed. But it is not the same file as <code>libraforge.json</code>, which sits right alongside it and holds LibraForge's own internal tracking: whether and how a book was processed, cached duration data, and more.</p>
        <p><strong>Because they're separate files:</strong> if you use Audiobookshelf's own "save metadata to file" feature (editing metadata inside ABS itself), ABS overwrites <code>metadata.json</code> with its version. This is safe. It never touches <code>libraforge.json</code>, so LibraForge still knows what it already did and won't reprocess or conflict on the next run.</p>
        <p><strong>Recommended metadata priority</strong>, per Audiobookshelf's own documented scanning behavior: <code>metadata.json</code>, then embedded tags, then folder/filename structure. metadata.json wins, so it's the authoritative source for what Audiobookshelf displays. Embedded tags matter mainly for portability outside ABS (playing the file elsewhere). Folder structure is ABS's last resort when nothing else is present.</p>
      </div>

    </details>
```

- [ ] **Step 2: Verify tag balance and parsing**

Run: `grep -o "<details" app/static/start-here.html | wc -l && grep -o "</details>" app/static/start-here.html | wc -l`

Expected: both counts equal 2.

Run:
```bash
docker compose exec libraforge /opt/venv/bin/python3 -c "
from html.parser import HTMLParser
with open('/app/app/static/start-here.html') as f:
    HTMLParser().feed(f.read())
print('parsed OK')
"
```

Expected: `parsed OK` with no exceptions.

- [ ] **Step 3: Commit**

```bash
git add app/static/start-here.html
git commit -m "feat(start-here): add metadata.json content to the guide"
```

---

### Task 4: Report types and Owned badge/duplicate handling content

**Files:**
- Modify: `app/static/start-here.html`
- Modify: `app/static/style.css`

**Interfaces:**
- Consumes: `.guide-section` from Task 1.
- Produces: the fifth and sixth `.guide-section` blocks (Report types, Owned
  badge). Also produces the `.lib-badge`/`.lib-badge.owned` CSS classes
  (locally scoped to this page, mirroring the pattern already used in
  `app/static/downloader.html`, since `start-here.html` does not share that
  page's local style block).

- [ ] **Step 1: Add the lib-badge CSS**

Run: `grep -n "lib-badge" app/static/downloader.html` to confirm the source
pattern being mirrored:

```
    .lib-badge { display:inline-block; font-size:0.7em; padding:1px 6px; border-radius:99px; background:var(--border); color:var(--text-soft); margin-top:5px; }
    .lib-badge.owned { background:#3a2f12; color:#e9c46a; }
```

Using the Edit tool, append this to the end of `app/static/style.css` (after
the block added in Task 1):

```css

/* Reused from downloader.html's owned-badge styling, scoped for the Start
   Here guide sample since this page doesn't share that page's local style
   block. */
.lib-badge { display: inline-block; font-size: 0.7em; padding: 1px 6px; border-radius: 99px; background: var(--border); color: var(--text-soft); }
.lib-badge.owned { background: #3a2f12; color: #e9c46a; }
```

- [ ] **Step 2: Insert the Report types and Owned badge sections**

Using the Edit tool, replace this exact text (the end of Task 3's
insertion):

```html
        <p><strong>Recommended metadata priority</strong>, per Audiobookshelf's own documented scanning behavior: <code>metadata.json</code>, then embedded tags, then folder/filename structure. metadata.json wins, so it's the authoritative source for what Audiobookshelf displays. Embedded tags matter mainly for portability outside ABS (playing the file elsewhere). Folder structure is ABS's last resort when nothing else is present.</p>
      </div>

    </details>
```

with:

```html
        <p><strong>Recommended metadata priority</strong>, per Audiobookshelf's own documented scanning behavior: <code>metadata.json</code>, then embedded tags, then folder/filename structure. metadata.json wins, so it's the authoritative source for what Audiobookshelf displays. Embedded tags matter mainly for portability outside ABS (playing the file elsewhere). Folder structure is ABS's last resort when nothing else is present.</p>
      </div>

      <div class="guide-section">
        <h3>Report types</h3>
        <p>What each tool produces, and where to find it.</p>
        <ul>
          <li><strong>Metadata Forge report</strong>: per-book match/write outcome (the badges above), downloadable after a run.</li>
          <li><strong>M4B Tool report</strong>: conversion/merge outcomes.</li>
          <li><strong>Folder Forge report</strong>: planned/applied moves.</li>
          <li><strong>Library Downloader report</strong>: per-book download outcome.</li>
          <li><strong>Suspect Report</strong>: generated on demand from an existing Metadata Forge report. Re-checks Matched items for signs of a false-positive match (series/title confusion) without re-running the whole match pipeline.</li>
        </ul>
      </div>

      <div class="guide-section">
        <h3>Owned badge &amp; duplicate handling</h3>
        <div class="guide-badge-row">
          <span class="guide-badge-sample"><span class="lib-badge owned">Owned</span></span>
          <span>This title's ASIN is already in your Audiobookshelf library, or, if ABS isn't connected, found via a local ASIN-tag scan fallback.</span>
        </div>
        <p>Duplicate handling when downloading an Owned title: <strong>Keep both copies</strong>, <strong>Replace the existing copy</strong>, or <strong>Choose per item</strong>.</p>
      </div>

    </details>
```

- [ ] **Step 3: Verify tag balance and parsing**

Run: `grep -o "<details" app/static/start-here.html | wc -l && grep -o "</details>" app/static/start-here.html | wc -l`

Expected: both counts equal 2.

Run:
```bash
docker compose exec libraforge /opt/venv/bin/python3 -c "
from html.parser import HTMLParser
with open('/app/app/static/start-here.html') as f:
    HTMLParser().feed(f.read())
print('parsed OK')
"
```

Expected: `parsed OK` with no exceptions.

- [ ] **Step 4: Commit**

```bash
git add app/static/start-here.html app/static/style.css
git commit -m "feat(start-here): add Report types and Owned badge content to the guide"
```

---

### Task 5: Exclude from the global explanations toggle, and full verification

**Files:**
- Read (no modification expected): `app/static/ui-preferences.js`
- Modify (only if Step 1 finds a conflict): `app/static/ui-preferences.js`

**Interfaces:**
- Consumes: `initializeExplanations()`'s candidate selector in
  `app/static/ui-preferences.js` (`.action-explanation, .note:not([id]),
  .audio-profile-help, .workflow-guide`).

- [ ] **Step 1: Confirm the guide is not swept into the global toggle**

Run: `grep -n "action-explanation\|workflow-guide\|audio-profile-help" app/static/start-here.html`

Expected: no matches. None of the classes used in Tasks 1-4
(`start-here-guide`, `guide-section`, `guide-badge-row`,
`guide-badge-sample`, `guide-smart-detail`, `guide-force-note`) overlap with
the selector `initializeExplanations()` in `app/static/ui-preferences.js`
scans for. Also confirm no bare `<p class="note">` (without an `id`) was
introduced in Tasks 1-4:

Run: `grep -n 'class="note"' app/static/start-here.html`

Expected: no matches inside the guide section (there may be unrelated
pre-existing `.note` elements elsewhere on the page from before this
feature; confirm any matches are outside the `#startHereGuide` block by
checking their line numbers against `grep -n "startHereGuide\|</details>" app/static/start-here.html`).

If either check finds a conflict, rename the offending class in
`app/static/start-here.html` to one of the `guide-*` names already in use,
and do not modify `ui-preferences.js`.

- [ ] **Step 2: Run the full backend test suite (regression check)**

Run: `docker compose exec libraforge /opt/venv/bin/python -m unittest discover -s app/tests -p "test_*.py"`

Expected: `OK` with the same test count as before this feature (this change
touches no Python files, so the count must be unchanged from the last
baseline run).

- [ ] **Step 3: Visually verify the rendered page**

Run: `docker compose exec libraforge curl -s http://127.0.0.1:5056/ | grep -c "startHereGuide"`

Expected: `1` (the guide container is present exactly once in the served
page).

Then, with the container running, open `http://127.0.0.1:5056/` in a
browser (or via the `run` skill if driving a headless browser) and confirm:
- The page loads with the guide collapsed by default (only the summary line
  "Guide: what the badges and modes mean" visible, no content below it).
- Clicking the summary expands all six sections in order: Edit modes, Write
  modes, Match badges, metadata.json, Report types, Owned badge & duplicate
  handling.
- Inside Write modes, the nested "How does Smart mode decide..." detail is
  collapsed by default and expands independently of the outer guide.
- Every badge sample (Matched, Smart-skipped, Skipped, Not Matched, Error,
  Manually Applied, score %, mode, provider, write-action, both reason tags,
  Owned) renders with real color, not plain unstyled text (this is the exact
  failure mode from the previous known-issue notice bug: confirm each badge
  actually has a background color and rounded pill shape, not default
  browser text).
- No em dashes appear anywhere in the rendered guide text.

- [ ] **Step 4: Commit (only if Step 1 required a class rename)**

```bash
git add app/static/start-here.html
git commit -m "fix(start-here): rename guide class to avoid the global explanations toggle"
```

If Step 1 found no conflict, skip this commit; there is nothing to commit
for this task.

---

## Self-Review Notes

- **Spec coverage:** all 6 numbered content sections from the spec (Edit
  modes, Write modes with nested Smart explanation and Force-reprocess note,
  Match badges, metadata.json, Report types, Owned badge & duplicate
  handling) map to Tasks 1-4. Placement (after hero, before folder picker),
  collapsed-by-default outer details, and separation from the global
  explanations toggle map to Task 1 and Task 5.
- **Placeholder scan:** no TBD/TODO; every step shows the literal HTML/CSS
  to write, not a description of what to write.
- **Type consistency:** N/A (no functions/types across tasks; this is static
  markup). Class names introduced in Task 1 (`guide-section`,
  `guide-badge-row`, `guide-badge-sample`, `guide-smart-detail`,
  `guide-force-note`, `start-here-guide`) are used identically in Tasks 2-4;
  verified no renaming drift between tasks.
