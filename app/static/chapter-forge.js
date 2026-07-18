let currentRun = null;
let pollTimer = null;
let loaded = null;
let chapters = [];
let activeEtaSeconds = 0;
let activeRunStartedAt = 0;
let evidencePlaybackSyncInstalled = false;
let showOnlyFlagged = false;
let lastRemoved = null;
let toastTimer = null;
let playAllState = null;
let savedSnapshot = null;
let confidenceMode = 'heuristic';
let promptMode = 'append';

function llmConfidenceBadge() {
  const review = loaded?.result?.hybrid?.llm_review;
  if (confidenceMode !== 'llm-book' || !review || !review.assessment) return '';
  const assessment = String(review.assessment || '');
  const confidence = String(review.confidence || '');
  const tone = { clean: 'success', resolved_by_focused_asr: 'success' }[assessment] || (
    assessment === 'llm_unavailable' ? 'muted' : 'warning'
  );
  const label = assessment.replace(/_/g, ' ');
  return `<span class="cf-llm-badge cf-llm-badge-${tone}" title="Book-level assessment from the optional LLM review step">LLM: ${escapeHtml(label)}${confidence ? ` (${escapeHtml(confidence)})` : ''}</span>`;
}

function chapterSnapshot() {
  return JSON.stringify(chapters.map((c) => ({ start: c.start, end: c.end, title: c.title })));
}

function markSaved() {
  savedSnapshot = chapterSnapshot();
}

const $ = (id) => document.getElementById(id);
const { escapeHtml, initFolderBrowser } = window.UiCommon;

const CONFIDENCE_FLAG_THRESHOLD = 0.85;
// This host's own benchmark runs (small/float32/beam5/VAD-off full pass;
// medium/int8 focused gap recovery) -- not extrapolated from vendor numbers.
const CPU_MINUTES_PER_AUDIO_MINUTE_BASELINE = 0.158;
const CPU_MINUTES_PER_FOCUSED_GAP = { medium: 2.47, 'large-v2': 4.43, 'large-v3': 4.16 };
// SoS silence+keyword scan only (tiny.en); averaged across 6 benchmarked books
// ranging 0.0017-0.0067 min/audio-min. Does not include evidence transcription
// or focused-gap recovery, which run afterward and aren't duration-driven.
const HYBRID_SOS_MINUTES_PER_AUDIO_MINUTE = 0.0035;

function secondsToStamp(value) {
  const total = Math.max(0, Number(value) || 0);
  const whole = Math.floor(total);
  const ms = Math.round((total - whole) * 1000);
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = whole % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

function formatMinutes(minutes) {
  if (!Number.isFinite(minutes) || minutes <= 0) return 'unknown';
  if (minutes < 1) return `${Math.max(1, Math.round(minutes * 60))} sec`;
  const rounded = Math.round(minutes);
  const hours = Math.floor(rounded / 60);
  const mins = rounded % 60;
  if (!hours) return `${rounded} min`;
  return `${hours}h ${String(mins).padStart(2, '0')}m`;
}

function formatCountdown(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return 'finishing';
  const rounded = Math.ceil(seconds);
  const h = Math.floor(rounded / 3600);
  const m = Math.floor((rounded % 3600) / 60);
  const s = rounded % 60;
  if (h) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function formatElapsed(seconds) {
  const rounded = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(rounded / 3600);
  const m = Math.floor((rounded % 3600) / 60);
  const s = rounded % 60;
  if (h) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function stampToSeconds(value) {
  const parts = String(value || '').trim().replace(',', '.').split(':');
  if (parts.length !== 3) return 0;
  return (parseInt(parts[0], 10) || 0) * 3600 + (parseInt(parts[1], 10) || 0) * 60 + (parseFloat(parts[2]) || 0);
}

function getBackend() {
  return document.querySelector('input[name="backend"]:checked')?.value || 'hybrid-sos-focused';
}

function showToast(message, { actionLabel = '', onAction = null, duration = 8000 } = {}) {
  let toast = document.getElementById('cfToast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'cfToast';
    toast.className = 'cf-toast';
    document.body.appendChild(toast);
  }
  clearTimeout(toastTimer);
  toast.innerHTML = '';
  const text = document.createElement('span');
  text.textContent = message;
  toast.appendChild(text);
  if (actionLabel && onAction) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ghost';
    btn.textContent = actionLabel;
    btn.addEventListener('click', () => {
      onAction();
      toast.classList.remove('visible');
    });
    toast.appendChild(btn);
  }
  toast.classList.add('visible');
  toastTimer = setTimeout(() => toast.classList.remove('visible'), duration);
}

function cleanTitleText(chapter) {
  const kind = String(chapter?.marker_kind || '').trim();
  if (!kind) return null;
  const number = chapter?.number;
  return number != null && number !== '' ? `${kind} ${number}` : kind;
}

function syncFieldVisibility() {
  const advancedOpen = $('advancedRunToggle')?.getAttribute('aria-expanded') === 'true';
  $('advancedRunToggle').textContent = advancedOpen ? 'Hide advanced' : 'Advanced';
  const hybrid = getBackend() === 'hybrid-sos-focused';
  document.querySelectorAll('.chapter-advanced-setting').forEach((el) => {
    const hybridOnly = el.classList.contains('cf-hybrid-only');
    el.hidden = !advancedOpen || (hybridOnly && !hybrid);
  });
  document.querySelectorAll('.cf-hybrid-only:not(.chapter-advanced-setting)').forEach((el) => {
    el.hidden = !hybrid;
  });
}

function normalizeChapters() {
  chapters.sort((a, b) => Number(a.start || 0) - Number(b.start || 0));
  chapters.forEach((chapter, index) => {
    chapter.id = index + 1;
    if (index + 1 < chapters.length) {
      chapter.end = chapters[index + 1].start;
    } else if (Number(chapter.end || 0) <= Number(chapter.start || 0)) {
      chapter.end = Number(chapter.start || 0) + 1;
    }
  });
}

function collectRows() {
  const previous = chapters;
  chapters = Array.from(document.querySelectorAll('#chapterRows tr.chapter-row')).map((row, index) => {
    const old = previous[index] || {};
    const start = stampToSeconds(row.querySelector('[data-field="start"]').value);
    return {
      ...old,
      id: index + 1,
      start,
      end: Number(old.end || start),
      title: row.querySelector('[data-field="title"]').value.trim() || `Chapter ${index + 1}`,
    };
  });
  normalizeChapters();
}

function setAudioPreview(sourcePath) {
  const audio = $('audioPreview');
  const files = loaded?.audio_files || [];
  if (files.length === 1) {
    audio.dataset.sourcePath = files[0];
    audio.dataset.offset = '0';
    audio.hidden = false;
  } else if (sourcePath && sourcePath.match(/\.(m4b|m4a|mp4|mp3|flac|ogg|opus|aac|wav)$/i)) {
    audio.dataset.sourcePath = sourcePath;
    audio.dataset.offset = '0';
    audio.hidden = false;
  } else {
    audio.removeAttribute('src');
    audio.dataset.sourcePath = '';
    audio.dataset.offset = '0';
    audio.hidden = true;
  }
}

function playRange(start, end) {
  const audio = $('audioPreview');
  const sourcePath = audio.dataset.sourcePath || loaded?.source_path || '';
  if (!sourcePath) return;
  installEvidencePlaybackSync();
  const clipStart = Math.max(0, Number(start) || 0);
  const clipEnd = Math.max(clipStart + 1, Number(end) || clipStart + 1);
  const duration = Math.min(180, Math.max(1, clipEnd - clipStart));
  const clipUrl = `/api/chaptering/audio-clip?path=${encodeURIComponent(sourcePath)}&start=${encodeURIComponent(clipStart.toFixed(3))}&duration=${encodeURIComponent(duration.toFixed(3))}`;
  audio.dataset.offset = String(clipStart);
  if (audio.src !== new URL(clipUrl, window.location.href).href) {
    audio.src = clipUrl;
  }
  audio.currentTime = 0;
  audio.play();
  const stopAt = duration;
  const onTime = () => {
    if (audio.currentTime >= stopAt) {
      audio.pause();
      audio.removeEventListener('timeupdate', onTime);
    }
  };
  audio.addEventListener('timeupdate', onTime);
}

const PLAY_ALL_CLIP_SECONDS = 6;

function stopPlayAll() {
  if (!playAllState) return;
  clearTimeout(playAllState.timer);
  playAllState = null;
  $('audioPreview').pause();
  const btn = $('playAllBtn');
  if (btn) {
    btn.textContent = 'Play all';
    btn.classList.remove('active');
  }
  document.querySelectorAll('.chapter-row.playing-all').forEach((row) => row.classList.remove('playing-all'));
}

function playAllStep() {
  if (!playAllState) return;
  if (playAllState.index >= chapters.length) {
    stopPlayAll();
    return;
  }
  document.querySelectorAll('.chapter-row.playing-all').forEach((row) => row.classList.remove('playing-all'));
  const chapter = chapters[playAllState.index];
  const row = document.getElementById(`chapter-row-${chapter.id}`);
  if (row) {
    row.classList.add('playing-all');
    row.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
  const start = Number(chapter.start || 0);
  const end = Math.min(Number(chapter.end || start + PLAY_ALL_CLIP_SECONDS), start + PLAY_ALL_CLIP_SECONDS);
  playRange(start, end);
  playAllState.index += 1;
  playAllState.timer = setTimeout(playAllStep, PLAY_ALL_CLIP_SECONDS * 1000);
}

function togglePlayAll() {
  if (playAllState) {
    stopPlayAll();
    return;
  }
  if (!chapters.length) return;
  playAllState = { index: 0, timer: null };
  const btn = $('playAllBtn');
  if (btn) {
    btn.textContent = 'Stop';
    btn.classList.add('active');
  }
  playAllStep();
}

function installEvidencePlaybackSync() {
  const audio = $('audioPreview');
  if (!audio || evidencePlaybackSyncInstalled) return;
  evidencePlaybackSyncInstalled = true;
  audio.addEventListener('timeupdate', () => {
    const offset = Number(audio.dataset.offset || 0);
    syncEvidencePlayback(offset + audio.currentTime);
  });
  audio.addEventListener('pause', () => {
    if (audio.currentTime >= audio.duration) syncEvidencePlayback(-1);
  });
}

function syncEvidencePlayback(time) {
  document.querySelectorAll('.chapter-evidence-word-inline.active').forEach((el) => el.classList.remove('active'));
  document.querySelectorAll('.chapter-evidence-item.playing').forEach((el) => el.classList.remove('playing'));
  if (!Number.isFinite(time) || time < 0) return;
  const activeWord = Array.from(document.querySelectorAll('.chapter-evidence-word-inline')).find((el) => {
    const start = Number(el.dataset.start || 0);
    const end = Number(el.dataset.end || start);
    return time >= start - 0.03 && time <= end + 0.03;
  });
  if (activeWord) {
    activeWord.classList.add('active');
    activeWord.closest('.chapter-evidence-item')?.classList.add('playing');
    activeWord.scrollIntoView({ block: 'nearest', inline: 'center' });
  }
}

function markerStartForChapter(chapter) {
  const number = String(chapter?.number || chapter?.id || '').replace(/[^0-9]/g, '');
  const words = wordEvidenceItems(chapter);
  for (let index = 0; index < words.length; index += 1) {
    const text = words[index].text.toLowerCase().replace(/[^a-z0-9]+/g, '');
    const next = (words[index + 1]?.text || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
    if (text === 'chapter' && (!number || next === number || next.startsWith(number))) {
      return words[index].start;
    }
  }
  const anyChapter = words.find((word) => word.text.toLowerCase().replace(/[^a-z0-9]+/g, '') === 'chapter');
  return anyChapter ? anyChapter.start : Number(chapter?.original_start || chapter?.start || 0);
}

function silenceEvidenceItems(chapter) {
  const start = Number(chapter?.start || 0);
  const markerStart = markerStartForChapter(chapter);
  let silences = Array.isArray(chapter?.evidence_silences) ? chapter.evidence_silences : [];
  if (!silences.length && Array.isArray(chapter?.evidence_anchors)) {
    const anchors = chapter.evidence_anchors
      .map((anchor) => ({
        time: Number(anchor.time ?? anchor.start ?? 0),
        kind: String(anchor.kind || ''),
        text: String(anchor.text || ''),
      }))
      .filter((anchor) => Number.isFinite(anchor.time))
      .sort((a, b) => a.time - b.time);
    const reconstructed = [];
    let pendingStart = null;
    anchors.forEach((anchor) => {
      const isStart = anchor.kind === 'silence' && anchor.text === 'silence start';
      const isEnd = anchor.kind === 'silence' && anchor.text === 'silence end';
      if (isStart) pendingStart = anchor.time;
      if (isEnd && pendingStart != null && anchor.time > pendingStart) {
        reconstructed.push({ start: pendingStart, end: anchor.time, duration: anchor.time - pendingStart });
        pendingStart = null;
      }
    });
    silences = reconstructed;
  }
  return silences
    .map((silence, index) => {
      const silenceStart = Number(silence.start || 0);
      const silenceEnd = Number(silence.end || silenceStart);
      const duration = Math.max(0, Number(silence.duration || (silenceEnd - silenceStart)));
      const distance = Math.min(
        Math.abs(silenceStart - start),
        Math.abs(silenceEnd - start),
        Math.abs(silenceStart - markerStart),
        Math.abs(silenceEnd - markerStart),
      );
      const beforeMarker = silenceEnd <= markerStart + 0.35;
      return { type: 'silence', start: silenceStart, end: silenceEnd, duration, distance, beforeMarker, index };
    })
    .filter((silence) => silence.duration >= 0.25 && silence.distance <= 12)
    .sort((a, b) => Number(b.beforeMarker) - Number(a.beforeMarker) || a.distance - b.distance)
    .slice(0, 5)
    .sort((a, b) => a.start - b.start);
}

function wordEvidenceItems(chapter) {
  const words = Array.isArray(chapter.evidence_words) ? chapter.evidence_words : [];
  return words
    .map((word, index) => ({
      type: 'word',
      start: Number(word.start || 0),
      end: Number(word.end || word.start || 0),
      text: String(word.text || word.word || '').trim(),
      probability: word.probability,
      index,
    }))
    .filter((word) => word.text && Number.isFinite(word.start))
    .sort((a, b) => a.start - b.start);
}

function transcriptEvidenceItems(evidenceText, activeTime = 0) {
  const items = [];
  const seen = new Set();
  String(evidenceText || '').split('\n').forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    const match = trimmed.match(/^\[([0-9:.]+)\s+-\s+([0-9:.]+)\]\s*(.*)$/);
    if (match) {
      const start = stampToSeconds(match[1]);
      const end = stampToSeconds(match[2]);
      const text = match[3] || '';
      const fingerprint = `${Math.round(start / 2)}:${text.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().slice(0, 80)}`;
      if (seen.has(fingerprint)) return;
      seen.add(fingerprint);
      items.push({ type: 'transcript', start, end, text, index });
    } else {
      items.push({ type: 'note', start: index / 1000, end: index / 1000, text: trimmed, index });
    }
  });
  items.sort((a, b) => Number(a.start || 0) - Number(b.start || 0) || String(a.type).localeCompare(String(b.type)));
  const filtered = [];
  items.forEach((item) => {
    const marker = String(item.text || '').toLowerCase().match(/^\s*(chapter|part|section)\s+([a-z0-9]+)\b/);
    if (!marker || item.type !== 'transcript') {
      filtered.push(item);
      return;
    }
    const duplicateIndex = filtered.findIndex((existing) => {
      const existingMarker = String(existing.text || '').toLowerCase().match(/^\s*(chapter|part|section)\s+([a-z0-9]+)\b/);
      return existing.type === 'transcript'
        && existingMarker
        && existingMarker[1] === marker[1]
        && existingMarker[2] === marker[2]
        && Math.abs(Number(existing.start || 0) - Number(item.start || 0)) <= 8;
    });
    if (duplicateIndex === -1) {
      filtered.push(item);
      return;
    }
    const existing = filtered[duplicateIndex];
    const existingDelta = Math.abs(Number(existing.start || 0) - activeTime);
    const itemDelta = Math.abs(Number(item.start || 0) - activeTime);
    if (itemDelta < existingDelta || (itemDelta === existingDelta && String(item.text || '').length < String(existing.text || '').length)) {
      filtered[duplicateIndex] = item;
    }
  });
  return filtered;
}

function wordsForTranscriptItem(item, words = []) {
  return words.filter((word) => {
    const start = Number(word.start || 0);
    return start >= Number(item.start || 0) - 0.1 && start <= Number(item.end || 0) + 0.1;
  });
}

function renderTranscriptWords(item, words = []) {
  const rowWords = wordsForTranscriptItem(item, words);
  if (!rowWords.length) return escapeHtml(item.text || '');
  return rowWords.map((word) => `
    <span class="chapter-evidence-word-inline" data-start="${word.start}" data-end="${word.end}" title="${escapeHtml(secondsToStamp(word.start))}">
      ${escapeHtml(word.text)}
    </span>
  `).join(' ');
}

function evidenceItems(items = [], activeAnchor = null, words = []) {
  const activeTime = Number(activeAnchor?.start ?? activeAnchor?.time ?? 0);
  return items.map((item) => {
    const isActiveTranscript = item.type === 'transcript'
      && activeTime >= Number(item.start || 0) - 0.05
      && activeTime <= Number(item.end || 0) + 0.05;
    const activeClass = isActiveTranscript ? ' active' : '';
    if (item.type === 'transcript') {
      return `
        <div class="chapter-evidence-item chapter-evidence-transcript${activeClass}" data-start="${item.start}" data-end="${item.end}" data-kind="transcript">
          <span class="chapter-evidence-stamp">${escapeHtml(secondsToStamp(item.start))} - ${escapeHtml(secondsToStamp(item.end))}</span>
          <span class="chapter-evidence-line">${renderTranscriptWords(item, words)}</span>
        </div>
      `;
    }
    return `<div class="chapter-evidence-item chapter-evidence-note">${escapeHtml(item.text)}</div>`;
  }).join('') || '<div class="chapter-evidence-item chapter-evidence-note">No transcript evidence stored for this row.</div>';
}

function silenceSnapItems(items = []) {
  if (!items.length) return '<div class="chapter-silence-empty">No nearby silence windows stored.</div>';
  return items.map((item) => {
    const oneSecond = Math.min(item.end, item.start + 1);
    const middle = item.start + ((item.end - item.start) / 2);
    return `
      <div class="chapter-silence-item" data-start="${item.start}" data-end="${item.end}">
        <span class="chapter-silence-range">${escapeHtml(secondsToStamp(item.start))} - ${escapeHtml(secondsToStamp(item.end))}</span>
        <span class="chapter-silence-duration">${escapeHtml(item.duration.toFixed(2))}s</span>
        <button class="secondary silence-snap" type="button" data-time="${item.start}" title="Snap to the beginning of this silence">Start</button>
        <button class="secondary silence-snap" type="button" data-time="${oneSecond}" title="Snap one second into this silence">+1s</button>
        <button class="secondary silence-snap" type="button" data-time="${middle}" title="Snap to the middle of this silence">Mid</button>
        <button class="secondary silence-snap" type="button" data-time="${item.end}" title="Snap to the end of this silence">End</button>
      </div>
    `;
  }).join('');
}

function updateEvidenceSelection(evidenceEl, anchor) {
  evidenceEl.querySelectorAll('.chapter-evidence-item.active').forEach((item) => item.classList.remove('active'));
  evidenceEl.querySelectorAll('.chapter-evidence-word-inline.selected').forEach((item) => {
    item.classList.remove('active');
    item.classList.remove('selected');
  });
  if (!anchor) return;
  const time = Number(anchor.start ?? anchor.time ?? 0);
  let best = null;
  let bestDelta = Infinity;
  evidenceEl.querySelectorAll('.chapter-evidence-item').forEach((item) => {
    const start = Number(item.dataset.start || 0);
    const end = Number(item.dataset.end || start);
    if (item.dataset.kind !== 'transcript') return;
    if (time >= start - 0.05 && time <= end + 0.05) {
      best = item;
      bestDelta = 0;
    } else {
      const delta = Math.min(Math.abs(start - time), Math.abs(end - time));
      if (delta < bestDelta) {
        best = item;
        bestDelta = delta;
      }
    }
  });
  if (best) {
    best.classList.add('active');
    best.scrollIntoView({ block: 'nearest' });
  }
}

function anchorLabel(anchor) {
  if (!anchor) return 'Detected boundary';
  const start = Number(anchor.start ?? anchor.time ?? 0);
  const end = Number(anchor.end ?? start);
  if ((anchor.type || '') === 'word') return `${secondsToStamp(start)} · ${anchor.text || ''}`;
  if (end > start + 0.05) return `${secondsToStamp(start)} - ${secondsToStamp(end)}`;
  return secondsToStamp(start);
}

function setChapterStartFromEvidence(tr, evidenceEl, time, label) {
  tr.querySelector('[data-field="start"]').value = secondsToStamp(time);
  const anchorLabelEl = evidenceEl.querySelector('.evidence-anchor-label');
  if (anchorLabelEl) anchorLabelEl.textContent = label || secondsToStamp(time);
  updateEvidenceSelection(evidenceEl, { start: time, end: time });
  collectRows();
  renderChapters();
}

function whyFlagged(chapter) {
  const reasons = chapter.reasons || [];
  const markerReason = reasons.find((r) => r.startsWith('marker:'));
  const marker = markerReason ? markerReason.split(':')[1] : '';
  if (marker && marker !== 'chapter') {
    return `Matched on "${marker}" mid-sentence, not a "Chapter N" marker -- likely a false positive, not a real boundary.`;
  }
  if (chapter.manual) return 'Added manually -- not from detection.';
  return 'Low-confidence detection. Listen to the preview before trusting this boundary.';
}

function buildEvidenceRow(chapter, tr) {
  const evidenceText = chapter.evidence_text || chapter.source_text || '';
  const transcriptItems = transcriptEvidenceItems(evidenceText, Number(chapter.start || 0));
  const wordItems = wordEvidenceItems(chapter);
  const silenceItems = silenceEvidenceItems(chapter);
  const anchors = transcriptItems.filter((item) => item.type === 'transcript');
  const start = Number(chapter.start || 0);
  const containing = anchors.findIndex((anchor) => start >= Number(anchor.start || 0) - 0.05 && start <= Number(anchor.end || anchor.start || 0) + 0.05);
  const activeAnchor = containing >= 0 ? anchors[containing] : { start, end: start, text: 'Detected boundary' };
  const isFlagged = (chapter.confidence == null ? 1 : Number(chapter.confidence)) < CONFIDENCE_FLAG_THRESHOLD;

  const evidenceTr = document.createElement('tr');
  evidenceTr.className = 'evidence-row collapsed';
  evidenceTr.innerHTML = `
    <td colspan="5">
      <div class="cf-evidence">
        <div class="cf-evidence-grid">
          <div class="cf-evidence-block">
            <h4>Transcript evidence</h4>
            <div class="cf-transcript chapter-evidence-text">${evidenceItems(transcriptItems, activeAnchor, wordItems)}</div>
            ${isFlagged ? `<p class="why-flagged">&#9888; ${escapeHtml(whyFlagged(chapter))}</p>` : ''}
          </div>
          <div class="cf-evidence-block">
            <h4>Nearby silence</h4>
            <div class="cf-silence-list chapter-silence-list">${silenceSnapItems(silenceItems)}</div>
          </div>
        </div>
        <div class="cf-evidence-foot">
          <span>Selected anchor: <span class="anchor evidence-anchor-label">${escapeHtml(containing >= 0 ? anchorLabel(anchors[containing]) : `${secondsToStamp(start)} · detected boundary`)}</span></span>
          <button class="ghost evidence-preview" type="button">Preview 4s before / 12s after</button>
          <button class="ghost evidence-set-start" type="button" title="Reset to the silence-snapped boundary detected by Chapter Forge">Reset to detected start</button>
        </div>
      </div>
    </td>
  `;

  const evidenceContentEl = evidenceTr.querySelector('.cf-evidence');
  evidenceTr.querySelectorAll('.chapter-evidence-transcript').forEach((item) => {
    item.addEventListener('click', () => {
      const start2 = Number(item.dataset.start || 0);
      const indexForRow = anchors.findIndex((anchor) => Math.abs(Number(anchor.start || 0) - start2) < 0.05);
      setChapterStartFromEvidence(tr, evidenceContentEl, start2, indexForRow >= 0 ? anchorLabel(anchors[indexForRow]) : '');
    });
  });
  evidenceTr.querySelectorAll('.silence-snap').forEach((item) => {
    item.addEventListener('click', () => {
      const time = Number(item.dataset.time || 0);
      const label = `${secondsToStamp(time)} · silence ${item.textContent.trim().toLowerCase()}`;
      setChapterStartFromEvidence(tr, evidenceContentEl, time, label);
    });
  });
  evidenceTr.querySelector('.evidence-preview').addEventListener('click', () => {
    const start2 = stampToSeconds(tr.querySelector('[data-field="start"]').value) || Number(chapter.start || 0);
    playRange(Math.max(0, start2 - 4), start2 + 12);
  });
  evidenceTr.querySelector('.evidence-set-start').addEventListener('click', () => {
    tr.querySelector('[data-field="start"]').value = secondsToStamp(Number(chapter.detected_start ?? chapter.start ?? 0));
    collectRows();
    renderChapters();
  });
  return evidenceTr;
}

function renderGapBanner() {
  const banner = $('gapBanner');
  const gaps = loaded?.result?.sequence_review || [];
  if (!gaps.length) {
    banner.hidden = true;
    banner.innerHTML = '';
    return;
  }
  const rows = gaps.map((gap) => {
    const nearest = chapters.reduce((best, chapter) => {
      const delta = Math.abs(Number(chapter.start || 0) - Number(gap.start || 0));
      return !best || delta < best.delta ? { chapter, delta } : best;
    }, null);
    const jump = nearest ? `<a href="#chapter-row-${nearest.chapter.id}">Jump to nearest candidate &rarr;</a>` : '';
    const expected = gap.expected_number != null ? `Chapter ${escapeHtml(String(gap.expected_number))}` : 'A chapter';
    return `
      <div class="cf-gap-banner-row">
        <span class="gap-icon">&#9888;</span>
        <div>
          <b>${expected} wasn't found.</b>
          <span class="gap-text">Expected around <code>${escapeHtml(secondsToStamp(gap.start))} &ndash; ${escapeHtml(secondsToStamp(gap.end))}</code>.</span>
        </div>
        ${jump}
      </div>
    `;
  }).join('');
  banner.innerHTML = rows;
  banner.hidden = false;
}

function renderChapters() {
  normalizeChapters();
  const tbody = $('chapterRows');
  tbody.innerHTML = '';

  const flagged = chapters.filter((c) => (c.confidence == null ? 1 : Number(c.confidence)) < CONFIDENCE_FLAG_THRESHOLD);
  const gapCount = (loaded?.result?.sequence_review || []).length;

  chapters.forEach((chapter, index) => {
    if (chapter.detected_start == null) chapter.detected_start = Number(chapter.start || 0);
    const isFlagged = flagged.includes(chapter);
    const shouldHide = showOnlyFlagged && !isFlagged;

    const tr = document.createElement('tr');
    tr.className = `chapter-row${isFlagged ? ' flagged' : ''}`;
    tr.id = `chapter-row-${chapter.id}`;
    tr.hidden = shouldHide;
    const confidenceCell = chapter.confidence == null
      ? '<span class="conf-clean">manual</span>'
      : isFlagged
        ? `<span class="conf-flag">&#9888; ${Math.round(Number(chapter.confidence) * 100)}%</span>`
        : `<span class="conf-clean">${Math.round(Number(chapter.confidence) * 100)}%</span>`;
    const cleanTitle = cleanTitleText(chapter);
    const showCleanBtn = cleanTitle && cleanTitle !== (chapter.title || '').trim();
    tr.innerHTML = `
      <td class="idx">${index + 1}</td>
      <td class="time">
        <input data-field="start" value="${escapeHtml(secondsToStamp(chapter.start))}" />
        <span class="time-arrow">&rarr;</span>
        <span class="time-end">${escapeHtml(secondsToStamp(chapter.end))}</span>
      </td>
      <td class="title-cell">
        <input data-field="title" value="${escapeHtml(chapter.title || `Chapter ${index + 1}`)}" title="${escapeHtml(chapter.source_text || '')}" />
        ${showCleanBtn ? `<button class="icon-button small clean-title" type="button" title="Strip to just “${escapeHtml(cleanTitle)}”, discarding the rest of the text">&#9986;</button>` : ''}
      </td>
      <td>${confidenceCell}</td>
      <td>
        <div class="row-actions">
          <button class="icon-button small preview-start" type="button" title="Preview">&#9654;</button>
          <button class="icon-button small expand" type="button" aria-expanded="false" title="Inspect evidence">&#9662;</button>
          <button class="icon-button small insert-after" type="button" title="Insert a chapter after this one">&#43;</button>
          <button class="icon-button small danger delete-row" type="button" title="Delete">&times;</button>
        </div>
      </td>
    `;

    const evidenceTr = buildEvidenceRow(chapter, tr);
    evidenceTr.hidden = shouldHide;

    tr.querySelectorAll('input').forEach((input) => {
      input.addEventListener('change', () => {
        collectRows();
        renderChapters();
      });
    });
    const expandBtn = tr.querySelector('.expand');
    const toggleEvidence = () => {
      const open = evidenceTr.classList.contains('collapsed');
      if (open) {
        document.querySelectorAll('#chapterRows tr.evidence-row:not(.collapsed)').forEach((row) => {
          row.classList.add('collapsed');
        });
        document.querySelectorAll('#chapterRows .icon-button.expand[aria-expanded="true"]').forEach((btn) => {
          btn.setAttribute('aria-expanded', 'false');
        });
      }
      evidenceTr.classList.toggle('collapsed', !open);
      expandBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    };
    expandBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      toggleEvidence();
    });
    tr.addEventListener('click', (event) => {
      if (event.target.closest('input, button, a')) return;
      toggleEvidence();
    });
    tr.querySelector('.clean-title')?.addEventListener('click', (event) => {
      event.stopPropagation();
      const titleInput = tr.querySelector('[data-field="title"]');
      titleInput.value = cleanTitle;
      collectRows();
      renderChapters();
    });
    tr.querySelector('.preview-start').addEventListener('click', (event) => {
      event.stopPropagation();
      collectRows();
      const current = chapters.find((c) => c.id === chapter.id) || chapter;
      playRange(current.start, current.start + 8);
    });
    tr.querySelector('.insert-after').addEventListener('click', (event) => {
      event.stopPropagation();
      collectRows();
      insertChapterAfter(chapter.id);
    });
    tr.querySelector('.delete-row').addEventListener('click', (event) => {
      event.stopPropagation();
      if (!confirm(`Delete "${chapter.title || `Chapter ${index + 1}`}"?`)) return;
      collectRows();
      const removeIndex = chapters.findIndex((c) => c.id === chapter.id);
      if (removeIndex < 0) return;
      const [removed] = chapters.splice(removeIndex, 1);
      renderChapters();
      lastRemoved = { chapter: removed, index: removeIndex };
      showToast(`Deleted "${removed.title || 'chapter'}".`, {
        actionLabel: 'Undo',
        onAction: () => {
          if (!lastRemoved) return;
          collectRows();
          chapters.splice(Math.min(lastRemoved.index, chapters.length), 0, lastRemoved.chapter);
          lastRemoved = null;
          renderChapters();
        },
      });
    });

    tbody.appendChild(tr);
    tbody.appendChild(evidenceTr);
  });

  const statsEl = $('chapterStats');
  if (!chapters.length) {
    statsEl.textContent = 'No chapters loaded.';
  } else {
    statsEl.innerHTML = `
      <span><b>${chapters.length}</b> chapters</span>
      <span><b>${chapters.length - flagged.length}</b> clean</span>
      ${flagged.length ? `<span style="color:var(--warning)"><b>${flagged.length}</b> need review</span>` : ''}
      ${gapCount ? `<span style="color:var(--danger)"><b>${gapCount}</b> sequence gap${gapCount === 1 ? '' : 's'}</span>` : ''}
      ${llmConfidenceBadge()}
    `;
  }

  const chip = $('flagFilterChip');
  chip.hidden = flagged.length === 0;
  chip.classList.toggle('active', showOnlyFlagged);
  chip.textContent = '';
  chip.append(showOnlyFlagged ? 'Show all chapters ' : 'Show only flagged ');
  const countSpan = document.createElement('span');
  countSpan.className = 'count';
  countSpan.textContent = String(flagged.length);
  chip.append(countSpan);

  renderGapBanner();

  $('saveBtn').disabled = !loaded || !chapters.length;
  $('addChapterBtn').disabled = !loaded;
  $('playAllBtn').disabled = !chapters.length;

  const dirty = savedSnapshot !== null && chapters.length && chapterSnapshot() !== savedSnapshot;
  const dirtyEl = $('saveDirtyNote');
  if (dirtyEl) dirtyEl.hidden = !dirty;
}

function cleanAllTitles() {
  collectRows();
  let changed = 0;
  chapters.forEach((chapter) => {
    const clean = cleanTitleText(chapter);
    if (clean && clean !== (chapter.title || '').trim()) {
      chapter.title = clean;
      changed += 1;
    }
  });
  if (changed) renderChapters();
  showToast(changed ? `Cleaned ${changed} title${changed === 1 ? '' : 's'}.` : 'No titles needed cleaning.');
}

function renderRunLog(entries) {
  const el = $('runLogBody');
  if (!el) return;
  const log = entries || loaded?.result?.run_log || [];
  if (!log.length) {
    el.innerHTML = '<p class="note">No run log recorded for this book yet.</p>';
    return;
  }
  el.innerHTML = log.map((entry) => `
    <div class="cf-runlog-item">
      <span class="cf-runlog-time">${escapeHtml(formatElapsed(entry.t))}</span>
      <span class="cf-runlog-label">${escapeHtml(entry.label || entry.phase || '')}</span>
      ${entry.detail ? `<span class="cf-runlog-detail">${escapeHtml(entry.detail)}</span>` : ''}
    </div>
  `).join('');
}

function renderAiReview() {
  const body = $('aiReviewBody');
  if (!body) return;
  const review = loaded?.result?.hybrid?.llm_review;
  if (!review || !review.assessment) {
    body.innerHTML = '<p class="note">No AI review data. Enable "LLM review names" under Advanced settings and re-run detection to see one here.</p>';
    return;
  }
  const corrections = review.accepted_corrections || [];
  const issues = review.unresolved_issues || [];
  const rules = review.validator_rules_to_apply || [];
  const notes = Array.isArray(review.notes) ? review.notes : (review.notes ? [review.notes] : []);
  const assessment = String(review.assessment || '');
  const tone = { clean: 'success', resolved_by_focused_asr: 'success' }[assessment] || (
    assessment === 'llm_unavailable' ? 'muted' : 'warning'
  );
  const meta = [review._model, review._ollama_duration_seconds != null ? `${review._ollama_duration_seconds}s` : '']
    .filter(Boolean).join(' · ');
  body.innerHTML = `
    <div class="cf-review-head">
      <span class="cf-llm-badge cf-llm-badge-${tone}">${escapeHtml(assessment.replace(/_/g, ' '))}${review.confidence ? ` (${escapeHtml(review.confidence)})` : ''}</span>
      ${meta ? `<span class="cf-review-meta">${escapeHtml(meta)}</span>` : ''}
    </div>
    ${review._error ? `<p class="note" style="color:var(--danger)">${escapeHtml(review._error)}</p>` : ''}
    <div class="cf-review-block">
      <h4>Accepted corrections <span class="n">${corrections.length}</span></h4>
      ${corrections.length ? corrections.map((c) => `
        <div class="cf-review-item">
          <b>${escapeHtml(c.action || '')}</b> chapter ${escapeHtml(String(c.number ?? ''))} at ${escapeHtml(c.timestamp || '')}: ${escapeHtml(c.title || '')}
          ${c.reason ? `<div class="cf-review-item-note">${escapeHtml(c.reason)}</div>` : ''}
        </div>
      `).join('') : '<p class="note">None.</p>'}
    </div>
    <div class="cf-review-block">
      <h4>Unresolved issues <span class="n">${issues.length}</span></h4>
      ${issues.length ? issues.map((item) => `
        <div class="cf-review-item">
          <b>${escapeHtml(item.type || '')}</b>
          <span class="cf-review-severity cf-review-severity-${escapeHtml(item.severity || 'low')}">${escapeHtml(item.severity || '')}</span>
          <div class="cf-review-item-note">${escapeHtml(item.details || '')}${item.recommended_action ? ` &mdash; ${escapeHtml(item.recommended_action)}` : ''}</div>
        </div>
      `).join('') : '<p class="note">None.</p>'}
    </div>
    ${rules.length ? `
      <div class="cf-review-block">
        <h4>Validator rules to apply</h4>
        ${rules.map((r) => `<div class="cf-review-item">${escapeHtml(r)}</div>`).join('')}
      </div>
    ` : ''}
    ${notes.length ? `
      <div class="cf-review-block">
        <h4>Notes</h4>
        ${notes.map((n) => `<div class="cf-review-item">${escapeHtml(n)}</div>`).join('')}
      </div>
    ` : ''}
  `;
}

function renderArtifacts(artifacts = {}) {
  const list = $('artifactList');
  const entries = Object.entries(artifacts);
  if (!entries.length) {
    list.innerHTML = '<p class="note">No files written yet.</p>';
    return;
  }
  list.innerHTML = entries.map(([kind, path]) => `
    <div class="file-row">
      <span class="file-kind">${escapeHtml(kind.toUpperCase())}</span>
      <span class="path">${escapeHtml(path)}</span>
    </div>
  `).join('');
}

async function findCandidate() {
  const list = $('candidateList');
  list.hidden = false;
  list.innerHTML = '<p class="note">Searching for single-file books without chapters...</p>';
  const res = await fetch('/api/chaptering/candidates', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ root_path: '/audiobooks', limit: 40 }),
  });
  const data = await res.json();
  if (!res.ok) {
    list.innerHTML = `<p class="note">${escapeHtml(data.detail || 'Candidate search failed')}</p>`;
    return;
  }
  const items = data.items || [];
  if (!items.length) {
    list.innerHTML = '<p class="note">No single-file candidates found.</p>';
    return;
  }
  list.innerHTML = items.map((item, index) => `
    <div class="file-item">
      <strong>${escapeHtml(item.name)}</strong><br>
      <span>${escapeHtml(item.path)}</span><br>
      <span>${escapeHtml(String(item.size_mb || 'unknown'))} MB</span><br>
      <button class="secondary" type="button" data-candidate="${index}">Use this file</button>
    </div>
  `).join('');
  list.querySelectorAll('[data-candidate]').forEach((button) => {
    button.addEventListener('click', () => {
      const item = items[Number(button.dataset.candidate)];
      $('sourcePath').value = item.path;
      list.hidden = true;
      loadChapters();
    });
  });
}

function applyResult(data) {
  const result = data?.result || data?.stats?.chaptering_result || data;
  if (!result) return;
  loaded = {
    source_path: result.source_path || $('sourcePath').value.trim(),
    audio_files: result.audio_files || loaded?.audio_files || [],
    duration: result.duration || loaded?.duration || 0,
    result,
  };
  chapters = (result.chapters || []).map((chapter) => ({ ...chapter }));
  setAudioPreview(loaded.source_path);
  markSaved();
  renderChapters();
  renderArtifacts(data?.stats?.artifacts || data?.artifacts || {});
  renderAiReview();
  renderRunLog();
}

async function loadChapters() {
  stopPlayAll();
  const res = await fetch('/api/chaptering/load', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_path: $('sourcePath').value.trim() }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Failed to load chapter source');
    return;
  }
  loaded = data;
  chapters = (data.result?.chapters || []).map((chapter) => ({ ...chapter }));
  setAudioPreview(data.source_path);
  markSaved();
  renderChapters();
  renderArtifacts({});
  renderAiReview();
  renderRunLog();
  $('loadStatus').textContent = data.result
    ? `Loaded existing chapters for ${data.source_path}`
    : `Source loaded with ${data.audio_files.length} audio file(s). No chapter artifact found.`;
  updateEtaStatus();
}

async function startDetection() {
  stopPlayAll();
  const body = {
    source_path: $('sourcePath').value.trim(),
    backend: getBackend(),
    remote_endpoint: $('remoteEndpoint').value.trim(),
    llm_review: $('llmReview')?.checked || false,
    llm_endpoint: $('llmEndpoint')?.value.trim() || '',
    llm_model: $('llmModel')?.value.trim() || 'gemma4:latest',
    llm_extra_instructions: $('llmExtraInstructions')?.value.trim() || '',
    model: $('model').value.trim() || 'small',
    device: $('device').value,
    compute_type: $('computeType').value,
    cpu_threads: parseInt($('cpuThreads').value || '0', 10),
    beam_size: parseInt($('beamSize').value || '1', 10),
    vad_filter: $('vadFilter').checked,
    language: $('language').value.trim() || 'en',
    condition_on_previous_text: $('carryContext').checked,
    silence_snap: $('silenceSnap').checked,
    silence_window: parseFloat($('silenceWindow').value || '4'),
    silence_marker_lead_seconds: parseFloat($('silenceMarkerLeadSeconds').value || '1'),
    save_full_transcript: $('saveFullTranscript').checked,
    focused_rescan: $('focusedRescan').checked,
    focused_model: $('focusedModel').value.trim(),
    focused_compute_type: $('focusedComputeType').value,
    focused_beam_size: parseInt($('focusedBeamSize').value || '5', 10),
    max_gap_rescans: parseInt($('maxGapRescans').value || '8', 10),
    max_audio_minutes: parseFloat($('maxAudioMinutes').value || '0'),
    chunk_minutes: parseFloat($('chunkMinutes').value || '20'),
    resource_guard: $('resourceGuard').checked,
    max_memory_percent: parseFloat($('maxMemoryPercent').value || '97'),
    min_memory_available_gb: parseFloat($('minMemoryAvailableGb').value || '2'),
    max_swap_percent: parseFloat($('maxSwapPercent').value || '90'),
    max_swap_growth_percent: parseFloat($('maxSwapGrowthPercent').value || '10'),
    max_cpu_percent: parseFloat($('maxCpuPercent').value || '100'),
  };
  const res = await fetch('/api/chaptering/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Failed to start detection. The selected backend may not be installed.');
    return;
  }
  currentRun = data.id;
  activeRunStartedAt = Date.now() / 1000;
  updateEtaStatus();
  $('detectBtn').disabled = true;
  $('cancelBtn').disabled = false;
  pollRun();
}

function firstPassMinutesPerAudioMinute() {
  const model = ($('model')?.value || 'small').trim().toLowerCase();
  const compute = $('computeType')?.value || 'float32';
  const beam = Number($('beamSize')?.value || 5);
  const vad = $('vadFilter')?.checked;
  let factor = CPU_MINUTES_PER_AUDIO_MINUTE_BASELINE;
  let caveat = '';
  if (model !== 'small' || compute !== 'float32' || beam !== 5 || vad) {
    caveat = 'extrapolated from the small/float32/beam5/VAD-off baseline';
    if (model === 'medium') factor *= 1.65;
    else if (model.startsWith('large')) factor *= 2.7;
    else if (model === 'base') factor *= 0.65;
    if (compute === 'int8') factor *= 0.85;
    if (beam > 5) factor *= 1 + ((beam - 5) * 0.06);
    if (vad) factor *= 1.03;
  }
  return { factor, caveat };
}

function estimateRunMinutes() {
  const durationMinutes = Math.max(0, Number(loaded?.duration || 0) / 60);
  if (!durationMinutes) return { minutes: 0, label: 'ETA appears after loading a source.', caveat: '' };
  if (getBackend() === 'hybrid-sos-focused') {
    const minutes = Math.max(0.1, durationMinutes * HYBRID_SOS_MINUTES_PER_AUDIO_MINUTE);
    return {
      minutes,
      label: `Estimated silence + keyword scan: ${formatMinutes(minutes)}.`,
      caveat: 'excludes per-chapter evidence transcription, which always runs after detection (roughly 5-6s per chapter found) and any focused-gap recovery -- actual runtime is typically longer, especially for books with many chapters',
    };
  }
  const limit = Number($('maxAudioMinutes')?.value || 0);
  const effectiveDuration = limit > 0 ? Math.min(durationMinutes, limit) : durationMinutes;
  const { factor, caveat } = firstPassMinutesPerAudioMinute();
  let minutes = effectiveDuration * factor;
  const focusModel = ($('focusedModel')?.value || $('model')?.value || 'medium').trim() || 'medium';
  if ($('focusedRescan')?.checked) {
    minutes += CPU_MINUTES_PER_FOCUSED_GAP[focusModel.toLowerCase()] || CPU_MINUTES_PER_FOCUSED_GAP.medium;
  }
  return {
    minutes,
    label: `Estimated CPU runtime: ${formatMinutes(minutes)} for ${formatMinutes(effectiveDuration)} audio.`,
    caveat,
  };
}

function updateEtaStatus() {
  const eta = estimateRunMinutes();
  activeEtaSeconds = Math.max(0, eta.minutes * 60);
  const parts = [eta.label];
  if (eta.caveat) parts.push(`(${eta.caveat})`);
  $('etaStatus').textContent = parts.join(' ');
  if (!currentRun) {
    $('etaCountdown').textContent = activeEtaSeconds
      ? `Estimated runtime: ${formatMinutes(activeEtaSeconds / 60)}`
      : 'ETA not calculated.';
  }
}

function updateActiveCountdown(percent = 0) {
  if (!currentRun || !activeEtaSeconds) return;
  const elapsed = activeRunStartedAt ? (Date.now() / 1000) - activeRunStartedAt : 0;
  const byClock = activeEtaSeconds - elapsed;
  const pct = Math.max(0, Math.min(99, Number(percent || 0)));
  const byProgress = pct > 1 ? elapsed * ((100 - pct) / pct) : byClock;
  const remaining = Math.max(0, Math.min(byClock || byProgress, byProgress || byClock));
  $('etaCountdown').textContent = `ETA remaining: ${formatCountdown(remaining)} · estimated total ${formatMinutes(activeEtaSeconds / 60)}`;
}

function renderResourceStatus(resources) {
  if (!resources) return;
  $('statCores').textContent = `Host ${resources.cpu_cores ?? '?'} cores`;
  $('statCpu').textContent = `CPU ${resources.cpu_percent ?? 0}%`;
  $('statRam').textContent = `RAM ${resources.memory_percent ?? 0}% (${resources.memory_available_gb ?? '?'} of ${resources.memory_total_gb ?? '?'} GB free)`;
  $('statSwap').textContent = Number(resources.swap_total_gb || 0) > 0 ? `Swap ${resources.swap_percent ?? 0}%` : 'Swap unavailable';
}

function renderModelSelectors(models = []) {
  const firstPass = $('model');
  const focused = $('focusedModel');
  if (!firstPass || !focused) return;
  const seen = new Set();
  const entries = [];
  models.forEach((item) => {
    const name = String(item?.name || '').trim();
    if (!name || seen.has(name)) return;
    seen.add(name);
    const labels = [];
    if (item.cached) labels.push('cached');
    if (item.recommended_first_pass) labels.push('recommended first pass');
    if (item.recommended_focused) labels.push('recommended focused');
    entries.push({ name, label: labels.join(', ') });
  });
  const firstValue = firstPass.value || firstPass.dataset.selected || 'small';
  const focusedValue = focused.value || focused.dataset.selected || 'medium';
  const options = entries.map((item) => (
    `<option value="${escapeHtml(item.name)}">${escapeHtml(item.label ? `${item.name} (${item.label})` : item.name)}</option>`
  )).join('');
  firstPass.innerHTML = options;
  focused.innerHTML = `<option value="">reuse first pass</option>${options}`;
  firstPass.value = entries.some((item) => item.name === firstValue) ? firstValue : (entries[0]?.name || 'small');
  focused.value = focusedValue === '' || entries.some((item) => item.name === focusedValue) ? focusedValue : 'medium';
  if (!entries.length) {
    $('etaStatus').textContent = 'faster-whisper is not installed in this image -- detection will fail until it is. See the Whisper model field tooltip.';
  }
}

async function loadResourceStatus() {
  try {
    const res = await fetch('/api/chaptering/resources');
    const data = await res.json();
    if (res.ok) {
      renderResourceStatus(data);
      renderModelSelectors(data.asr_models || []);
      const cores = Number(data.cpu_cores || 0);
      if (cores > 0) $('cpuThreads').max = String(cores);
    }
  } catch (_error) {
    $('statCpu').textContent = 'Resource status unavailable.';
  }
}

async function loadLlmDefaultPrompt() {
  const el = $('llmDefaultPrompt');
  if (!el) return;
  try {
    const res = await fetch('/api/chaptering/llm-default-prompt');
    const data = await res.json();
    el.textContent = res.ok ? (data.instructions || '(empty)') : 'Failed to load default prompt.';
  } catch (_error) {
    el.textContent = 'Failed to load default prompt.';
  }
}

async function pollRun() {
  if (!currentRun) return;
  const res = await fetch(`/api/runs/${currentRun}`);
  const data = await res.json();
  if (!res.ok) {
    clearTimeout(pollTimer);
    return;
  }
  const pct = Math.max(0, Math.min(100, Number(data.percent || 0)));
  $('ring').style.setProperty('--pct', pct.toFixed(1));
  $('percent').textContent = `${pct.toFixed(1)}%`;
  $('phaseLabel').textContent = data.phase_label || data.status || 'Running';
  $('phaseDetail').textContent = data.phase_detail || '';
  $('tail').textContent = (data.tail || []).join('\n');
  if (data.stats?.resources) renderResourceStatus(data.stats.resources);
  if (data.stats?.phase_log) renderRunLog(data.stats.phase_log);
  updateActiveCountdown(pct);
  if (data.status === 'completed') {
    $('detectBtn').disabled = false;
    $('cancelBtn').disabled = true;
    applyResult(data);
    currentRun = null;
    $('etaCountdown').textContent = 'Run complete.';
    return;
  }
  if (data.status === 'failed' || data.status === 'cancelled') {
    $('detectBtn').disabled = false;
    $('cancelBtn').disabled = true;
    $('phaseDetail').textContent = data.error || data.phase_detail || data.status;
    currentRun = null;
    $('etaCountdown').textContent = 'Run stopped.';
    return;
  }
  pollTimer = setTimeout(pollRun, 2000);
}

async function cancelRun() {
  if (!currentRun) return;
  await fetch(`/api/runs/${currentRun}/cancel`, { method: 'POST' });
}

async function saveEdits() {
  collectRows();
  const res = await fetch('/api/chaptering/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_path: loaded?.source_path || $('sourcePath').value.trim(),
      duration: loaded?.duration || 0,
      settings: loaded?.result?.settings || {},
      chapters,
      segments: loaded?.result?.segments || [],
      save_full_transcript: $('saveFullTranscript').checked,
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Failed to save chapters');
    return;
  }
  applyResult(data);
  $('loadStatus').textContent = 'Chapter edits saved.';
}

function addChapter() {
  collectRows();
  const last = chapters[chapters.length - 1];
  const start = last ? Number(last.end || last.start || 0) : 0;
  chapters.push({
    id: chapters.length + 1,
    start,
    end: start + 300,
    title: `Chapter ${chapters.length + 1}`,
    confidence: null,
    reasons: ['manual'],
    manual: true,
  });
  renderChapters();
}

function insertChapterAfter(afterId) {
  const index = chapters.findIndex((c) => c.id === afterId);
  if (index < 0) return;
  const current = chapters[index];
  const next = chapters[index + 1];
  const currentEnd = Number(current.end || current.start || 0);
  const nextStart = next ? Number(next.start || 0) : currentEnd + 300;
  const start = next && nextStart > currentEnd
    ? currentEnd + Math.max(1, (nextStart - currentEnd) / 2)
    : currentEnd + 60;
  chapters.splice(index + 1, 0, {
    id: 0,
    start,
    end: next ? nextStart : start + 300,
    title: 'New chapter',
    confidence: null,
    reasons: ['manual'],
    manual: true,
  });
  renderChapters();
}

async function init() {
  const prefs = window.LibraForgePrefs?.get() || {};
  const libraryRoot = prefs.defaultRootPath || '/audiobooks';
  initFolderBrowser({
    inputEl: $('sourcePath'),
    datalistEl: $('sourceSuggestions'),
    browserEl: $('sourceBrowser'),
    browseBtnEl: $('sourceBrowseBtn'),
    listEl: $('sourceFbList'),
    breadcrumbEl: $('sourceFbBreadcrumb'),
    currentLabelEl: $('sourceFbCurrentLabel'),
    upBtnEl: $('sourceFbUp'),
    homeBtnEl: $('sourceFbHome'),
    closeBtnEl: $('sourceFbClose'),
    selectBtnEl: $('sourceFbSelect'),
    libraryRoot,
  });
  $('advancedRunToggle').addEventListener('click', () => {
    const open = $('advancedRunToggle').getAttribute('aria-expanded') === 'true';
    $('advancedRunToggle').setAttribute('aria-expanded', open ? 'false' : 'true');
    syncFieldVisibility();
  });
  document.querySelectorAll('input[name="backend"]').forEach((radio) => {
    radio.addEventListener('change', () => {
      syncFieldVisibility();
      updateEtaStatus();
    });
  });
  syncFieldVisibility();
  $('loadBtn').addEventListener('click', loadChapters);
  $('findCandidateBtn').addEventListener('click', findCandidate);
  $('detectBtn').addEventListener('click', startDetection);
  $('cancelBtn').addEventListener('click', cancelRun);
  $('saveBtn').addEventListener('click', saveEdits);
  $('addChapterBtn').addEventListener('click', addChapter);
  $('playAllBtn').addEventListener('click', togglePlayAll);
  $('cleanAllTitlesBtn').addEventListener('click', cleanAllTitles);
  $('confidenceMode').addEventListener('change', (event) => {
    confidenceMode = event.target.value;
    renderChapters();
  });
  $('promptMode').addEventListener('change', (event) => {
    promptMode = event.target.value;
  });
  $('flagFilterChip').addEventListener('click', () => {
    showOnlyFlagged = !showOnlyFlagged;
    renderChapters();
  });
  [
    'model', 'computeType', 'beamSize', 'vadFilter', 'focusedRescan',
    'focusedModel', 'focusedComputeType', 'focusedBeamSize', 'maxAudioMinutes',
  ].forEach((id) => {
    const el = $(id);
    if (el) el.addEventListener('input', updateEtaStatus);
    if (el) el.addEventListener('change', updateEtaStatus);
  });
  renderChapters();
  renderArtifacts({});
  updateEtaStatus();
  loadResourceStatus();
  loadLlmDefaultPrompt();
}

document.addEventListener('DOMContentLoaded', init);
