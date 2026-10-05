// Runs the REAL static/js/page.js on a Konvert page (CP17): the letter's
// sections wait while the envelope is sealed, and each one is shown after
// the seal is tapped -- in order. Prints JSON for tests/test_page_js.py.
//
//   node tests/js/envelope.mjs <path-to-page.js>
import { readFileSync } from "node:fs";
import vm from "node:vm";

const [, , scriptPath] = process.argv;

function element(id) {
  const classes = new Set();
  return {
    id,
    hidden: false,
    classes,
    listeners: {},
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
    },
    addEventListener(type, fn) {
      (this.listeners[type] ||= []).push(fn);
    },
    getAttribute: () => null,
    focus() {},
  };
}

const sections = ["ornament", "eyebrow", "names", "when", "venue"].map(element);
const elements = { envelope: element("envelope"), seal: element("seal") };
const body = element("body");
const timers = [];
const sandbox = {
  document: {
    getElementById: (id) => elements[id] || null,
    querySelectorAll: (selector) => (selector === ".card > *" ? sections : []),
    body,
  },
  window: {
    matchMedia: () => ({ matches: false }),
    setTimeout: (fn, ms) => {
      timers.push([ms, fn]);
      return timers.length;
    },
    setInterval: () => 0,
  },
  fetch: () => Promise.resolve({ ok: true }),
  JSON,
  Math,
  String,
  Date,
};

vm.runInNewContext(readFileSync(scriptPath, "utf-8"), sandbox);
const sealed = {
  waiting: body.classes.has("reveal-wait"),
  shown: sections.filter((s) => s.classes.has("is-shown")).length,
};
for (const fn of elements.seal.listeners.click || []) fn();
const order = [];
timers
  .sort((a, b) => a[0] - b[0])
  .forEach(([ms, fn]) => {
    const before = new Set(sections.filter((s) => s.classes.has("is-shown")).map((s) => s.id));
    fn();
    sections
      .filter((s) => s.classes.has("is-shown") && !before.has(s.id))
      .forEach((s) => order.push([s.id, ms]));
  });
console.log(
  JSON.stringify({
    sealed,
    opened: body.classes.has("is-opened"),
    order,
    allShown: sections.every((s) => s.classes.has("is-shown")),
  }),
);
