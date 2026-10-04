/* Every page's behaviour, in one small file served from this origin.
 *
 * The Content-Security-Policy forbids inline script, so nothing here is
 * generated per page: whatever a page needs (where to POST, the No button's
 * lines, the event time) arrives in data- attributes the server escaped.
 * Positions are set through the CSSOM, which the policy allows, never through
 * style="" attributes, which it does not.
 *
 * Works without this file: the question, the invitation and the shop's link
 * are plain HTML. Only the games and the RSVP need it.
 */
(function () {
  "use strict";

  var doc = document;
  var reduce = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  function byId(id) {
    return doc.getElementById(id);
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      // A header a plain cross-site <form> cannot send: the request needs a
      // CORS preflight, which this server never grants.
      headers: { "Content-Type": "application/json", "X-Requested-With": "gulbot" },
      body: JSON.stringify(body || {}),
      keepalive: true,
    });
  }

  /* --- envelope ------------------------------------------------------- */

  var envelope = byId("envelope");
  if (envelope) {
    var seal = byId("seal");
    var opened = false;
    var open = function () {
      if (opened) return;
      opened = true;
      envelope.classList.add("is-open");
      doc.body.classList.add("is-opened");
      window.setTimeout(function () {
        envelope.hidden = true;
      }, reduce ? 0 : 1500);
    };
    seal.addEventListener("click", open);
    envelope.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") open();
    });
    seal.focus({ preventScroll: true });
  }

  /* --- countdown ------------------------------------------------------ */

  var countdown = byId("countdown");
  if (countdown) {
    var at = Date.parse(countdown.getAttribute("data-at") || "");
    var cells = countdown.querySelectorAll("[data-unit]");
    var pad = function (n) {
      return n < 10 ? "0" + n : String(n);
    };
    var tick = function () {
      var left = Math.floor((at - Date.now()) / 1000);
      if (!(left > 0)) {
        countdown.hidden = true;
        return;
      }
      var parts = {
        d: Math.floor(left / 86400),
        h: Math.floor((left % 86400) / 3600),
        m: Math.floor((left % 3600) / 60),
        s: left % 60,
      };
      for (var i = 0; i < cells.length; i++) {
        var unit = cells[i].getAttribute("data-unit");
        cells[i].textContent = unit === "d" ? String(parts.d) : pad(parts[unit]);
      }
      window.setTimeout(tick, 1000 - (Date.now() % 1000));
    };
    if (!isNaN(at)) {
      countdown.hidden = false;
      tick();
    }
  }

  /* --- confetti ------------------------------------------------------- */

  function burst() {
    if (reduce) return;
    var style = window.getComputedStyle(doc.documentElement);
    var colours = [
      style.getPropertyValue("--accent"),
      style.getPropertyValue("--accent-2"),
      "#ffffff",
      "#ffd166",
    ];
    var box = doc.createElement("div");
    box.className = "burst";
    box.setAttribute("aria-hidden", "true");
    for (var i = 0; i < 90; i++) {
      var piece = doc.createElement("i");
      if (i % 3 === 0) piece.className = "h";
      piece.style.setProperty("--x", (Math.random() * 100).toFixed(2) + "vw");
      piece.style.setProperty("--d", (Math.random() * 0.9).toFixed(2) + "s");
      piece.style.setProperty("--t", (2.4 + Math.random() * 1.8).toFixed(2) + "s");
      piece.style.setProperty("--c", colours[i % colours.length].trim() || "#e91e63");
      piece.style.setProperty("--drift", Math.round(Math.random() * 160 - 80) + "px");
      piece.style.setProperty("--spin", Math.round(Math.random() * 900 - 450) + "deg");
      piece.style.setProperty("--w", (6 + Math.random() * 6).toFixed(1) + "px");
      box.appendChild(piece);
    }
    doc.body.appendChild(box);
    window.setTimeout(function () {
      box.remove();
    }, 6000);
  }

  /* --- Ha / Yo'q ------------------------------------------------------ */

  var yes = byId("yes");
  var no = byId("no");
  if (yes && no) {
    var lines = [];
    try {
      lines = JSON.parse(no.getAttribute("data-lines") || "[]");
    } catch (ignored) {
      lines = [];
    }
    var tries = 0;

    // Ha keeps growing, so keep clear of where it is going to be, not only
    // of where it is now.
    var farFromYes = function (x, y, w, h) {
      var r = yes.getBoundingClientRect();
      var gap = 16 + r.width * 0.35;
      return x + w < r.left - gap || x > r.right + gap || y + h < r.top - gap || y > r.bottom + gap;
    };

    var dodge = function (event) {
      if (event && event.cancelable) event.preventDefault();
      if (no.classList.contains("is-gone")) return;
      tries += 1;
      yes.style.setProperty("--yes-scale", String(Math.min(1.6, 1 + tries * 0.05)));
      no.style.setProperty("--no-scale", String(Math.max(0.62, 1 - tries * 0.03)));
      // Each line once, in order -- never the same one twice in a visit. When
      // they run out, Yo'q has nothing left to say and leaves.
      if (tries >= lines.length) {
        no.classList.add("is-gone");
        no.setAttribute("aria-hidden", "true");
        no.tabIndex = -1;
        return;
      }
      no.textContent = lines[tries];
      if (reduce) return;

      var w = no.offsetWidth;
      var h = no.offsetHeight;
      var margin = 12;
      var x = margin;
      var y = margin;
      if (!no.classList.contains("is-loose")) {
        var start = no.getBoundingClientRect();
        // Hold Yo'q's place, or Ha slides into the middle -- under the spot
        // that was just chosen as "away from Ha".
        var ghost = doc.createElement("span");
        ghost.className = "btn-ghost";
        ghost.style.width = start.width + "px";
        ghost.style.height = start.height + "px";
        no.parentNode.insertBefore(ghost, no);
        no.style.left = start.left + "px";
        no.style.top = start.top + "px";
        no.classList.add("is-loose");
        void no.offsetWidth; // commit the start position so the move animates
      }
      for (var attempt = 0; attempt < 40; attempt++) {
        x = margin + Math.random() * Math.max(1, window.innerWidth - w - 2 * margin);
        y = margin + Math.random() * Math.max(1, window.innerHeight - h - 2 * margin);
        if (farFromYes(x, y, w, h)) break;
      }
      no.style.left = Math.round(x) + "px";
      no.style.top = Math.round(y) + "px";
    };

    no.addEventListener("pointerenter", function (event) {
      if (event.pointerType === "mouse") dodge(event);
    });
    no.addEventListener("touchstart", dodge, { passive: false });
    no.addEventListener("click", dodge);

    yes.addEventListener("click", function () {
      if (yes.disabled) return;
      yes.disabled = true;
      no.classList.add("is-gone");
      byId("ask").hidden = true;
      byId("answers").hidden = true;
      byId("celebrate").hidden = false;
      burst();
      post(yes.getAttribute("data-post")).catch(function () {
        /* the celebration does not depend on the server */
      });
    });
  }

  /* --- RSVP ----------------------------------------------------------- */

  var form = byId("rsvp-form");
  if (form) {
    var done = byId("rsvp-done");
    var error = byId("rsvp-error");
    var guestsBox = byId("rsvp-guests");
    var count = byId("rsvp-count");
    var guests = 1;

    var answer = function () {
      var checked = form.querySelector("input[name=answer]:checked");
      return checked ? checked.value : "";
    };
    var sync = function () {
      guestsBox.hidden = answer() !== "yes";
    };
    form.addEventListener("change", sync);
    sync();

    byId("rsvp-minus").addEventListener("click", function () {
      guests = Math.max(1, guests - 1);
      count.textContent = String(guests);
    });
    byId("rsvp-plus").addEventListener("click", function () {
      guests = Math.min(10, guests + 1);
      count.textContent = String(guests);
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var chosen = answer();
      if (!chosen) {
        error.hidden = false;
        return;
      }
      error.hidden = true;
      var button = form.querySelector("button[type=submit]");
      button.disabled = true;
      post(form.getAttribute("data-post"), {
        answer: chosen,
        guests: chosen === "yes" ? guests : 0,
        name: (byId("rsvp-name").value || "").slice(0, 60),
      })
        .then(function (response) {
          if (!response.ok) throw new Error(String(response.status));
          form.hidden = true;
          done.textContent = form.getAttribute(chosen === "yes" ? "data-thanks-yes" : "data-thanks-no");
          done.hidden = false;
          if (chosen === "yes") burst();
        })
        .catch(function () {
          button.disabled = false;
          error.textContent = form.getAttribute("data-failed");
          error.hidden = false;
        });
    });
  }
})();
