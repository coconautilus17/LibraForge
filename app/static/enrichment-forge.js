const $ = (id) => document.getElementById(id);
const { escapeHtml } = window.UiCommon;

let currentBooks = [];
let currentSeriesName = "";
let currentSourceStatus = {};

async function searchSeries(query) {
  const res = await fetch(`/api/enrichment/series?q=${encodeURIComponent(query)}`).catch(() => null);
  if (!res || !res.ok) return [];
  const data = await res.json();
  return data.series || [];
}

function renderSeriesResults(rows) {
  const container = $("seriesResults");
  if (!rows.length) {
    container.innerHTML = "";
    return;
  }
  container.innerHTML = rows.map((row) => `
    <div class="series-result-row" data-name="${escapeHtml(row.name)}" data-key="${escapeHtml(row.key || "")}">
      <span class="series-result-name">${escapeHtml(row.name)}</span>
      <span class="series-result-count">${row.book_count} books</span>
    </div>
  `).join("");
  container.querySelectorAll(".series-result-row").forEach((el) => {
    el.addEventListener("click", () => {
      $("seriesSearch").value = el.dataset.name;
      container.innerHTML = "";
      compileSeries(el.dataset.name, el.dataset.key);
    });
  });
}

function renderGenreChips(genres) {
  const container = $("genreChips");
  container.innerHTML = genres.map((g) => `
    <span class="badge chip" data-genre="${escapeHtml(g)}">${escapeHtml(g)} <button type="button" class="chip-remove" aria-label="Remove ${escapeHtml(g)}">&times;</button></span>
  `).join("");
  container.querySelectorAll(".chip-remove").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.target.closest("[data-genre]").remove();
    });
  });
}

function currentGenreList() {
  return Array.from($("genreChips").querySelectorAll("[data-genre]")).map((el) => el.dataset.genre);
}

function addGenreChip(value) {
  const trimmed = value.trim();
  if (!trimmed) return;
  const existing = currentGenreList();
  if (existing.some((g) => g.toLowerCase() === trimmed.toLowerCase())) return;
  renderGenreChips([...existing, trimmed]);
}

function renderBookList(books) {
  $("bookList").innerHTML = books.map((book) => {
    // Items with no audio (placeholders, ebooks) come back excluded by default (#301).
    const included = book.default_include !== false;
    const grExplicit = book.goodreads_explicit && book.goodreads_explicit.significant;
    return `
    <div class="book-row${included ? "" : " excluded"}" data-id="${escapeHtml(book.id)}">
      <div class="book-main">
        <div class="book-title">${escapeHtml(book.title)}</div>
        <div class="book-src-line">
          <span class="audible">Audible: ${escapeHtml(book.audible_genres.join(", ") || "none")}</span>
          &nbsp;&middot;&nbsp;
          <span class="goodreads">Goodreads: ${escapeHtml(book.goodreads_genres.join(", ") || "none")}</span>
        </div>
        <div class="book-src-line">
          <span class="local">Current genres: ${escapeHtml((book.existing_genres || []).join(", ") || "none")}</span>
          &nbsp;&middot;&nbsp;
          <span class="local">Tags: ${escapeHtml((book.existing_tags || []).join(", ") || "none")}</span>
        </div>
      </div>
      ${book.has_audio === false ? '<span class="badge evidence-pill" title="No audio files: not searched, excluded by default">No audio</span>' : ""}
      ${book.flagged_explicit ? '<span class="badge evidence-pill">&#9888; Erotica</span>' : ""}
      ${grExplicit ? `<span class="badge evidence-pill" title="Goodreads readers shelved this as erotica/smut/nsfw">&#9888; Goodreads explicit shelves &times;${book.goodreads_explicit.votes}</span>` : ""}
      <button type="button" class="secondary include-toggle${included ? " in" : ""}" data-included="${included}">${included ? "In" : "Excluded"}</button>
    </div>
  `;
  }).join("");

  $("bookList").querySelectorAll(".include-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const included = btn.dataset.included === "true";
      btn.dataset.included = included ? "false" : "true";
      btn.textContent = included ? "Excluded" : "In";
      btn.classList.toggle("in", !included);
      btn.closest(".book-row").classList.toggle("excluded", included);
      updateIncludedCount();
    });
  });
}

function updateIncludedCount() {
  const rows = $("bookList").querySelectorAll(".book-row");
  const included = Array.from(rows).filter((row) => row.querySelector(".include-toggle").dataset.included === "true");
  $("includedCount").textContent = `${included.length} of ${rows.length} included`;
}

function sourceChipHtml(key, status, total) {
  if (!status) return "";
  const searched = Number(status.searched || 0);
  let state = "not used";
  if (status.state === "searched") {
    state = key === "goodreads" && status.found !== undefined
      ? `found ${Number(status.found || 0)} of ${searched} searched`
      : `${searched} of ${total} searched`;
    if (Number(status.failed || 0)) state += `, ${status.failed} failed`;
    if (status.rate_limited) state += ", rate-limited, paused";
  }
  const detail = status.detail ? ` title="${escapeHtml(status.detail)}"` : "";
  return `<span class="source-chip ${key} ${status.state || ""}"${detail}><span class="dot"></span> ${escapeHtml(status.label || key)}, ${state}</span>`;
}

function renderSourceStrip(sourceStatus, totalCount, elapsedSeconds) {
  const chips = ["audible", "goodreads"]
    .map((key) => sourceChipHtml(key, sourceStatus[key], totalCount))
    .filter(Boolean);
  $("sourceStrip").innerHTML = `
    ${chips.join('<span class="sep"></span>')}
    <span class="time">${elapsedSeconds}s</span>
  `;
}

const EXPLICIT_EVIDENCE_CAVEAT = "That doesn't confirm the rest are clean, the same signal has missed equally explicit books before, so use your own judgment for the whole series.";

function renderExplicitEvidence(note) {
  const caveatIndex = note.indexOf(EXPLICIT_EVIDENCE_CAVEAT);
  const body = caveatIndex === -1
    ? escapeHtml(note)
    : `<strong>${escapeHtml(note.slice(0, caveatIndex).trim())}</strong> ${escapeHtml(note.slice(caveatIndex))}`;
  $("explicitEvidence").innerHTML = `<span class="dot">&#9679;</span><span>${body}</span>`;
}

async function compileSeries(seriesName, seriesKey) {
  // Compile always reads the series from ABS first -- it's the mandatory
  // library source here. Audible is only an optional, better-quality search
  // source (the backend falls back to ABS's own Audible provider when direct
  // auth is missing), so gate on ABS specifically rather than "any provider".
  if (window.LibraForgeAuth && !(await window.LibraForgeAuth.ensureConnected("abs"))) {
    return;
  }
  currentSeriesName = seriesName;
  $("compileCard").hidden = false;
  $("compileSub").textContent = `${seriesName}, searching...`;
  $("sourceStrip").innerHTML = "";

  const startedAt = performance.now();
  const res = await fetch("/api/enrichment/compile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ series_name: seriesName, series_key: seriesKey || "" }),
  }).catch(() => null);

  if (!res || !res.ok) {
    const detail = res ? await res.json().then((d) => d.detail).catch(() => "") : "";
    $("compileSub").textContent = detail
      ? `Compile failed: ${detail}`
      : "Compile failed. Check that Audiobookshelf is reachable and configured.";
    return;
  }

  const data = await res.json();
  const elapsedSeconds = ((performance.now() - startedAt) / 1000).toFixed(1);
  currentBooks = data.books;
  currentSourceStatus = data.source_status || {};
  $("compileSub").textContent = `${seriesName}, ${data.books.length} books.`;
  renderSourceStrip(currentSourceStatus, data.books.length, elapsedSeconds);
  renderGenreChips(data.genre);
  // Narrators differ per book and edition, so nothing is pre-filled (#299).
  $("narratorInput").value = "";
  $("applyNarratorCheckbox").checked = false;
  $("narratorSuggestions").textContent = data.narrator ? `Narrators found across this series: ${data.narrator}` : "";
  $("explicitSelect").value = "";
  $("sequenceRangeInput").value = data.sequence_range;
  renderExplicitEvidence(data.explicit_evidence_note);
  renderBookList(data.books);
  updateIncludedCount();
}

async function applyEnrichment() {
  const rows = $("bookList").querySelectorAll(".book-row");
  const books = Array.from(rows).map((row) => {
    const book = currentBooks.find((b) => b.id === row.dataset.id);
    return {
      id: row.dataset.id,
      path: book.path,
      is_file: book.is_file,
      title: book.title,
      include: row.querySelector(".include-toggle").dataset.included === "true",
    };
  });
  const explicitValue = $("explicitSelect").value;

  const res = await fetch("/api/enrichment/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      books,
      genre: currentGenreList(),
      narrator: $("narratorInput").value,
      apply_narrator: $("applyNarratorCheckbox").checked,
      explicit: explicitValue === "" ? null : explicitValue === "true",
    }),
  }).catch(() => null);

  if (!res || !res.ok) {
    const detail = res ? await res.json().then((d) => d.detail).catch(() => "") : "";
    $("compileSub").textContent = `Apply failed${detail ? `: ${detail}` : ". Check that Audiobookshelf is reachable."}`;
    return;
  }
  const data = await res.json();
  const parts = [`Applied to ${data.applied} book${data.applied === 1 ? "" : "s"}.`];
  const legacy = data.legacy_json || {};
  const merged = legacy.consolidated_then_deleted || 0;
  const removed = (legacy.deleted_identical || 0) + (legacy.deleted_abs_newer || 0) + merged;
  if (removed > 0) {
    parts.push(`Removed ${removed} old metadata.json file${removed === 1 ? "" : "s"}${merged ? ` (${merged} merged into Audiobookshelf first)` : ""}.`);
  }
  if (data.failed && data.failed.length) {
    parts.push(`${data.failed.length} failed: ${data.failed.map((f) => `${f.title || f.path} (${f.error})`).join("; ")}`);
  }
  $("compileSub").textContent = parts.join(" ");
}

let searchDebounce = null;
$("seriesSearch").addEventListener("input", (e) => {
  clearTimeout(searchDebounce);
  const query = e.target.value.trim();
  if (!query) {
    renderSeriesResults([]);
    return;
  }
  searchDebounce = setTimeout(async () => {
    // The page-load redirect (ui-common.js) only fires once per notice --
    // it won't re-trigger on a later visit once dismissed. Every search
    // still hits /api/enrichment/series, which needs ABS just like compile
    // does, so re-check live here too instead of silently 400ing.
    if (window.LibraForgeAuth && !(await window.LibraForgeAuth.ensureConnected("abs"))) {
      return;
    }
    renderSeriesResults(await searchSeries(query));
  }, 250);
});

$("cancelBtn").addEventListener("click", () => {
  $("compileCard").hidden = true;
});
$("applyBtn").addEventListener("click", applyEnrichment);

$("genreAddBtn").addEventListener("click", () => {
  addGenreChip($("genreAddInput").value);
  $("genreAddInput").value = "";
});
$("genreAddInput").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  e.preventDefault();
  addGenreChip($("genreAddInput").value);
  $("genreAddInput").value = "";
});
