// Taklifnoma Studio (CP27): the only script. Everything works without it; it
// adds the "Nusxalash" (copy) button on the result page. Same origin only.
(function () {
  "use strict";
  var buttons = document.querySelectorAll("[data-copy]");
  Array.prototype.forEach.call(buttons, function (button) {
    var input = document.getElementById(button.getAttribute("data-copy"));
    if (!input) return;
    button.hidden = false;
    button.addEventListener("click", function () {
      var done = function () {
        button.textContent = button.getAttribute("data-done");
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(input.value).then(done, function () {
          input.select();
        });
      } else {
        input.select();
        try {
          if (document.execCommand("copy")) done();
        } catch (e) {
          /* the link stays selected for a manual copy */
        }
      }
    });
  });
})();
