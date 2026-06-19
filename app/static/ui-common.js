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

  // Redirect to /auth-setup if the auth file is missing, on pages that need it.
  const _AUTH_PAGES = new Set(["fixer", "m4b-tool"]);
  const _page = document.body.dataset.page;
  if (_AUTH_PAGES.has(_page)) {
    fetch("/api/auth/status")
      .then((r) => r.json())
      .then((data) => {
        if (!data.auth_ok) {
          window.location.href = "/auth-setup";
        }
      })
      .catch(() => {
        // If the status check itself fails, don't block the user.
      });
  }

  let _absAggRequiredParams = {};

  async function loadAbsAggProviders(selectEl) {
    try {
      const res = await fetch("/api/abs-agg/providers");
      const data = await res.json();
      _absAggRequiredParams = data.required_params || {};
      Object.entries(data.providers || {}).forEach(([key, label]) => {
        const opt = document.createElement("option");
        opt.value = key;
        opt.textContent = label;
        selectEl.appendChild(opt);
      });
    } catch {}
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
    loadAbsAggSettings,
    saveAbsAggUrl,
    searchAbsAgg,
    scoreBadge,
  };
})();
