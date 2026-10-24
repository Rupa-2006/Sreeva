// New booking on phones: three short steps (Customer → Event → Price).
// On wider screens everything stays on one page; this only shows/hides groups.
(function () {
  var main = document.querySelector(".bf-main");
  var steps = main ? main.querySelectorAll(".bf-step") : [];
  if (steps.length !== 3) return;
  var nav = main.querySelector(".bf-steps");
  var bar = nav.querySelector(".bf-progress span");
  var current = 1;
  var phone = window.matchMedia("(max-width: 760px)");

  function show(n, scroll) {
    current = Math.max(1, Math.min(3, n));
    steps.forEach(function (s) { s.classList.toggle("on", +s.dataset.step === current); });
    nav.querySelectorAll("[data-go]").forEach(function (b) {
      var g = +b.dataset.go;
      b.classList.toggle("on", g === current);
      b.classList.toggle("done", g < current);
      b.setAttribute("aria-current", g === current ? "step" : "false");
    });
    bar.style.width = ((current - 1) / 2 * 100) + "%";
    main.dataset.current = current;
    if (scroll && phone.matches) window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // fields that must be filled before moving on from a step
  function missing(step) {
    var bad = null;
    steps[step - 1].querySelectorAll("input[required], select[required]").forEach(function (el) {
      if (bad || el.disabled || el.closest(".session-card.removed") || el.type === "hidden") return;
      if (!String(el.value || "").trim()) bad = el;
    });
    return bad;
  }
  function flag(el) {
    var field = el.closest(".field") || el.parentNode;
    field.classList.add("need");
    el.focus({ preventScroll: true });
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.addEventListener("input", function () { field.classList.remove("need"); }, { once: true });
    el.addEventListener("change", function () { field.classList.remove("need"); }, { once: true });
  }

  // every event needs at least one item; returns the first event card with none
  function cardWithoutItems() {
    var st = document.getElementById("id_status");
    if (st && st.value !== "confirmed") return null;
    var cards = main.querySelectorAll(".session-card:not(.removed)");
    for (var i = 0; i < cards.length; i++) {
      var inputs = cards[i].querySelectorAll(".res-item input[type=number]");
      if (!inputs.length) continue;
      var any = Array.prototype.some.call(inputs, function (el) { return (parseInt(el.value || "0", 10) || 0) > 0; });
      if (!any) return cards[i];
    }
    return null;
  }
  function flagItems(card) {
    var msg = card.querySelector(".items-error");
    if (msg) { msg.hidden = false; msg.classList.remove("pop"); void msg.offsetWidth; msg.classList.add("pop"); }
    (msg || card).scrollIntoView({ behavior: "smooth", block: "center" });
  }
  main.addEventListener("input", function (e) {
    var card = e.target.closest(".session-card");
    if (card && e.target.closest(".res-item") && (parseInt(e.target.value || "0", 10) || 0) > 0) {
      var msg = card.querySelector(".items-error");
      if (msg) msg.hidden = true;
    }
  });

  function go(target) {
    if (phone.matches && target > current) {
      for (var s = current; s < target; s++) {
        var bad = missing(s);
        if (bad) { show(s); flag(bad); return; }
        if (s === 2) {
          var card = cardWithoutItems();
          if (card) { show(2); flagItems(card); return; }
        }
      }
    }
    show(target, true);
  }

  // the * on Items only shows when items are needed (not for an enquiry)
  function markRequired() {
    var st = document.getElementById("id_status");
    var enquiry = st && st.value !== "confirmed";
    main.querySelectorAll("[data-items-req]").forEach(function (s) { s.hidden = enquiry; });
    if (enquiry) main.querySelectorAll(".items-error").forEach(function (m) { m.hidden = true; });
  }
  var stSel = document.getElementById("id_status");
  if (stSel) stSel.addEventListener("change", markRequired);
  new MutationObserver(markRequired).observe(document.getElementById("sessions"), { childList: true });
  markRequired();

  var form = main.closest("form");
  if (form) form.addEventListener("submit", function (e) {
    var card = cardWithoutItems();
    if (card) { e.preventDefault(); e.stopImmediatePropagation(); show(2); flagItems(card); }
  }, true);

  nav.addEventListener("click", function (e) {
    var b = e.target.closest("[data-go]");
    if (b) go(+b.dataset.go);
  });
  main.addEventListener("click", function (e) {
    var b = e.target.closest("[data-step-move]");
    if (b) go(current + (+b.dataset.stepMove));
  });

  // came back from the server with a mistake: open the step that has it
  var err = main.querySelector(".errorlist, .field.has-error, .form-errors");
  var start = 1;
  if (err) {
    var holder = err.closest(".bf-step");
    start = holder ? +holder.dataset.step : 1;
  }
  main.classList.add("stepped");
  show(start);
})();
