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
        genres with a comma (e.g. "Fantasy, LitRPG") - each is saved as
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
    <p id="mreResult" class="manual-apply-body" hidden></p>
    <p id="mreWarning" class="manual-apply-warning" hidden></p>
    <div class="manual-apply-actions">
      <button id="mreCancelBtn" class="secondary">Cancel</button>
      <button id="mreSaveBtn">Save</button>
    </div>`;
  document.body.appendChild(dlg);

  $('mreTabFieldsBtn').addEventListener('click', () => mreSwitchTab('fields'));
  $('mreTabCoverBtn').addEventListener('click', () => mreSwitchTab('cover'));
  $('mreCoverSearchBtn').addEventListener('click', mreSearchCovers);
  $('mreCoverUrlUseBtn').addEventListener('click', mreUseCoverUrl);
  $('mreCoverFileInput').addEventListener('change', () => {
    const file = $('mreCoverFileInput').files[0];
    if (file) mreUploadCoverFile(file);
  });
}

function mreSwitchTab(name) {
  const fieldsActive = name === 'fields';
  $('mreTabFieldsBtn').classList.toggle('active', fieldsActive);
  $('mreTabCoverBtn').classList.toggle('active', !fieldsActive);
  $('mreFieldsPanel').classList.toggle('active', fieldsActive);
  $('mreCoverPanel').classList.toggle('active', !fieldsActive);
}

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
  $('mreCoverQuery').value = '';
  $('mreCoverResults').innerHTML = '';
  $('mreCoverUrlInput').value = '';
  $('mreCoverFileInput').value = '';

  const dlg = $('mreDialog');

  function onCancel() { dlg.close(); }
  function onSave() { mreSave(); }

  $('mreCancelBtn').addEventListener('click', onCancel, { once: true });
  $('mreSaveBtn').replaceWith($('mreSaveBtn').cloneNode(true));
  $('mreSaveBtn').addEventListener('click', onSave);
  dlg.addEventListener('cancel', onCancel, { once: true });
  dlg.showModal();
}

window.ManualReviewEdit = { open: mreOpen };

document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('manualEditBtn');
  if (btn) btn.addEventListener('click', mreOpen);
});
