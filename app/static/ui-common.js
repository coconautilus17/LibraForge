(() => {
  function escapeHtml(value) {
    return String(value).replace(
      /[&<>'"]/g,
      (character) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "'": "&#39;",
        '"': "&quot;",
      })[character],
    );
  }

  function renderDownloadLinks(target, downloads = {}) {
    const links = [];
    if (downloads.log) links.push(`<a href="${downloads.log}">Download output log</a>`);
    if (downloads.report) links.push(`<a href="${downloads.report}">Download JSON report</a>`);
    target.innerHTML = links.join(" · ");
  }

  function statCard(label, value, help) {
    return `<div class="stat"><small>${label}</small><strong>${value ?? 0}</strong><small>${help || ""}</small></div>`;
  }

  // Redirect to the Settings Accounts section if neither an Audible account
  // nor an ABS connection is configured, unless the user explicitly skipped
  // setup or debug mode is on. See CONNECTION_NOTICE_KEY below for how this
  // avoids re-nagging on every page load.
  const _AUTH_PAGES = new Set(["fixer", "m4b-tool"]);
  const _page = document.body.dataset.page;
  function _isDebugMode() {
    try { return JSON.parse(localStorage.getItem("libraforge-preferences") || "{}").debugMode === true; } catch { return false; }
  }

  const CONNECTION_NOTICE_KEY = "libraforge-connection-notice-shown";
  function _hasShownConnectionNotice() {
    try { return localStorage.getItem(CONNECTION_NOTICE_KEY) === "1"; } catch { return false; }
  }
  function _markConnectionNoticeShown() {
    try { localStorage.setItem(CONNECTION_NOTICE_KEY, "1"); } catch { /* ignore */ }
  }

  // ABS reachability — checked once on load, result shared across the page.
  let _absStatus = { configured: false, reachable: false };
  const _absStatusReady = fetch("/api/abs/status")
    .then((r) => r.json())
    .then((d) => { _absStatus = d; })
    .catch(() => {});

  async function checkAbsReachable() {
    await _absStatusReady;
    return _absStatus.reachable;
  }

  function isAbsConfigured() { return _absStatus.configured; }

  async function getConnectionState() {
    // Always fetch both live -- must NOT reuse the page-load-cached
    // _absStatusReady/_absStatus here. Those are captured once when this
    // script first executes and are never refreshed for the page's
    // lifetime; if the browser restores the page from back/forward cache
    // (bfcache) after the user navigates away and back, that stale
    // in-memory value survives even though the server-side connection
    // state may have changed since, producing a false "still connected".
    const [authData, absData] = await Promise.all([
      fetch("/api/auth/status").then((r) => r.json()).catch(() => ({ auth_ok: false })),
      fetch("/api/abs/status").then((r) => r.json()).catch(() => ({ configured: false })),
    ]);
    return { audible: Boolean(authData.auth_ok), abs: Boolean(absData.configured) };
  }

  async function _isAnyProviderConnected() {
    const state = await getConnectionState();
    return state.audible || state.abs;
  }

  // Shared entry point other pages can call right before an action that
  // actually needs a provider (e.g. starting a Metadata Forge run, or the
  // m4b-tool/Enrichment Forge/Library actions below). Unlike the silent
  // page-load check below, this always re-checks live and always redirects
  // (with the explanatory notice) if the requirement still isn't met, even
  // if the notice was already shown once before. "Skip for now" only
  // suppresses the passive page-load nag (below) -- it can NOT bypass this
  // check, since these actions genuinely cannot work without their provider.
  //
  // `require` narrows what counts as "connected": some actions work with
  // either provider ("any", the default), but some have a hard dependency
  // on one specific provider regardless of the other:
  //   - "audible": e.g. Load my library -- lists Audible purchases directly,
  //     no ABS equivalent exists.
  //   - "abs": e.g. Enrichment Forge compile -- ABS is the mandatory library
  //     source; Audible is only an optional, better-quality search source.
  async function ensureConnected(require = "any") {
    if (_isDebugMode()) return true;
    const state = await getConnectionState();
    const ok = require === "audible" ? state.audible
      : require === "abs" ? state.abs
      : (state.audible || state.abs);
    if (!ok) {
      _markConnectionNoticeShown();
      const params = new URLSearchParams({ authRequired: "1" });
      if (require !== "any") params.set("require", require);
      window.location.href = `/settings?${params.toString()}#accounts`;
      return false;
    }
    return true;
  }
  window.LibraForgeAuth = { ensureConnected, getConnectionState };

  if (_AUTH_PAGES.has(_page) && !sessionStorage.getItem("audible-skipped") && !_isDebugMode() && !_hasShownConnectionNotice()) {
    _isAnyProviderConnected().then((connected) => {
      if (!connected) {
        _markConnectionNoticeShown();
        window.location.href = "/settings?authRequired=1#accounts";
      }
    });
  }

  let _absAggRequiredParams = {};
  let _absAggReachable = false;

  async function loadAbsAggProviders(selectEl) {
    try {
      const res = await fetch("/api/abs-agg/providers");
      const data = await res.json();
      _absAggRequiredParams = data.required_params || {};
      _absAggReachable = data.reachable === true;
      Object.entries(data.providers || {}).forEach(([key, label]) => {
        const opt = document.createElement("option");
        opt.value = key;
        opt.textContent = label;
        selectEl.appendChild(opt);
      });
    } catch {}
  }

  function isAbsAggReachable() {
    return _absAggReachable;
  }

  function getAbsAggProviderParamHint(providerId) {
    const info = _absAggRequiredParams[providerId];
    if (!info) return null;
    const [param, example, description] = info;
    return { param, example, description, required: true };
  }

  async function loadAbsAggSettings() {
    try {
      const res = await fetch("/api/abs-agg/settings");
      return await res.json();
    } catch {
      return { url: "http://abs-agg:3000" };
    }
  }

  async function saveAbsAggUrl(url) {
    try {
      await fetch("/api/abs-agg/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
    } catch {}
  }

  async function searchAbsAgg({ query, author = "", provider, providerParams = "", baseUrl = "", limit = 10 }) {
    return fetch("/api/abs-agg/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        author,
        provider,
        provider_params: providerParams,
        limit,
        base_url: baseUrl,
      }),
    });
  }

  function scoreBadge(result) {
    if (result.score !== null && result.score !== undefined) {
      return Number(result.score).toFixed(2);
    }
    return result.abs_agg_provider || "abs-agg";
  }

  /**
   * initFolderBrowser({ inputEl, datalistEl, browserEl, browseBtnEl,
   *   listEl, breadcrumbEl, upBtnEl, homeBtnEl, closeBtnEl, selectBtnEl,
   *   currentLabelEl, libraryRoot, onSelect })
   *
   * Wires up path autocomplete and the folder browser panel.
   * onSelect(path) is called when the user clicks "Select this folder".
   */
  function initFolderBrowser({
    inputEl, datalistEl, browserEl, browseBtnEl,
    listEl, breadcrumbEl, upBtnEl, homeBtnEl, closeBtnEl, selectBtnEl,
    currentLabelEl, libraryRoot = "/audiobooks", onSelect = null,
  }) {
    let fbPath = libraryRoot;

    function esc(s) {
      return String(s).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[c]);
    }

    function fbNavigate(path) {
      fbPath = path;
      fetch(`/api/fs/ls?path=${encodeURIComponent(path)}`)
        .then(r => r.json())
        .then(data => { fbPath = data.path; renderBrowser(data.path, data.dirs || []); })
        .catch(() => renderBrowser(path, []));
    }

    function renderBrowser(currentPath, dirs) {
      const parts = currentPath.replace(/\/+$/, "").split("/").filter(Boolean);
      const segments = parts.map((seg, i) => {
        const p = "/" + parts.slice(0, i + 1).join("/");
        return `<button type="button" data-fbpath="${esc(p)}">${esc(seg)}</button>`;
      });
      breadcrumbEl.innerHTML = (parts.length === 0 ? "<span>/</span>" : "") + segments.join('<span class="fb-sep">/</span>');
      if (currentLabelEl) currentLabelEl.textContent = currentPath;
      if (dirs.length === 0) {
        listEl.innerHTML = '<li class="fb-empty" role="option">No subdirectories</li>';
      } else {
        listEl.innerHTML = dirs.map(d => {
          const name = d.split("/").pop();
          return `<li role="option" tabindex="0" data-fbpath="${esc(d)}">
            <span class="fb-item-icon" aria-hidden="true">📁</span>
            <span class="fb-item-name">${esc(name)}</span>
            <span class="fb-item-arrow" aria-hidden="true">›</span>
          </li>`;
        }).join("");
      }
    }

    listEl.addEventListener("click", e => {
      const li = e.target.closest("li[data-fbpath]");
      if (li) fbNavigate(li.dataset.fbpath);
    });
    listEl.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") {
        const li = e.target.closest("li[data-fbpath]");
        if (li) { e.preventDefault(); fbNavigate(li.dataset.fbpath); }
      }
    });
    breadcrumbEl.addEventListener("click", e => {
      const btn = e.target.closest("button[data-fbpath]");
      if (btn) fbNavigate(btn.dataset.fbpath);
    });

    const closeBrowser = () => {
      browserEl.hidden = true;
      if (browseBtnEl) browseBtnEl.setAttribute("aria-expanded", "false");
    };

    if (browseBtnEl) {
      browseBtnEl.addEventListener("click", () => {
        const open = !browserEl.hidden;
        browserEl.hidden = open;
        browseBtnEl.setAttribute("aria-expanded", String(!open));
        if (!open) fbNavigate(inputEl.value.trim() || fbPath || libraryRoot);
      });
    }
    if (closeBtnEl) closeBtnEl.addEventListener("click", closeBrowser);
    if (upBtnEl) upBtnEl.addEventListener("click", () => {
      fbNavigate(fbPath.replace(/\/[^/]+\/?$/, "") || "/");
    });
    if (homeBtnEl) homeBtnEl.addEventListener("click", () => fbNavigate(libraryRoot));
    if (selectBtnEl) selectBtnEl.addEventListener("click", () => {
      if (inputEl) inputEl.value = fbPath;
      if (onSelect) onSelect(fbPath);
      closeBrowser();
    });

    // Path autocomplete
    if (inputEl && datalistEl) {
      let lsTimer = null;
      inputEl.addEventListener("input", () => {
        clearTimeout(lsTimer);
        lsTimer = setTimeout(() => {
          const val = inputEl.value;
          const dir = val.endsWith("/") ? val : val.slice(0, val.lastIndexOf("/") + 1) || "/";
          fetch(`/api/fs/ls?path=${encodeURIComponent(dir)}`)
            .then(r => r.json())
            .then(data => {
              datalistEl.innerHTML = "";
              (data.dirs || []).filter(d => d.startsWith(val)).forEach(d => {
                const opt = document.createElement("option");
                opt.value = d;
                datalistEl.appendChild(opt);
              });
            })
            .catch(() => {});
        }, 180);
      });
    }

    return { navigate: fbNavigate, close: closeBrowser };
  }

  // Active-run persistence: remember the run id for a page so navigating away
  // or reloading can re-attach to a run that is still going in the background
  // (the server keeps the worker thread alive independent of the browser).
  const RUN_STORAGE_PREFIX = "libraforge:activeRun:";
  function saveActiveRun(pageKey, runId) {
    try { localStorage.setItem(RUN_STORAGE_PREFIX + pageKey, runId); } catch (_e) { /* private mode */ }
  }
  function clearActiveRun(pageKey) {
    try { localStorage.removeItem(RUN_STORAGE_PREFIX + pageKey); } catch (_e) { /* private mode */ }
  }
  function loadActiveRun(pageKey) {
    try { return localStorage.getItem(RUN_STORAGE_PREFIX + pageKey) || null; } catch (_e) { return null; }
  }

  // ---------------------------------------------------------------------------
  // Suspect report shared rendering
  // ---------------------------------------------------------------------------

  const SUSPECT_REASON_FIELDS = {
    title_mismatch: 'Title',
    series_mismatch: 'Series',
    author_mismatch: 'Author',
    sequence_conflict: 'Sequence',
    visible_number_conflict: 'Sequence',
    provider_missing_sequence: 'Sequence',
    organizer_source_number_conflict: 'Sequence',
    organizer_target_number_conflict: 'Sequence',
    duration_mismatch: 'Duration',
    low_score: 'Score',
    unsafe_match: 'Mode',
    series_only_mode: 'Mode',
    duplicate_asin: 'Duplicate',
    duplicate_local_identity: 'Duplicate',
    unknown_title: 'Title',
    unknown_author: 'Author',
    bitrate_in_title: 'Title',
    title_bracket_artifact: 'Title',
    title_has_redundant_series_prefix: 'Title',
    generic_omnibus_title: 'Title',
  };

  // Cross-item suspects (duplicate ASIN / duplicate author+series+sequence
  // across separate local files) have no single local/match pair -- the real
  // evidence is the list of related files in `related_paths` and the reason's
  // `evidence.titles`/`evidence.asin`. The normal compare-table render path
  // leaves these cards with an empty "(cross-item)" header and no rows, so
  // they get their own render path that lists the actual files involved.
  function buildCrossItemSuspectCard(item) {
    const sev = item.severity || 'info';
    const sevCls = `sev-${sev}`;
    const reasons = item.reasons || [];
    const relatedPaths = item.related_paths || [];
    const evidence = (reasons[0] && reasons[0].evidence) || {};
    const titles = (evidence.titles || []).filter(Boolean);
    const asin = evidence.asin || '';

    const headerLabel = titles.length ? titles.join(' / ')
      : (relatedPaths.length ? `${relatedPaths.length} related files` : '(cross-item)');

    const article = document.createElement('article');
    article.className = `mrep-card suspect-mrep-card ${sevCls}`;

    const details = document.createElement('details');
    details.className = 'mrep-details';

    const summary = document.createElement('summary');
    summary.className = 'mrep-head';
    summary.innerHTML = `
      <span class="suspect-sev-badge ${sevCls}">${escapeHtml(sev)}</span>
      <span class="mrep-title">${escapeHtml(headerLabel)}</span>
      <div class="mrep-badges">
        ${asin ? `<span class="match-provider-badge">ASIN ${escapeHtml(asin)}</span>` : ''}
        <span class="suspect-trigger-badge">${relatedPaths.length} file${relatedPaths.length === 1 ? '' : 's'}</span>
      </div>
    `;
    details.appendChild(summary);

    const body = document.createElement('div');
    body.className = 'mrep-body';

    const pathsHtml = relatedPaths.length
      ? relatedPaths.map((p) => {
          // Book identity usually lives in the folder name, not the filename
          // (e.g. "cover.m4b" repeated across every book) -- show the last
          // two segments so the two files can actually be told apart.
          const segments = p ? p.split('/').filter(Boolean) : [];
          const shown = segments.length ? segments.slice(-2).join('/') : '(unknown path)';
          return `<li title="${escapeHtml(p)}">${escapeHtml(shown)}</li>`;
        }).join('')
      : '<li>(no related files recorded)</li>';

    const reasonsHtml = reasons.map(r =>
      `<li><strong>${escapeHtml(r.code.replace(/_/g, ' '))}</strong>: ${escapeHtml(r.message)}</li>`
    ).join('');

    body.innerHTML = `
      <div class="suspect-cross-item-paths">
        <strong>Related files</strong>
        <ul>${pathsHtml}</ul>
      </div>
      <div class="suspect-reasons-section">
        <strong>Flags</strong>
        <ul>${reasonsHtml}</ul>
        <div class="suspect-recommendation">Recommendation: <em>${escapeHtml(item.recommendation || '')}</em></div>
      </div>
    `;

    details.appendChild(body);
    article.appendChild(details);
    return article;
  }

  function buildSeriesGroupCard(item) {
    const evidence = (item.reasons[0] && item.reasons[0].evidence) || {};
    const members = evidence.members || [];
    const isPassOne = item.reasons[0].code === 'series_group_missing';

    const article = document.createElement('article');
    article.className = 'mrep-card suspect-mrep-card sev-low series-group-card';
    article.dataset.seriesGroup = JSON.stringify({
      contextNote: item.reasons[0].message,
      authorNote: evidence.author_note || '',
      suggestedSeries: evidence.suggested_series || '',
      suggestedAuthor: evidence.suggested_author || '',
      suggestedGenre: evidence.suggested_genre || '',
      suggestedNarrator: evidence.suggested_narrator || '',
      members,
      taggedSiblings: evidence.tagged_siblings || [],
    });

    const details = document.createElement('details');
    details.className = 'mrep-details';
    const summary = document.createElement('summary');
    summary.className = 'mrep-head';
    summary.innerHTML = `
      <span class="suspect-sev-badge sev-low">${isPassOne ? 'no series' : 'series drift'}</span>
      <span class="mrep-title">${escapeHtml(evidence.suggested_series || '(series group)')}</span>
      <div class="mrep-badges">
        <span class="suspect-trigger-badge">${members.length} books</span>
      </div>
    `;
    details.appendChild(summary);

    const body = document.createElement('div');
    body.className = 'mrep-body';
    const memberRows = members.map((m) => `<li>${escapeHtml(m.title)}${m.flag ? ` <em>(${escapeHtml(m.flag.replace(/_/g, ' '))})</em>` : ''}</li>`).join('');
    body.innerHTML = `
      <p class="note">${escapeHtml(item.reasons[0].message)}</p>
      ${evidence.author_note ? `<p class="note fs-author-note">${escapeHtml(evidence.author_note)}</p>` : ''}
      <ul class="series-group-members">${memberRows}</ul>
      <div class="actions"><button type="button" class="secondary fs-open-btn">Fix Series</button></div>
    `;
    details.appendChild(body);
    article.appendChild(details);

    body.querySelector('.fs-open-btn').addEventListener('click', () => {
      if (window.FixSeries) window.FixSeries.open(JSON.parse(article.dataset.seriesGroup));
    });

    return article;
  }

  function buildSuspectCard(item) {
    if (item.status === 'cross_item') return buildCrossItemSuspectCard(item);
    if (item.status === 'series_group') return buildSeriesGroupCard(item);

    const sev = item.severity || 'info';
    const sevCls = `sev-${sev}`;
    const local = item.local || {};
    const match = item.match || {};
    const reasons = item.reasons || [];

    const flaggedFields = new Set(
      reasons.map(r => SUSPECT_REASON_FIELDS[r.code]).filter(Boolean)
    );
    const triggerLabels = [...new Set(reasons.map(r => SUSPECT_REASON_FIELDS[r.code]).filter(Boolean))];
    const triggerBadgesHtml = triggerLabels.map(l => `<span class="suspect-trigger-badge">${escapeHtml(l)}</span>`).join('');

    const pathName = item.path ? item.path.split('/').pop() : '(unknown)';
    const bookName = local.title || pathName;
    const scorePct = item.score != null && item.score > 0 ? Math.round(item.score * 100) : null;
    const providerLabel = item.provider || '';
    const writeAction = (item.write_action || '').replace(/_/g, ' ');

    const article = document.createElement('article');
    article.className = `mrep-card suspect-mrep-card ${sevCls}`;

    const details = document.createElement('details');
    details.className = 'mrep-details';

    const summary = document.createElement('summary');
    summary.className = 'mrep-head';
    summary.innerHTML = `
      <span class="suspect-sev-badge ${sevCls}">${escapeHtml(sev)}</span>
      ${writeAction ? `<span class="match-write-badge">${escapeHtml(writeAction)}</span>` : ''}
      <span class="mrep-title">${escapeHtml(bookName)}</span>
      <div class="mrep-badges">
        ${triggerBadgesHtml}
        ${scorePct != null ? `<span class="match-score-badge">${scorePct}%</span>` : ''}
        ${providerLabel ? `<span class="match-provider-badge">${escapeHtml(providerLabel)}</span>` : ''}
      </div>
    `;
    details.appendChild(summary);

    const body = document.createElement('div');
    body.className = 'mrep-body';

    const coverFolder = (item.path || '').replace(/\\/g, '/');
    const localCoverUrl = coverFolder ? `/api/book/cover?path=${encodeURIComponent(coverFolder)}` : '';
    const localCoverImg = localCoverUrl
      ? `<img class="cover-thumb" src="${escapeHtml(localCoverUrl)}" alt="Local cover" onerror="this.style.display='none'" loading="lazy">`
      : '<p class="note">No cover</p>';
    const matchCoverImg = match.cover_url
      ? `<img class="cover-thumb" src="${escapeHtml(match.cover_url)}" alt="Match cover" onerror="this.style.display='none'" loading="lazy">`
      : '<p class="note">No cover</p>';

    const providerHead = escapeHtml(providerLabel || 'Match');
    const titleMatch = match.title ? (match.title + (match.subtitle ? ': ' + match.subtitle : '')) : '';
    const localDur = local.duration_minutes != null ? `${local.duration_minutes} min` : '';
    const matchDur = match.duration_minutes != null ? `${match.duration_minutes} min` : '';
    const queryHtml = item.used_query
      ? `<div class="mrep-query">Query: <span>${escapeHtml(item.used_query)}</span></div>` : '';

    const isOrganizerItem = item.tool === 'organizer';
    const tableRows = isOrganizerItem
      ? [
          ['Title',    local.title,  ''],
          ['Author',   local.author, ''],
          ['Series',   local.series, ''],
          ['Sequence', local.sequence, ''],
          ['Source',   item.path || '', ''],
          ['Target',   local.target || '', ''],
          ['Metadata', local.metadata_source || '', ''],
        ].filter(([, lv]) => lv)
         .map(([label, lv]) => {
           const flagged = flaggedFields.has(label) ? ' suspect-flagged' : '';
           return `<tr class="${flagged}">
             <th>${escapeHtml(label)}</th>
             <td colspan="2">${escapeHtml(String(lv))}</td>
           </tr>`;
         }).join('')
      : [
          ['Title',    local.title,    titleMatch],
          ['Author',   local.author,   match.author],
          ['Narrator', local.narrator, match.narrator],
          ['Series',   local.series,   match.series],
          ['Sequence', local.sequence, match.sequence],
          ['Duration', localDur,       matchDur],
          ['Year',     '',             match.year],
          ['ASIN',     '',             match.asin],
        ].filter(([, lv, mv]) => lv || mv)
         .map(([label, lv, mv]) => {
           const flagged = flaggedFields.has(label) ? ' suspect-flagged' : '';
           return `<tr class="${flagged}">
             <th>${escapeHtml(label)}</th>
             <td>${escapeHtml(String(lv || '—'))}</td>
             <td>${escapeHtml(String(mv || '—'))}</td>
           </tr>`;
         }).join('');

    const reasonsHtml = reasons.map(r =>
      `<li><strong>${escapeHtml(r.code.replace(/_/g, ' '))}</strong>: ${escapeHtml(r.message)}</li>`
    ).join('');

    body.innerHTML = `
      <div class="cover-comparison mrep-covers">
        <div><strong>Local</strong>${localCoverImg}</div>
        <div><strong>${providerHead}</strong>${matchCoverImg}</div>
      </div>
      ${queryHtml}
      <table class="compare-table mrep-compare">
        <thead><tr><th></th>${isOrganizerItem ? '<th colspan="2">Organizer</th>' : `<th>Local</th><th>${escapeHtml(providerHead)}</th>`}</tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
      <div class="suspect-reasons-section">
        <strong>Flags</strong>
        <ul>${reasonsHtml}</ul>
        <div class="suspect-recommendation">Recommendation: <em>${escapeHtml(item.recommendation || '')}</em></div>
      </div>
    `;

    details.appendChild(body);
    article.appendChild(details);
    return article;
  }

  function renderSuspectReport(data, btnEl, widgetEl, listEl) {
    const suspects = data.suspects || [];
    const summary = data.summary || {};

    widgetEl.hidden = false;
    btnEl.disabled = false;
    btnEl.textContent = 'Hide Suspicion Report';

    listEl.innerHTML = '';

    if (!suspects.length) {
      listEl.innerHTML = '<p class="note">No suspects found -- all items look clean.</p>';
      return;
    }

    const header = document.createElement('div');
    header.className = 'suspect-summary';
    header.innerHTML = `
      <span>${suspects.length} suspect${suspects.length !== 1 ? 's' : ''}</span>
      ${Object.entries(summary.severity_counts || {}).reverse().map(([sev, n]) =>
        `<span class="suspect-sev-badge sev-${sev}">${sev}: ${n}</span>`
      ).join('')}
    `;
    listEl.appendChild(header);

    const reasonCodes = [...new Set(
      suspects.flatMap((item) => (item.reasons || []).map((r) => r.code))
    )].sort();

    const toolbar = document.createElement('div');
    toolbar.className = 'move-toolbar';
    toolbar.innerHTML = `
      <label>Search suspects
        <input type="search" class="suspect-search" placeholder="Title, path, or flag" />
      </label>
      <label>Filter by flag
        <select class="suspect-reason-filter">
          <option value="">All flags</option>
          ${reasonCodes.map((code) => `<option value="${escapeHtml(code)}">${escapeHtml(code.replace(/_/g, ' '))}</option>`).join('')}
        </select>
      </label>
      <strong class="suspect-count"></strong>
    `;
    listEl.appendChild(toolbar);

    const entries = suspects.map((item) => {
      const reasons = item.reasons || [];
      const haystack = [
        item.path,
        item.local?.title,
        item.severity,
        ...(item.related_paths || []),
        ...reasons.map((r) => `${r.code} ${r.message}`),
      ].filter(Boolean).join(' ').toLowerCase();
      return { item, reasons, haystack, el: buildSuspectCard(item) };
    });
    for (const entry of entries) listEl.appendChild(entry.el);

    const searchInput = toolbar.querySelector('.suspect-search');
    const reasonSelect = toolbar.querySelector('.suspect-reason-filter');
    const countEl = toolbar.querySelector('.suspect-count');

    function applyFilter() {
      const query = searchInput.value.trim().toLowerCase();
      const reasonCode = reasonSelect.value;
      let shown = 0;
      for (const entry of entries) {
        const matchesQuery = !query || entry.haystack.includes(query);
        const matchesReason = !reasonCode || entry.reasons.some((r) => r.code === reasonCode);
        const visible = matchesQuery && matchesReason;
        entry.el.hidden = !visible;
        if (visible) shown++;
      }
      countEl.textContent = `Showing ${shown} of ${entries.length}`;
    }

    searchInput.addEventListener('input', applyFilter);
    reasonSelect.addEventListener('change', applyFilter);
    applyFilter();
  }

  window.UiCommon = {
    escapeHtml,
    renderDownloadLinks,
    statCard,
    saveActiveRun,
    clearActiveRun,
    loadActiveRun,
    loadAbsAggProviders,
    getAbsAggProviderParamHint,
    isAbsAggReachable,
    checkAbsReachable,
    isAbsConfigured,
    loadAbsAggSettings,
    saveAbsAggUrl,
    searchAbsAgg,
    scoreBadge,
    initFolderBrowser,
    buildSeriesGroupCard,
    buildSuspectCard,
    renderSuspectReport,
    SUSPECT_REASON_FIELDS,
  };
})();
