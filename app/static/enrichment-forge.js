const $ = (id) => document.getElementById(id);
const { escapeHtml } = window.UiCommon;

let currentBooks = [];
let currentSeriesName = "";
let currentSourceStatus = {};
let currentEvidence = {};
let pinnedGenres = new Set();
let mainVocabulary = [];

// Display names for the evidence sources the compile reports per genre and per book.
const SOURCE_LABELS = {
  audible: "Audible",
  goodreads: "Goodreads",
  audiosilo: "AudioSilo",
  openlibrary: "Open Library",
  keywords: "Keywords in descriptions",
  file_tags: "File tags",
  abs_existing: "Current ABS genres/tags",
  yours: "Set by you in Audiobookshelf",
  "series-source": "Series list",
  implied: "Implied by LitRPG / Cultivation",
  progressionfantasy: "progressionfantasy.co.uk",
  haremlit: "HaremLit wiki",
};
const BOOK_SOURCES = ["audible", "file_tags", "goodreads", "audiosilo", "openlibrary", "keywords", "abs_existing"];
const SERIES_SOURCES = ["progressionfantasy", "haremlit"];

// Source labels arrive normalized to lowercase; a few need their real casing back.
const LABEL_CASING = { litrpg: "LitRPG", gamelit: "GameLit", haremlit: "HaremLit" };

function titleCase(label) {
  const text = String(label);
  return LABEL_CASING[text] || text.replace(/(^|[\s-])([a-z])/g, (m, sep, ch) => sep + ch.toUpperCase());
}

function evidenceText(genre) {
  const ev = currentEvidence[genre];
  if (!ev || !Object.keys(ev).length) return "Added by you";
  const parts = Object.entries(ev)
    .sort((a, b) => b[1] - a[1])
    .map(([src, n]) => (["series-source", "implied", "yours"].includes(src) ? SOURCE_LABELS[src] : `${SOURCE_LABELS[src] || src} ×${n}`));
  return `Supported by ${parts.join(", ")}`;
}

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
      ${row.standalone
        ? '<span class="badge standalone-badge">Standalone</span>'
        : `<span class="series-result-count">${row.book_count} book${row.book_count === 1 ? "" : "s"}</span>`}
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

function renderGenreChips(containerId, genres) {
  const container = $(containerId);
  container.innerHTML = genres.map((g) => {
    const sources = Object.keys(currentEvidence[g] || {}).filter((src) => src !== "yours").length;
    const pinned = pinnedGenres.has(g);
    return `
    <span class="badge chip${pinned ? " pinned" : ""}" data-genre="${escapeHtml(g)}" title="${escapeHtml(evidenceText(g))}">${pinned ? '<span class="chip-yours">yours</span> ' : ""}${escapeHtml(g)}${sources ? ` <span class="chip-support" aria-label="${sources} sources">${sources}</span>` : ""} <button type="button" class="chip-remove" aria-label="Remove ${escapeHtml(g)}">&times;</button></span>
  `;
  }).join("");
  container.querySelectorAll(".chip-remove").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.target.closest("[data-genre]").remove();
      renderSuggestions();
    });
  });
}

function chipValues(containerId) {
  return Array.from($(containerId).querySelectorAll("[data-genre]")).map((el) => el.dataset.genre);
}

// Main genres first, then subgenres: the order they are written to Audiobookshelf.
function currentGenreList() {
  return [...chipValues("mainGenreChips"), ...chipValues("subGenreChips")];
}

function addGenreChip(value) {
  const trimmed = value.trim();
  if (!trimmed) return;
  const same = (g) => g.toLowerCase() === trimmed.toLowerCase();
  const main = mainVocabulary.find(same);
  if (chipValues("mainGenreChips").some(same)) return;
  if (main) {
    // A main-genre name typed while it sits in Subgenres moves it up.
    renderGenreChips("subGenreChips", chipValues("subGenreChips").filter((g) => !same(g)));
    renderGenreChips("mainGenreChips", [...chipValues("mainGenreChips"), main]);
  } else if (chipValues("subGenreChips").some(same)) {
    return;
  } else {
    renderGenreChips("subGenreChips", [...chipValues("subGenreChips"), trimmed]);
  }
  renderSuggestions();
}

let currentSuggestions = [];

// Every other genre any source suggested, one click to add.
function renderSuggestions() {
  const present = new Set(currentGenreList().map((g) => g.toLowerCase()));
  const left = currentSuggestions.filter((g) => !present.has(g.toLowerCase()));
  $("otherSuggestions").innerHTML = left.length
    ? `<span class="suggestions-label">Other suggestions:</span> ${left.map((g) => `<button type="button" class="suggestion" data-genre="${escapeHtml(g)}">+ ${escapeHtml(g)}</button>`).join(" ")}`
    : "";
  $("otherSuggestions").querySelectorAll(".suggestion").forEach((btn) => {
    btn.addEventListener("click", () => addGenreChip(btn.dataset.genre));
  });
}

function renderBookList(books) {
  $("bookList").innerHTML = books.map((book) => {
    // Items with no audio (placeholders, ebooks) come back excluded by default (#301).
    const included = book.default_include !== false;
    const grExplicit = book.goodreads_explicit && book.goodreads_explicit.significant;
    const sources = book.sources || {};
    const sourceParts = BOOK_SOURCES.filter((key) => (sources[key] || []).length)
      .map((key) => `<span class="src src-${key}">${escapeHtml(SOURCE_LABELS[key])}: ${escapeHtml(sources[key].map(titleCase).join(", "))}</span>`);
    return `
    <div class="book-row${included ? "" : " excluded"}" data-id="${escapeHtml(book.id)}">
      <div class="book-main">
        <div class="book-title">${escapeHtml(book.title)}</div>
        ${book.has_audio === false ? "" : `<div class="book-src-line"><strong>Book vote:</strong> ${escapeHtml((book.book_main || []).join(", ") || "no agreement")}${(book.manual_genres || []).length ? ` &nbsp;&middot;&nbsp; <strong>Set by you:</strong> ${escapeHtml(book.manual_genres.join(", "))}` : ""}</div>`}
        <div class="book-src-line">
          ${sourceParts.join(" &nbsp;&middot;&nbsp; ") || '<span class="local">No source found this book</span>'}
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

function sourceChipHtml(key, status) {
  if (!status) return "";
  const searched = Number(status.searched || 0);
  let state = status.state === "failed" ? "failed" : "not used";
  if (status.state === "searched") {
    if (SERIES_SOURCES.includes(key)) {
      state = Number(status.found || 0) ? "series listed" : (status.rate_limited ? "paused" : "not listed");
    } else {
      state = `found ${Number(status.found || 0)} of ${searched}`;
    }
    if (Number(status.failed || 0)) state += `, ${status.failed} failed`;
    if (status.rate_limited && !SERIES_SOURCES.includes(key)) state += ", rate-limited, paused";
  }
  const cls = status.state === "searched" && (status.rate_limited || Number(status.failed || 0)) ? "degraded" : (status.state || "").replace(/\s+/g, "-");
  const detail = status.detail ? ` title="${escapeHtml(status.detail)}"` : "";
  return `<span class="source-chip ${key} ${cls}"${detail}><span class="dot"></span> ${escapeHtml(status.label || SOURCE_LABELS[key] || key)}, ${state}</span>`;
}

function renderSourceStrip(sourceStatus, totalCount, elapsedSeconds) {
  const chips = ["audible", "goodreads", "audiosilo", "openlibrary", ...SERIES_SOURCES]
    .map((key) => sourceChipHtml(key, sourceStatus[key]))
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
  $("compileSub").textContent = `${seriesName}, ${data.books.length} book${data.books.length === 1 ? "" : "s"}.`;
  renderSourceStrip(currentSourceStatus, data.books.length, elapsedSeconds);
  currentEvidence = data.genre_evidence || {};
  pinnedGenres = new Set(data.pinned_genres || []);
  mainVocabulary = data.main_vocabulary || [];
  const agreed = data.agreement !== "none";
  // With no agreement the backend returns every suggestion in `genre`; they
  // are offered as subgenres so nothing is presented as a confirmed main genre.
  renderGenreChips("mainGenreChips", agreed ? (data.main_genres || []) : []);
  renderGenreChips("subGenreChips", agreed ? (data.sub_genres || []) : data.genre);
  currentSuggestions = data.genre_suggestions || [];
  renderSuggestions();
  $("agreementNotice").hidden = agreed;
  $("agreementNotice").innerHTML = agreed ? "" : `<span class="dot">&#9679;</span><span><strong>No genre reached agreement across the sources for this ${data.standalone ? "book" : "series"}.</strong> The subgenres below are every genre any source suggested; keep the ones that fit. Type a genre like Fantasy or Thriller into Add to make it a main genre.</span>`;
  $("seriesEvidence").textContent = (data.series_evidence || []).length ? `Series lists: ${data.series_evidence.join(" · ")}` : "";
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
  const kept = Object.entries(legacy).filter(([action]) => action.startsWith("kept_")).reduce((sum, [, n]) => sum + n, 0);
  if (kept > 0) {
    parts.push(`Warning: ${kept} old metadata.json file${kept === 1 ? "" : "s"} could not be removed; Audiobookshelf may undo ${kept === 1 ? "that book's" : "those books'"} changes on its next scan. Check ${kept === 1 ? "the file is" : "the files are"} readable and writable.`);
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
