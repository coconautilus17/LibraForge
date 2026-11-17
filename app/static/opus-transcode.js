// Opus Transcode (DEV / WIP) section of the M4B Tool page.
// Hidden unless /api/config lists "opus_transcode" (or "all") in dev_features
// (server env LIBRAFORGE_DEV_FEATURES). Self-contained: its own run, status and output,
// so it never touches the merge controls above it.
(() => {
  const $ = (id) => document.getElementById(id);
  const { escapeHtml } = window.UiCommon;
  let runId = null;
  let pollTimer = null;

  const num = (id) => Number($(id).value);

  function request(apply) {
    return {
      root_path: $('opusRootPath').value.trim(),
      staging_path: $('opusStagingPath').value.trim(),
      apply,
      only: $('opusOnly').value.split(',').map(s => s.trim()).filter(Boolean),
      workers: num('opusWorkers'),
      mode: $('opusMode').value,
      mono_kbps: num('opusMonoKbps'),
      stereo_kbps: num('opusStereoKbps'),
      src_cap_ratio: num('opusSrcCap'),
      leave_alone_kbps: num('opusLeaveAlone'),
      max_size_ratio: num('opusMaxSize'),
      frame_ms: num('opusFrameMs'),
      side_margin_db: num('opusSideMargin'),
      side_floor_db: num('opusSideFloor'),
    };
  }

  // Mirrors app/opus_transcode.py build_command() for display only; the server builds the real one.
  function renderPreview() {
    const r = request(false);
    const q = (s) => /^[\w./:=,-]+$/.test(s) ? s : `'${s.replace(/'/g, "'\\''")}'`;
    const parts = ['python3', '-u', 'scripts/opus-transcode.py', q(r.root_path || '<folder>'),
      '--staging', q(r.staging_path || '<staging>'), '--workers', r.workers,
      '--mono-kbps', r.mono_kbps, '--stereo-kbps', r.stereo_kbps, '--src-cap-ratio', r.src_cap_ratio,
      '--leave-alone-kbps', r.leave_alone_kbps, '--max-size-ratio', r.max_size_ratio, '--mode', r.mode,
      '--frame-ms', r.frame_ms, '--side-margin-db', r.side_margin_db, '--side-floor-db', r.side_floor_db];
    r.only.forEach(o => parts.push('--only', q(o)));
    $('opusCommandPreview').textContent = parts.join(' ') + '\n# Transcode adds --apply';
  }

  const ACTION_LABEL = {
    'CONVERT': 'Convert', 'LEAVE-ALONE': 'Leave alone', 'SKIP-DONE': 'Already done',
    'SKIP-SMALL-GAIN': 'Small gain', 'REVIEW': 'Review',
  };

  function bookName(row) {
    const p = row.kind === 'grouped' ? row.folder : (row.files || [''])[0];
    return String(p || '').split('/').filter(Boolean).slice(-2).join(' / ');
  }

  function renderRun(data) {
    const opus = (data.stats && data.stats.opus) || { plan: [], results: [], summary: {} };
    $('opusRunStatus').textContent = data.phase_label || data.status || 'Running';
    const detail = [data.phase_detail, data.current_file && data.status === 'running' ? `Now: ${data.current_file}` : '']
      .filter(Boolean).join(' · ');
    $('opusRunDetail').textContent = data.error ? `Error: ${data.error}` : (detail || '');
    $('opusTail').textContent = (data.tail || []).join('\n');

    const s = opus.summary || {};
    if (s.books !== undefined) {
      const counts = Object.entries(s.by_action || {}).map(([k, v]) => `${ACTION_LABEL[k] || k}: ${v}`).join(', ');
      let html = `<p><strong>${s.books} books</strong> (${escapeHtml(counts)}). Convert: ${s.convert_hours} h, `
        + `${(s.convert_source_mb / 1000).toFixed(2)} GB to about ${(s.convert_predicted_mb / 1000).toFixed(2)} GB.</p>`;
      if (s.applied && s.verified !== undefined) {
        html += `<p><strong>${s.verified} verified, ${s.failed} failed</strong>: ${(s.src_mb / 1000).toFixed(2)} GB to `
          + `${(s.out_mb / 1000).toFixed(2)} GB. Originals untouched.</p>`;
      }
      $('opusSummary').innerHTML = html;
    }

    const resultByKey = new Map((opus.results || []).map(r => [r.key, r]));
    const rows = (opus.plan || []).map(row => {
      const res = resultByKey.get(row.key);
      const target = res && res.target
        ? `${res.target.channels === 1 ? 'mono' : 'stereo'} ${res.target.bitrate_kbps}k`
        : (row.action === 'CONVERT' ? `≤ ${row.target_kbps}k` : '');
      const size = res && res.out_size
        ? `${Math.round(res.src_size / 1e6)} → ${Math.round(res.out_size / 1e6)} MB`
        : (row.predicted_mb ? `${row.source_mb} → ~${row.predicted_mb} MB` : (row.source_mb ? `${row.source_mb} MB` : ''));
      let result = row.reason || '';
      if (res) {
        result = res.status === 'verified' ? 'Verified' : `${res.status}${res.failed_checks.length ? ': ' + res.failed_checks.join(', ') : ''}${res.error ? ' ' + res.error : ''}`;
      }
      const source = [row.src_codec && row.src_codec.join('+'), row.src_kbps && `${row.src_kbps} kbps`,
        row.channels && (row.channels === 1 ? 'mono' : 'stereo'), row.duration_h && `${row.duration_h} h`].filter(Boolean).join(', ');
      return `<tr><td>${escapeHtml(ACTION_LABEL[row.action] || row.action)}</td><td>${escapeHtml(bookName(row))}</td>`
        + `<td>${escapeHtml(source)}</td><td>${escapeHtml(target)}</td><td>${escapeHtml(size)}</td><td>${escapeHtml(result)}</td></tr>`;
    });
    $('opusPlanTable').hidden = rows.length === 0;
    $('opusPlanTable').querySelector('tbody').innerHTML = rows.join('');
  }

  function setRunning(running) {
    $('opusPlanBtn').disabled = running;
    $('opusStartBtn').disabled = running;
    $('opusCancelBtn').disabled = !running;
  }

  async function poll() {
    if (!runId) return;
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderRun(data);
      if (!['running', 'queued'].includes(data.status)) {
        setRunning(false);
        return;
      }
    } catch (err) {
      $('opusRunDetail').textContent = `Could not read run status: ${err.message}`;
    }
    pollTimer = setTimeout(poll, 1500);
  }

  async function start(apply) {
    const body = request(apply);
    if (!body.root_path || !body.staging_path) {
      $('opusRunDetail').textContent = 'Fill in both the folder to scan and the staging folder.';
      return;
    }
    if (apply && !window.confirm(`Encode the books marked Convert into\n${body.staging_path}\n\nOriginals are only read, never changed.`)) return;
    clearTimeout(pollTimer);
    setRunning(true);
    $('opusRunStatus').textContent = apply ? 'Starting transcode' : 'Starting plan';
    $('opusSummary').innerHTML = '';
    $('opusPlanTable').hidden = true;
    try {
      const res = await fetch('/api/opus/runs', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      runId = data.id;
      poll();
    } catch (err) {
      setRunning(false);
      $('opusRunStatus').textContent = 'Could not start';
      $('opusRunDetail').textContent = err.message;
    }
  }

  async function cancel() {
    if (!runId) return;
    await fetch(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' }).catch(() => {});
  }

  async function init() {
    let cfg = {};
    try { cfg = await fetch('/api/config').then(r => r.json()); } catch { return; }
    const enabled = (cfg.dev_features || []).some(f => f === 'opus_transcode' || f === 'all');
    if (!enabled) return;
    $('opus-transcode').hidden = false;
    $('opusNavLink').hidden = false;
    if (!$('opusRootPath').value && cfg.audiobooks_root) $('opusRootPath').value = `${cfg.audiobooks_root}/_unorganized`;
    $('opus-transcode').addEventListener('input', renderPreview);
    $('opus-transcode').addEventListener('change', renderPreview);
    $('opusPlanBtn').addEventListener('click', () => start(false));
    $('opusStartBtn').addEventListener('click', () => start(true));
    $('opusCancelBtn').addEventListener('click', cancel);
    renderPreview();
  }

  init();
})();
