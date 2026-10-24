// Small progressive-enhancement helpers. Every page still works without JS.
(function () {
  // Mobile sidebar
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-nav-toggle]")) document.body.classList.toggle("nav-open");
    else if (e.target.closest(".backdrop")) document.body.classList.remove("nav-open");
  });

  // Dismiss flash messages
  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".msg .close");
    if (btn) btn.parentElement.remove();
  });

  // Whole table rows clickable
  document.addEventListener("click", function (e) {
    var row = e.target.closest("tr[data-href]");
    if (row && !e.target.closest("a, button, form")) window.location = row.dataset.href;
  });

  // Ask before destructive actions: <form data-confirm="Are you sure?">
  document.addEventListener("submit", function (e) {
    var form = e.target;
    var msg = form.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) { e.preventDefault(); return; }
    // Block double-clicks: a second submit while the first is still sending is ignored.
    if (form.method.toLowerCase() === "post") {
      if (form.dataset.submitting) { e.preventDefault(); return; }
      form.dataset.submitting = "1";
      form.querySelectorAll("button[type=submit], button:not([type])").forEach(function (b) {
        b.disabled = true;
        b.dataset.label = b.innerHTML;
        b.innerHTML = "Please wait…";
      });
    }
  });
  // If the user comes back with the browser Back button, re-enable the form.
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form[data-submitting]").forEach(function (f) {
      delete f.dataset.submitting;
      f.querySelectorAll("button[disabled]").forEach(function (b) {
        b.disabled = false;
        if (b.dataset.label) b.innerHTML = b.dataset.label;
      });
    });
  });

  // Folded optional sections (<details class="fold" data-auto-open>) open by themselves
  // when they already contain something: an edit, a restored draft, or an error.
  function openFilledFolds() {
    document.querySelectorAll("details[data-auto-open]").forEach(function (d) {
      var filled = Array.prototype.some.call(d.querySelectorAll("input:not([type=hidden]):not([type=checkbox]), textarea"),
        function (el) { return el.value && el.value.trim() !== ""; });
      if (filled || d.querySelector(".has-error, .error")) d.open = true;
    });
  }
  openFilledFolds();
  document.addEventListener("draft:restored", openFilledFolds);

  // "Show N more" buttons reveal the rest of a long list.
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-show-more]");
    if (!b) return;
    var box = document.querySelector(b.getAttribute("data-show-more"));
    if (box) box.classList.remove("collapsed");
    b.parentElement.remove();
  });
})();

// "Booking saved – send details" card on the booking page
(function () {
  var card = document.querySelector("[data-send-card]");
  if (!card) return;
  try { history.replaceState(null, "", location.pathname + location.search.replace(/([?&])saved=1(&|$)/, "$1").replace(/[?&]$/, "")); } catch (e) {}
  card.addEventListener("click", function (e) {
    if (e.target.closest("[data-send-close]")) card.hidden = true;
    if (e.target.closest("[data-send-done]")) setTimeout(function () { card.hidden = true; }, 600);
  });
})();
