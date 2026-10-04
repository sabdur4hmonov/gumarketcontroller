// Runs the REAL static/js/page.js against a minimal DOM and presses Yo'q until
// it is gone. Prints JSON: the label after each press, and when it vanished.
//
//   node tests/js/no_button.mjs <path-to-page.js> <lines-json>
//
// Not a browser: only what page.js touches on a Ha/Yo'q page is modelled. The
// point is the escalation rule -- every press a NEW line, in order, never a
// repeat, and gone when they run out -- which tests/test_page_js.py asserts.
import { readFileSync } from "node:fs";
import vm from "node:vm";

const [, , scriptPath, linesJson] = process.argv;

function element(id, attrs = {}) {
  const classes = new Set();
  return {
    id,
    attrs,
    hidden: false,
    textContent: "",
    tabIndex: 0,
    disabled: false,
    offsetWidth: 100,
    offsetHeight: 50,
    listeners: {},
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
    },
    style: { setProperty() {} },
    parentNode: { insertBefore() {} },
    addEventListener(type, fn) {
      (this.listeners[type] ||= []).push(fn);
    },
    getAttribute(name) {
      return name in this.attrs ? this.attrs[name] : null;
    },
    setAttribute(name, value) {
      this.attrs[name] = value;
    },
    getBoundingClientRect() {
      return { left: 130, top: 300, right: 230, bottom: 350, width: 100, height: 50 };
    },
    querySelector() {
      return null;
    },
    appendChild() {},
    remove() {},
    focus() {},
  };
}

const no = element("no", { "data-lines": linesJson });
const elements = {
  yes: element("yes", { "data-post": "/p/x/yes" }),
  no,
  ask: element("ask"),
  answers: element("answers"),
  celebrate: element("celebrate"),
};
const sandbox = {
  document: {
    getElementById: (id) => elements[id] || null,
    documentElement: {},
    body: { classList: element("body").classList, appendChild() {} },
    createElement: () => element("x"),
  },
  window: {
    matchMedia: () => ({ matches: false }),
    innerWidth: 360,
    innerHeight: 780,
    getComputedStyle: () => ({ getPropertyValue: () => "#000" }),
    setTimeout: () => 0,
  },
  fetch: () => Promise.resolve({ ok: true, json: () => ({}) }),
  JSON,
  Math,
  String,
  Date,
  isNaN,
  parseInt,
};
vm.runInNewContext(readFileSync(scriptPath, "utf8"), sandbox);

const seen = [];
let goneAfter = null;
for (let press = 1; press <= 40; press++) {
  for (const fn of no.listeners.touchstart || []) {
    fn({ cancelable: true, preventDefault() {} });
  }
  if (no.classList.contains("is-gone")) {
    goneAfter = press;
    break;
  }
  seen.push(no.textContent);
}
console.log(JSON.stringify({ seen, goneAfter }));
