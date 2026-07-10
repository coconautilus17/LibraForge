// The "Fix Series" bulk-edit dialog: lets the user assign/normalize a
// series (and author/genre/narrator/explicit/language) across several
// books at once, with a per-book editable sequence number and an
// include/exclude toggle. See
// docs/design/2026-07-09-fix-series-cross-book-editor-design.md.
//
// Relies on globals already defined by app.js, loaded before this file:
// $, escapeHtml, matchReportItems.

let fsCurrentGroup = null;
let fsBookState = []; // [{path, title, flag, sequence, included}]

function fsBuildDialog() {
  if ($('fsDialog')) return;

  const dlg = document.createElement('dialog');
  dlg.id = 'fsDialog';
  dlg.className = 'manual-apply-dialog fs-dialog';
  dlg.innerHTML = `
    <h3 class="manual-apply-title">Fix Series</h3>
    <p id="fsContextNote" class="manual-apply-body"></p>
    <p id="fsAuthorNote" class="manual-apply-body fs-author-note" hidden></p>
    <div class="manual-apply-edit-fields">
      <label>Series<input id="fsSeries" /></label>
      <label>Author<input id="fsAuthor" /></label>
      <label>Genre<input id="fsGenre" placeholder="leave blank to skip" /></label>
      <label class="mae-full-width">Narrator<input id="fsNarrator" placeholder="leave blank to skip" /></label>
      <label><input type="checkbox" id="fsExplicit" /> Mark as explicit</label>
      <label>Language<input id="fsLanguage" placeholder="leave blank to skip" /></label>
      <p class="note mae-full-width">Explicit + Language are written only to metadata.json and picked up by ABS, can leave blank to skip.</p>
    </div>
    <p class="note" style="margin-top:14px">Books in this group</p>
    <div class="fs-sibling-bar">
      <button type="button" id="fsAddSiblingsBtn" class="secondary"></button>
      <div class="fs-search-box">
        <input id="fsSearchInput" placeholder="Search the report to add another book..." />
      </div>
      <div id="fsSearchDropdown" class="fs-search-dropdown" hidden></div>
    </div>
    <div id="fsBookList" class="fs-book-list"></div>
    <p id="fsResult" class="manual-apply-body" hidden></p>
    <div class="manual-apply-actions">
      <span id="fsFootNote" class="note" style="margin-right:auto"></span>
      <button id="fsCancelBtn" class="secondary">Cancel</button>
      <button id="fsApplyBtn">Apply</button>
    </div>`;
  document.body.appendChild(dlg);

  $('fsAddSiblingsBtn').addEventListener('click', fsAddTaggedSiblings);
  $('fsSearchInput').addEventListener('input', fsRunSearch);
  $('fsSearchInput').addEventListener('blur', () => {
    setTimeout(() => { $('fsSearchDropdown').hidden = true; }, 150);
  });
}

function fsRenderBookList() {
  $('fsBookList').innerHTML = fsBookState.map((b, i) => `
    <div class="fs-book-row ${b.included ? '' : 'fs-excluded'}" data-fs-row="${i}">
      <div class="fs-book-title">${escapeHtml(b.title)}${b.flag ? `<span class="fs-flag">${escapeHtml(b.flag)}</span>` : ''}</div>
      <input class="fs-seq-input" data-fs-seq="${i}" value="${escapeHtml(b.sequence || '')}" placeholder="-" />
      <div class="fs-toggle-pill ${b.included ? 'fs-in' : ''}" data-fs-toggle="${i}">${b.included ? 'In' : 'Excluded'}</div>
    </div>
  `).join('');

  for (const el of $('fsBookList').querySelectorAll('[data-fs-toggle]')) {
    el.addEventListener('click', () => {
      const i = Number(el.getAttribute('data-fs-toggle'));
      fsBookState[i].included = !fsBookState[i].included;
      fsRenderBookList();
    });
  }
  for (const el of $('fsBookList').querySelectorAll('[data-fs-seq]')) {
    el.addEventListener('input', () => {
      const i = Number(el.getAttribute('data-fs-seq'));
      fsBookState[i].sequence = el.value.trim();
    });
  }

  const includedCount = fsBookState.filter((b) => b.included).length;
  $('fsAddSiblingsBtn').textContent = `+ Add tagged siblings (${fsCurrentGroup.taggedSiblings.length} found)`;
  $('fsAddSiblingsBtn').disabled = fsCurrentGroup.taggedSiblings.every(
    (s) => fsBookState.some((b) => b.path === s.path)
  );
  $('fsFootNote').textContent = `${includedCount} of ${fsBookState.length} included`;
  $('fsApplyBtn').textContent = `Apply to ${includedCount} books`;
}

function fsAddTaggedSiblings() {
  for (const sib of fsCurrentGroup.taggedSiblings) {
    if (fsBookState.some((b) => b.path === sib.path)) continue;
    fsBookState.push({
      path: sib.path,
      title: sib.title,
      flag: `Already tagged: series "${sib.series}"`,
      sequence: '',
      included: true,
    });
  }
  fsRenderBookList();
}

function fsRunSearch() {
  const query = $('fsSearchInput').value.trim().toLowerCase();
  const dropdown = $('fsSearchDropdown');
  if (!query) { dropdown.hidden = true; return; }

  const existing = new Set(fsBookState.map((b) => b.path));
  const results = (window.matchReportItems || []).filter((item) => {
    const path = item.path || '';
    if (existing.has(path)) return false;
    const title = ((item.local || {}).title || '').toLowerCase();
    return title.includes(query) || path.toLowerCase().includes(query);
  }).slice(0, 8);

  if (!results.length) {
    dropdown.innerHTML = '<p class="note" style="padding:6px 8px">No matches.</p>';
  } else {
    dropdown.innerHTML = results.map((item, i) => `
      <div class="fs-search-result" data-fs-search-pick="${i}">
        <div class="fs-r-title">${escapeHtml((item.local || {}).title || item.path)}<small>${escapeHtml(item.path)}</small></div>
      </div>
    `).join('') + '<p class="note" style="padding:8px 8px 4px">Matches title/path across this report only - not a library-wide search.</p>';
    for (const el of dropdown.querySelectorAll('[data-fs-search-pick]')) {
      el.addEventListener('mousedown', () => {
        const i = Number(el.getAttribute('data-fs-search-pick'));
        const item = results[i];
        fsBookState.push({
          path: item.path, title: (item.local || {}).title || item.path,
          flag: null, sequence: '', included: true,
        });
        $('fsSearchInput').value = '';
        dropdown.hidden = true;
        fsRenderBookList();
      });
    }
  }
  dropdown.hidden = false;
}

async function fsApply() {
  const applyBtn = $('fsApplyBtn');
  applyBtn.disabled = true;
  applyBtn.textContent = 'Applying...';
  $('fsResult').hidden = true;

  const included = fsBookState.filter((b) => b.included);
  const explicitEl = $('fsExplicit');

  try {
    const res = await fetch('/api/manual-review/apply-series-group', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        script_name: $('script').value,
        series: $('fsSeries').value.trim(),
        author: $('fsAuthor').value.trim(),
        genre: $('fsGenre').value.trim(),
        narrator: $('fsNarrator').value.trim(),
        language: $('fsLanguage').value.trim(),
        explicit: explicitEl.checked,
        explicit_set: explicitEl.dataset.touched === 'true',
        books: included.map((b) => ({ path: b.path, sequence: b.sequence || '' })),
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      $('fsResult').hidden = false;
      $('fsResult').textContent = data.detail || 'Apply failed';
      return;
    }
    const failed = (data.results || []).filter((r) => r.status === 'failed');
    $('fsResult').hidden = false;
    $('fsResult').textContent = failed.length
      ? `Applied to ${data.results.length - failed.length} of ${data.results.length} books. Failed: ${failed.map((f) => f.path).join(', ')}`
      : `Applied to ${data.results.length} books.`;
    if (!failed.length) {
      await loadLastReport();
    }
  } catch (e) {
    $('fsResult').hidden = false;
    $('fsResult').textContent = 'Error: ' + e.message;
  } finally {
    applyBtn.disabled = false;
    applyBtn.textContent = `Apply to ${included.length} books`;
  }
}

function fsOpen(group) {
  fsBuildDialog();
  fsCurrentGroup = group;
  fsBookState = group.members.map((m) => ({
    path: m.path, title: m.title, flag: m.flag ? m.flag.replace(/_/g, ' ') : null,
    sequence: m.sequence || '', included: true,
  }));

  $('fsContextNote').textContent = group.contextNote;
  $('fsAuthorNote').hidden = !group.authorNote;
  $('fsAuthorNote').textContent = group.authorNote || '';
  $('fsSeries').value = group.suggestedSeries || '';
  $('fsAuthor').value = group.suggestedAuthor || '';
  $('fsGenre').value = group.suggestedGenre || '';
  $('fsNarrator').value = group.suggestedNarrator || '';
  $('fsLanguage').value = '';
  $('fsExplicit').checked = false;
  $('fsExplicit').dataset.touched = 'false';
  $('fsExplicit').onchange = () => { $('fsExplicit').dataset.touched = 'true'; };
  $('fsSearchInput').value = '';
  $('fsSearchDropdown').hidden = true;
  $('fsResult').hidden = true;

  fsRenderBookList();

  const dlg = $('fsDialog');
  function onCancel() { dlg.close(); }
  $('fsCancelBtn').addEventListener('click', onCancel, { once: true });
  $('fsApplyBtn').replaceWith($('fsApplyBtn').cloneNode(true));
  $('fsApplyBtn').addEventListener('click', fsApply);
  dlg.addEventListener('cancel', onCancel, { once: true });
  dlg.showModal();
}

window.FixSeries = { open: fsOpen };
