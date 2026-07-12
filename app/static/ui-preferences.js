(() => {
  const storageKey = "libraforge-preferences";
  const legacyStorageKey = "audible-metadata-ui-preferences";
  const surfaceOptions = {
    dark: [
      ["charcoal", "Charcoal"],
      ["ash", "Ash"],
      ["warm", "Warm"],
      ["wood", "Wood"],
      ["forest", "Forest"],
      ["plum", "Plum"],
      ["oled", "OLED"],
    ],
    light: [
      ["paper", "Paper"],
      ["snow", "Snow"],
      ["cream", "Cream"],
      ["sage", "Sage"],
      ["rose", "Rose"],
      ["lavender", "Lavender"],
    ],
  };
  const defaults = {
    theme: "system",
    darkSurface: "charcoal",
    lightSurface: "paper",
    accent: "sky",
    density: "comfortable",
    explanationsExpanded: true,
    debugTrace: false,
    debugTraceFile: "",
    defaultRootPath: "",
    ignoredFolders: [".", "#", "@"],
    persistentSkipPatterns: "",
    usePersistentSkip: false,
  };

  function readPreferences() {
    try {
      const stored = JSON.parse(
        localStorage.getItem(storageKey)
          || localStorage.getItem(legacyStorageKey)
          || "{}",
      );
      if (stored.surface && !stored.darkSurface) {
        stored.darkSurface = stored.surface;
      }
      return { ...defaults, ...stored };
    } catch {
      return { ...defaults };
    }
  }

  function resolvedTheme(theme) {
    if (theme !== "system") return theme;
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }

  function surfaceForTheme(preferences, theme) {
    return theme === "light" ? preferences.lightSurface : preferences.darkSurface;
  }

  function applyPreferences(preferences) {
    const root = document.documentElement;
    const theme = resolvedTheme(preferences.theme);
    root.dataset.theme = theme;
    root.dataset.themePreference = preferences.theme;
    root.dataset.surface = surfaceForTheme(preferences, theme);
    root.dataset.accent = preferences.accent;
    root.dataset.density = preferences.density;
  }

  function savePreferences(preferences) {
    try {
      localStorage.setItem(storageKey, JSON.stringify(preferences));
    } catch {
      // Keep the active preference even when browser storage is unavailable.
    }
    applyPreferences(preferences);
  }

  function populateSurfaceSelect(select, preferences) {
    const theme = resolvedTheme(preferences.theme);
    const selected = surfaceForTheme(preferences, theme);
    select.replaceChildren(
      ...surfaceOptions[theme].map(([value, label]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        return option;
      }),
    );
    select.value = selected;
    select.setAttribute("aria-label", `${theme === "light" ? "Light" : "Dark"} surface palette`);
    select.title = `${theme === "light" ? "Light" : "Dark"} surface palette`;
  }

  function initializeVersionTag() {
    const tag = document.getElementById("versionTag");
    if (!tag) return;
    fetch("/api/version")
      .then((r) => r.json())
      .then((data) => {
        const version = data.version || "dev";
        tag.textContent = `v${version}`;
        if (/^\d+\.\d+\.\d+$/.test(version)) {
          tag.href = `https://github.com/coconautilus17/LibraForge/releases/tag/v${version}`;
        }
      })
      .catch(() => { tag.textContent = ""; });
  }

  function initializeInfoTips() {
    const markers = [...document.querySelectorAll(".info-tip[data-tooltip]")];
    if (!markers.length) return;

    const tooltip = document.createElement("div");
    tooltip.className = "ui-tooltip";
    tooltip.setAttribute("role", "tooltip");
    tooltip.hidden = true;
    document.body.appendChild(tooltip);
    let activeMarker = null;

    const hide = () => {
      if (activeMarker) activeMarker.setAttribute("aria-expanded", "false");
      activeMarker = null;
      tooltip.hidden = true;
    };

    const show = (marker) => {
      if (activeMarker && activeMarker !== marker) {
        activeMarker.setAttribute("aria-expanded", "false");
      }
      activeMarker = marker;
      marker.setAttribute("aria-expanded", "true");
      tooltip.textContent = marker.dataset.tooltip;
      tooltip.hidden = false;

      const markerRect = marker.getBoundingClientRect();
      const tooltipRect = tooltip.getBoundingClientRect();
      const margin = 8;
      const left = Math.min(
        window.innerWidth - tooltipRect.width - 12,
        Math.max(12, markerRect.left + markerRect.width / 2 - tooltipRect.width / 2),
      );
      const spaceBelow = window.innerHeight - markerRect.bottom;
      const top = spaceBelow >= tooltipRect.height + margin
        ? markerRect.bottom + margin
        : markerRect.top - tooltipRect.height - margin;
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${Math.max(8, top)}px`;
    };

    for (const marker of markers) {
      marker.textContent = "";
      marker.setAttribute("tabindex", "0");
      marker.setAttribute("role", "button");
      marker.setAttribute("aria-expanded", "false");
      marker.setAttribute("aria-label", marker.dataset.tooltip);
      marker.addEventListener("mouseenter", () => show(marker));
      marker.addEventListener("mouseleave", () => {
        if (document.activeElement !== marker) hide();
      });
      marker.addEventListener("focus", () => show(marker));
      marker.addEventListener("blur", hide);
      marker.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (activeMarker === marker && !tooltip.hidden) {
          hide();
          marker.blur();
        } else {
          marker.focus();
          show(marker);
        }
      });
      marker.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          hide();
          marker.blur();
        }
      });
    }

    window.addEventListener("resize", hide);
    window.addEventListener("scroll", hide, true);
  }

  function createTextElement(tag, text, className = "") {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function initializeSettingsPanel() {
    const toggle = document.getElementById("settingsToggle");
    const close = document.getElementById("settingsClose");
    const panel = document.getElementById("globalSettings");
    if (!toggle || !close || !panel) return;
    document.body.appendChild(panel);

    const positionPanel = () => {
      if (panel.hidden) return;
      const toggleRect = toggle.getBoundingClientRect();
      const margin = window.innerWidth <= 520 ? 8 : 12;
      const gap = 10;
      const panelWidth = Math.min(760, window.innerWidth - margin * 2);
      const left = Math.min(
        window.innerWidth - panelWidth - margin,
        Math.max(margin, toggleRect.right - panelWidth),
      );
      const top = toggleRect.bottom + gap;
      panel.style.left = `${left}px`;
      panel.style.right = "auto";
      panel.style.top = `${top}px`;
      panel.style.bottom = "auto";
      panel.style.width = `${panelWidth}px`;
      panel.style.maxHeight = `${Math.max(160, window.innerHeight - top - margin)}px`;
      panel.style.setProperty(
        "--settings-anchor-x",
        `${Math.max(18, Math.min(panelWidth - 18, toggleRect.left + toggleRect.width / 2 - left))}px`,
      );
    };

    const setOpen = (open) => {
      panel.hidden = !open;
      document.body.classList.toggle("settings-open", open);
      toggle.setAttribute("aria-expanded", String(open));
      toggle.setAttribute("aria-label", `${open ? "Close" : "Open"} global settings`);
      if (open) {
        positionPanel();
        panel.querySelector("select, input, button")?.focus();
      }
    };

    toggle.addEventListener("click", () => setOpen(panel.hidden));
    close.addEventListener("click", () => {
      setOpen(false);
      toggle.focus();
    });
    document.addEventListener("click", (event) => {
      if (panel.hidden || panel.contains(event.target) || toggle.contains(event.target)) return;
      setOpen(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !panel.hidden) {
        setOpen(false);
        toggle.focus();
      }
    });
    window.addEventListener("resize", positionPanel);
  }

  function initializeExplanations() {
    const candidates = [
      ...document.querySelectorAll(
        ".action-explanation, .note:not([id]), .audio-profile-help, .workflow-guide",
      ),
    ].filter((element) => !element.closest(".settings-panel"));
    if (!candidates.length) return;

    const disclosures = candidates.map((content) => {
      const details = document.createElement("details");
      details.className = "explanation-disclosure";
      details.open = preferences.explanationsExpanded;
      const summary = createTextElement("summary", "Explanation");
      content.parentNode.insertBefore(details, content);
      details.append(summary, content);
      return details;
    });
    const toggle = document.getElementById("explanationsToggle");
    if (!toggle) return;

    const updateToggle = () => {
      const allOpen = disclosures.every((details) => details.open);
      toggle.textContent = allOpen ? "Collapse explanations" : "Expand explanations";
      toggle.setAttribute("aria-pressed", String(!allOpen));
    };

    toggle.addEventListener("click", () => {
      const expand = !disclosures.every((details) => details.open);
      disclosures.forEach((details) => {
        details.open = expand;
      });
      preferences = { ...preferences, explanationsExpanded: expand };
      savePreferences(preferences);
      updateToggle();
    });
    disclosures.forEach((details) => details.addEventListener("toggle", updateToggle));
    updateToggle();
  }

  function titleNoiseCustomId(label) {
    const slug = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    return `custom-${slug || Date.now()}`;
  }

  // The Publishers and Title noise lists render asynchronously after the
  // initial page load, so a URL fragment like /settings#accounts can resolve
  // to the browser's native scroll-to-anchor before those lists exist -- once
  // they render, the growth in page height leaves the anchor scrolled well
  // past its target. Re-apply the scroll after each list finishes loading.
  function reapplyHashScroll() {
    const hash = window.location.hash;
    if (!hash || hash.length < 2) return;
    const target = document.getElementById(hash.slice(1));
    if (target) target.scrollIntoView({ block: "start" });
  }

  // Landed here via the auth/ABS-required redirect (see ui-common.js
  // ensureConnected/the auth-page load check) -- explain why, and flash the
  // sections that need attention so it's not just a silent drop-off.
  function initializeConnectionNotice() {
    if (document.body.dataset.page !== "settings") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("authRequired") !== "1") return;
    const require = params.get("require") || "any"; // "any" | "audible" | "abs" | "abs-agg" | "abs-tract"

    // Don't leave the params in the URL -- a refresh/bookmark shouldn't re-show this.
    params.delete("authRequired");
    params.delete("require");
    const query = params.toString();
    const newUrl = window.location.pathname + (query ? `?${query}` : "") + window.location.hash;
    window.history.replaceState(null, "", newUrl);

    const targetIds = require === "audible" ? ["accounts", "skipBtn"]
      : require === "abs" ? ["absSection", "skipBtn"]
      : require === "abs-agg" ? ["abs-agg"]
      : require === "abs-tract" ? ["abs-tract"]
      : ["accounts", "absSection", "skipBtn"];
    const flashConnectionTargets = () => {
      targetIds
        .map((id) => document.getElementById(id))
        .filter(Boolean)
        .forEach((el) => {
          // Restart the animation even if it's already mid-flash.
          el.classList.remove("connection-flash-highlight");
          void el.offsetWidth;
          el.classList.add("connection-flash-highlight");
          el.addEventListener("animationend", () => el.classList.remove("connection-flash-highlight"), { once: true });
        });
    };
    flashConnectionTargets();

    const copy = require === "audible"
      ? {
        title: "Connect an Audible account to continue",
        body: 'This action reads your Audible purchases directly, so an Audiobookshelf connection alone isn\'t enough here. Set up your <strong>Audible account</strong> below, or use <strong>Skip for now</strong> if you\'ll do this later.',
      }
      : require === "abs"
      ? {
        title: "Connect Audiobookshelf to continue",
        body: 'This action needs an <strong>Audiobookshelf (ABS) connection</strong>, the library source this reads from. An Audible account is optional and only improves match quality. Set up ABS below, or use <strong>Skip for now</strong> if you\'ll do this later.',
      }
      : require === "abs-agg"
      ? {
        title: "Connect abs-agg to continue",
        body: 'This action needs a reachable <strong>abs-agg</strong> connection, the service LibraForge uses to search GraphicAudio and SoundBooth Theater. Set its URL below.',
      }
      : require === "abs-tract"
      ? {
        title: "Connect abs-tract to continue",
        body: 'This action needs an <strong>abs-tract</strong> URL configured, the service LibraForge uses to search Goodreads and Kindle. Set it below.',
      }
      : {
        title: "Connect a metadata provider to continue",
        body: 'LibraForge needs at least one of the two highlighted sections below to work: an <strong>Audible account</strong>, or an <strong>Audiobookshelf (ABS) connection</strong>. Set up either one, or use <strong>Skip for now</strong> if you\'ll do this later.',
      };

    const dlg = document.createElement("dialog");
    dlg.className = "manual-apply-dialog connection-notice-dialog";
    dlg.innerHTML = `
      <h3 class="manual-apply-title">${copy.title}</h3>
      <p class="manual-apply-body">${copy.body}</p>
      <div class="manual-apply-actions">
        <button id="connectionNoticeOk" class="secondary">Got it</button>
      </div>`;
    document.body.appendChild(dlg);
    const close = () => { dlg.close(); dlg.remove(); };
    dlg.querySelector("#connectionNoticeOk").addEventListener("click", () => {
      flashConnectionTargets();
      close();
    });
    dlg.addEventListener("click", (e) => { if (e.target === dlg) close(); });
    dlg.showModal();
  }

  function initializeTitleNoiseSettings() {
    const defaultsContainer = document.getElementById("titleNoiseDefaults");
    const customContainer = document.getElementById("titleNoiseCustom");
    const status = document.getElementById("titleNoiseStatus");
    const labelInput = document.getElementById("titleNoiseLabel");
    const patternInput = document.getElementById("titleNoisePattern");
    const addButton = document.getElementById("titleNoiseAddBtn");
    const saveButton = document.getElementById("titleNoiseSaveBtn");
    if (!defaultsContainer || !customContainer || !status || !labelInput || !patternInput || !addButton || !saveButton) return;

    let policy = null;

    const render = () => {
      const patterns = policy?.patterns || [];
      defaultsContainer.replaceChildren(
        ...patterns.filter((item) => item.source === "default").map((item) => {
          const row = document.createElement("label");
          row.className = "pattern-row";
          const input = document.createElement("input");
          input.type = "checkbox";
          input.checked = item.enabled;
          input.dataset.titleNoiseDefault = item.id;
          const copy = document.createElement("span");
          copy.append(
            createTextElement("strong", item.label),
            createTextElement("small", item.description || item.pattern),
          );
          row.append(input, copy);
          return row;
        }),
      );

      const custom = patterns.filter((item) => item.source === "custom");
      if (!custom.length) {
        customContainer.replaceChildren(createTextElement("p", "No custom patterns.", "note"));
        return;
      }
      customContainer.replaceChildren(...custom.map((item) => {
        const row = document.createElement("div");
        row.className = "pattern-row custom-pattern-row";
        row.dataset.titleNoiseCustom = item.id;
        const label = document.createElement("label");
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = item.enabled;
        input.dataset.patternEnabled = "";
        const copy = document.createElement("span");
        copy.append(
          createTextElement("strong", item.label),
          createTextElement("small", item.phrase || item.pattern, "mono"),
        );
        label.append(input, copy);
        const remove = createTextElement("button", "Remove", "secondary");
        remove.type = "button";
        remove.addEventListener("click", () => {
          policy.patterns = policy.patterns.filter((candidate) => candidate.id !== item.id);
          render();
          status.textContent = "Pattern removed locally. Save to apply the change.";
        });
        row.append(label, remove);
        return row;
      }));
    };

    const load = async () => {
      const response = await fetch("/api/settings/title-noise");
      const data = await response.json();
      if (!response.ok) {
        status.textContent = data.detail || "Could not load title patterns.";
        return;
      }
      policy = data;
      render();
      status.textContent = "Using shared defaults and local overrides.";
      reapplyHashScroll();
    };

    addButton.addEventListener("click", () => {
      const label = labelInput.value.trim();
      const phrase = patternInput.value.trim();
      if (!label || !phrase) {
        status.textContent = "Enter both a label and a noise phrase.";
        return;
      }
      policy ||= { patterns: [] };
      policy.patterns.push({
        id: titleNoiseCustomId(label),
        label,
        description: "",
        phrase,
        pattern: phrase,
        source: "custom",
        enabled: true,
      });
      labelInput.value = "";
      patternInput.value = "";
      render();
      status.textContent = "Custom pattern added locally. Save to apply it.";
    });

    saveButton.addEventListener("click", async () => {
      const disabledDefaults = [
        ...defaultsContainer.querySelectorAll("[data-title-noise-default]:not(:checked)"),
      ].map((input) => input.dataset.titleNoiseDefault);
      const customPatterns = [
        ...customContainer.querySelectorAll("[data-title-noise-custom]"),
      ].map((row) => {
        const item = policy.patterns.find((candidate) => candidate.id === row.dataset.titleNoiseCustom);
        return {
          id: item.id,
          label: item.label,
          description: item.description || "",
          pattern: item.pattern,
          enabled: row.querySelector("[data-pattern-enabled]").checked,
        };
      });
      const response = await fetch("/api/settings/title-noise", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          disabled_defaults: disabledDefaults,
          custom_patterns: customPatterns,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        status.textContent = data.detail || "Could not save title patterns.";
        return;
      }
      policy = data;
      render();
      status.textContent = "Saved. New runs now use these title patterns.";
    });

    load();
  }

  function publisherCustomId(name) {
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    return slug || `publisher-${Date.now()}`;
  }

  function initializePublisherSettings() {
    const defaultsContainer = document.getElementById("publisherDefaults");
    const customContainer = document.getElementById("publisherCustom");
    const status = document.getElementById("publisherStatus");
    const nameInput = document.getElementById("publisherName");
    const specialSelect = document.getElementById("publisherSpecial");
    const addButton = document.getElementById("publisherAddBtn");
    const saveButton = document.getElementById("publisherSaveBtn");
    if (!defaultsContainer || !customContainer || !status || !nameInput || !addButton || !saveButton) return;

    let policy = null;

    const specialLabel = (id) => (policy?.special_providers || {})[id] || id;

    const render = () => {
      const entries = policy?.publishers || [];
      defaultsContainer.replaceChildren(
        ...entries.filter((item) => item.source === "default").map((item) => {
          const row = document.createElement("label");
          row.className = "pattern-row";
          const input = document.createElement("input");
          input.type = "checkbox";
          input.checked = item.enabled;
          input.dataset.publisherDefault = item.id;
          const copy = document.createElement("span");
          const detail = [item.aliases?.length ? `aka ${item.aliases.join(", ")}` : "", item.special_provider ? `→ ${specialLabel(item.special_provider)} endpoint` : ""].filter(Boolean).join(" · ");
          copy.append(createTextElement("strong", item.name), createTextElement("small", detail || "publisher / imprint"));
          row.append(input, copy);
          return row;
        }),
      );

      const custom = entries.filter((item) => item.source !== "default");
      if (!custom.length) {
        customContainer.replaceChildren(createTextElement("p", "No custom or learned publishers.", "note"));
        return;
      }
      customContainer.replaceChildren(...custom.map((item) => {
        const row = document.createElement("div");
        row.className = "pattern-row custom-pattern-row";
        row.dataset.publisherCustom = item.id;
        const label = document.createElement("label");
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = item.enabled;
        input.dataset.patternEnabled = "";
        const copy = document.createElement("span");
        const detail = [item.source === "learned" ? "learned" : "custom", item.special_provider ? `→ ${specialLabel(item.special_provider)} endpoint` : ""].filter(Boolean).join(" · ");
        copy.append(createTextElement("strong", item.name), createTextElement("small", detail));
        label.append(input, copy);
        const remove = createTextElement("button", "Remove", "secondary");
        remove.type = "button";
        remove.addEventListener("click", () => {
          policy.publishers = policy.publishers.filter((candidate) => candidate.id !== item.id);
          render();
          status.textContent = "Publisher removed locally. Save to apply the change.";
        });
        row.append(label, remove);
        return row;
      }));
    };

    const load = async () => {
      const response = await fetch("/api/settings/publishers");
      const data = await response.json();
      if (!response.ok) {
        status.textContent = data.detail || "Could not load publishers.";
        return;
      }
      policy = data;
      render();
      status.textContent = "Using shared defaults and local overrides.";
      reapplyHashScroll();
    };

    addButton.addEventListener("click", () => {
      const name = nameInput.value.trim();
      if (!name) {
        status.textContent = "Enter a publisher name.";
        return;
      }
      policy ||= { publishers: [] };
      policy.publishers.push({
        id: publisherCustomId(name),
        name,
        aliases: [],
        special_provider: specialSelect && specialSelect.value ? specialSelect.value : null,
        source: "custom",
        enabled: true,
      });
      nameInput.value = "";
      if (specialSelect) specialSelect.value = "";
      render();
      status.textContent = "Publisher added locally. Save to apply it.";
    });

    saveButton.addEventListener("click", async () => {
      const disabledDefaults = [
        ...defaultsContainer.querySelectorAll("[data-publisher-default]:not(:checked)"),
      ].map((input) => input.dataset.publisherDefault);
      const customPublishers = [
        ...customContainer.querySelectorAll("[data-publisher-custom]"),
      ].map((row) => {
        const item = policy.publishers.find((candidate) => candidate.id === row.dataset.publisherCustom);
        return {
          id: item.id,
          name: item.name,
          aliases: item.aliases || [],
          special_provider: item.special_provider || null,
          source: item.source === "learned" ? "learned" : "custom",
          enabled: row.querySelector("[data-pattern-enabled]").checked,
        };
      });
      const response = await fetch("/api/settings/publishers", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          disabled_defaults: disabledDefaults,
          custom_publishers: customPublishers,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        status.textContent = data.detail || "Could not save publishers.";
        return;
      }
      policy = data;
      render();
      status.textContent = "Saved. New runs now use these publishers.";
    });

    load();
  }

  let preferences = readPreferences();
  applyPreferences(preferences);

  // Expose read-only access for page scripts that need preference values.
  window.LibraForgePrefs = { get: () => preferences };

  const systemTheme = window.matchMedia("(prefers-color-scheme: light)");
  const handleSystemThemeChange = () => {
    if (preferences.theme !== "system") return;
    applyPreferences(preferences);
    const surface = document.getElementById("uiSurface");
    if (surface) populateSurfaceSelect(surface, preferences);
  };
  if (systemTheme.addEventListener) {
    systemTheme.addEventListener("change", handleSystemThemeChange);
  } else {
    systemTheme.addListener(handleSystemThemeChange);
  }

  window.addEventListener("DOMContentLoaded", () => {
    initializeVersionTag();
    initializeInfoTips();
    initializeSettingsPanel();
    initializeExplanations();
    initializeConnectionNotice();
    initializeTitleNoiseSettings();
    initializePublisherSettings();
    const theme = document.getElementById("uiTheme");
    const surface = document.getElementById("uiSurface");
    const accent = document.getElementById("uiAccent");
    const density = document.getElementById("uiDensity");

    const debugTraceEl = document.getElementById("debugTrace");
    const debugTraceFileEl = document.getElementById("debugTraceFile");
    if (debugTraceEl) {
      debugTraceEl.checked = preferences.debugTrace;
      debugTraceEl.addEventListener("change", () => {
        preferences = { ...preferences, debugTrace: debugTraceEl.checked };
        savePreferences(preferences);
      });
    }
    if (debugTraceFileEl) {
      debugTraceFileEl.value = preferences.debugTraceFile || "";
      debugTraceFileEl.addEventListener("change", () => {
        preferences = { ...preferences, debugTraceFile: debugTraceFileEl.value.trim() };
        savePreferences(preferences);
      });
    }

    const defaultRootEl = document.getElementById("defaultRootPath");
    if (defaultRootEl) {
      defaultRootEl.value = preferences.defaultRootPath || "";
      defaultRootEl.addEventListener("change", () => {
        preferences = { ...preferences, defaultRootPath: defaultRootEl.value.trim() };
        savePreferences(preferences);
      });
    }

    const ignoredFoldersContainer = document.getElementById("ignoredFoldersList");
    const ignoredFoldersInput = document.getElementById("ignoredFoldersInput");
    const ignoredFoldersAddBtn = document.getElementById("ignoredFoldersAdd");

    // Fire-and-forget: an ignore-list edit can invalidate the Manual Review
    // filesystem search index (it's built with these tokens pruned during
    // the walk, not just post-filtered). Pinging the status endpoint here
    // lets a rebuild start right away in the background instead of waiting
    // for the next time someone happens to open Manual Review and search.
    function pingManualReviewSearchIndex(folders) {
      const params = new URLSearchParams();
      for (const folder of folders || []) params.append("ignored_folders", folder);
      fetch(`/api/manual-review/search-index/status?${params.toString()}`).catch(() => {});
    }

    function renderIgnoredFolders() {
      if (!ignoredFoldersContainer) return;
      ignoredFoldersContainer.replaceChildren(
        ...(preferences.ignoredFolders || []).map((entry) => {
          const row = document.createElement("div");
          row.className = "pattern-row";
          const label = document.createElement("span");
          label.textContent = entry;
          label.className = "mono";
          const remove = document.createElement("button");
          remove.type = "button";
          remove.textContent = "Remove";
          remove.className = "secondary";
          remove.style.fontSize = "0.8em";
          remove.addEventListener("click", () => {
            preferences = { ...preferences, ignoredFolders: preferences.ignoredFolders.filter(f => f !== entry) };
            savePreferences(preferences);
            pingManualReviewSearchIndex(preferences.ignoredFolders);
            renderIgnoredFolders();
          });
          row.append(label, remove);
          return row;
        })
      );
    }
    renderIgnoredFolders();

    if (ignoredFoldersAddBtn && ignoredFoldersInput) {
      ignoredFoldersAddBtn.addEventListener("click", () => {
        const val = ignoredFoldersInput.value.trim();
        if (!val || (preferences.ignoredFolders || []).includes(val)) return;
        preferences = { ...preferences, ignoredFolders: [...(preferences.ignoredFolders || []), val] };
        savePreferences(preferences);
        pingManualReviewSearchIndex(preferences.ignoredFolders);
        ignoredFoldersInput.value = "";
        renderIgnoredFolders();
      });
    }

    const persistentSkipEl = document.getElementById("persistentSkipPatterns");
    if (persistentSkipEl) {
      persistentSkipEl.value = preferences.persistentSkipPatterns || "";
      persistentSkipEl.addEventListener("change", () => {
        preferences = { ...preferences, persistentSkipPatterns: persistentSkipEl.value };
        savePreferences(preferences);
      });
    }

    const usePersistentSkipEl = document.getElementById("usePersistentSkip");
    if (usePersistentSkipEl) {
      usePersistentSkipEl.checked = preferences.usePersistentSkip || false;
      usePersistentSkipEl.addEventListener("change", () => {
        preferences = { ...preferences, usePersistentSkip: usePersistentSkipEl.checked };
        savePreferences(preferences);
      });
    }

    if (!theme || !surface || !accent || !density) return;

    theme.value = preferences.theme;
    accent.value = preferences.accent;
    density.value = preferences.density;
    populateSurfaceSelect(surface, preferences);

    theme.addEventListener("change", () => {
      preferences = { ...preferences, theme: theme.value };
      savePreferences(preferences);
      populateSurfaceSelect(surface, preferences);
    });
    surface.addEventListener("change", () => {
      const themeName = resolvedTheme(preferences.theme);
      preferences = {
        ...preferences,
        [themeName === "light" ? "lightSurface" : "darkSurface"]: surface.value,
      };
      savePreferences(preferences);
    });
    accent.addEventListener("change", () => {
      preferences = { ...preferences, accent: accent.value };
      savePreferences(preferences);
    });
    density.addEventListener("change", () => {
      preferences = { ...preferences, density: density.value };
      savePreferences(preferences);
    });
  });
})();
