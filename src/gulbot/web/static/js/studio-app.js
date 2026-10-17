// Taklifnoma Studio inside Telegram (CP27.4). Telegram puts the launch data in
// the URL fragment (#tgWebAppData=...). It is read here, removed from the
// address bar, and posted to our own server, which checks it with THIS shop's
// bot token. No telegram.org script is loaded; nothing leaves this origin.
(function () {
  "use strict";
  var root = document.getElementById("webapp");
  if (!root) return;
  var data = new URLSearchParams(window.location.hash.slice(1)).get("tgWebAppData");
  if (window.history && window.history.replaceState) {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }
  function show(which) {
    document.getElementById("wa-wait").hidden = true;
    document.getElementById("wa-" + which).hidden = false;
  }
  if (!data || !root.getAttribute("data-shop")) {
    show("missing");
    return;
  }
  fetch("/studio/webapp", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Requested-With": "gulbot" },
    body: JSON.stringify({
      shop: root.getAttribute("data-shop"),
      bot: root.getAttribute("data-bot"),
      init_data: data
    })
  })
    .then(function (response) {
      if (!response.ok) throw new Error(String(response.status));
      return response.json();
    })
    .then(function (answer) {
      window.location.replace(answer.next);
    })
    .catch(function () {
      show("refused");
    });
})();
