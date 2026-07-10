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
    <div class="series-result-row" data-name="${escapeHtml(row.name)}" style="display:flex;justify-content:space-between;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);margin-bottom:6px;cursor:pointer">
      <span>${escapeHtml(row.name)}</span>
      <span style="color:var(--muted);font-size:12.5px">${row.book_count} books</span>
    </div>
  `).join("");
  container.querySelectorAll(".series-result-row").forEach((el) => {
    el.addEventListener("click", () => compileSeries(el.dataset.name));
  });
}

function renderGenreChips(genres) {
  const container = $("genreChips");
  container.innerHTML = genres.map((g) => `
    <span class="badge" data-genre="${escapeHtml(g)}">${escapeHtml(g)} <button type="button" class="chip-remove" aria-label="Remove ${escapeHtml(g)}">&times;</button></span>
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

function renderBookList(books) {
  $("bookList").innerHTML = books.map((book) => `
    <div class="book-row" data-id="${escapeHtml(book.id)}" style="display:flex;align-items:center;gap:10px;padding:9px 11px;border:1px solid var(--border);border-radius:var(--radius-sm)">
      <div style="flex:1;min-width:0">
        <div style="font-weight:650;font-size:14px">${escapeHtml(book.title)}</div>
        <div style="font-size:12px;color:var(--muted)">
          Audible: ${escapeHtml(book.audible_genres.join(", ") || "none")}
          &nbsp;&middot;&nbsp;
          Goodreads: ${escapeHtml(book.goodreads_genres.join(", ") || "none")}
        </div>
      </div>
      ${book.flagged_explicit ? '<span class="badge" style="background:var(--warning-soft);color:var(--warning)">Erotica</span>' : ""}
      <button type="button" class="secondary include-toggle" data-included="true">In</button>
    </div>
  `).join("");

  $("bookList").querySelectorAll(".include-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const included = btn.dataset.included === "true";
      btn.dataset.included = included ? "false" : "true";
      btn.textContent = included ? "Excluded" : "In";
      btn.closest(".book-row").style.opacity = included ? "0.5" : "1";
      updateIncludedCount();
    });
  });
}

function updateIncludedCount() {
  const rows = $("bookList").querySelectorAll(".book-row");
  const included = Array.from(rows).filter((row) => row.querySelector(".include-toggle").dataset.included === "true");
  $("includedCount").textContent = `${included.length} of ${rows.length} included`;
}

async function compileSeries(seriesName) {
  currentSeriesName = seriesName;
  $("compileCard").hidden = false;
  $("compileTitle").textContent = `2. Compiled from Audible + Goodreads`;
  $("compileSub").textContent = `${seriesName}, searching...`;

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
  currentBooks = data.books;
  $("compileSub").textContent = `${seriesName}, ${data.books.length} books.`;
  renderGenreChips(data.genre);
  $("narratorInput").value = data.narrator;
  $("explicitEvidence").textContent = data.explicit_evidence_note;
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
    $("compileSub").textContent = `Applied to ${data.applied} books.`;
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
