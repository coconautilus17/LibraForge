(() => {
  const storageKey = "libraforge-preferences";
  const legacyStorageKey = "audible-metadata-ui-preferences";
  const surfaceOptions = {
    dark: [
      ["charcoal", "Charcoal"],
      ["ash", "Ash"],
      ["warm", "Warm"],
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
    debugMode: false,
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
    initializeInfoTips();
    initializeSettingsPanel();
    initializeExplanations();
    initializeTitleNoiseSettings();
    initializePublisherSettings();
    const theme = document.getElementById("uiTheme");
    const surface = document.getElementById("uiSurface");
    const accent = document.getElementById("uiAccent");
    const density = document.getElementById("uiDensity");
    const debugModeEl = document.getElementById("debugMode");
    const debugLinks = document.getElementById("debugLinks");

    if (debugModeEl) {
      debugModeEl.checked = preferences.debugMode;
      if (debugLinks) debugLinks.hidden = !preferences.debugMode;
      debugModeEl.addEventListener("change", () => {
        preferences = { ...preferences, debugMode: debugModeEl.checked };
        savePreferences(preferences);
        if (debugLinks) debugLinks.hidden = !preferences.debugMode;
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
