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

  // Redirect to /auth-setup if the auth file is missing on pages that need it,
  // unless the user explicitly skipped Audible setup or debug mode is on.
  const _AUTH_PAGES = new Set(["fixer", "m4b-tool"]);
  const _page = document.body.dataset.page;
  function _isDebugMode() {
    try { return JSON.parse(localStorage.getItem("libraforge-preferences") || "{}").debugMode === true; } catch { return false; }
  }
  if (_AUTH_PAGES.has(_page) && !sessionStorage.getItem("audible-skipped") && !_isDebugMode()) {
    fetch("/api/auth/status")
      .then((r) => r.json())
      .then((data) => {
        if (!data.auth_ok) {
          window.location.href = "/auth-setup";
        }
      })
      .catch(() => {});
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

  async function searchAbsAgg({ query, provider, providerParams = "", baseUrl = "", limit = 10 }) {
    return fetch("/api/abs-agg/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
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

  window.UiCommon = {
    escapeHtml,
    renderDownloadLinks,
    statCard,
    loadAbsAggProviders,
    getAbsAggProviderParamHint,
    isAbsAggReachable,
    checkAbsReachable,
    isAbsConfigured,
    loadAbsAggSettings,
    saveAbsAggUrl,
    searchAbsAgg,
    scoreBadge,
  };
})();
