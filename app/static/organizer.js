let currentRun = null;
let pollTimer = null;
let latestMoveItems = [];
let latestStats = {};
let currentOrgReportId = null;
let lastRequest = null;
let noSidecarsHandledForRun = null;

// Mirrors the backend's matches_skip_patterns: a plain case-insensitive
// substring check of the pattern against the source path. Derived live from
// the current Skip patterns textarea (not tracked separately) so removing a
// line -- or a fresh run whose patterns no longer include it -- immediately
// stops showing the item as excluded.
function isExcludedByPattern(item) {
  const source = String(item.source || "").toLowerCase();
  const patterns = $("skipPatterns").value.split("\n").map((s) => s.trim().toLowerCase()).filter(Boolean);
  return patterns.some((p) => source.includes(p));
}

// Strip the trailing filename from a path so only the directory is shown.
// Paths ending in a known audio extension are treated as files; others as dirs.
function pathDir(p) {
  if (!p) return p;
  const audioExts = /\.(m4b|m4a|mp3|ogg|opus|flac|aac|wma)$/i;
  if (audioExts.test(p)) {
    const idx = p.lastIndexOf('/');
    return idx > 0 ? p.slice(0, idx) : p;
  }
  return p;
}

const $ = (id) => document.getElementById(id);
const { escapeHtml, renderDownloadLinks, statCard: stat, saveActiveRun, clearActiveRun, loadActiveRun } = window.UiCommon;
const RUN_KEY = 'organizer';

// Re-attach polling/UI to an existing run id (used by start and by reconnect).
function attachToRun(id) {
  currentRun = id;
  saveActiveRun(RUN_KEY, id);
  $('startBtn').disabled = true;
  $('cancelBtn').disabled = false;
  clearInterval(pollTimer);
  pollTimer = setInterval(poll, 1000);
  poll();
}

// On load, resume showing a run that is still going (or just finished) in the
// background so navigating away and back does not lose it.
async function resumeActiveRun() {
  const id = loadActiveRun(RUN_KEY);
  if (!id) return;
  const res = await fetch(`/api/runs/${id}`).catch(() => null);
  if (!res || !res.ok) { clearActiveRun(RUN_KEY); return; }
  // A fresh run may have been started (via the Start button) while this
  // fetch was in flight -- don't clobber currentRun/polling with the stale
  // resumed id, which would silently show the wrong run's progress and log.
  if (currentRun) return;
  attachToRun(id);
}

async function loadScripts() {
  const res = await fetch('/api/scripts');
  const data = await res.json();
  const select = $('script');
  select.innerHTML = '';
  for (const name of data.organizer_scripts || data.scripts) {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    if (name === data.default_organizer_script) opt.selected = true;
    select.appendChild(opt);
  }
}

function isAdvancedRunSettingsOpen() {
  return $('advancedRunToggle')?.getAttribute('aria-expanded') === 'true';
}

function syncAdvancedRunSettings() {
  const open = isAdvancedRunSettingsOpen();
  const toggle = $('advancedRunToggle');
  if (toggle) {
    toggle.textContent = open ? 'Hide advanced' : 'Advanced';
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  document.querySelectorAll('.organizer-advanced-setting').forEach((el) => {
    el.hidden = !open;
  });
}

function collectRequest() {
  const prefs = window.LibraForgePrefs?.get() || {};
  const skipPatterns = $('skipPatterns').value.split('\n').map((s) => s.trim()).filter(Boolean);
  if ($('usePersistentSkip')?.checked) {
    const persistent = (prefs.persistentSkipPatterns || '').split('\n').map(s => s.trim()).filter(Boolean);
    for (const p of persistent) {
      if (!skipPatterns.includes(p)) skipPatterns.push(p);
    }
  }
  return {
    script_name: $('script').value,
    root_path: $('rootPath').value.trim(),
    destination_root: $("destinationRoot").value.trim(),
    apply: $('apply').checked,
    m4b_only: $('m4bOnly').checked,
    allow_unknown_author: $("allowUnknownAuthor").checked,
    include_existing_book_folders: $('includeExisting').checked,
    no_companions: $('noCompanions').checked,
    rebuild_structure_cache: $("rebuildStructureCache").checked,
    index_only: $("indexOnly").checked,
    consolidate_structures: $("consolidateStructures").checked,
    remove_empty_dirs: $('removeEmptyDirs').checked,
    max_items: parseInt($('maxItems').value || '0', 10),
    progress_every: parseInt($('progressEvery').value || '1', 10),
    skip_patterns: skipPatterns,
    use_default_scheme: $('useDefaultScheme').checked,
    naming_template: $('namingTemplate').value.trim(),
  };
}

function buildOrgConfirmDialog() {
  if ($('orgApplyConfirmDialog')) return;
  const dlg = document.createElement('dialog');
  dlg.id = 'orgApplyConfirmDialog';
  dlg.className = 'manual-apply-dialog org-confirm-dialog';
  dlg.innerHTML = `
    <h3 class="manual-apply-title org-confirm-danger-title">Files will be moved — are you sure?</h3>
    <div class="org-confirm-paths">
      <div class="org-confirm-path-row">
        <span class="org-confirm-label">From</span>
        <span class="org-confirm-path-value mono" id="orgConfirmFrom"></span>
      </div>
      <div class="org-confirm-path-row">
        <span class="org-confirm-label">To</span>
        <span class="org-confirm-path-value mono" id="orgConfirmTo"></span>
      </div>
    </div>
    <p class="org-confirm-stat" id="orgConfirmStat"></p>
    <div class="manual-apply-warning">
      <strong>Before applying:</strong> review all flagged cards and their review reasons above.
      Generate a <strong>Suspicion Report</strong> to catch identity mismatches before committing.
      Any moves that fail or are skipped will need to be corrected manually afterwards.
    </div>
    <div class="manual-apply-actions">
      <button id="orgConfirmCancel" class="secondary">Cancel</button>
      <button id="orgConfirmOk" class="danger">Move files</button>
    </div>`;
  document.body.appendChild(dlg);
}

function showOrgApplyConfirm(req) {
  buildOrgConfirmDialog();
  const dlg = $('orgApplyConfirmDialog');
  $('orgConfirmFrom').textContent = req.root_path;
  $('orgConfirmTo').textContent = req.destination_root;

  const parts = [];
  if (latestStats.structure_cache_entries != null) parts.push(`${latestStats.structure_cache_entries} cached series structures`);
  if (latestStats.planned_moves != null) parts.push(`${latestStats.planned_moves} moves planned in last run`);
  const stat = $('orgConfirmStat');
  stat.textContent = parts.join(' · ');
  stat.hidden = parts.length === 0;

  return new Promise((resolve) => {
    const onOk = () => { cleanup(); resolve(true); };
    const onCancel = () => { cleanup(); resolve(false); };
    const onBackdrop = (e) => { if (e.target === dlg) onCancel(); };
    function cleanup() {
      $('orgConfirmOk').removeEventListener('click', onOk);
      $('orgConfirmCancel').removeEventListener('click', onCancel);
      dlg.removeEventListener('click', onBackdrop);
      dlg.close();
    }
    $('orgConfirmOk').addEventListener('click', onOk);
    $('orgConfirmCancel').addEventListener('click', onCancel);
    dlg.addEventListener('click', onBackdrop);
    dlg.showModal();
  });
}

function buildNoSidecarsConfirmDialog() {
  if ($('orgNoSidecarsDialog')) return;
  const dlg = document.createElement('dialog');
  dlg.id = 'orgNoSidecarsDialog';
  dlg.className = 'manual-apply-dialog org-confirm-dialog';
  dlg.innerHTML = `
    <h3 class="manual-apply-title org-confirm-danger-title">Fixer was not applied</h3>
    <p>No item in this scan has a fixer/marker sidecar. Multi-file book handling (grouping split chapters, and title/author/series identity across them) relies on metadata the fixer script writes -- without it, folder names and moves for split books may be wrong.</p>
    <div class="manual-apply-actions">
      <button id="orgNoSidecarsCancel" class="secondary">Cancel</button>
      <button id="orgNoSidecarsContinue" class="danger">Continue anyway</button>
    </div>`;
  document.body.appendChild(dlg);
}

function showNoSidecarsConfirm() {
  buildNoSidecarsConfirmDialog();
  const dlg = $('orgNoSidecarsDialog');
  return new Promise((resolve) => {
    const onOk = () => { cleanup(); resolve(true); };
    const onCancel = () => { cleanup(); resolve(false); };
    const onBackdrop = (e) => { if (e.target === dlg) onCancel(); };
    function cleanup() {
      $('orgNoSidecarsContinue').removeEventListener('click', onOk);
      $('orgNoSidecarsCancel').removeEventListener('click', onCancel);
      dlg.removeEventListener('click', onBackdrop);
      dlg.close();
    }
    $('orgNoSidecarsContinue').addEventListener('click', onOk);
    $('orgNoSidecarsCancel').addEventListener('click', onCancel);
    dlg.addEventListener('click', onBackdrop);
    dlg.showModal();
  });
}

async function startRun(reqOverride) {
  const req = reqOverride || collectRequest();
  if (!reqOverride && !req.use_default_scheme && !req.naming_template) {
    alert('Enter a naming template, or check "Use ABS default structure scheme".');
    return;
  }
  if (req.apply && !reqOverride) {
    const ok = await showOrgApplyConfirm(req);
    if (!ok) return;
  }
  lastRequest = req;

  const res = await fetch('/api/organizer/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Failed to start organizer run');
    return;
  }

  attachToRun(data.id);
}

async function cancelRun() {
  if (!currentRun) return;
  await fetch(`/api/runs/${currentRun}/cancel`, { method: 'POST' });
  poll();
}

async function poll() {
  if (!currentRun) return;
  const res = await fetch(`/api/runs/${currentRun}`);
  if (!res.ok) return;
  const state = await res.json();
  render(state);

  if (state.stats?.no_sidecars_warning && noSidecarsHandledForRun !== currentRun) {
    noSidecarsHandledForRun = currentRun;
    const req = lastRequest;
    showNoSidecarsConfirm().then((proceed) => {
      if (proceed && req) {
        startRun({ ...req, acknowledge_no_sidecars: true });
      }
    });
  }

  if (['completed', 'failed', 'cancelled'].includes(state.status)) {
    clearInterval(pollTimer);
    clearActiveRun(RUN_KEY);
    $('startBtn').disabled = false;
    $('cancelBtn').disabled = true;
  }
}

function render(state) {
  const stats = state.stats || {};
  const pct = Number(state.percent || 0);
  $('ring').style.setProperty('--pct', pct.toFixed(1));
  $('percent').textContent = `${pct.toFixed(1)}%`;
  const count = state.total ? ` · ${state.current || 0}/${state.total}` : '';
  $('runStatus').textContent = `${state.phase_label || state.status.toUpperCase()}${count}`;
  const phaseDetail = state.phase_detail || '';
  const currentPath = state.current_file || '';
  $('currentFile').textContent = state.error
    || [phaseDetail, currentPath && currentPath !== phaseDetail ? currentPath : ''].filter(Boolean).join(' · ')
    || 'Waiting for output...';
  $('command').textContent = (state.command || []).join(' ');
  $('tail').textContent = (state.tail || []).join('\n');
  $('tail').scrollTop = $('tail').scrollHeight;
  renderDownloadLinks($('downloadLinks'), state.downloads || {});
  latestStats = stats;
  renderStats(stats);
  renderApplyResult(stats);
  latestMoveItems = stats.move_items || [];
  populateReviewReasonFilter(latestMoveItems);
  renderRisks(latestMoveItems);
  renderMoves(latestMoveItems);

  if (state.id && state.id !== currentOrgReportId) {
    currentOrgReportId = state.id;
    $('suspectReportBtn').hidden = false;
    $('suspectReportBtn').disabled = false;
    $('suspectReportBtn').textContent = 'Generate Suspicion Report';
    $('suspectReportWidget').hidden = true;
    $('suspectReportList').innerHTML = '';
    probeSuspectReport(state.id);
  }
}

function renderStats(stats) {
  const reviewItems = (stats.move_items || []).filter(isReviewMove).length;
  $('stats').innerHTML = [
    stat('Found Items', stats.found_items, 'Organizer items scanned after filtering.'),
    stat('Ignored MP3', stats.ignored_mp3_files, 'MP3 files skipped outside organizer processing.'),
    stat("Skipped Unknown", stats.skipped_unknown_author, "Items without author metadata, blocked by default."),
    stat("Skipped By Pattern", stats.skipped_pattern_match, "Items whose source path or metadata matched a configured skip pattern."),
    stat('Skipped Existing', stats.skipped_existing_book_folders, 'Folders treated as already organized.'),
    stat("Cached Structures", stats.structure_cache_entries, "Existing series destinations indexed from the library."),
    stat("Existing Matches", stats.matched_existing_structure, "Moves routed into an indexed series folder."),
    stat("Ambiguous", stats.ambiguous_structure_matches, "Series with multiple indexed destinations; review required."),
    stat('Skipped In Place', stats.skipped_already_target, 'Items already sitting in the target folder.'),
    stat("Skipped Ambiguous", stats.skipped_ambiguous_structure, "Moves blocked because multiple existing series folders were equally plausible."),
    stat('Skipped Conflicts', stats.skipped_conflicts, 'Moves blocked by target collisions or subtree issues.'),
    stat('Planned Moves', stats.planned_moves, 'Move operations parsed from the current run output.'),
    stat('Review Items', reviewItems, 'Planned moves using inferred, conflicting, or incomplete identity data.'),
    stat('Mode', stats.mode || '-', 'Dry run or apply.'),
  ].join('');
}

function renderApplyResult(stats) {
  const summaryEl = $('applyResultSummary');
  const sectionEl = $('failedMovesSection');
  const listEl = $('failedMovesList');
  const succeeded = stats.moves_succeeded || 0;
  const failed = stats.moves_failed || 0;
  const attempted = succeeded + failed;

  if (stats.mode !== 'APPLY' || attempted === 0) {
    summaryEl.hidden = true;
    sectionEl.hidden = true;
    return;
  }

  summaryEl.hidden = false;
  summaryEl.className = failed ? 'review-alert danger' : 'review-alert';
  summaryEl.innerHTML = failed
    ? `<strong>${succeeded} succeeded, ${failed} failed.</strong> See Failed Moves below.`
    : `<strong>${succeeded} succeeded, 0 failed.</strong>`;

  const failedItems = stats.failed_move_items || [];
  sectionEl.hidden = failedItems.length === 0;
  listEl.innerHTML = failedItems.map((item) => `
    <article class="result-card review-card">
      <div class="result-head">
        <div>
          <h3>${escapeHtml(item.title || 'Unknown Title')}</h3>
          <p>${escapeHtml(item.author || 'Unknown Author')}</p>
        </div>
      </div>
      <div class="review-alert danger"><strong>Error:</strong> ${escapeHtml(item.error || 'unknown error')}</div>
      <div class="result-meta">
        <span>From: ${escapeHtml(item.source || '-')}</span>
        <span>To: ${escapeHtml(item.target || '-')}</span>
      </div>
    </article>
  `).join('');
}

function isReviewMove(item) {
  return (item.review_reasons || []).length > 0
    || !item.author
    || item.author === "Unknown Author"
    || !item.title
    || item.title === "Unknown Title"
    || !item.source
    || !item.target
    || item.structure === "ambiguous";
}
function renderRisks(items) {
  const reviewItems = items.filter((item) => (item.review_reasons || []).length > 0).length;
  const unknownAuthors = items.filter((item) => !item.author || item.author === "Unknown Author").length;
  const ambiguousStructures = items.filter((item) => item.structure === "ambiguous").length;
  // Duplicate source only matters for folder moves — multiple loose files
  // from the same source folder is normal and not a conflict.
  const folderMoves = items.filter((item) => item.kind === "folder");
  const duplicateSources = folderMoves.length - new Set(folderMoves.map((item) => item.source)).size;
  const duplicateTargets = items.length - new Set(items.map((item) => item.target)).size;
  const risks = [];
  if (reviewItems) risks.push(`${reviewItems} move${reviewItems === 1 ? "" : "s"} use inferred or conflicting identity data`);
  if (unknownAuthors) risks.push(`${unknownAuthors} move${unknownAuthors === 1 ? "" : "s"} have an unknown author`);
  if (ambiguousStructures) risks.push(`${ambiguousStructures} move${ambiguousStructures === 1 ? "" : "s"} have ambiguous existing series folders`);
  if (duplicateSources) risks.push(`${duplicateSources} duplicate source entr${duplicateSources === 1 ? "y" : "ies"}`);
  if (duplicateTargets) risks.push(`${duplicateTargets} duplicate target entr${duplicateTargets === 1 ? "y" : "ies"}`);
  $("moveRiskSummary").innerHTML = risks.length
    ? `<strong>Review required:</strong> ${risks.map(escapeHtml).join("; ")}.`
    : "No inferred identity, unknown-author, ambiguous-series, or duplicate-path risks were found.";
  $("moveRiskSummary").className = risks.length ? "review-alert danger" : "review-alert";
}

function populateReviewReasonFilter(items) {
  const select = $("reviewReasonFilter");
  const current = select.value;
  const reasons = [...new Set(
    items.flatMap((item) => item.review_reasons || [])
  )].sort();
  select.innerHTML = '<option value="">All reasons</option>'
    + reasons.map((r) => `<option value="${escapeHtml(r)}"${r === current ? " selected" : ""}>${escapeHtml(r)}</option>`).join("");
}

function renderMoves(items) {
  const query = $("moveSearch").value.trim().toLowerCase();
  const reviewOnly = $("reviewOnly").checked;
  const reasonFilter = $("reviewReasonFilter").value;
  const filtered = items.filter((item) => {
    if (reviewOnly && !isReviewMove(item)) return false;
    if (reasonFilter && !(item.review_reasons || []).includes(reasonFilter)) return false;
    if (!query) return true;
    return [item.title, item.author, item.series, item.number, item.source, item.target]
      .some((value) => String(value || "").toLowerCase().includes(query));
  });

  $("moveCount").textContent = `Showing ${filtered.length} of ${items.length} planned moves`;
  $("moveItems").innerHTML = filtered.length
    ? filtered.map((item) => {
      const excluded = isExcludedByPattern(item);
      return `
      <article class="result-card ${isReviewMove(item) ? "review-card" : ""} ${excluded ? "excluded-card" : ""}">
        <div class="result-head">
          <div>
            <h3>${escapeHtml(item.title || "Unknown Title")}</h3>
            <p>${escapeHtml(item.author || "Unknown Author")}</p>
          </div>
          <div class="score-badge">${escapeHtml(String(item.files || 1))} file${Number(item.files || 1) === 1 ? "" : "s"}</div>
          <span>Structure: ${escapeHtml(item.structure || "new")}</span>
        </div>
        <div class="actions">
          <button type="button" class="secondary" data-exclude-source="${escapeHtml(item.source)}" ${excluded ? "disabled" : ""}>
            ${excluded ? "Excluded (run again to apply)" : "Exclude from organizer run"}
          </button>
        </div>
        <div class="result-meta">
          <span>Kind: ${escapeHtml(item.kind || "-")}</span>
          <span>Metadata: ${escapeHtml(item.metadata_source || "-")}</span>
          <span>Series: ${escapeHtml(item.series || "-")}</span>
          <span>Number: ${escapeHtml(item.number || "-")}</span>
          <span>Companions: ${Math.floor((item.companions || []).length / 2)}</span>
        </div>
        ${(item.review_reasons || []).length ? `<div class="review-alert danger"><strong>Review:</strong> ${(item.review_reasons || []).map(escapeHtml).join("; ")}.</div>` : ""}
        <details class="move-details">
          <summary>Show source, destination, and companion files</summary>
          <div class="file-list">
            <div class="file-item"><strong>From</strong><br>${escapeHtml(pathDir(item.source) || "-")}</div>
            <div class="file-item"><strong>To</strong><br>${escapeHtml(pathDir(item.target) || "-")}</div>
            ${(item.companions || []).length ? `<div class="file-item"><strong>Companions</strong><br>${(item.companions || []).map((entry) => escapeHtml(entry)).join("<br>")}</div>` : ""}
          </div>
        </details>
      </article>
    `;
    }).join("")
    : `<p class="note">${items.length ? "No moves match the current filters." : "No planned moves were parsed from this run."}</p>`;

  for (const button of $("moveItems").querySelectorAll("button[data-exclude-source]")) {
    button.addEventListener("click", () => {
      const source = button.getAttribute("data-exclude-source");
      const textarea = $("skipPatterns");
      const lines = textarea.value.split("\n").map((s) => s.trim()).filter(Boolean);
      if (!lines.includes(source)) {
        lines.push(source);
        textarea.value = lines.join("\n");
      }
      renderMoves(latestMoveItems);
    });
  }
}

$("moveSearch").addEventListener("input", () => renderMoves(latestMoveItems));
$("reviewOnly").addEventListener("change", () => renderMoves(latestMoveItems));
$("reviewReasonFilter").addEventListener("change", () => renderMoves(latestMoveItems));
$("skipPatterns").addEventListener("input", () => renderMoves(latestMoveItems));

const { renderSuspectReport: _renderSuspectReport } = window.UiCommon;

function renderOrgSuspectReport(data) {
  _renderSuspectReport(data, $('suspectReportBtn'), $('suspectReportWidget'), $('suspectReportList'));
}

async function probeSuspectReport(reportId) {
  const btn = $('suspectReportBtn');
  const res = await fetch(`/api/reports/${encodeURIComponent(reportId)}/suspect-review`).catch(() => null);
  if (!res || !res.ok) { btn.hidden = false; return; }
  const data = await res.json();
  if (data.suspects) renderOrgSuspectReport(data);
}

async function generateSuspectReport() {
  const btn = $('suspectReportBtn');
  btn.disabled = true;
  btn.textContent = 'Generating...';
  const res = await fetch(`/api/reports/${encodeURIComponent(currentOrgReportId)}/suspect-review`, { method: 'POST' }).catch(() => null);
  if (!res || !res.ok) { btn.disabled = false; btn.textContent = 'Generate Suspicion Report'; return; }
  const data = await res.json();
  renderOrgSuspectReport(data);
}

$('suspectReportBtn').addEventListener('click', () => {
  const btn = $('suspectReportBtn');
  const widget = $('suspectReportWidget');
  if ($('suspectReportList').children.length) {
    const isHidden = widget.hidden;
    widget.hidden = !isHidden;
    btn.textContent = isHidden ? 'Hide Suspicion Report' : 'Show Suspicion Report';
  } else {
    generateSuspectReport();
  }
});

async function runCleanup() {
  const btn = $('cleanupBtn');
  const report = $('cleanupReport');
  btn.disabled = true;
  btn.textContent = 'Cleaning…';
  report.hidden = true;
  try {
    const res = await fetch('/api/organizer/cleanup-source', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root_path: $('rootPath').value.trim() }),
    });
    const data = await res.json();
    if (!res.ok) { alert(data.detail || 'Cleanup failed'); return; }
    renderCleanupReport(data);
  } catch (e) {
    alert('Cleanup request failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Cleanup source folder';
  }
}

function renderCleanupReport(data) {
  const report = $('cleanupReport');
  const lines = [];

  lines.push(`<p class="cleanup-summary"><strong>${data.empty_dirs_deleted}</strong> empty folder${data.empty_dirs_deleted === 1 ? '' : 's'} removed.</p>`);

  if (data.json_files.length) {
    lines.push('<p class="cleanup-section-title">Cache JSON files deleted:</p><ul class="cleanup-list">');
    for (const f of data.json_files) {
      const folderLabel = f.folder === '.' ? '(root)' : f.folder;
      const ok = f.status === 'deleted';
      lines.push(`<li class="${ok ? '' : 'cleanup-error'}">${escapeHtml(f.name)} <span class="cleanup-folder">in ${escapeHtml(folderLabel)}</span>${ok ? '' : ` — ${escapeHtml(f.status)}`}</li>`);
    }
    lines.push('</ul>');
  } else {
    lines.push('<p class="cleanup-none">No cache JSON files found.</p>');
  }

  if (data.thumbs_db.length) {
    lines.push('<p class="cleanup-section-title">Thumbs.db files:</p><ul class="cleanup-list">');
    for (const t of data.thumbs_db) {
      const folderLabel = t.path === '.' ? '(root)' : t.path;
      const ok = t.status === 'deleted';
      lines.push(`<li class="${ok ? '' : 'cleanup-error'}">${escapeHtml(t.path === '.' ? t.name : t.path + '/' + t.name)}${ok ? ' — deleted' : ` — ${escapeHtml(t.status)}`}</li>`);
      if (!ok) {
        lines.push(`<li class="cleanup-tip">
          <strong>Thumbs.db</strong> is a Windows thumbnail cache automatically created by File Explorer when you browse a folder.
          It is safe to delete but may be locked if File Explorer has the folder open.
          To force removal: close File Explorer, then from an administrator command prompt run
          <code>attrib -r -h -s "${escapeHtml(folderLabel)}\\Thumbs.db"</code> followed by
          <code>del /f /q "${escapeHtml(folderLabel)}\\Thumbs.db"</code>.
          On Linux/Mac you can use <code>rm -f</code> directly.
        </li>`);
      }
    }
    lines.push('</ul>');
  }

  report.innerHTML = `<div class="cleanup-report">${lines.join('')}</div>`;
  report.hidden = false;
}

function renderNamingTemplateStatus(problems) {
  const el = $('namingTemplateStatus');
  if (!problems || !problems.length) {
    el.hidden = true;
    el.textContent = '';
    el.classList.remove('naming-template-status-error');
    return;
  }
  el.hidden = false;
  el.textContent = problems.join(' ');
  el.classList.add('naming-template-status-error');
}

function renderNamingTemplatePreview(previews) {
  const el = $('namingTemplatePreview');
  if (!previews || !previews.length) {
    el.hidden = true;
    el.innerHTML = '';
    return;
  }
  el.hidden = false;
  el.innerHTML = previews.map((p) => {
    const dest = p.filename ? `${p.target_dir}/${p.filename}` : `${p.target_dir}/`;
    const flagged = p.review_reasons && p.review_reasons.length
      ? `<div class="naming-template-preview-flag">${escapeHtml(p.review_reasons.join('; '))}</div>`
      : '';
    return `<div class="naming-template-preview-row">
      <div class="naming-template-preview-source mono">${escapeHtml(p.source)}</div>
      <div class="naming-template-preview-arrow">&#8594;</div>
      <div class="naming-template-preview-target mono">${escapeHtml(dest)}</div>
      ${flagged}
    </div>`;
  }).join('');
}

function renderNamingTemplateExamples(previews) {
  const body = $('namingTemplateExamplesBody');
  if (!previews || !previews.length) {
    body.innerHTML = '';
    return;
  }
  body.innerHTML = previews.map((p) => {
    const dest = p.filename ? `${p.target_dir}/${p.filename}` : `${p.target_dir}/`;
    const flagged = p.review_reasons && p.review_reasons.length
      ? `<div class="naming-template-preview-flag">${escapeHtml(p.review_reasons.join('; '))}</div>`
      : '';
    return `<tr>
      <td>${escapeHtml(p.scenario || '')}</td>
      <td><code>${escapeHtml(p.target_dir)}</code>${flagged}</td>
      <td>${p.filename ? `<code>${escapeHtml(p.filename)}</code>` : '<em>unchanged</em>'}</td>
    </tr>`;
  }).join('');
}

async function refreshNamingTemplateExamples(template) {
  const res = await fetch('/api/organizer/naming-template/example-preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ template }),
  }).catch(() => null);
  if (!res || !res.ok) {
    renderNamingTemplateExamples([]);
    return;
  }
  const body = await res.json();
  renderNamingTemplateExamples(body.previews || []);
}

let namingTemplateDebounce = null;
async function refreshNamingTemplatePreview() {
  const template = $('namingTemplate').value.trim();
  if (!template) {
    renderNamingTemplateStatus([]);
    renderNamingTemplatePreview([]);
    renderNamingTemplateExamples([]);
    return;
  }
  const validateRes = await fetch('/api/organizer/naming-template/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ template }),
  }).catch(() => null);
  const validateBody = validateRes && validateRes.ok ? await validateRes.json() : null;
  if (!validateBody || !validateBody.valid) {
    renderNamingTemplateStatus((validateBody && validateBody.problems) || ['Could not validate template.']);
    renderNamingTemplatePreview([]);
    renderNamingTemplateExamples([]);
    return;
  }
  renderNamingTemplateStatus([]);

  // The real-library preview and the bundled-example preview only share the
  // already-validated template as an input, not each other's result, so run
  // them concurrently instead of paying for two round trips back to back.
  await Promise.all([
    fetch('/api/organizer/naming-template/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        template,
        root_path: $('rootPath').value.trim(),
        destination_root: $('destinationRoot').value.trim(),
      }),
    }).catch(() => null).then(async (previewRes) => {
      if (!previewRes || !previewRes.ok) {
        renderNamingTemplatePreview([]);
      } else {
        const previewBody = await previewRes.json();
        renderNamingTemplatePreview(previewBody.previews || []);
      }
    }),
    refreshNamingTemplateExamples(template),
  ]);
}

$('namingTemplate').addEventListener('input', () => {
  clearTimeout(namingTemplateDebounce);
  namingTemplateDebounce = setTimeout(refreshNamingTemplatePreview, 400);
});

function syncNamingSchemeToggle() {
  const useDefault = $('useDefaultScheme').checked;
  const section = document.querySelector('.naming-template-section');
  const field = $('namingTemplate');
  field.disabled = useDefault;
  section.classList.toggle('using-default-scheme', useDefault);
  if (useDefault) {
    renderNamingTemplateStatus([]);
    renderNamingTemplatePreview([]);
    renderNamingTemplateExamples([]);
  } else {
    refreshNamingTemplatePreview();
  }
}

$('useDefaultScheme').addEventListener('change', syncNamingSchemeToggle);
syncNamingSchemeToggle();

$('startBtn').addEventListener('click', () => startRun());
$('cancelBtn').addEventListener('click', cancelRun);
$('cleanupBtn').addEventListener('click', runCleanup);
$('advancedRunToggle')?.addEventListener('click', () => {
  const open = !isAdvancedRunSettingsOpen();
  $('advancedRunToggle').setAttribute('aria-expanded', open ? 'true' : 'false');
  syncAdvancedRunSettings();
});
syncAdvancedRunSettings();
loadScripts();
resumeActiveRun();
refreshNamingTemplatePreview();
