let currentRun = null;
let pollTimer = null;
let latestState = null;
let manualContext = null;
let manualCurrentCoverUrl = '';
let manualReviewItems = [];
let manualSearchResultsCache = [];
let goodreadsBreakerHandledForRun = null;

const $ = (id) => document.getElementById(id);
const { escapeHtml, renderDownloadLinks, statCard: stat, loadAbsAggProviders, getAbsAggProviderParamHint, isAbsAggReachable, checkAbsReachable, loadAbsAggSettings, saveAbsAggUrl, searchAbsAgg, scoreBadge, initFolderBrowser, saveActiveRun, clearActiveRun, loadActiveRun } = window.UiCommon;
const RUN_KEY = 'fixer';

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

// On load, resume showing a fixer run that is still going (or just finished) in
// the background so navigating away and back does not lose it.
async function resumeActiveRun() {
  const id = loadActiveRun(RUN_KEY);
  if (!id) return;
  const res = await fetch(`/api/runs/${id}`).catch(() => null);
  if (!res || !res.ok) { clearActiveRun(RUN_KEY); return; }
  attachToRun(id);
}

const PROVIDER_LABELS = {
  'audible': 'Audible',
  'abs': 'Audiobookshelf',
  'abs-agg': 'abs-agg',
  'graphicaudio': 'GraphicAudio',
  'soundbooththeater': 'SoundBooth Theater',
  'goodreads': 'Goodreads',
  'kindle': 'Kindle (cover)',
};

function fixerMajorVersion(scriptName) {
  const m = scriptName.match(/-v(\d+)/i);
  return m ? parseInt(m[1]) : 0;
}

function updateV5Fields() {
  const isV5 = fixerMajorVersion($('script').value) >= 5;
  $('v5Fields').style.display = isV5 ? '' : 'none';
}

async function loadScripts() {
  const res = await fetch('/api/scripts');
  const data = await res.json();
  const select = $('script');
  select.innerHTML = '';
  for (const name of data.fixer_scripts || data.scripts) {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    if (name === data.default_script) opt.selected = true;
    select.appendChild(opt);
  }
  updateV5Fields();
}

function collectRequest() {
  const prefs = window.LibraForgePrefs?.get() || {};
  const ignoredFolders = (prefs.ignoredFolders || []).map(f => f.trim()).filter(Boolean);
  const skipPatterns = $('skipPatterns').value.split('\n').map((s) => s.trim()).filter(Boolean);
  if ($('usePersistentSkip')?.checked) {
    const persistent = (prefs.persistentSkipPatterns || '').split('\n').map(s => s.trim()).filter(Boolean);
    for (const p of persistent) {
      if (!skipPatterns.includes(p)) skipPatterns.push(p);
    }
  }
  return {
    script_name: $('script').value,
    target_path: $('targetPath').value.trim(),
    auth_file: $('authFile').value.trim(),
    apply: $('apply').checked,
    backup: $('backup').checked,
    restore_metadata: $('restore').checked,
    force: $('force').checked,
    force_original: $('forceOriginal').checked,
    cover_if_missing: $('coverIfMissing').checked,
    replace_cover: $('replaceCover').checked,
    metadata_json_only: $('metadataJsonOnly').checked,
    workers: fixerMajorVersion($('script').value) >= 5 ? parseInt($('workers').value || '1', 10) : undefined,
    write_workers: fixerMajorVersion($('script').value) >= 5 ? parseInt($('writeWorkers').value || '1', 10) : undefined,
    api_delay_ms: fixerMajorVersion($('script').value) >= 5 ? parseInt($('apiDelayMs').value || '0', 10) : 0,
    write_mode: fixerMajorVersion($('script').value) >= 5 ? ($('writeMode').value || 'smart') : 'smart',
    provider: fixerMajorVersion($('script').value) >= 5 ? ($('batchProvider')?.value || 'audible') : 'audible',
    abs_provider: fixerMajorVersion($('script').value) >= 5 ? ($('batchAbsProvider')?.value || 'audible') : 'audible',
    enable_goodreads_fallback: fixerMajorVersion($('script').value) >= 5 ? Boolean($('enableGoodreadsFallback')?.checked) : false,
    debug_trace: fixerMajorVersion($('script').value) >= 5 ? Boolean(prefs.debugTrace) : false,
    debug_trace_file: prefs.debugTraceFile || "",
    min_score: parseFloat($('minScore').value || '0.7'),
    limit: parseInt($('limit').value || '50', 10),
    max_files: parseInt($('maxFiles').value || '0', 10),
    duration_review_threshold: parseFloat($('durationThreshold').value || '10'),
    skip_patterns: skipPatterns,
    ignored_folders: ignoredFolders,
  };
}

function collectManualMetadata() {
  return {
    title: $('manualTitle').value.trim(),
    subtitle: '',
    author: $('manualAuthor').value.trim(),
    narrator: $('manualNarrator').value.trim(),
    series: $('manualSeries').value.trim(),
    sequence: $('manualSequence').value.trim(),
    year: '',
    summary: '',
    cover_url: '',
    asin: '',
    local_duration_minutes: manualContext?.metadata?.local_duration_minutes ?? null,
  };
}

async function startRun() {
  // Block if a previous run's workers are still draining.
  const drainCheck = await fetch('/api/runs/draining').then(r => r.json()).catch(() => ({ draining: false }));
  if (drainCheck.draining) {
    showWorkerDrainBanner(true);
    return;
  }
  const req = collectRequest();
  if (req.cover_if_missing && req.replace_cover) {
    const ok = confirm('Both cover options are enabled. Replace existing cover already covers missing covers too. Continue with replace-cover behavior?');
    if (!ok) return;
  }
  const res = await fetch('/api/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    alert(await res.text());
    return;
  }
  const data = await res.json();
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
  latestState = state;
  await render(state);
  if (['completed', 'failed', 'cancelled'].includes(state.status)) {
    if (state.workers_draining) {
      // Workers are still finishing writes -- keep polling, block start.
      showWorkerDrainBanner(true);
      return;
    }
    clearInterval(pollTimer);
    clearActiveRun(RUN_KEY);
    showWorkerDrainBanner(false);
    $('startBtn').disabled = false;
    $('cancelBtn').disabled = true;
    if (state.stats?.goodreads_circuit_tripped && goodreadsBreakerHandledForRun !== currentRun) {
      goodreadsBreakerHandledForRun = currentRun;
      showGoodreadsBreakerWarning(state.stats.search_workers);
    }
  }
}

// Given the effective search-worker count this run used, decide what to
// suggest for the next Goodreads-enabled run: cap at 5, then step down by one
// each time the breaker keeps tripping; at 1 worker there is nothing left to
// lower, so the likely cause is Goodreads-side congestion, not our own rate.
function computeGoodreadsWorkerSuggestion(currentWorkers) {
  const n = Number(currentWorkers);
  if (!Number.isFinite(n) || n <= 0) return { kind: 'unknown' };
  if (n > 5) return { kind: 'lower', current: n, suggested: 5 };
  if (n > 1) return { kind: 'lower', current: n, suggested: n - 1 };
  return { kind: 'wait_only', current: n };
}

function buildGoodreadsBreakerDialog() {
  if ($('goodreadsBreakerDialog')) return;
  const dlg = document.createElement('dialog');
  dlg.id = 'goodreadsBreakerDialog';
  dlg.className = 'manual-apply-dialog org-confirm-dialog';
  dlg.innerHTML = `
    <h3 class="manual-apply-title org-confirm-danger-title">Goodreads rate limit hit</h3>
    <p>This run tried the Goodreads (abs-tract) fallback and got blocked enough times in a
    row that the circuit breaker opened, skipping Goodreads/Kindle lookups for the rest of
    the cooldown window. Books affected are marked with a "GR LIMITED" badge in the match
    report instead of being counted as genuine no-matches.</p>
    <p id="goodreadsBreakerAdvice"></p>
    <div class="manual-apply-actions">
      <button id="goodreadsBreakerOk" class="primary">Got it</button>
    </div>`;
  document.body.appendChild(dlg);
}

function showGoodreadsBreakerWarning(searchWorkers) {
  buildGoodreadsBreakerDialog();
  const dlg = $('goodreadsBreakerDialog');
  const suggestion = computeGoodreadsWorkerSuggestion(searchWorkers);
  let advice;
  if (suggestion.kind === 'lower') {
    advice = `Wait about 2 minutes after this run finishes before starting another
      Goodreads-enabled run, and lower search workers from ${suggestion.current} to
      ${suggestion.suggested} to ease off Goodreads next time.`;
  } else if (suggestion.kind === 'wait_only') {
    advice = `This run already used just 1 search worker, so lowering it further won't
      help. Goodreads may simply be under heavy traffic right now, independent of our
      request rate -- it's best to wait and try again another time rather than retrying
      immediately.`;
  } else {
    advice = `Wait about 2 minutes after this run finishes before starting another
      Goodreads-enabled run, and consider lowering the search worker count if this
      keeps happening.`;
  }
  $('goodreadsBreakerAdvice').textContent = advice;
  return new Promise((resolve) => {
    const onOk = () => { cleanup(); resolve(); };
    const onBackdrop = (e) => { if (e.target === dlg) onOk(); };
    function cleanup() {
      $('goodreadsBreakerOk').removeEventListener('click', onOk);
      dlg.removeEventListener('click', onBackdrop);
      dlg.close();
    }
    $('goodreadsBreakerOk').addEventListener('click', onOk);
    dlg.addEventListener('click', onBackdrop);
    dlg.showModal();
  });
}

function showWorkerDrainBanner(visible) {
  const banner = $('workerDrainBanner');
  if (!banner) return;
  banner.hidden = !visible;
  $('startBtn').disabled = visible;
  if (visible && !window._drainPollTimer) {
    window._drainPollTimer = setInterval(async () => {
      const r = await fetch('/api/runs/draining').then(rr => rr.json()).catch(() => ({ draining: true }));
      if (!r.draining) {
        clearInterval(window._drainPollTimer);
        window._drainPollTimer = null;
        showWorkerDrainBanner(false);
      }
    }, 3000);
  }
}

async function render(state) {
  const pct = Number(state.percent || 0).toFixed(1);
  $('ring').style.setProperty('--pct', pct);
  $('percent').textContent = `${pct}%`;
  $('runStatus').textContent = state.phase_label || state.status.toUpperCase();
  const phaseDetail = state.phase_detail || '';
  const currentPath = state.current_file || '';
  $('currentFile').textContent = state.error
    || [phaseDetail, currentPath && currentPath !== phaseDetail ? currentPath : ''].filter(Boolean).join(' · ')
    || 'Waiting for output...';
  $('command').textContent = (state.command || []).join(' ');
  $('tail').textContent = (state.tail || []).join('\n');
  $('tail').scrollTop = $('tail').scrollHeight;
  renderDownloadLinks($('downloadLinks'), state.downloads || {});
  renderPhaseCounters(state);
  renderCategories(state.files_by_category || {});
  renderManualReview(state.manual_review_items || []);
  currentReportId = state.id || null;
  await renderMatchReport(state.report_items || []);
  renderStats(state.stats || {}, state.started_at, state.finished_at);
}

function renderPhaseCounters(state) {
  const el = $('phaseCounters');
  if (!el) return;
  if (state.run_type !== 'fixer') { el.style.display = 'none'; return; }
  el.style.display = '';

  const total = state.total || 0;
  const matchCurrent = state.current || 0;
  const writeCurrent = state.write_current || 0;
  const isRunning = state.status === 'running';
  const isTerminal = ['completed', 'failed', 'cancelled'].includes(state.status);
  const scanDone = total > 0;

  // Scan bar: indeterminate while scanning, solid green when found
  const scanFill = $('scanFill');
  if (scanDone) {
    scanFill.className = 'phase-fill complete';
  } else if (isRunning) {
    scanFill.className = 'phase-fill indeterminate';
  } else {
    scanFill.className = 'phase-fill';
  }
  $('scanCount').textContent = scanDone ? 'done' : (isRunning ? '…' : '-');

  // Match bar -- also mark done when we're in the write phase (current locked at total)
  const matchPct = total ? (matchCurrent / total * 100) : 0;
  const inWritePhase = ['writing', 'recording'].includes(state.phase);
  const matchDone = total > 0 && (matchCurrent >= total || inWritePhase);
  const matchFill = $('matchFill');
  matchFill.className = 'phase-fill' + (matchDone ? ' complete' : '');
  if (!matchDone) matchFill.style.width = `${matchPct}%`;
  $('matchCount').textContent = total ? `${matchDone ? total : matchCurrent} / ${total}` : '-';

  // Write bar
  const writePct = total ? Math.min(100, writeCurrent / total * 100) : 0;
  const writeDone = isTerminal && writeCurrent > 0 && writePct >= 99.9;
  const writeFill = $('writeFill');
  writeFill.className = 'phase-fill' + (writeDone ? ' complete' : '');
  if (!writeDone) writeFill.style.width = `${writePct}%`;
  $('writeCount').textContent = total ? `${writeCurrent} / ${total}` : '-';
}

function formatElapsed(startedAt, finishedAt) {
  if (!startedAt) return null;
  const seconds = Math.round(((finishedAt ? finishedAt * 1000 : Date.now()) - startedAt * 1000) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60), s = seconds % 60;
  if (m < 60) return `${m}m ${s.toString().padStart(2, '0')}s`;
  return `${Math.floor(m / 60)}h ${(m % 60).toString().padStart(2, '0')}m`;
}

function renderStats(stats, startedAt, finishedAt) {
  const mode = stats.mode_breakdown || {};
  const duration = stats.duration_breakdown || {};
  const provider = stats.provider_breakdown || {};
  const threshold = stats.large_duration_threshold || 10;
  const elapsed = formatElapsed(startedAt, finishedAt);
  const fill = stats.fill_breakdown;
  const manualAppliedCount = (latestState?.files_by_category?.['status:manual_applied'] || []).length;
  $('stats').innerHTML = [
    elapsed ? stat('Run duration', elapsed, 'Total elapsed time for this run.') : '',
    stat('Found', stats.found, 'Supported files discovered before filtering.'),
    stat('Matched', stats.matched, 'Files where the script selected a usable match.'),
    stats.smart_skipped ? stat('Smart-skipped', stats.smart_skipped, 'Tags already matched the planned values — in-file write skipped by smart mode.') : '',
    stat('Skipped', stats.skipped, 'Files intentionally not processed.'),
    manualAppliedCount ? stat('Manually applied', manualAppliedCount, 'Books previously applied via manual review. Shown with a green badge in the manual review list.') : '',
    stat('Failed', stats.failed, 'Files that hit an error.'),
    fill ? stat('Fill: books filled', fill.filled, 'Fill-missing: books that gained at least one empty field.') : '',
    fill ? stat('Fill: already complete', fill.complete, 'Fill-missing: books where every field was already present (no write).') : '',
    fill ? stat('Fill: ASIN filled', fill.asin, 'Fill-missing: books that gained an ASIN tag.') : '',
    stat('Mode: full', mode.full, 'Full metadata rewrite planned/applied.'),
    stat('Mode: series_only', mode.series_only, 'Only grouping-critical metadata is changed.'),
    stat('Mode: none', mode.none, 'No safe edit selected.'),
    provider.graphicaudio ? stat('Via GraphicAudio', provider.graphicaudio, 'Books matched via the GraphicAudio abs-agg endpoint.') : '',
    provider.soundbooththeater ? stat('Via Soundbooth Theater', provider.soundbooththeater, 'Books matched via the Soundbooth Theater abs-agg endpoint.') : '',
    provider.goodreads ? stat('Via Goodreads', provider.goodreads, 'Books matched via the Goodreads (abs-tract) fallback, used when Audible did not return a confident match.') : '',
    stats.goodreads_circuit_tripped ? stat('GR rate-limited', matchReportItems.filter((i) => i.goodreads_rate_limited).length, 'Goodreads (abs-tract) circuit breaker opened during this run; these books were skipped for Goodreads instead of counted as a real no-match. See the GR LIMITED badge in the match report.') : '',
    stat('Duration > threshold', (stats.large_duration_items || []).length, `Runtime difference above ${threshold}%.`),
    stat('Duration: perfect', duration.perfect, 'Runtime difference <= 3%.'),
    stat('Duration: strong', duration.strong, 'Runtime difference <= 10%.'),
    stat('Duration: acceptable', duration.acceptable, 'Runtime difference <= 20%; review advised.'),
    stat('Duration: mismatch', duration.mismatch, 'Runtime difference > 20%; no full rewrite expected.'),
  ].join('');

  const large = stats.large_duration_items || [];
  $('largeDuration').innerHTML = large.length
    ? `<h3>Large duration differences</h3><div class="file-list">${large.map((item) => `<div class="file-item"><strong>${item.diff_percent}%</strong> ${escapeHtml(item.path)}</div>`).join('')}</div>`
    : '<p class="note">No selected matches above the large duration threshold.</p>';
}

function renderCategories(categories) {
  const select = $('categorySelect');
  const previous = select.value;
  const keys = Object.keys(categories).sort();
  select.innerHTML = '<option value="">Select category</option>';
  for (const key of keys) {
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = `${key} (${categories[key].length})`;
    select.appendChild(opt);
  }
  if (keys.includes(previous)) select.value = previous;
  renderCategoryFiles();
}

function renderCategoryFiles() {
  const key = $('categorySelect').value;
  const items = (latestState?.files_by_category || {})[key] || [];
  $('categoryFiles').innerHTML = items.length
    ? items.map((item) => `
        <div class="file-item file-item-row">
          <div>${escapeHtml(item.path)}${item.title ? `<br><span>${escapeHtml(item.title)}</span>` : ''}</div>
          <button class="secondary" data-cat-load="${escapeHtml(item.path)}">Load target</button>
        </div>`).join('')
    : '<div class="file-item">No category selected.</div>';

  for (const button of $('categoryFiles').querySelectorAll('button[data-cat-load]')) {
    button.addEventListener('click', () => loadManualTarget(button.getAttribute('data-cat-load')));
  }
}

function renderManualDiscovery(data) {
  const items = data.items || [];
  const summary = data.truncated
    ? `Showing ${data.returned} of ${data.total} books (30-book limit).`
    : `Found ${data.total} book${data.total === 1 ? '' : 's'}.`;
  $('manualDiscoveryMeta').textContent = summary;
  $('manualDiscoveryList').innerHTML = items.length
    ? items.map((item) => `
      <div class="file-item">
        <div>${escapeHtml(item.display_path)}</div>
        ${item.is_grouped ? '<div class="reason-badges"><span class="reason-badge">grouped book</span></div>' : ''}
        <button class="secondary" data-discovered-load="${encodeURIComponent(item.path)}">Load target</button>
      </div>
    `).join('')
    : '<div class="file-item">No supported books found.</div>';

  for (const button of $('manualDiscoveryList').querySelectorAll('button[data-discovered-load]')) {
    button.addEventListener('click', () => loadManualTarget(decodeURIComponent(button.getAttribute('data-discovered-load'))));
  }
}

async function discoverManualTargets(path = $('manualBrowsePath').value.trim()) {
  if (!path) {
    alert('Enter a file or folder path.');
    return;
  }
  $('manualDiscoverBtn').disabled = true;
  $("manualDiscoveryMeta").textContent = "Scanning for books...";
  $("manualDiscoveryList").innerHTML = "";
  $("manualDiscoverBtn").textContent = "Loading...";
  const res = await fetch('/api/manual-review/discover', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, script_name: $('script').value }),
  });
  const data = await res.json();
  $('manualDiscoverBtn').disabled = false;
  $("manualDiscoverBtn").textContent = "Load Path";
  if (!res.ok) {
    alert(data.detail || 'Failed to load file or folder');
    return;
  }
  $('manualBrowsePath').value = data.path || path;
  renderManualDiscovery(data);
}

async function browseManualPath(path = $('manualBrowsePath').value.trim() || '/audiobooks') {
  $("manualDiscoveryMeta").textContent = "Loading folder...";
  $("manualBrowseBtn").disabled = true;
  $("manualBrowseBtn").textContent = "Loading...";
  const res = await fetch(`/api/manual-review/browse?path=${encodeURIComponent(path)}`);
  const data = await res.json();
  $("manualBrowseBtn").disabled = false;
  $("manualBrowseBtn").textContent = "Browse Folders";
  if (!res.ok) {
    alert(data.detail || 'Failed to browse audiobook folders');
    return;
  }

  $('manualBrowsePath').value = data.current_path;
  const parentButton = data.parent_path
    ? `<button class="secondary" data-browse-path="${encodeURIComponent(data.parent_path)}">Up one folder</button>`
    : '';
  const directories = (data.directories || []).map((item) =>
    `<button class="path-entry secondary" data-browse-path="${encodeURIComponent(item.path)}">Folder: ${escapeHtml(item.name)}</button>`
  ).join('');
  const files = (data.files || []).map((item) =>
    `<button class="path-entry secondary" data-browse-file="${encodeURIComponent(item.path)}">File: ${escapeHtml(item.name)}</button>`
  ).join('');
  const browser = $('manualPathBrowser');
  browser.hidden = false;
  browser.innerHTML = `
    <div class="browser-head">
      <strong>${escapeHtml(data.current_path)}</strong>
      <div class="browser-actions">
        ${parentButton}
        <button data-use-folder="${encodeURIComponent(data.current_path)}">Use this folder</button>
        <button class="secondary" data-close-browser>Close</button>
      </div>
    </div>
    <div class="browser-entries">${directories || files ? directories + files : '<span class="note">No folders or supported audio files here.</span>'}</div>
    ${data.truncated ? '<p class="note">This folder listing is truncated to 200 entries per type.</p>' : ''}
  `;

  for (const button of browser.querySelectorAll('button[data-browse-path]')) {
    button.addEventListener('click', () => browseManualPath(decodeURIComponent(button.getAttribute('data-browse-path'))));
  }
  for (const button of browser.querySelectorAll('button[data-browse-file]')) {
    button.addEventListener('click', () => {
      const selectedPath = decodeURIComponent(button.getAttribute('data-browse-file'));
      $('manualBrowsePath').value = selectedPath;
      browser.hidden = true;
      discoverManualTargets(selectedPath);
    });
  }
  browser.querySelector('button[data-use-folder]').addEventListener('click', () => {
    const selectedPath = decodeURIComponent(browser.querySelector('button[data-use-folder]').getAttribute('data-use-folder'));
    browser.hidden = true;
    discoverManualTargets(selectedPath);
  });
  browser.querySelector('button[data-close-browser]').addEventListener('click', () => { browser.hidden = true; });
}

function renderManualReview(items) {
  manualReviewItems = items || [];

  // Populate the reason filter from the union of reasons (with counts).
  const filter = $('manualReviewFilter');
  if (filter) {
    const counts = {};
    for (const item of manualReviewItems) {
      for (const reason of item.reasons || []) {
        counts[reason] = (counts[reason] || 0) + 1;
      }
    }
    const previous = filter.value;
    const reasons = Object.keys(counts).sort();
    filter.innerHTML = `<option value="">All reasons (${manualReviewItems.length})</option>`
      + reasons.map((r) => `<option value="${escapeHtml(r)}">${escapeHtml(r)} (${counts[r]})</option>`).join('');
    filter.value = reasons.includes(previous) ? previous : '';
  }

  renderManualReviewList();
}

function renderManualReviewList() {
  const filter = $('manualReviewFilter');
  const selected = filter ? filter.value : '';
  const items = selected
    ? manualReviewItems.filter((item) => (item.reasons || []).includes(selected))
    : manualReviewItems;

  const _dangerReasons = new Set(['no match','asin conflict','low score','missing metadata','unsafe match','no metadata','status:skipped','mode:none']);
  const _successReasons = new Set(['manually applied']);
  $('manualReviewList').innerHTML = items.length
    ? items.map((item) => `
      <div class="file-item">
        <div>${escapeHtml(item.path)}</div>
        <div class="reason-badges">
          ${(item.reasons || []).map((reason) => `<span class="reason-badge ${_dangerReasons.has(reason) ? 'danger' : _successReasons.has(reason) ? 'recommended' : ''}">${escapeHtml(reason)}</span>`).join('')}
          ${item.diff_percent ? `<span class="reason-badge danger">${escapeHtml(String(item.diff_percent))}% diff</span>` : ''}
        </div>
        <button class="secondary" data-manual-load="${escapeHtml(item.path)}">Load target</button>
      </div>
    `).join('')
    : `<div class="file-item">${manualReviewItems.length ? 'No items match this reason.' : 'No manual review items in this run.'}</div>`;

  for (const button of $('manualReviewList').querySelectorAll('button[data-manual-load]')) {
    button.addEventListener('click', () => loadManualTarget(button.getAttribute('data-manual-load')));
  }
}

async function loadManualTarget(path, useBackupTags = false) {
  $("manualMeta").textContent = "Inspecting selected target...";
  $("manualSearchResults").innerHTML = "";
  const res = await fetch('/api/manual-review/load', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      path,
      script_name: $('script').value,
      use_backup_tags: useBackupTags,
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Failed to inspect manual review target');
    return;
  }

  manualContext = data;
  $('manualGroupedBadge').hidden = !data.is_grouped;
  await loadManualCurrentCover();
  $('manualTargetPath').value = data.display_path || data.path || '';
  $('manualSourcePath').value = data.source_path || '';
  $('manualQuery').value = data.queries?.[0] || '';
  $('manualTitle').value = data.metadata?.title || '';
  $('manualAuthor').value = data.metadata?.author || '';
  $('manualSeries').value = data.metadata?.series || '';
  $('manualSequence').value = data.metadata?.sequence || '';
  $('manualNarrator').value = data.metadata?.narrator || '';
  $('manualMeta').textContent = data.queries?.length
    ? `Suggested queries: ${data.queries.join(' | ')}`
    : 'No suggested queries were derived from this target.';
  $('manualSearchResults').innerHTML = '<p class="note">Search this target to review manual candidates.</p>';

  // Auto-detect GraphicAudio / SoundBooth Theater from series or metadata
  // and switch the provider so the search hits the right endpoint.
  const detectedSeries = (data.metadata?.series || '').toLowerCase();
  const detectedPub   = (data.metadata?.publisher || '').toLowerCase();
  const isTitleQueryProvider = detectedSeries.includes('graphicaudio') || detectedPub.includes('graphicaudio')
    || detectedSeries.includes('soundbooth') || detectedPub.includes('soundbooth');
  // Update the hint before calling toggleManualProviderFields -- that function lives
  // inside an async IIFE and is out of scope here, so the call may throw.
  if ($('manualTitleQueryNote')) $('manualTitleQueryNote').hidden = !isTitleQueryProvider;
  if (detectedSeries.includes('graphicaudio') || detectedPub.includes('graphicaudio')) {
    $('manualProvider').value = 'graphicaudio';
    try { toggleManualProviderFields(); } catch {}
  } else if (detectedSeries.includes('soundbooth') || detectedPub.includes('soundbooth')) {
    $('manualProvider').value = 'soundbooththeater';
    try { toggleManualProviderFields(); } catch {}
  }

  $('manualTargetPath').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function loadManualCurrentCover() {
  if (manualCurrentCoverUrl) {
    URL.revokeObjectURL(manualCurrentCoverUrl);
    manualCurrentCoverUrl = '';
  }

  $('manualCoverStatus').textContent = 'Loading current cover...';
  if (!manualContext?.path) return;

  const params = new URLSearchParams({
    path: manualContext.path,
    script_name: $('script').value,
  });
  const res = await fetch(`/api/manual-review/current-cover?${params}`);
  if (!res.ok) {
    $('manualCoverStatus').textContent = 'No current embedded or folder cover was found.';
    return;
  }

  manualCurrentCoverUrl = URL.createObjectURL(await res.blob());
  $('manualCoverStatus').textContent = 'Current cover loaded once for comparison with all candidates.';
}

const COMPARE_FIELDS = [
  ['Title', 'title'],
  ['Subtitle', 'subtitle'],
  ['Author', 'author'],
  ['Narrator', 'narrator'],
  ['Series', 'series'],
  ['Sequence', 'sequence'],
  ['Year', 'year'],
  ['ASIN', 'asin'],
  ['Publisher', 'publisher'],
  ['Genre', 'genre'],
];

function chosenMetadataFor(result, mode) {
  return (result.chosen_metadata_by_mode && result.chosen_metadata_by_mode[mode])
    || result.chosen_metadata
    || {
      title: result.title,
      subtitle: result.subtitle,
      author: (result.authors || []).join(', '),
      narrator: (result.narrators || []).join(', '),
      series: result.series,
      sequence: result.sequence,
      year: result.year,
      asin: result.asin,
      summary: result.summary,
      genre: '',
    };
}

function buildCompareTable(result, mode) {
  const local = (manualContext && manualContext.metadata) || {};
  const chosen = chosenMetadataFor(result, mode);
  const rows = COMPARE_FIELDS.map(([label, key]) => {
    const current = String(local[key] ?? '').trim();
    // Publisher is preserved from the local file (the match never overwrites it).
    const willWrite = key === 'publisher'
      ? current
      : String(chosen[key] ?? '').trim();
    const changed = willWrite && willWrite !== current;
    return `
      <tr class="${changed ? 'changed' : ''}">
        <th>${label}</th>
        <td>${escapeHtml(current || '-')}</td>
        <td>${escapeHtml(willWrite || '-')}</td>
      </tr>`;
  }).join('');
  // Duration is informational (the match never rewrites runtime): compare local
  // runtime against the Audible candidate's, with the match status/diff.
  const dur = result.duration || {};
  const fmtMin = (v) => (v || v === 0) ? `${Number(v).toFixed(1)} min` : '';
  const localDur = fmtMin(local.local_duration_minutes ?? dur.local_minutes);
  const audibleDurVal = result.duration_minutes ?? dur.audible_minutes;
  let audibleDur = fmtMin(audibleDurVal);
  if (audibleDur && dur.status) {
    const pct = (dur.diff_percent || dur.diff_percent === 0) ? ` · ${dur.diff_percent}%` : '';
    audibleDur += ` (${dur.status}${pct})`;
  }
  const durationRow = `
      <tr>
        <th>Duration</th>
        <td>${escapeHtml(localDur || '-')}</td>
        <td>${escapeHtml(audibleDur || '-')}</td>
      </tr>`;

  const summary = String(chosenMetadataFor(result, mode).summary ?? '').trim();
  const summaryBlock = summary
    ? `<details class="compare-summary"><summary>Summary</summary><p>${escapeHtml(summary)}</p></details>`
    : '';
  return `
    <table class="compare-table">
      <thead><tr><th>Field</th><th>Current</th><th>Will write</th></tr></thead>
      <tbody>${rows}${durationRow}</tbody>
    </table>
    ${summaryBlock}`;
}

function renderCompareTable(index, result, mode) {
  const holder = $('manualSearchResults').querySelector(`div[data-compare="${index}"]`);
  if (holder) holder.innerHTML = buildCompareTable(result, mode);
}

function renderManualSearchResults(results = []) {
  manualSearchResultsCache = results;
  $('manualSearchResults').innerHTML = results.length
    ? results.map((result, index) => {
      const duration = result.duration || {};
      const subtitle = result.subtitle ? `<p>${escapeHtml(result.subtitle)}</p>` : '';
      return `
        <article class="result-card">
          <div class="result-head">
            <div>
              <h3>${escapeHtml(result.title)}</h3>
              ${subtitle}
            </div>
            <div class="score-badge">${scoreBadge(result)}</div>
          </div>
          <div class="cover-comparison">
            <div>
              <strong>Current</strong>
              ${manualCurrentCoverUrl
                ? `<img class="cover-thumb" src="${escapeHtml(manualCurrentCoverUrl)}" alt="Current book cover" />`
                : '<p class="note">No current cover</p>'}
            </div>
            <div>
              <strong>${
                result.provider === 'abs-agg' ? (PROVIDER_LABELS[result.abs_agg_provider] || result.abs_agg_provider || 'abs-agg')
                : result.provider === 'abs-tract' ? (result.abs_tract_provider === 'kindle' ? 'Kindle (cover)' : 'Goodreads')
                : 'Audible'
              }</strong>
              ${result.cover_url
                ? `<img class="cover-thumb" src="${escapeHtml(result.cover_url)}" alt="Match cover" />`
                : '<p class="note">No cover</p>'}
            </div>
          </div>
          <div class="result-meta">
            <span>Recommended mode: ${escapeHtml(result.recommended_edit_mode || result.edit_mode || '-')}</span>
            <span>ASIN: ${escapeHtml(result.asin || '-')}</span>
            <span>Series: ${escapeHtml(result.series || '-')} ${result.sequence ? `#${escapeHtml(String(result.sequence))}` : ''}</span>
            <span>Authors: ${escapeHtml((result.authors || []).join(', ') || '-')}</span>
            <span>Narrators: ${escapeHtml((result.narrators || []).join(', ') || '-')}</span>
            <span>Runtime: ${escapeHtml(String(result.duration_minutes || '-'))} min</span>
            <span>Duration status: ${escapeHtml(duration.status || '-')}</span>
          </div>
          <details class="compare-panel">
            <summary>Compare metadata (Current vs. Will write)</summary>
            <div data-compare="${index}">${buildCompareTable(result, result.recommended_edit_mode || result.edit_mode)}</div>
          </details>
          <div class="actions">
            <label>Apply mode
              <select data-manual-mode="${index}">
                ${(result.allowed_edit_modes || []).map((mode) => `
                  <option value="${escapeHtml(mode)}" ${mode === (result.recommended_edit_mode || result.edit_mode) ? 'selected' : ''}>
                    ${mode === 'full' ? 'Full metadata' : 'Series only'}
                  </option>
                `).join('')}
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                data-manual-replace-cover="${index}"
                ${result.cover_url ? '' : 'disabled'}
              />
              Overwrite current cover
            </label>
            <button data-manual-apply-index="${index}">Apply this match</button>
          </div>
        </article>
      `;
    }).join('')
    : '<p class="note">No Audible results for this manual review target.</p>';

  for (const button of $('manualSearchResults').querySelectorAll('button[data-manual-apply-index]')) {
    button.addEventListener('click', () => {
      const index = Number(button.getAttribute('data-manual-apply-index'));
      const mode = $('manualSearchResults').querySelector(`select[data-manual-mode="${index}"]`)?.value || '';
      const replaceCover = $('manualSearchResults').querySelector(`input[data-manual-replace-cover="${index}"]`)?.checked || false;
      applyManualMatch(results[index], mode, replaceCover, button);
    });
  }

  for (const select of $('manualSearchResults').querySelectorAll('select[data-manual-mode]')) {
    const updateCoverControl = () => {
      const index = select.getAttribute('data-manual-mode');
      const checkbox = $('manualSearchResults').querySelector(`input[data-manual-replace-cover="${index}"]`);
      renderCompareTable(Number(index), results[Number(index)], select.value);
      if (!checkbox) return;
      checkbox.disabled = select.value !== 'full' || !results[Number(index)]?.cover_url;
      if (checkbox.disabled) checkbox.checked = false;
    };
    select.addEventListener('change', updateCoverControl);
    updateCoverControl();
  }
}

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

function buildManualApplyDialogs() {
  if ($('manualApplyEditDialog')) return;

  const editDlg = document.createElement('dialog');
  editDlg.id = 'manualApplyEditDialog';
  editDlg.className = 'manual-apply-dialog manual-apply-edit-dialog';
  editDlg.innerHTML = `
    <h3 class="manual-apply-title">Review before applying</h3>
    <p id="manualApplyEditContext" class="manual-apply-body"></p>
    <p id="manualApplyEditCoverNote" class="manual-apply-cover-note" hidden>The current cover will be replaced with the match cover.</p>
    <p class="manual-apply-write-policy-note">
      <strong>Apply Fill</strong> writes only the fields filled in below &mdash; a blank field is left completely
      untouched in the file. <strong>Full Overwrite</strong> writes every field exactly as shown, including
      blanks &mdash; a blank field here clears that tag. Separate multiple genres with a comma
      (e.g. "Fantasy, LitRPG") &mdash; each is saved as its own genre tag, not one combined genre.
    </p>
    <div class="manual-apply-edit-fields">
      <label>Title<input id="maeTitle" /></label>
      <label>Subtitle<input id="maeSubtitle" /></label>
      <label>Author<input id="maeAuthor" /></label>
      <label>Narrator<input id="maeNarrator" /></label>
      <label>Series<input id="maeSeries" /></label>
      <label>Sequence<input id="maeSequence" /></label>
      <label>Year<input id="maeYear" /></label>
      <label>ASIN<input id="maeAsin" /></label>
      <label>Publisher<input id="maePublisher" /></label>
      <label>Genre<input id="maeGenre" placeholder="e.g. Fantasy, LitRPG" /></label>
      <label class="mae-full-width">Comment / Summary<textarea id="maeSummary" rows="4"></textarea></label>
    </div>
    <div class="manual-apply-actions">
      <button id="maeCancelBtn" class="secondary">Cancel</button>
      <button id="maeFillBtn">Apply Fill</button>
      <button id="maeOverwriteBtn">Full Overwrite</button>
    </div>`;
  document.body.appendChild(editDlg);

  const progDlg = document.createElement('dialog');
  progDlg.id = 'manualApplyProgressDialog';
  progDlg.className = 'manual-apply-dialog';
  progDlg.innerHTML = `
    <h3 class="manual-apply-title" id="manualApplyProgressTitle">Applying…</h3>
    <div class="manual-apply-progress-bar">
      <div class="manual-apply-progress-fill indeterminate" id="manualApplyProgressFill"></div>
    </div>
    <p id="manualApplyProgressDetail" class="manual-apply-output-detail"></p>
    <p id="manualApplyProgressResult" class="manual-apply-body" hidden></p>
    <p id="manualApplyProgressPolicyWarning" class="manual-apply-warning" hidden></p>
    <p id="manualApplyProgressWarning" class="manual-apply-warning" hidden>
      Apply is still running in the background. You will be notified when it finishes.
    </p>
    <div class="manual-apply-actions">
      <button id="manualApplyDismissBtn" class="secondary">Dismiss</button>
    </div>`;
  document.body.appendChild(progDlg);
}

const MANUAL_APPLY_OUTPUT_DESCRIPTIONS = {
  tags: "Written directly into the audio file's embedded tags. Used for finalized single-file M4B books.",
  json_sidecar: 'Saved to a .libraforge.json sidecar file next to the audio. Used for multi-part books or files pending M4B conversion -- the M4B Tool picks this up automatically.',
};

async function applyManualMatch(result, editMode, replaceCover = false, applyBtn = null) {
  if (!manualContext?.path) { alert('Load a manual review target first.'); return; }
  if (!editMode) { alert('Choose an apply mode first.'); return; }

  buildManualApplyDialogs();
  const editDlg = $('manualApplyEditDialog');
  const progDlg = $('manualApplyProgressDialog');

  // Pre-fill edit dialog from the chosen result for the selected mode.
  const chosen = chosenMetadataFor(result, editMode);
  $('manualApplyEditContext').textContent =
    `Applying ${editMode} mode to: ${manualContext.display_path || manualContext.path}`;
  $('manualApplyEditCoverNote').hidden = !replaceCover;
  $('maeTitle').value     = chosen.title     || '';
  $('maeSubtitle').value  = chosen.subtitle  || '';
  $('maeAuthor').value    = chosen.author    || '';
  $('maeNarrator').value  = chosen.narrator  || '';
  $('maeSeries').value    = chosen.series    || '';
  $('maeSequence').value  = chosen.sequence  || '';
  $('maeYear').value      = chosen.year      || '';
  $('maeAsin').value      = chosen.asin      || '';
  $('maePublisher').value = chosen.publisher || '';
  $('maeGenre').value     = chosen.genre     || '';
  $('maeSummary').value   = chosen.summary   || '';

  // Resolves to null (cancelled) or the chosen write policy, 'fill' | 'overwrite'.
  const writePolicy = await new Promise(resolve => {
    function cleanup(val) {
      $('maeFillBtn').removeEventListener('click', onFill);
      $('maeOverwriteBtn').removeEventListener('click', onOverwrite);
      $('maeCancelBtn').removeEventListener('click', onCancel);
      editDlg.removeEventListener('cancel', onCancel);
      editDlg.close();
      resolve(val);
    }
    const onFill      = () => cleanup('fill');
    const onOverwrite = () => cleanup('overwrite');
    const onCancel    = () => cleanup(null);
    $('maeFillBtn').addEventListener('click', onFill);
    $('maeOverwriteBtn').addEventListener('click', onOverwrite);
    $('maeCancelBtn').addEventListener('click', onCancel);
    editDlg.addEventListener('cancel', onCancel, { once: true });
    editDlg.showModal();
  });

  if (!writePolicy) return;

  // Collect every field that differs from the match's pre-filled value --
  // including a field the user cleared back to blank, which is now sent as
  // an explicit "" override (an intentional clear) rather than silently
  // omitted (which would fall back to the match's own value, ignoring that
  // the user cleared it). See docs/design/manual-review-apply-rewrite-rules.md.
  const metadataOverride = {};
  const fields = [
    ['title', 'maeTitle'], ['subtitle', 'maeSubtitle'], ['author', 'maeAuthor'],
    ['narrator', 'maeNarrator'], ['series', 'maeSeries'], ['sequence', 'maeSequence'],
    ['year', 'maeYear'], ['asin', 'maeAsin'], ['publisher', 'maePublisher'],
    ['genre', 'maeGenre'], ['summary', 'maeSummary'],
  ];
  for (const [key, id] of fields) {
    const val = $(id).value.trim();
    const original = String(chosen[key] ?? '').trim();
    if (val !== original) metadataOverride[key] = val; // val may legitimately be ''
  }

  let completed = false;
  let dismissed = false;

  $('manualApplyProgressTitle').textContent = 'Applying…';
  $('manualApplyProgressFill').className = 'manual-apply-progress-fill indeterminate';
  $('manualApplyProgressDetail').innerHTML = `Mode: <strong>${escapeHtml(editMode)}</strong>`;
  $('manualApplyProgressResult').hidden = true;
  $('manualApplyProgressPolicyWarning').hidden = true;
  $('manualApplyProgressWarning').hidden = true;
  $('manualApplyDismissBtn').textContent = 'Dismiss';

  if (applyBtn) { applyBtn.disabled = true; applyBtn.textContent = 'Applying…'; }

  const dismissBtn = $('manualApplyDismissBtn');

  function handleDismiss() {
    if (!completed) {
      $('manualApplyProgressWarning').hidden = false;
      dismissed = true;
      progDlg.close();
    } else {
      progDlg.close();
    }
  }

  dismissBtn.addEventListener('click', handleDismiss, { once: true });
  progDlg.addEventListener('cancel', e => { e.preventDefault(); handleDismiss(); }, { once: true });
  progDlg.showModal();

  try {
    const res = await fetch('/api/manual-review/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: manualContext.path,
        script_name: $('script').value,
        selected_result: result,
        edit_mode: editMode,
        backup: $('backup').checked,
        cover_if_missing: false,
        replace_cover: replaceCover,
        writer: 'auto',
        metadata_override: metadataOverride,
        write_policy: writePolicy,
      }),
    });
    const data = await res.json();
    completed = true;
    if (applyBtn) { applyBtn.disabled = false; applyBtn.textContent = 'Apply this match'; }

    if (!res.ok) {
      const msg = data.detail || 'Failed to apply manual match';
      if (dismissed) { alert(`Manual apply failed:\n${msg}`); return; }
      $('manualApplyProgressTitle').textContent = 'Apply failed';
      $('manualApplyProgressFill').className = 'manual-apply-progress-fill error';
      $('manualApplyProgressResult').textContent = msg;
      $('manualApplyProgressResult').hidden = false;
      dismissBtn.textContent = 'Close';
      return;
    }

    const outputKind  = data.output_kind || 'tags';
    const outputLabel = outputKind === 'json_sidecar' ? 'sidecar' : 'tags';
    const desc        = MANUAL_APPLY_OUTPUT_DESCRIPTIONS[outputKind] || '';

    if (dismissed) {
      alert(`Manual apply complete.\nMode: ${data.edit_mode}  ·  Output: ${outputLabel}\n${data.target_path}`);
      return;
    }

    // Silently refresh the context so compare tables show post-apply values.
    try {
      const reloadRes = await fetch('/api/manual-review/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: manualContext.path, script_name: $('script').value, use_backup_tags: false }),
      });
      if (reloadRes.ok) {
        const reloadData = await reloadRes.json();
        manualContext = { ...manualContext, metadata: reloadData.metadata, queries: reloadData.queries };
        for (const div of $('manualSearchResults').querySelectorAll('div[data-compare]')) {
          const idx = Number(div.getAttribute('data-compare'));
          const mode = $('manualSearchResults').querySelector(`select[data-manual-mode="${idx}"]`)?.value
            || manualSearchResultsCache[idx]?.recommended_edit_mode
            || manualSearchResultsCache[idx]?.edit_mode;
          if (manualSearchResultsCache[idx]) renderCompareTable(idx, manualSearchResultsCache[idx], mode);
        }
      }
    } catch {}

    $('manualApplyProgressTitle').textContent = 'Applied successfully';
    $('manualApplyProgressFill').className = 'manual-apply-progress-fill complete';
    $('manualApplyProgressDetail').innerHTML =
      `Mode: <strong>${escapeHtml(data.edit_mode)}</strong> &nbsp;&middot;&nbsp; ` +
      `Output: <strong>${escapeHtml(outputLabel)}</strong>` +
      (desc ? `<span class="manual-apply-output-desc">${escapeHtml(desc)}</span>` : '');
    if (data.warning) {
      $('manualApplyProgressPolicyWarning').textContent = data.warning;
      $('manualApplyProgressPolicyWarning').hidden = false;
    }
    $('manualApplyProgressResult').textContent = `Target: ${data.target_path}`;
    $('manualApplyProgressResult').hidden = false;
    dismissBtn.textContent = 'Done';

  } catch (err) {
    completed = true;
    if (applyBtn) { applyBtn.disabled = false; applyBtn.textContent = 'Apply this match'; }
    if (dismissed) { alert('Manual apply encountered an error.'); return; }
    $('manualApplyProgressTitle').textContent = 'Apply error';
    $('manualApplyProgressFill').className = 'manual-apply-progress-fill error';
    $('manualApplyProgressResult').textContent = String(err);
    $('manualApplyProgressResult').hidden = false;
    dismissBtn.textContent = 'Close';
  }
}

function syncForceOriginal() {
  const forceOn = $('force').checked;
  const fo = $('forceOriginal');
  fo.disabled = !forceOn;
  fo.closest('label').style.opacity = forceOn ? '' : '0.4';
  if (!forceOn) fo.checked = false;
  const note = $('manualBackupNote');
  if (note) note.hidden = !(forceOn && fo.checked);
}
$('force').addEventListener('change', syncForceOriginal);
$('forceOriginal').addEventListener('change', syncForceOriginal);
syncForceOriginal();

$('workers').addEventListener('input', () => {
  $('writeWorkers').value = Math.min(parseInt($('workers').value || '1', 10), 10);
});
$('writeWorkers').addEventListener('input', () => {
  const v = parseInt($('writeWorkers').value || '1', 10);
  if (v > 10) $('writeWorkers').value = 10;
});

async function loadLastReport() {
  const btn = $('loadLastReportBtn');
  const prev = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Loading…';
  try {
    const res = await fetch('/api/reports/latest');
    if (!res.ok) { alert((await res.json()).detail || 'No report found'); return; }
    const report = await res.json();
    latestState = report;
    currentReportId = report.id || null;
    renderStats(report.stats || {}, report.started_at, report.finished_at);
    renderCategories(report.files_by_category || {});
    renderManualReview(report.manual_review_items || []);
    await renderMatchReport(report.report_items || []);
    $('runStatus').textContent = `Last report loaded (${report.status || 'unknown'})`;
    $('currentFile').textContent = report.id || '';
  } finally {
    btn.disabled = false;
    btn.textContent = prev;
  }
}

// ── Match Report Widget ──────────────────────────────────────────────────────

let matchReportItems = [];
let currentReportId = null;
let seriesGroupsRenderToken = 0;

async function renderMatchReport(items) {
  matchReportItems = items || [];
  const count = $('matchReportCount');
  const card = $('matchReportCard');
  if (!card) return;
  if (!matchReportItems.length) {
    count.style.display = 'none';
    $('matchReportWidget').hidden = true;
    $('matchReportBtn').textContent = 'View full match report';
    $('suspectReportBtn').hidden = true;
    return;
  }
  count.textContent = `${matchReportItems.length} book${matchReportItems.length !== 1 ? 's' : ''}`;
  count.style.display = '';
  buildMatchReportCards();
  if (currentReportId) {
    probeSuspectReport(currentReportId);
    const myToken = ++seriesGroupsRenderToken;
    const groups = await ensureSeriesGroupsForMatchReport(currentReportId);
    if (myToken !== seriesGroupsRenderToken) return; // a newer render call superseded this one
    if (groups.length) {
      const container = $('matchReportList');
      for (const group of groups.reverse()) {
        container.insertBefore(window.UiCommon.buildSeriesGroupCard(group), container.firstChild);
      }
    }
  }
}

async function probeSuspectReport(reportId) {
  const btn = $('suspectReportBtn');
  btn.hidden = false;
  try {
    const res = await fetch(`/api/reports/${encodeURIComponent(reportId)}/suspect-review`);
    const data = res.ok ? await res.json() : null;
    if (data && data.exists !== false) {
      renderSuspectReport(data);
    } else {
      btn.textContent = 'Generate Suspicion Report';
      btn.disabled = false;
    }
  } catch {
    btn.textContent = 'Generate Suspicion Report';
    btn.disabled = false;
  }
}

async function ensureSeriesGroupsForMatchReport(reportId) {
  if (!reportId) return [];
  let data;
  try {
    const probe = await fetch(`/api/reports/${reportId}/suspect-review`);
    data = await probe.json();
    if (data.exists === false) {
      const gen = await fetch(`/api/reports/${reportId}/suspect-review`, { method: 'POST' });
      data = await gen.json();
    }
  } catch (e) {
    return [];
  }
  return (data.suspects || []).filter((s) => s.status === 'series_group');
}

async function generateSuspectReport() {
  const btn = $('suspectReportBtn');
  btn.disabled = true;
  btn.textContent = 'Generating...';
  try {
    const res = await fetch(`/api/reports/${encodeURIComponent(currentReportId)}/suspect-review`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || 'Failed to generate suspicion report');
      btn.textContent = 'Generate Suspicion Report';
      btn.disabled = false;
      return;
    }
    const data = await res.json();
    renderSuspectReport(data);
  } catch (e) {
    alert('Error: ' + e.message);
    btn.textContent = 'Generate Suspicion Report';
    btn.disabled = false;
  }
}

const { buildSuspectCard, renderSuspectReport: _renderSuspectReport } = window.UiCommon;

function renderSuspectReport(data) {
  _renderSuspectReport(data, $('suspectReportBtn'), $('suspectReportWidget'), $('suspectReportList'));
}


function buildMatchReportCards() {
  const list = $('matchReportList');
  if (!list) return;
  const query = ($('matchReportSearch')?.value || '').toLowerCase().trim();
  const statusFilter = $('matchReportFilter')?.value || '';
  list.innerHTML = '';
  let shown = 0;
  for (const item of matchReportItems) {
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
    if (query) {
      const local = item.local || {};
      const m = item.match || {};
      const haystack = [
        item.path, local.title, local.author, local.series,
        m.title, m.author, m.series, m.asin,
      ].filter(Boolean).join(' ').toLowerCase();
      if (!haystack.includes(query)) continue;
    }
    list.appendChild(buildMatchCard(item));
    shown++;
  }
  if (!shown) {
    list.innerHTML = '<p class="note" style="grid-column:1/-1">No items match the current filter.</p>';
  }
}

function bookNameFromPath(p) {
  if (!p) return '';
  const parts = p.replace(/\\/g, '/').split('/').filter(Boolean);
  let name = parts[parts.length - 1] || '';
  name = name.replace(/\.[^.]+$/, '');
  return name;
}

function coverFolderFromPath(p) {
  if (!p) return '';
  return p.replace(/\\/g, '/');
}

function matchStatusInfo(item) {
  const s = (item.status || '').toLowerCase();
  const writeAction = (item.write_action || '').toLowerCase();
  if (writeAction === 'smart_skipped') return { label: 'Smart-skipped', cls: 'status-smart-skipped' };
  if (item.match) return { label: 'Matched', cls: 'status-matched' };
  if (s === 'skipped') {
    const reason = item.skip_reason ? ` — ${item.skip_reason}` : '';
    return { label: `Skipped${reason}`, cls: 'status-skipped' };
  }
  if (s === 'error') return { label: 'Error', cls: 'status-error' };
  if (s === 'matched' || s === 'applied' || s === 'written') return { label: 'Matched', cls: 'status-matched' };
  return { label: 'Not Matched', cls: 'status-unmatched' };
}

function buildMatchCard(item) {
  const hasMatch = !!item.match;
  const scorePct = item.score != null && item.score > 0 ? Math.round(item.score * 100) : null;
  const mode = item.mode || '';
  const folderPath = item.path || '';
  const coverFolder = coverFolderFromPath(folderPath);
  const localCoverUrl = coverFolder ? `/api/book/cover?path=${encodeURIComponent(coverFolder)}` : '';
  const bookName = item.local?.title || bookNameFromPath(folderPath) || folderPath;
  const { label: statusLabel, cls: statusClass } = matchStatusInfo(item);
  const local = item.local || {};
  const m = item.match || {};
  const providerLabel = escapeHtml(item.provider || 'Match');
  const writeAction = String(item.write_action || '').replace(/_/g, ' ');
  const writeNote = item.write_note ? ` title="${escapeHtml(item.write_note)}"` : '';

  const article = document.createElement('article');
  article.className = 'mrep-card';

  const details = document.createElement('details');
  details.className = 'mrep-details';

  const summary = document.createElement('summary');
  summary.className = 'mrep-head';
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
  details.appendChild(summary);

  const body = document.createElement('div');
  body.className = 'mrep-body';

  const localCoverImg = localCoverUrl
    ? `<img class="cover-thumb" src="${escapeHtml(localCoverUrl)}" alt="Local cover" onerror="this.style.display='none'" loading="lazy">`
    : '<p class="note">No cover</p>';
  const matchCoverImg = hasMatch && m.cover_url
    ? `<img class="cover-thumb" src="${escapeHtml(m.cover_url)}" alt="Match cover" onerror="this.style.display='none'" loading="lazy">`
    : '<p class="note">No cover</p>';

  const titleMatch = m.title ? (m.title + (m.subtitle ? ': ' + m.subtitle : '')) : '';
  const durationDiff = m.duration_diff_pct != null
    ? `${m.duration_diff_pct > 0 ? '+' : ''}${m.duration_diff_pct}%` : '';
  const localDur = local.duration_minutes != null ? `${local.duration_minutes} min` : '';
  const matchDur = m.duration_minutes != null ? `${m.duration_minutes} min` : '';

  const queryHtml = item.used_query
    ? `<div class="mrep-query">Query: <span>${escapeHtml(item.used_query)}</span></div>` : '';

  body.innerHTML = `
    <div class="cover-comparison mrep-covers">
      <div><strong>Local</strong>${localCoverImg}</div>
      <div><strong>${providerLabel}</strong>${matchCoverImg}</div>
    </div>
    ${queryHtml}
    <table class="compare-table mrep-compare">
      <thead><tr><th></th><th>Local</th><th>${hasMatch ? providerLabel : 'Match'}</th></tr></thead>
      <tbody>
        ${mrepRow('Title', local.title, titleMatch)}
        ${mrepRow('Author', local.author, m.author)}
        ${mrepRow('Narrator', local.narrator, m.narrator)}
        ${mrepRow('Series', local.series, m.series)}
        ${mrepRow('Sequence', local.sequence, m.sequence)}
        ${mrepRow('Genre', local.genre, m.genre)}
        ${mrepRow('Year', local.year, m.year)}
        ${mrepRow('ASIN', local.asin, m.asin)}
        ${mrepRow('ISBN', local.isbn, m.isbn)}
        ${mrepRow('Duration', localDur, matchDur)}
        ${durationDiff ? mrepRow('Dur. diff', '', durationDiff) : ''}
      </tbody>
    </table>
  `;

  const loadBtn = document.createElement('button');
  loadBtn.className = 'secondary mrep-load-btn';
  loadBtn.textContent = 'Load into Manual Review';
  loadBtn.addEventListener('click', () => {
    if (!folderPath) return;
    loadManualTarget(folderPath);
    $('manualTargetPath')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
  body.appendChild(loadBtn);

  details.appendChild(body);
  article.appendChild(details);
  return article;
}

function mrepRow(label, localVal, matchVal) {
  if (!localVal && !matchVal) return '';
  return `<tr>
    <th>${escapeHtml(label)}</th>
    <td>${escapeHtml(String(localVal || '—'))}</td>
    <td>${escapeHtml(String(matchVal || '—'))}</td>
  </tr>`;
}

$('matchReportBtn').addEventListener('click', () => {
  const widget = $('matchReportWidget');
  widget.hidden = !widget.hidden;
  $('matchReportBtn').textContent = widget.hidden ? 'View full match report' : 'Hide match report';
});
$('matchReportSearch').addEventListener('input', buildMatchReportCards);
$('matchReportFilter').addEventListener('change', buildMatchReportCards);

$('suspectReportBtn').addEventListener('click', () => {
  const btn = $('suspectReportBtn');
  const widget = $('suspectReportWidget');
  // If report is already rendered (list has children), just toggle.
  if ($('suspectReportList').children.length) {
    widget.hidden = !widget.hidden;
    btn.textContent = widget.hidden ? 'View Suspicion Report' : 'Hide Suspicion Report';
  } else {
    generateSuspectReport();
  }
});

$('startBtn').addEventListener('click', startRun);
$('cancelBtn').addEventListener('click', cancelRun);
$('loadLastReportBtn').addEventListener('click', loadLastReport);
$('script').addEventListener('change', updateV5Fields);
$('categorySelect').addEventListener('change', renderCategoryFiles);
$('manualReviewFilter')?.addEventListener('change', renderManualReviewList);
$('manualSearchBtn').addEventListener('click', searchManualTarget);
$("manualDiscoverBtn").addEventListener("click", () => discoverManualTargets());
$("manualBrowseBtn").addEventListener("click", () => browseManualPath());
$("manualReloadCoverBtn").addEventListener("click", loadManualCurrentCover);
loadScripts();
resumeActiveRun();

// On load: check if a cancelled run from a previous session is still draining.
fetch('/api/runs/draining').then(r => r.json()).then(d => { if (d.draining) showWorkerDrainBanner(true); }).catch(() => {});

// Target path folder browser + default root from preferences
(async () => {
  const prefs = window.LibraForgePrefs?.get() || {};
  let libraryRoot = "/audiobooks";
  try {
    const cfg = await fetch("/api/config").then(r => r.json());
    libraryRoot = cfg.audiobooks_root || "/audiobooks";
  } catch {}
  const effectiveRoot = prefs.defaultRootPath || libraryRoot;
  const targetInput = $('targetPath');
  if (targetInput && (!targetInput.value || targetInput.value === '/audiobooks')) {
    targetInput.value = effectiveRoot;
  }
  if ($('targetBrowser')) {
    initFolderBrowser({
      inputEl: targetInput,
      datalistEl: $('targetSuggestions'),
      browserEl: $('targetBrowser'),
      browseBtnEl: $('targetBrowseBtn'),
      listEl: $('targetFbList'),
      breadcrumbEl: $('targetFbBreadcrumb'),
      upBtnEl: $('targetFbUp'),
      homeBtnEl: $('targetFbHome'),
      closeBtnEl: $('targetFbClose'),
      selectBtnEl: $('targetFbSelect'),
      currentLabelEl: $('targetFbCurrentLabel'),
      libraryRoot: effectiveRoot,
    });
  }
})();

// Target path scan
if ($('targetScanBtn')) {
  $('targetScanBtn').addEventListener('click', async () => {
    const path = $('targetPath').value.trim();
    if (!path) return;
    const btn = $('targetScanBtn');
    const results = $('fixerScanResults');
    const meta = $('fixerScanMeta');
    const err = $('fixerScanError');
    btn.disabled = true;
    btn.textContent = 'Scanning…';
    results.hidden = true;
    err.hidden = true;
    try {
      const scanPrefs = window.LibraForgePrefs?.get() || {};
      const res = await fetch('/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, ignored_folders: (scanPrefs.ignoredFolders || []) }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Scan failed'); }
      const data = await res.json();
      $('fixerCountMetadata').textContent = data.needs_metadata;
      $('fixerCountProcessed').textContent = (data.organized ?? 0) + (data.ready_to_organize ?? 0);
      $('fixerCountConversion').textContent = data.needs_conversion;
      const elapsed = data.scan_ms < 1000 ? `${data.scan_ms}ms` : `${(data.scan_ms/1000).toFixed(1)}s`;
      const cached = data.from_cache ? ' (cached)' : '';
      meta.textContent = `${data.total} book${data.total !== 1 ? 's' : ''} found · ${elapsed}${cached}`;
      results.hidden = false;
    } catch (e) {
      err.textContent = e.message || 'Scan failed.';
      err.hidden = false;
    } finally {
      btn.disabled = false;
      btn.textContent = 'Scan';
    }
  });
}

// Provider selectors for manual review and batch runs
(async () => {
  // Load abs-agg providers
  await loadAbsAggProviders($('manualAbsAggProvider'));
  const settings = await loadAbsAggSettings();
  if (settings.url) $('manualAbsAggUrl').value = settings.url;

  // Load ABS providers for manual review and batch
  async function loadAbsProviders(selectEl) {
    try {
      const res = await fetch('/api/abs/providers');
      const data = await res.json();
      selectEl.innerHTML = '';
      Object.entries(data.providers || {}).forEach(([value, text]) => {
        const opt = document.createElement('option');
        opt.value = value;
        opt.textContent = text;
        if (value === 'audible') opt.selected = true;
        selectEl.appendChild(opt);
      });
    } catch {}
  }
  await loadAbsProviders($('manualAbsProvider'));
  if ($('batchAbsProvider')) await loadAbsProviders($('batchAbsProvider'));

  function updateAbsAggParamHint(selectEl, paramsInputEl) {
    const hint = getAbsAggProviderParamHint(selectEl.value);
    if (hint) {
      paramsInputEl.placeholder = hint.example;
      paramsInputEl.title = `${hint.required ? 'Required' : 'Optional'}: ${hint.description}`;
    } else {
      paramsInputEl.placeholder = '';
      paramsInputEl.title = '';
    }
  }

  $('manualAbsAggProvider').addEventListener('change', () =>
    updateAbsAggParamHint($('manualAbsAggProvider'), $('manualAbsAggParams'))
  );
  updateAbsAggParamHint($('manualAbsAggProvider'), $('manualAbsAggParams'));

  function toggleManualProviderFields() {
    const v = $('manualProvider').value;
    const isAbs = v === 'abs';
    const isAbsAgg = v === 'abs-agg';
    if ($('manualAbsProviderLabel')) $('manualAbsProviderLabel').hidden = !isAbs;
    if ($('absWarning')) $('absWarning').hidden = !isAbs;
    ['manualAbsAggProviderLabel', 'manualAbsAggParamsLabel', 'manualAbsAggUrlLabel'].forEach(id => {
      if ($(id)) $(id).hidden = !isAbsAgg;
    });
    if ($('absAggWarning')) $('absAggWarning').hidden = !(isAbsAgg && !isAbsAggReachable());
    if (isAbs && $('absWarning')) {
      checkAbsReachable().then(reachable => {
        if ($('manualProvider').value === 'abs' && $('absWarning')) $('absWarning').hidden = reachable;
      });
    }
    // Update provider hint near "Search query"
    if ($('manualProviderHintName')) {
      $('manualProviderHintName').textContent = PROVIDER_LABELS[v] || v;
    }
    if ($('manualTitleQueryNote')) {
      $('manualTitleQueryNote').hidden = !(v === 'graphicaudio' || v === 'soundbooththeater' || v === 'goodreads' || v === 'kindle');
    }
  }
  $('manualProvider').addEventListener('change', toggleManualProviderFields);
  toggleManualProviderFields();

  function toggleBatchProviderFields() {
    if (!$('batchProvider')) return;
    const isAbs = $('batchProvider').value === 'abs';
    if ($('batchAbsProviderLabel')) $('batchAbsProviderLabel').hidden = !isAbs;
  }
  if ($('batchProvider')) {
    $('batchProvider').addEventListener('change', toggleBatchProviderFields);
    toggleBatchProviderFields();
  }
  $('manualAbsAggUrl').addEventListener('change', () => saveAbsAggUrl($('manualAbsAggUrl').value.trim()));
})();
