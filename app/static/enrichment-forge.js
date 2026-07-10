const $ = (id) => document.getElementById(id);
const { escapeHtml } = window.UiCommon;

let currentBooks = [];
let currentSeriesName = "";

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
    <div class="series-result-row" data-name="${escapeHtml(row.name)}">
      <span class="series-result-name">${escapeHtml(row.name)}</span>
      <span class="series-result-count">${row.book_count} books</span>
    </div>
  `).join("");
  container.querySelectorAll(".series-result-row").forEach((el) => {
    el.addEventListener("click", () => {
      container.querySelectorAll(".series-result-row.picked").forEach((picked) => picked.classList.remove("picked"));
      el.classList.add("picked");
      compileSeries(el.dataset.name);
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
  $("bookList").innerHTML = books.map((book) => `
    <div class="book-row" data-id="${escapeHtml(book.id)}">
      <div class="book-main">
        <div class="book-title">${escapeHtml(book.title)}</div>
        <div class="book-src-line">
          <span class="audible">Audible: ${escapeHtml(book.audible_genres.join(", ") || "none")}</span>
          &nbsp;&middot;&nbsp;
          <span class="goodreads">Goodreads: ${escapeHtml(book.goodreads_genres.join(", ") || "none")}</span>
        </div>
      </div>
      ${book.flagged_explicit ? '<span class="badge evidence-pill">&#9888; Erotica</span>' : ""}
      <button type="button" class="secondary include-toggle in" data-included="true">In</button>
    </div>
  `).join("");

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

function renderSourceStrip(searchedCount, elapsedSeconds) {
  $("sourceStrip").innerHTML = `
    <span class="source-chip audible"><span class="dot"></span> Audible, ${searchedCount} of ${searchedCount} searched</span>
    <span class="sep"></span>
    <span class="source-chip goodreads"><span class="dot"></span> Goodreads, ${searchedCount} of ${searchedCount} searched</span>
    <span class="time">${elapsedSeconds}s</span>
  `;
}

function renderExplicitEvidence(note) {
  $("explicitEvidence").innerHTML = `<span class="dot">&#9679;</span><span>${escapeHtml(note)}</span>`;
}

async function compileSeries(seriesName) {
  currentSeriesName = seriesName;
  $("compileCard").hidden = false;
  $("compileSub").textContent = `${seriesName}, searching...`;
  $("sourceStrip").innerHTML = "";

  const startedAt = performance.now();
  const res = await fetch("/api/enrichment/compile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ series_name: seriesName }),
  }).catch(() => null);

  if (!res || !res.ok) {
    $("compileSub").textContent = "Compile failed. Check that Audiobookshelf and Audible auth are configured.";
    return;
  }

  const data = await res.json();
  const elapsedSeconds = ((performance.now() - startedAt) / 1000).toFixed(1);
  currentBooks = data.books;
  $("compileSub").textContent = `${seriesName}, ${data.books.length} books.`;
  renderSourceStrip(data.books.length, elapsedSeconds);
  renderGenreChips(data.genre);
  $("narratorInput").value = data.narrator;
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
      include: row.querySelector(".include-toggle").dataset.included === "true",
    };
  });

  const res = await fetch("/api/enrichment/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      books,
      genre: currentGenreList(),
      narrator: $("narratorInput").value,
      explicit: $("explicitCheckbox").checked,
    }),
  }).catch(() => null);

  if (res && res.ok) {
    const data = await res.json();
    if (data.failed && data.failed.length) {
      $("compileSub").textContent = `Applied to ${data.applied} books. ${data.failed.length} failed.`;
    } else {
      $("compileSub").textContent = `Applied to ${data.applied} books.`;
    }
  }
}

let searchDebounce = null;
$("seriesSearch").addEventListener("input", (e) => {
  clearTimeout(searchDebounce);
  const query = e.target.value.trim();
  searchDebounce = setTimeout(async () => {
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
