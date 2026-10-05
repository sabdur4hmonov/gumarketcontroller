// Runs the REAL static/js/music.js against a minimal DOM and a counting fake
// Web Audio API. Prints JSON: how many audio contexts and notes existed before
// any tap, after the first tap, and whether the second tap paused.
//
//   node tests/js/music.mjs <path-to-music.js> <track>
//
// The rule tests/test_page_js.py asserts: NOTHING sounds until the visitor
// taps -- no AudioContext is even created -- and a tap starts it.
import { readFileSync } from "node:fs";
import vm from "node:vm";

const [, , scriptPath, track] = process.argv;

const counts = { contexts: 0, notes: 0, suspended: 0, intervals: 0 };

class FakeParam {
  setValueAtTime() {}
  exponentialRampToValueAtTime() {}
}

class FakeContext {
  constructor() {
    counts.contexts += 1;
    this.currentTime = 0;
    this.destination = {};
  }
  createGain() {
    return { gain: Object.assign(new FakeParam(), { value: 1 }), connect() {} };
  }
  createOscillator() {
    return {
      type: "sine",
      frequency: new FakeParam(),
      connect() {},
      start() {
        counts.notes += 1;
      },
      stop() {},
    };
  }
  resume() {}
  suspend() {
    counts.suspended += 1;
  }
}

const listeners = {};
const attrs = { "data-track": track, "aria-pressed": "false" };
const button = {
  hidden: true,
  classList: { add() {}, remove() {} },
  getAttribute: (name) => (name in attrs ? attrs[name] : null),
  setAttribute: (name, value) => {
    attrs[name] = value;
  },
  addEventListener(type, fn) {
    (listeners[type] ||= []).push(fn);
  },
};

const sandbox = {
  document: {
    getElementById: (id) => (id === "music" ? button : null),
    addEventListener() {},
    hidden: false,
  },
  window: {
    AudioContext: FakeContext,
    setInterval: () => {
      counts.intervals += 1;
      return 1;
    },
    clearInterval() {},
  },
  Math,
};
sandbox.window.document = sandbox.document;

vm.runInNewContext(readFileSync(scriptPath, "utf-8"), sandbox);
const before = { ...counts, shown: !button.hidden };
for (const fn of listeners.click || []) fn();
const afterTap = { ...counts, pressed: attrs["aria-pressed"] };
for (const fn of listeners.click || []) fn();
const afterSecond = { ...counts, pressed: attrs["aria-pressed"] };
console.log(JSON.stringify({ before, afterTap, afterSecond }));
