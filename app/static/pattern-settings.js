/* One renderer for the Settings pattern sections (Publishers, Title noise, Author names).
 * Each section shows Known patterns (shipped, can be switched off) and Private patterns
 * (yours: add, switch off, remove). The server owns the data; this only draws it.
 * Every change (add, remove, switch) is saved right away, so there is no Save button. */
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
    if (!els || !els.defaults || !els.custom || !els.status || !els.addButton) return null;
    if ((cfg.requiredInputs || []).some((input) => !input)) return null;

    let policy = null;
    let knownRows = [];
    let privateRows = [];

    const items = () => (policy && policy[cfg.listKey]) || [];
    const setStatus = (message) => { els.status.textContent = message; };

    const syncSwitches = () => {
      knownRows.concat(privateRows).forEach((row) => { row.item.enabled = row.box.checked; });
    };

    // Saves the whole list. On failure the server copy is reloaded, so a rejected
    // change never lingers on the page.
    const save = async (okMessage) => {
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
        await reload();
        setStatus(cfg.text.saveError);
        return;
      }
      if (!response.ok) {
        await reload();
        setStatus(data.detail || cfg.text.saveError);
        return;
      }
      policy = data;
      render();
      setStatus(okMessage);
      if (cfg.onLoaded) cfg.onLoaded(policy);
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
          box.addEventListener("change", () => save(cfg.text.saved));
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
        box.addEventListener("change", () => save(cfg.text.saved));
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
          save(cfg.text.removed);
        });
        row.append(label, remove);
        return row;
      }));
    };

    // Fetches the server copy and draws it; returns false (with a message) when that fails.
    const reload = async () => {
      let response;
      let data;
      try {
        response = await fetch(cfg.endpoint);
        data = await response.json();
      } catch (error) {
        setStatus(cfg.text.loadError);
        return false;
      }
      if (!response.ok) {
        setStatus(data.detail || cfg.text.loadError);
        return false;
      }
      policy = data;
      render();
      if (cfg.onLoaded) cfg.onLoaded(policy);
      return true;
    };

    const load = async () => {
      if (!(await reload())) return;
      setStatus(cfg.text.loaded);
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
      save(cfg.text.added);
    });

    return { load, getPolicy: () => policy };
  }

  window.LibraForgePatterns = { createSection };
})();
