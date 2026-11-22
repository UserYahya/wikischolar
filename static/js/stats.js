// Statistics page: show the custom date fields only when "Custom" is picked (without JS they are
// always shown; the server ignores them for the other choices). Typing a date picks "Custom".
(function () {
  var form = document.getElementById("statsForm");
  if (!form) return;
  var blocks = form.querySelectorAll("[data-when]");
  function sync() {
    blocks.forEach(function (el) {
      var select = form.elements[el.dataset.when];
      el.hidden = !select || select.value !== el.dataset.value;
    });
  }
  ["range", "cmp"].forEach(function (name) {
    var select = form.elements[name];
    if (select) select.addEventListener("change", sync);
  });
  blocks.forEach(function (el) {
    el.addEventListener("input", function () {
      var select = form.elements[el.dataset.when];
      if (select) select.value = el.dataset.value;
    });
  });
  sync();
})();
