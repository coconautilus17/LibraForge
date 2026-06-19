let currentRun = null;
let pollTimer = null;
let loadedState = null;
let discoveryCache = null;

const $ = (id) => document.getElementById(id);
const { escapeHtml, renderDownloadLinks, loadAbsAggProviders, getAbsAggProviderParamHint, isAbsAggReachable, loadAbsAggSettings, saveAbsAggUrl, searchAbsAgg, scoreBadge } = window.UiCommon;

async function initProviderSelector() {
  await loadAbsAggProviders($('absAggProvider'));
  const settings = await loadAbsAggSettings();
  if (settings.url) $('absAggUrl').value = settings.url;

  function toggleAbsAggFields() {
    const isAbsAgg = $('metaProvider').value === 'abs-agg';
    ['absAggProviderLabel', 'absAggParamsLabel', 'absAggUrlLabel'].forEach(id => {
      $(id).hidden = !isAbsAgg;
    });
    if ($('absAggWarning')) $('absAggWarning').hidden = !(isAbsAgg && !isAbsAggReachable());
  }
  $('metaProvider').addEventListener('change', toggleAbsAggFields);
  toggleAbsAggFields();
  $('absAggUrl').addEventListener('change', () => saveAbsAggUrl($('absAggUrl').value.trim()));

  function updateAbsAggParamHint() {
    const hint = getAbsAggProviderParamHint($('absAggProvider').value);
    const input = $('absAggParams');
    if (hint) {
      input.placeholder = hint.example;
      input.title = `${hint.required ? 'Required' : 'Optional'}: ${hint.description}`;
    } else {
      input.placeholder = '';
      input.title = '';
    }
  }
  $('absAggProvider').addEventListener('change', updateAbsAggParamHint);
  updateAbsAggParamHint();
}

async function loadScripts() {
  const res = await fetch('/api/scripts');
  const data = await res.json();
  const select = $('searchScript');
  select.innerHTML = '';
  for (const name of data.fixer_scripts || data.scripts) {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    if (name === data.default_script) opt.selected = true;
    select.appendChild(opt);
  }
}

function collectMetadata() {
  return {
    title: $('title').value.trim(),
    subtitle: $('subtitle').value.trim(),
    author: $('author').value.trim(),
    narrator: $('narrator').value.trim(),
    series: $('series').value.trim(),
    sequence: $('sequence').value.trim(),
    year: $('year').value.trim(),
    summary: $('summary').value.trim(),
    cover_url: $('coverUrl').value.trim(),
    asin: $('asin').value.trim(),
    local_duration_minutes: loadedState?.metadata?.local_duration_minutes ?? null,
  };
}

function fillMetadata(metadata = {}) {
  $('title').value = metadata.title || '';
  $('subtitle').value = metadata.subtitle || '';
  $('author').value = metadata.author || '';
  $('narrator').value = metadata.narrator || '';
  $('series').value = metadata.series || '';
  $('sequence').value = metadata.sequence || '';
  $('year').value = metadata.year || '';
  $('summary').value = metadata.summary || '';
  $('coverUrl').value = metadata.cover_url || '';
  $('asin').value = metadata.asin || '';
  updateCommandPreview();
}

function buildCommandPreview() {
  const inputPath = $('sourcePath').value.trim();
  const outputPath = $('outputPath').value.trim();
  const metadata = collectMetadata();
  const parts = ['m4b-tool', 'merge', JSON.stringify(inputPath), `--output-file=${JSON.stringify(outputPath)}`, '-v'];
  if ($('force').checked) parts.push('--force');
  const jobs = parseInt($('jobs').value || '0', 10);
  if (jobs > 0) parts.push(`--jobs=${jobs}`);
  if ($('noConversion').checked) {
    parts.push('--no-conversion');
  } else {
    parts.push(`--audio-codec=${$('audioCodec').value}`);
    parts.push(`--audio-bitrate=${$('audioBitrate').value}`);
    parts.push(`--audio-samplerate=${$('audioSamplerate').value}`);
    if ($('audioChannels').value) parts.push(`--audio-channels=${$('audioChannels').value}`);
  }
  if ($('useFilenamesAsChapters').checked) parts.push('--use-filenames-as-chapters');
  if (metadata.title) {
    parts.push(`--name=${JSON.stringify(metadata.title)}`);
    parts.push(`--album=${JSON.stringify(metadata.title)}`);
  }
  if (metadata.author) {
    parts.push(`--artist=${JSON.stringify(metadata.author)}`);
    parts.push(`--albumartist=${JSON.stringify(metadata.author)}`);
  }
  if (metadata.narrator) parts.push(`--writer=${JSON.stringify(metadata.narrator)}`);
  if (metadata.series) parts.push(`--series=${JSON.stringify(metadata.series)}`);
  if (metadata.sequence) parts.push(`--series-part=${JSON.stringify(metadata.sequence)}`);
  if (metadata.year) parts.push(`--year=${JSON.stringify(metadata.year)}`);
  if (metadata.summary) {
    parts.push(`--description=${JSON.stringify(metadata.summary.slice(0, 240))}`);
    parts.push(`--longdesc=${JSON.stringify(metadata.summary)}`);
  }
  parts.push('--genre=Audiobook');
  parts.push('--encoded-by=LibraForge');
  if (metadata.cover_url) parts.push(`--cover=${JSON.stringify('[downloaded temp cover file]')}`);
  return parts.join(' ');
}

function updateCommandPreview() {
  $('commandPreview').textContent = buildCommandPreview();
}

function formatAudioSummary(summary = {}) {
  const codecs = summary.codec_labels || summary.codecs || [];
  const containers = summary.containers || [];
  const bitrates = summary.bitrates_kbps || [];
  const channels = summary.channels || [];
  const sampleRates = summary.sample_rates_hz || [];
  const formatValues = (values, formatter) => values.length ? values.map(formatter).join('/') : 'unknown';
  const codec = formatValues(codecs, value => value);
  const container = formatValues(containers, value => value);
  const bitrate = formatValues(bitrates, value => `${value} kbps`);
  const channelText = formatValues(channels, value => {
    if (value === 1) return 'Mono (1 channel)';
    if (value === 2) return 'Stereo (2 channels)';
    return `${value} channels`;
  });
  const sampleRate = formatValues(sampleRates, value => {
    const khz = value / 1000;
    return `${Number.isInteger(khz) ? khz.toFixed(0) : khz.toFixed(2)} kHz`;
  });
  const mixedProperties = summary.mixed_properties || [];
  const mixed = mixedProperties.length ? ` · Mixed: ${mixedProperties.join(', ')}` : '';
  return `Audio: ${codec} · ${container} · ${bitrate} · ${channelText} · ${sampleRate}${mixed}`;
}

function formatAudioRecommendation(summary = {}) {
  const recommendation = summary.no_conversion || {};
  return {
    status: recommendation.status || 'unknown',
    label: recommendation.label || 'Recommendation unavailable',
    reason: recommendation.reason || 'Audio properties have not been loaded.',
  };
}

function renderAudioProfile(summary = {}) {
  $('audioSummary').textContent = formatAudioSummary(summary);
  const recommendation = formatAudioRecommendation(summary);
  const element = $('audioRecommendation');
  element.className = `audio-recommendation ${recommendation.status}`;
  element.innerHTML = `<strong>${escapeHtml(recommendation.label)}.</strong> ${escapeHtml(recommendation.reason)}`;
}

async function loadSidecar() {
  const res = await fetch('/api/m4b/metadata/load', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: $('sourcePath').value.trim() }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Failed to load sidecar');
    return;
  }

  loadedState = data;
  fillMetadata(data.metadata || {});
  $('sidecarPath').value = data.selected_sidecar || data.sidecars?.[0] || '';
  $('outputPath').value = data.output_path || '';
  const found = data.selected_sidecar ? `Loaded sidecar: ${data.selected_sidecar}` : 'No sidecar found, form is ready for manual entry.';
  $('loadStatus').textContent = `${found} Source: ${data.source_path || data.path}`;
  renderAudioProfile(data.audio_summary);
}

function renderDiscoveryResults(data) {
  const items = data.items || [];
  const label = data.mode === 'multipart' ? 'multipart books' : 'non-M4B books';
  const cache = discoveryCache?.info || {};
  const cacheDetail = cache.source === 'cache'
    ? ` Loaded saved search from ${new Date(cache.refreshed_at).toLocaleString()}; no library scan was performed.`
    : cache.source === 'refresh'
      ? ` Search refreshed; reused ${cache.chapter_probes_reused || 0} chapter and ${cache.audio_probes_reused || 0} audio probes; ran ${cache.chapter_probes_run || 0} chapter and ${cache.audio_probes_run || 0} audio probes.`
      : '';
  $('discoveryMeta').textContent = (data.truncated
    ? `Showing ${data.returned} of ${data.total} ${label}.`
    : `Found ${data.total} ${label}.`) + cacheDetail;
  $('discoveryResults').innerHTML = items.length
    ? items.map((item) => {
      const audio = item.audio_summary || {};
      const recommendation = formatAudioRecommendation(audio);
      const codec = (audio.codec_labels || audio.codecs || []).join('/') || 'codec unknown';
      const properties = [
        (audio.bitrates_kbps || []).map(value => `${value} kbps`).join('/'),
        (audio.sample_rates_hz || []).map(value => `${value / 1000} kHz`).join('/'),
        (audio.channels || []).map(value => value === 1 ? 'mono' : value === 2 ? 'stereo' : `${value} ch`).join('/'),
      ].filter(Boolean).join(' · ');
      return `
      <div class="file-item">
        <div><strong>${escapeHtml(item.display_path)}</strong></div>
        <div class="reason-badges">
          <span class="reason-badge">${item.file_count} file${item.file_count === 1 ? '' : 's'}</span>
          <span class="reason-badge">${escapeHtml((item.formats || []).join(', ').toUpperCase())}</span>
          <span class="reason-badge">${escapeHtml(codec)}</span>
          ${item.is_grouped ? '<span class="reason-badge">validated group</span>' : ''}
          <span class="reason-badge ${recommendation.status === 'copy' ? 'recommended' : 'danger'}">${escapeHtml(recommendation.label)}</span>
        </div>
        <div class="note">${escapeHtml(item.reason || '')}</div>
        <div class="note">${escapeHtml(properties)}</div>
        <div class="note"><strong>${escapeHtml(recommendation.label)}:</strong> ${escapeHtml(recommendation.reason)}</div>
        <button class="secondary" data-load-discovered="${encodeURIComponent(item.path)}">Load this book</button>
      </div>
    `;
    }).join('')
    : `<div class="file-item">No ${label} found under this path.</div>`;

  for (const button of $('discoveryResults').querySelectorAll('button[data-load-discovered]')) {
    button.addEventListener('click', async () => {
      const path = decodeURIComponent(button.getAttribute('data-load-discovered'));
      $('sourcePath').value = path;
      updateCommandPreview();
      await loadSidecar();
      $('sourcePath').scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }
}

async function refreshMultipartAudioProfiles() {
  const button = $('refreshAudioProfilesBtn');
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = 'Updating sidecars...';
  $('discoveryMeta').textContent = 'Writing cached multipart audio profiles to existing sidecars...';

  try {
    const res = await fetch('/api/m4b/discover/refresh-audio-profiles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: $('discoveryRoot').value.trim(),
        script_name: $('searchScript').value,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      $('discoveryMeta').textContent = data.detail || 'Sidecar update failed.';
      return;
    }
    const skipped = data.skipped
      ? ` ${data.skipped} had no existing fixer sidecar and were skipped.`
      : '';
    const failed = data.failed ? ` ${data.failed} failed.` : '';
    $('discoveryMeta').textContent = `Updated ${data.updated} of ${data.multipart_count} multipart sidecars.${skipped}${failed}`;
  } catch (error) {
    $('discoveryMeta').textContent = `Sidecar update failed: ${error.message}`;
  } finally {
    button.textContent = originalLabel;
    button.disabled = !(discoveryCache?.results?.multipart?.total > 0);
  }
}

async function discoverConversionCandidates(mode, forceRefresh = false) {
  const cacheKey = JSON.stringify({
    path: $('discoveryRoot').value.trim(),
    script_name: $('searchScript').value,
  });
  if (!forceRefresh && discoveryCache?.key === cacheKey) {
    renderDiscoveryResults(discoveryCache.results[mode]);
    return;
  }

  let cacheAction = forceRefresh ? 'refresh' : 'load';
  if (!forceRefresh) {
    try {
      const statusResponse = await fetch('/api/m4b/discover/cache-status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: cacheKey,
      });
      const status = await statusResponse.json();
      if (!statusResponse.ok || !status.available) {
        cacheAction = 'refresh';
      }
    } catch (error) {
      cacheAction = 'refresh';
    }
  }

  const buttons = [$('findMultipartBtn'), $('findNonM4bBtn'), $('refreshDiscoveryBtn')];
  const originalLabels = buttons.map(button => button.textContent);
  for (const button of buttons) button.disabled = true;
  if (cacheAction === 'load') {
    (mode === 'multipart' ? buttons[0] : buttons[1]).textContent = 'Loading...';
  } else {
    buttons[2].textContent = 'Refreshing...';
  }
  $('discoveryMeta').textContent = cacheAction === 'load'
    ? 'Loading saved discovery search...'
    : 'Refreshing search with fixer processing rules; unchanged chapter and audio probes will be reused...';
  $('discoveryResults').innerHTML = '';

  try {
    const res = await fetch('/api/m4b/discover', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: $('discoveryRoot').value.trim(),
        mode: 'all',
        script_name: $('searchScript').value,
        limit: 200,
        cache_action: cacheAction,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.detail || 'Discovery scan failed');
      $('discoveryMeta').textContent = data.detail || 'Discovery scan failed.';
      return;
    }
    discoveryCache = { key: cacheKey, results: data.results, info: data.cache || {} };
    $('refreshAudioProfilesBtn').disabled = !(data.results.multipart?.total > 0);
    renderDiscoveryResults(data.results[mode]);
  } catch (error) {
    $('discoveryMeta').textContent = `Discovery scan failed: ${error.message}`;
  } finally {
    buttons.forEach((button, index) => {
      button.disabled = false;
      button.textContent = originalLabels[index];
    });
  }
}

async function saveSidecar() {
  const payload = {
    path: $('sourcePath').value.trim(),
    source_path: loadedState?.source_path || $('sourcePath').value.trim(),
    sidecar_path: $('sidecarPath').value.trim(),
    metadata: collectMetadata(),
  };
  const res = await fetch('/api/m4b/metadata/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Failed to save sidecar');
    return;
  }
  $('sidecarPath').value = data.sidecar_path || '';
  $('loadStatus').textContent = `Saved sidecar: ${data.sidecar_path}`;
}

function renderResults(results = []) {
  $('searchResults').innerHTML = results.length
    ? results.map(result => {
      const duration = result.duration || {};
      const subtitle = result.subtitle ? `<p>${escapeHtml(result.subtitle)}</p>` : '';
      const summary = result.summary ? `<p class="result-summary">${escapeHtml(result.summary.slice(0, 260))}</p>` : '';
      return `
        <article class="result-card">
          <div class="result-head">
            <div>
              <h3>${escapeHtml(result.title)}</h3>
              ${subtitle}
            </div>
            <div class="score-badge">${scoreBadge(result)}</div>
          </div>
          ${result.cover_url ? `<img class="cover-thumb" src="${escapeHtml(result.cover_url)}" alt="" />` : ''}
          <div class="result-meta">
            <span>Mode: ${escapeHtml(result.edit_mode || '-')}</span>
            <span>ASIN: ${escapeHtml(result.asin || '-')}</span>
            <span>Series: ${escapeHtml(result.series || '-')} ${result.sequence ? `#${escapeHtml(result.sequence)}` : ''}</span>
            <span>Authors: ${escapeHtml((result.authors || []).join(', ') || '-')}</span>
            <span>Narrators: ${escapeHtml((result.narrators || []).join(', ') || '-')}</span>
            <span>Runtime: ${escapeHtml(String(result.duration_minutes || '-'))} min</span>
            <span>Duration status: ${escapeHtml(duration.status || '-')}</span>
          </div>
          ${summary}
          <div class="actions">
            <button data-use-match="${encodeURIComponent(JSON.stringify(result.chosen_metadata))}">Use this match</button>
          </div>
        </article>
      `;
    }).join('')
    : '<p class="note">No results yet.</p>';

  for (const button of $('searchResults').querySelectorAll('button[data-use-match]')) {
    button.addEventListener('click', () => {
      const metadata = JSON.parse(decodeURIComponent(button.getAttribute('data-use-match')));
      fillMetadata(metadata);
    });
  }
}

async function searchMetadata() {
  const provider = $('metaProvider').value;
  let res, data;

  if (provider === 'abs-agg') {
    res = await searchAbsAgg({
      query: $('searchQuery').value.trim(),
      provider: $('absAggProvider').value,
      providerParams: $('absAggParams').value.trim(),
      baseUrl: $('absAggUrl').value.trim(),
      limit: 10,
    });
  } else {
    const payload = {
      query: $('searchQuery').value.trim(),
      auth_file: $('authFile').value.trim(),
      metadata: collectMetadata(),
      limit: 10,
      script_name: $('searchScript').value,
    };
    res = await fetch('/api/m4b/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }

  data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Search failed');
    return;
  }
  $('searchMeta').textContent = data.queries?.length ? `Queries: ${data.queries.join(' | ')}` : '';
  renderResults(data.results || []);
}

function collectRunRequest() {
  return {
    input_path: $('sourcePath').value.trim(),
    output_path: $('outputPath').value.trim(),
    save_sidecar: $('saveSidecar').checked,
    sidecar_path: $('sidecarPath').value.trim(),
    metadata: collectMetadata(),
    force: $('force').checked,
    jobs: parseInt($('jobs').value || '0', 10),
    no_conversion: $('noConversion').checked,
    use_filenames_as_chapters: $('useFilenamesAsChapters').checked,
    audio_codec: $('audioCodec').value,
    audio_bitrate: $('audioBitrate').value,
    audio_samplerate: parseInt($('audioSamplerate').value, 10),
    audio_channels: $('audioChannels').value ? parseInt($('audioChannels').value, 10) : null,
  };
}

async function startRun() {
  const req = collectRunRequest();
  const res = await fetch('/api/m4b/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Failed to start m4b-tool run');
    return;
  }
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

function renderRun(state) {
  const pct = state.status === 'completed' ? 100 : Number(state.percent || 0);
  $('ring').style.setProperty('--pct', pct.toFixed(1));
  $('percent').textContent = `${pct.toFixed(1)}%`;
  const count = state.total ? ` · ${state.current || 0}/${state.total}` : '';
  $('runStatus').textContent = `${state.phase_label || state.status.toUpperCase()}${count}`;
  const phaseDetail = state.phase_detail || '';
  const currentPath = state.current_file || '';
  $('currentFile').textContent = state.error
    || [phaseDetail, currentPath && currentPath !== phaseDetail ? currentPath : ''].filter(Boolean).join(' · ')
    || 'Waiting for output...';
  const chapters = state.stats && state.stats.chapters_created;
  $('chapterResult').textContent = Number.isInteger(chapters) ? `Chapters created: ${chapters}` : '';
  $('command').textContent = (state.command || []).join(' ');
  $('tail').textContent = (state.tail || []).join('\n');
  $('tail').scrollTop = $('tail').scrollHeight;
  renderDownloadLinks($('downloadLinks'), state.downloads || {});
}

async function poll() {
  if (!currentRun) return;
  const res = await fetch(`/api/runs/${currentRun}`);
  if (!res.ok) return;
  const state = await res.json();
  renderRun(state);
  if (['completed', 'failed', 'cancelled'].includes(state.status)) {
    clearInterval(pollTimer);
    $('startBtn').disabled = false;
    $('cancelBtn').disabled = true;
  }
}

document.addEventListener('input', (event) => {
  if (!event.target?.id) return;
  if (['title', 'subtitle', 'author', 'narrator', 'series', 'sequence', 'year', 'summary', 'coverUrl', 'sourcePath', 'outputPath', 'jobs', 'audioCodec', 'audioBitrate', 'audioSamplerate', 'audioChannels'].includes(event.target.id)) {
    updateCommandPreview();
  }
});
$('loadBtn').addEventListener('click', loadSidecar);
$('saveBtn').addEventListener('click', saveSidecar);
$('findMultipartBtn').addEventListener('click', () => discoverConversionCandidates('multipart'));
$('findNonM4bBtn').addEventListener('click', () => discoverConversionCandidates('non_m4b'));
$('refreshDiscoveryBtn').addEventListener('click', () => discoverConversionCandidates('multipart', true));
$('refreshAudioProfilesBtn').addEventListener('click', refreshMultipartAudioProfiles);
$('searchBtn').addEventListener('click', searchMetadata);
$('startBtn').addEventListener('click', startRun);
$('cancelBtn').addEventListener('click', cancelRun);
$('force').addEventListener('change', updateCommandPreview);
$('noConversion').addEventListener('change', updateCommandPreview);
$('useFilenamesAsChapters').addEventListener('change', updateCommandPreview);

loadScripts();
initProviderSelector();
updateCommandPreview();
