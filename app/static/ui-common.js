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

  window.UiCommon = {
    escapeHtml,
    renderDownloadLinks,
    statCard,
  };
})();
