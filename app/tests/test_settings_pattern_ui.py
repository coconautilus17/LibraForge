"""Runs the real Settings pattern-section JavaScript in QuickJS with a small DOM stub.

Skipped when the optional `quickjs` package is not installed (pip install quickjs).
"""
import json
import re
import unittest
from pathlib import Path

try:
    import quickjs
except ImportError:  # pragma: no cover
    quickjs = None

STATIC = Path(__file__).parents[1] / "static"

DOM_STUB = r"""
class Node {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.dataset = {}; this.listeners = {};
    this.className = ""; this.textContent = ""; this.checked = false; this.value = ""; this.type = "";
    this.opened = false; this.closed = false;
  }
  append(...items) { items.forEach((x) => this.children.push(typeof x === "string" ? { tagName: "#text", textContent: x, children: [] } : x)); }
  appendChild(c) { this.children.push(c); return c; }
  replaceChildren(...items) { this.children = []; this.append(...items); }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  async fire(type) { for (const fn of (this.listeners[type] || [])) await fn({ target: this }); }
  remove() {}
  close() { this.closed = true; }
  showModal() { this.opened = true; }
  text() { return (this.textContent || "") + this.children.map((c) => c.text ? c.text() : c.textContent).join(" "); }
  find(pred, out = []) { this.children.forEach((c) => { if (c.find) { if (pred(c)) out.push(c); c.find(pred, out); } }); return out; }
}
const registry = {};
globalThis.calls = [];
globalThis.responses = {};
globalThis.document = {
  createElement: (tag) => new Node(tag),
  getElementById: (id) => registry[id] || null,
  body: new Node("body"),
};
globalThis.window = { location: { hash: "", href: "" } };
globalThis.fetch = (url, opts) => {
  calls.push({ url, method: (opts && opts.method) || "GET", body: opts && opts.body ? JSON.parse(opts.body) : null });
  const key = ((opts && opts.method) || "GET") + " " + url;
  const reply = responses[key];
  const value = typeof reply === "function" ? reply(opts) : reply;
  if (!value) return Promise.reject(new Error("no response for " + key));
  return Promise.resolve({ ok: value.ok !== false, json: () => Promise.resolve(value.body) });
};
const el = (id, tag = "div") => (registry[id] = new Node(tag));
"""


def extract(source: str, name: str) -> str:
    match = re.search(rf"^  (?:async )?function {name}\(", source, re.M)
    assert match, name
    end = re.compile(r"\n  (?:async )?function |\n  window\.addEventListener").search(source, match.end())
    return source[match.start(): end.start()]


@unittest.skipIf(quickjs is None, "quickjs not installed")
class PatternUiTests(unittest.TestCase):
    def setUp(self):
        self.ctx = quickjs.Context()
        prefs = (STATIC / "ui-preferences.js").read_text(encoding="utf-8")
        funcs = "\n".join(extract(prefs, n) for n in (
            "createTextElement", "titleNoiseCustomId", "publisherCustomId", "reapplyHashScroll",
            "initializeTitleNoiseSettings", "initializePublisherSettings",
            "initializeAuthorNameSettings", "initializeAuthorNameNotice"))
        self.ctx.eval(DOM_STUB)
        self.ctx.eval((STATIC / "pattern-settings.js").read_text(encoding="utf-8"))
        self.ctx.eval("(function(){" + funcs + "\nglobalThis.fns = { initializeTitleNoiseSettings, initializePublisherSettings, initializeAuthorNameSettings, initializeAuthorNameNotice };})();")

    def run_js(self, code):
        result = self.ctx.eval(code)
        while self.ctx.execute_pending_job():
            pass
        return result

    def json(self, expr):
        raw = self.run_js(f"JSON.stringify({expr})")
        return json.loads(raw) if raw else None

    def respond(self, key, body, ok=True):
        self.run_js(f"responses[{json.dumps(key)}] = {{ ok: {json.dumps(ok)}, body: {json.dumps(body)} }};")

    # ------------------------------------------------------------ title noise
    def make_title_noise(self):
        self.run_js("""['titleNoiseDefaults','titleNoiseCustom','titleNoiseStatus'].forEach((id) => el(id));
          ['titleNoiseAddBtn','titleNoiseSaveBtn'].forEach((id) => el(id,'button'));
          ['titleNoiseLabel','titleNoisePattern'].forEach((id) => el(id,'input'));""")
        self.respond("GET /api/settings/title-noise", {"patterns": [
            {"id": "generic", "label": "Generic", "description": "desc", "pattern": "x", "source": "default", "enabled": True},
            {"id": "other", "label": "Other", "description": "", "pattern": "y", "source": "default", "enabled": True},
            {"id": "custom-bbc", "label": "bbc", "description": "", "phrase": "bbc", "pattern": "bbc", "source": "custom", "enabled": True},
        ]})
        self.run_js("fns.initializeTitleNoiseSettings();")

    def test_title_noise_renders_known_and_private_lists(self):
        self.make_title_noise()
        self.assertEqual(self.json("registry.titleNoiseDefaults.children.length"), 2)
        self.assertEqual(self.json("registry.titleNoiseCustom.children.length"), 1)
        self.assertIn("Known patterns ship", self.run_js("registry.titleNoiseStatus.textContent"))

    def test_title_noise_save_sends_the_same_shape_as_before(self):
        self.make_title_noise()
        self.respond("PUT /api/settings/title-noise", {"patterns": []})
        self.run_js("registry.titleNoiseDefaults.children[1].children[0].checked = false;")
        self.run_js("registry.titleNoiseSaveBtn.fire('click');")
        body = json.loads(self.run_js("JSON.stringify(calls.filter(c => c.method === 'PUT')[0].body)"))
        self.assertEqual(body, {
            "disabled_defaults": ["other"],
            "custom_patterns": [{"id": "custom-bbc", "label": "bbc", "description": "", "pattern": "bbc", "enabled": True}],
        })

    def test_adding_keeps_unsaved_switches_and_clears_the_form(self):
        self.make_title_noise()
        self.run_js("registry.titleNoiseDefaults.children[0].children[0].checked = false;")
        self.run_js("registry.titleNoiseLabel.value = 'SoL'; registry.titleNoisePattern.value = 'A slice of life';")
        self.run_js("registry.titleNoiseAddBtn.fire('click');")
        self.assertEqual(self.json("registry.titleNoiseCustom.children.length"), 2)
        self.assertFalse(self.run_js("registry.titleNoiseDefaults.children[0].children[0].checked"))
        self.assertEqual(self.run_js("registry.titleNoiseLabel.value"), "")
        self.respond("PUT /api/settings/title-noise", {"patterns": []})
        self.run_js("registry.titleNoiseSaveBtn.fire('click');")
        body = json.loads(self.run_js("JSON.stringify(calls.filter(c => c.method === 'PUT')[0].body)"))
        self.assertEqual(body["disabled_defaults"], ["generic"])
        self.assertEqual([p["pattern"] for p in body["custom_patterns"]], ["bbc", "A slice of life"])

    def test_empty_form_shows_the_old_message(self):
        self.make_title_noise()
        self.run_js("registry.titleNoiseAddBtn.fire('click');")
        self.assertEqual(self.run_js("registry.titleNoiseStatus.textContent"), "Enter both a label and a noise phrase.")

    def test_remove_and_save_error_message(self):
        self.make_title_noise()
        self.run_js("registry.titleNoiseCustom.children[0].children[1].fire('click');")
        self.assertEqual(self.json("registry.titleNoiseCustom.children[0].className"), "note")
        self.respond("PUT /api/settings/title-noise", {"detail": "bad regex"}, ok=False)
        self.run_js("registry.titleNoiseSaveBtn.fire('click');")
        self.assertEqual(self.run_js("registry.titleNoiseStatus.textContent"), "bad regex")

    # -------------------------------------------------------------- publishers
    def test_publishers_keep_learned_entries_and_the_special_endpoint(self):
        self.run_js("""['publisherDefaults','publisherCustom','publisherStatus'].forEach((id) => el(id));
          ['publisherAddBtn','publisherSaveBtn'].forEach((id) => el(id,'button'));
          el('publisherName','input'); el('publisherSpecial','select');""")
        self.respond("GET /api/settings/publishers", {"special_providers": {"graphicaudio": "Graphic Audio"}, "publishers": [
            {"id": "tantor", "name": "Tantor Audio", "aliases": ["Tantor"], "special_provider": None, "source": "default", "enabled": True},
            {"id": "ga", "name": "Graphic Audio", "aliases": [], "special_provider": "graphicaudio", "source": "default", "enabled": True},
            {"id": "aethon", "name": "Aethon Audio", "aliases": [], "special_provider": None, "source": "learned", "enabled": True},
        ]})
        self.run_js("fns.initializePublisherSettings();")
        self.assertEqual(self.json("registry.publisherDefaults.children.length"), 2)
        detail = self.run_js("registry.publisherDefaults.children[1].children[1].children[1].textContent")
        self.assertEqual(detail, "→ Graphic Audio endpoint")
        self.run_js("registry.publisherName.value = 'Podium'; registry.publisherSpecial.value = 'graphicaudio';")
        self.run_js("registry.publisherAddBtn.fire('click');")
        self.respond("PUT /api/settings/publishers", {"publishers": []})
        self.run_js("registry.publisherSaveBtn.fire('click');")
        body = json.loads(self.run_js("JSON.stringify(calls.filter(c => c.method === 'PUT')[0].body)"))
        self.assertEqual(body["disabled_defaults"], [])
        self.assertEqual(body["custom_publishers"], [
            {"id": "aethon", "name": "Aethon Audio", "aliases": [], "special_provider": None, "source": "learned", "enabled": True},
            {"id": "podium", "name": "Podium", "aliases": [], "special_provider": "graphicaudio", "source": "custom", "enabled": True},
        ])

    # ------------------------------------------------------------ author names
    def make_authors(self, scheme=False, origin="upgraded"):
        self.run_js("""['authorNameDefaults','authorNameCustom','authorNameStatus','authorSchemeStatus'].forEach((id) => el(id));
          ['authorNameAddBtn','authorNameSaveBtn'].forEach((id) => el(id,'button'));
          ['authorNamePattern','authorNameSpelling'].forEach((id) => el(id,'input')); el('authorSchemeToggle','input');""")
        self.respond("GET /api/settings/author-names", {"scheme_enabled": scheme, "origin": origin, "names": [
            {"id": "mashton-xx", "label": "Mashton XX", "description": "part of the name", "name": "Mashton XX", "spelling": "Mashton XX", "source": "default", "enabled": True},
        ]})
        self.run_js("fns.initializeAuthorNameSettings();")

    def test_authors_show_the_switch_state_and_why(self):
        self.make_authors(scheme=False, origin="upgraded")
        self.assertFalse(self.run_js("registry.authorSchemeToggle.checked"))
        self.assertIn("updated from an earlier version", self.run_js("registry.authorSchemeStatus.textContent"))
        self.make_authors(scheme=True, origin="fresh")
        self.assertTrue(self.run_js("registry.authorSchemeToggle.checked"))
        self.assertIn("new install", self.run_js("registry.authorSchemeStatus.textContent"))

    def test_flipping_the_switch_sends_only_the_switch(self):
        self.make_authors()
        self.respond("PUT /api/settings/author-names", {"scheme_enabled": True, "origin": "upgraded", "names": []})
        self.run_js("registry.authorSchemeToggle.checked = true; registry.authorSchemeToggle.fire('change');")
        self.assertEqual(self.json("calls.filter(c => c.method === 'PUT')[0].body"), {"scheme_enabled": True})
        self.assertTrue(self.run_js("registry.authorSchemeToggle.checked"))

    def test_a_failed_switch_save_puts_the_checkbox_back(self):
        self.make_authors()
        self.respond("PUT /api/settings/author-names", {"detail": "nope"}, ok=False)
        self.run_js("registry.authorSchemeToggle.checked = true; registry.authorSchemeToggle.fire('change');")
        self.assertFalse(self.run_js("registry.authorSchemeToggle.checked"))
        self.assertEqual(self.run_js("registry.authorSchemeStatus.textContent"), "Could not save the setting.")

    def test_private_author_pattern_defaults_the_spelling_to_the_name(self):
        self.make_authors()
        self.run_js("registry.authorNamePattern.value = 'TJ Klune';")
        self.run_js("registry.authorNameAddBtn.fire('click');")
        self.respond("PUT /api/settings/author-names", {"scheme_enabled": False, "origin": "upgraded", "names": []})
        self.run_js("registry.authorNameSaveBtn.fire('click');")
        body = self.json("calls.filter(c => c.method === 'PUT')[0].body")
        self.assertEqual(body, {"disabled_defaults": [], "custom_names": [
            {"id": "custom-tjklune", "label": "TJ Klune", "description": "", "name": "TJ Klune", "spelling": "TJ Klune", "enabled": True}]})
        self.assertNotIn("scheme_enabled", body)

    # ------------------------------------------------------- upgrade notice
    def notice_buttons(self):
        return self.json("(() => { const d = document.body.children[0]; return d ? d.find(n => n.tagName === 'button').map(b => b.textContent) : null })()")

    def test_notice_is_shown_once_for_an_upgrade_with_three_choices(self):
        self.respond("GET /api/install-state", {"author_notice_pending": True, "author_scheme_enabled": False, "origin": "upgraded"})
        self.run_js("fns.initializeAuthorNameNotice();")
        self.assertEqual(self.notice_buttons(), ["Keep it off", "Turn it on", "Open Author names settings"])
        self.assertTrue(self.run_js("document.body.children[0].opened"))
        text = self.run_js("document.body.children[0].text()")
        self.assertIn("switched off", text)
        self.assertIn("Settings, Author names", text)

    def test_no_notice_for_fresh_installs_or_when_already_acknowledged(self):
        self.respond("GET /api/install-state", {"author_notice_pending": False, "author_scheme_enabled": True, "origin": "fresh"})
        self.run_js("fns.initializeAuthorNameNotice();")
        self.assertEqual(self.json("document.body.children.length"), 0)

    def test_no_notice_and_no_error_when_the_state_endpoint_is_unavailable(self):
        self.run_js("fns.initializeAuthorNameNotice();")
        self.assertEqual(self.json("document.body.children.length"), 0)

    def test_keep_acknowledges_without_turning_it_on(self):
        self.respond("GET /api/install-state", {"author_notice_pending": True})
        self.respond("POST /api/install-state/ack-author-notice", {"author_notice_pending": False})
        self.run_js("fns.initializeAuthorNameNotice();")
        self.run_js("document.body.children[0].find(n => n.tagName === 'button')[0].fire('click');")
        self.assertEqual(self.json("calls.map(c => c.method + ' ' + c.url)"),
                         ["GET /api/install-state", "POST /api/install-state/ack-author-notice"])
        self.assertTrue(self.run_js("document.body.children[0].closed"))

    def test_turn_on_saves_the_switch_then_acknowledges(self):
        self.respond("GET /api/install-state", {"author_notice_pending": True})
        self.respond("PUT /api/settings/author-names", {"scheme_enabled": True})
        self.respond("POST /api/install-state/ack-author-notice", {"author_notice_pending": False})
        self.run_js("fns.initializeAuthorNameNotice();")
        self.run_js("document.body.children[0].find(n => n.tagName === 'button')[1].fire('click');")
        self.assertEqual(self.json("calls.map(c => c.method + ' ' + c.url)"),
                         ["GET /api/install-state", "PUT /api/settings/author-names", "POST /api/install-state/ack-author-notice"])
        self.assertEqual(self.json("calls[1].body"), {"scheme_enabled": True})

    def test_open_settings_acknowledges_and_navigates(self):
        self.respond("GET /api/install-state", {"author_notice_pending": True})
        self.respond("POST /api/install-state/ack-author-notice", {"author_notice_pending": False})
        self.run_js("fns.initializeAuthorNameNotice();")
        self.run_js("document.body.children[0].find(n => n.tagName === 'button')[2].fire('click');")
        self.assertEqual(self.run_js("window.location.href"), "/settings#author-names")


class StaticPageTests(unittest.TestCase):
    def test_settings_page_has_the_ids_the_scripts_need_and_loads_the_shared_component(self):
        html = (STATIC / "settings.html").read_text(encoding="utf-8")
        for element_id in (
            "titleNoiseDefaults", "titleNoiseCustom", "titleNoiseStatus", "titleNoiseAddBtn", "titleNoiseSaveBtn",
            "titleNoiseLabel", "titleNoisePattern", "publisherDefaults", "publisherCustom", "publisherStatus",
            "publisherAddBtn", "publisherSaveBtn", "publisherName", "publisherSpecial", "authorSchemeToggle",
            "authorSchemeStatus", "authorNameDefaults", "authorNameCustom", "authorNameStatus", "authorNameAddBtn",
            "authorNameSaveBtn", "authorNamePattern", "authorNameSpelling",
        ):
            self.assertIn(f'id="{element_id}"', html, element_id)
        self.assertIn('href="#author-names"', html)
        self.assertLess(html.index("pattern-settings.js"), html.index("ui-preferences.js"))
        self.assertEqual(html.count("<h3>Known patterns</h3>"), 3)
        self.assertEqual(html.count("<h3>Private patterns</h3>"), 3)


if __name__ == "__main__":
    unittest.main()
