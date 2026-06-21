let currentRun = null;
let pollTimer = null;
let latestMoveItems = [];

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
const { escapeHtml, renderDownloadLinks, statCard: stat } = window.UiCommon;

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

function collectRequest() {
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
    progress_every: parseInt($('progressEvery').value || '25', 10),
  };
}

async function startRun() {
  const req = collectRequest();
  if (req.apply) {
    const ok = confirm('This run will move files or folders. Continue?');
    if (!ok) return;
  }

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
  render(state);
  if (['completed', 'failed', 'cancelled'].includes(state.status)) {
    clearInterval(pollTimer);
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
  renderStats(stats);
  latestMoveItems = stats.move_items || [];
  renderRisks(latestMoveItems);
  renderMoves(latestMoveItems);
}

function renderStats(stats) {
  const reviewItems = (stats.move_items || []).filter(isReviewMove).length;
  $('stats').innerHTML = [
    stat('Found Items', stats.found_items, 'Organizer items scanned after filtering.'),
    stat('Ignored MP3', stats.ignored_mp3_files, 'MP3 files skipped outside organizer processing.'),
    stat("Skipped Unknown", stats.skipped_unknown_author, "Items without author metadata, blocked by default."),
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

function renderMoves(items) {
  const query = $("moveSearch").value.trim().toLowerCase();
  const reviewOnly = $("reviewOnly").checked;
  const filtered = items.filter((item) => {
    if (reviewOnly && !isReviewMove(item)) return false;
    if (!query) return true;
    return [item.title, item.author, item.series, item.number, item.source, item.target]
      .some((value) => String(value || "").toLowerCase().includes(query));
  });

  $("moveCount").textContent = `Showing ${filtered.length} of ${items.length} planned moves`;
  $("moveItems").innerHTML = filtered.length
    ? filtered.map((item) => `
      <article class="result-card ${isReviewMove(item) ? "review-card" : ""}">
        <div class="result-head">
          <div>
            <h3>${escapeHtml(item.title || "Unknown Title")}</h3>
            <p>${escapeHtml(item.author || "Unknown Author")}</p>
          </div>
          <div class="score-badge">${escapeHtml(String(item.files || 1))} file${Number(item.files || 1) === 1 ? "" : "s"}</div>
          <span>Structure: ${escapeHtml(item.structure || "new")}</span>
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
    `).join("")
    : `<p class="note">${items.length ? "No moves match the current filters." : "No planned moves were parsed from this run."}</p>`;
}

$("moveSearch").addEventListener("input", () => renderMoves(latestMoveItems));
$("reviewOnly").addEventListener("change", () => renderMoves(latestMoveItems));

$('startBtn').addEventListener('click', startRun);
$('cancelBtn').addEventListener('click', cancelRun);
loadScripts();
