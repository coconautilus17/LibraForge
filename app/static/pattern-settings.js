/* One renderer for the Settings pattern sections (Publishers, Title noise, Author names).
 * Each section shows Known patterns (shipped, can be switched off) and Private patterns
 * (yours: add, switch off, remove). The server owns the data; this only draws it. */
(function () {
  "use strict";

  function text(tag, value, className) {
    const node = document.createElement(tag);
    node.textContent = value;
    if (className) node.className = className;
    return node;
  }

  function createSection(cfg) {
    const els = cfg.elements;
    if (!els || !els.defaults || !els.custom || !els.status || !els.addButton || !els.saveButton) return null;
    if ((cfg.requiredInputs || []).some((input) => !input)) return null;

    let policy = null;
    let knownRows = [];
    let privateRows = [];

    const items = () => (policy && policy[cfg.listKey]) || [];
    const setStatus = (message) => { els.status.textContent = message; };

    // Keep switches the user flipped but has not saved when the lists redraw.
    const syncSwitches = () => {
      knownRows.concat(privateRows).forEach((row) => { row.item.enabled = row.box.checked; });
    };

    const render = () => {
      knownRows = [];
      privateRows = [];
      els.defaults.replaceChildren(
        ...items().filter((item) => item.source === "default").map((item) => {
          const row = document.createElement("label");
          row.className = "pattern-row";
          const box = document.createElement("input");
          box.type = "checkbox";
          box.checked = item.enabled;
          knownRows.push({ item, box });
          const copy = document.createElement("span");
          const view = cfg.describeKnown(item, policy);
          copy.append(text("strong", view.title), text("small", view.detail, view.mono ? "mono" : ""));
          row.append(box, copy);
          return row;
        }),
      );

      const mine = items().filter((item) => item.source !== "default");
      if (!mine.length) {
        els.custom.replaceChildren(text("p", cfg.text.emptyPrivate, "note"));
        return;
      }
      els.custom.replaceChildren(...mine.map((item) => {
        const row = document.createElement("div");
        row.className = "pattern-row custom-pattern-row";
        const label = document.createElement("label");
        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = item.enabled;
        privateRows.push({ item, box });
        const copy = document.createElement("span");
        const view = cfg.describePrivate(item, policy);
        copy.append(text("strong", view.title), text("small", view.detail, view.mono ? "mono" : ""));
        label.append(box, copy);
        const remove = text("button", "Remove", "secondary");
        remove.type = "button";
        remove.addEventListener("click", () => {
          syncSwitches();
          policy[cfg.listKey] = items().filter((candidate) => candidate.id !== item.id);
          render();
          setStatus(cfg.text.removed);
        });
        row.append(label, remove);
        return row;
      }));
    };

    const load = async () => {
      let response;
      let data;
      try {
        response = await fetch(cfg.endpoint);
        data = await response.json();
      } catch (error) {
        setStatus(cfg.text.loadError);
        return;
      }
      if (!response.ok) {
        setStatus(data.detail || cfg.text.loadError);
        return;
      }
      policy = data;
      render();
      setStatus(cfg.text.loaded);
      if (cfg.onLoaded) cfg.onLoaded(policy);
      if (cfg.afterLoad) cfg.afterLoad();
    };

    els.addButton.addEventListener("click", () => {
      const result = cfg.readAddForm();
      if (result.error) {
        setStatus(result.error);
        return;
      }
      syncSwitches();
      policy ||= {};
      policy[cfg.listKey] ||= [];
      policy[cfg.listKey].push(result.item);
      cfg.clearAddForm();
      render();
      setStatus(cfg.text.added);
    });

    els.saveButton.addEventListener("click", async () => {
      syncSwitches();
      const body = {
        disabled_defaults: knownRows.filter((row) => !row.box.checked).map((row) => row.item.id),
        [cfg.customKey]: privateRows.map((row) => cfg.serializePrivate(row.item, row.box.checked)),
      };
      let response;
      let data;
      try {
        response = await fetch(cfg.endpoint, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        data = await response.json();
      } catch (error) {
        setStatus(cfg.text.saveError);
        return;
      }
      if (!response.ok) {
        setStatus(data.detail || cfg.text.saveError);
        return;
      }
      policy = data;
      render();
      setStatus(cfg.text.saved);
      if (cfg.onLoaded) cfg.onLoaded(policy);
    });

    return { load, getPolicy: () => policy };
  }

  window.LibraForgePatterns = { createSection };
})();
