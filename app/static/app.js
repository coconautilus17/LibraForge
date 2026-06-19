let currentRun = null;
let pollTimer = null;
let latestState = null;
let manualContext = null;
let manualCurrentCoverUrl = '';

const $ = (id) => document.getElementById(id);
const { escapeHtml, renderDownloadLinks, statCard: stat, loadAbsAggProviders, getAbsAggProviderParamHint, isAbsAggReachable, checkAbsReachable, loadAbsAggSettings, saveAbsAggUrl, searchAbsAgg, scoreBadge } = window.UiCommon;

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
  const skipPatterns = $('skipPatterns').value.split('\n').map((s) => s.trim()).filter(Boolean);
  return {
    script_name: $('script').value,
    target_path: $('targetPath').value.trim(),
    auth_file: $('authFile').value.trim(),
    apply: $('apply').checked,
    backup: $('backup').checked,
    restore_metadata: $('restore').checked,
    aggressive: $('aggressive').checked,
    force: $('force').checked,
    force_original: $('forceOriginal').checked,
    reprobe: $('reprobe').checked,
    show_asin_report: $('showAsin').checked,
    cover_if_missing: $('coverIfMissing').checked,
    replace_cover: $('replaceCover').checked,
    metadata_json: $('metadataJson').checked,
    workers: fixerMajorVersion($('script').value) >= 5 ? parseInt($('workers').value || '1', 10) : undefined,
    api_delay_ms: fixerMajorVersion($('script').value) >= 5 ? parseInt($('apiDelayMs').value || '0', 10) : 0,
    write_mode: fixerMajorVersion($('script').value) >= 5 ? ($('writeMode').value || 'smart') : 'smart',
    provider: fixerMajorVersion($('script').value) >= 5 ? ($('batchProvider')?.value || 'audible') : 'audible',
    abs_provider: fixerMajorVersion($('script').value) >= 5 ? ($('batchAbsProvider')?.value || 'audible') : 'audible',
    min_score: parseFloat($('minScore').value || '0.7'),
    limit: parseInt($('limit').value || '50', 10),
    max_files: parseInt($('maxFiles').value || '0', 10),
    duration_review_threshold: parseFloat($('durationThreshold').value || '10'),
    skip_patterns: skipPatterns,
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
  currentRun = data.id;
  $('startBtn').disabled = true;
  $('cancelBtn').disabled = false;
  pollTimer = setInterval(poll, 1000);
  poll();
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
  render(state);
  if (['completed', 'failed', 'cancelled'].includes(state.status)) {
    clearInterval(pollTimer);
    $('startBtn').disabled = false;
    $('cancelBtn').disabled = true;
  }
}

function render(state) {
  const pct = Number(state.percent || 0).toFixed(1);
  $('ring').style.setProperty('--pct', pct);
  $('percent').textContent = `${pct}%`;
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
  renderStats(state.stats || {}, state.started_at, state.finished_at);
  renderCategories(state.files_by_category || {});
  renderManualReview(state.manual_review_items || []);
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
  const threshold = stats.large_duration_threshold || 10;
  const elapsed = formatElapsed(startedAt, finishedAt);
  $('stats').innerHTML = [
    elapsed ? stat('Run duration', elapsed, 'Total elapsed time for this run.') : '',
    stat('Found', stats.found, 'Supported files discovered before filtering.'),
    stat('Matched', stats.matched, 'Files where the script selected a usable match.'),
    stat('Skipped', stats.skipped, 'Files intentionally not processed.'),
    stat('Failed', stats.failed, 'Files that hit an error.'),
    stat('Mode: full', mode.full, 'Full metadata rewrite planned/applied.'),
    stat('Mode: series_only', mode.series_only, 'Only grouping-critical metadata is changed.'),
    stat('Mode: none', mode.none, 'No safe edit selected.'),
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
    ? items.map((item) => `<div class="file-item">${escapeHtml(item.path)}${item.title ? `<br><span>${escapeHtml(item.title)}</span>` : ''}</div>`).join('')
    : '<div class="file-item">No category selected.</div>';
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
  $('manualReviewList').innerHTML = items.length
    ? items.map((item) => `
      <div class="file-item">
        <div>${escapeHtml(item.path)}</div>
        <div class="reason-badges">
          ${(item.reasons || []).map((reason) => `<span class="reason-badge ${['no match','asin conflict','low score','missing metadata','unsafe match','no metadata','status:skipped','mode:none'].includes(reason) ? 'danger' : ''}">${escapeHtml(reason)}</span>`).join('')}
          ${item.diff_percent ? `<span class="reason-badge danger">${escapeHtml(String(item.diff_percent))}% diff</span>` : ''}
        </div>
        <button class="secondary" data-manual-load="${escapeHtml(item.path)}">Load target</button>
      </div>
    `).join('')
    : '<div class="file-item">No manual review items in this run.</div>';

  for (const button of $('manualReviewList').querySelectorAll('button[data-manual-load]')) {
    button.addEventListener('click', () => loadManualTarget(button.getAttribute('data-manual-load')));
  }
}

async function loadManualTarget(path) {
  $("manualMeta").textContent = "Inspecting selected target...";
  $("manualSearchResults").innerHTML = "";
  const res = await fetch('/api/manual-review/load', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      path,
      script_name: $('script').value,
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Failed to inspect manual review target');
    return;
  }

  manualContext = data;
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

function renderManualSearchResults(results = []) {
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
              <strong>${result.provider === 'abs-agg' ? (result.abs_agg_provider || 'abs-agg') : 'Audible'}</strong>
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
      applyManualMatch(results[index], mode, replaceCover);
    });
  }

  for (const select of $('manualSearchResults').querySelectorAll('select[data-manual-mode]')) {
    const updateCoverControl = () => {
      const index = select.getAttribute('data-manual-mode');
      const checkbox = $('manualSearchResults').querySelector(`input[data-manual-replace-cover="${index}"]`);
      if (!checkbox) return;
      checkbox.disabled = select.value !== 'full' || !results[Number(index)]?.cover_url;
      if (checkbox.disabled) checkbox.checked = false;
    };
    select.addEventListener('change', updateCoverControl);
    updateCoverControl();
  }
}

async function searchManualTarget() {
  if (!manualContext?.path) {
    alert('Load a manual review target first.');
    return;
  }

  const provider = $('manualProvider').value;
  let res;

  if (provider === 'abs') {
    const absRes = await fetch('/api/abs/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: $('manualQuery').value.trim(),
        provider: $('manualAbsProvider').value || 'audible',
        limit: 10,
      }),
    });
    res = await absRes.json();
  } else if (provider === 'abs-agg') {
    res = await searchAbsAgg({
      query: $('manualQuery').value.trim(),
      provider: $('manualAbsAggProvider').value,
      providerParams: $('manualAbsAggParams').value.trim(),
      baseUrl: $('manualAbsAggUrl').value.trim(),
      limit: 10,
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

  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Search failed');
    return;
  }
  $('manualMeta').textContent = data.queries?.length ? `Search queries tried: ${data.queries.join(' | ')}` : 'No search queries were produced.';
  renderManualSearchResults(data.results || []);
}

async function applyManualMatch(result, editMode, replaceCover = false) {
  if (!manualContext?.path) {
    alert('Load a manual review target first.');
    return;
  }
  if (!editMode) {
    alert('Choose an apply mode first.');
    return;
  }
  const coverMessage = replaceCover ? '\n\nThe current cover will be overwritten with the selected match cover.' : '';
  const ok = confirm(`Apply the selected match in ${editMode} mode to:\n${manualContext.display_path || manualContext.path}${coverMessage}`);
  if (!ok) return;

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
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Failed to apply manual match');
    return;
  }
  alert(`Applied manual match in ${data.edit_mode} mode.\nTarget: ${data.target_path}\nOutput: ${data.output_kind}\nSaved to: ${data.output_path}`);
}

$('startBtn').addEventListener('click', startRun);
$('cancelBtn').addEventListener('click', cancelRun);
$('script').addEventListener('change', updateV5Fields);
$('categorySelect').addEventListener('change', renderCategoryFiles);
$('manualSearchBtn').addEventListener('click', searchManualTarget);
$("manualDiscoverBtn").addEventListener("click", () => discoverManualTargets());
$("manualBrowseBtn").addEventListener("click", () => browseManualPath());
$("manualReloadCoverBtn").addEventListener("click", loadManualCurrentCover);
loadScripts();

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
    if ($('absWarning')) $('absWarning').hidden = !isAbs; // hide immediately; async check refines
    ['manualAbsAggProviderLabel', 'manualAbsAggParamsLabel', 'manualAbsAggUrlLabel'].forEach(id => {
      if ($(id)) $(id).hidden = !isAbsAgg;
    });
    if ($('absAggWarning')) $('absAggWarning').hidden = !(isAbsAgg && !isAbsAggReachable());
    // Async: refine ABS warning once status is known
    if (isAbs && $('absWarning')) {
      checkAbsReachable().then(reachable => {
        if ($('manualProvider').value === 'abs' && $('absWarning')) $('absWarning').hidden = reachable;
      });
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
