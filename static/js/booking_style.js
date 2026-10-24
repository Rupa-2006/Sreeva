// New-booking form look & feel (runs after booking_form.js; changes no data):
//  - dropdowns marked data-chips become one-tap buttons (status, time slot)
//  - item counts get − / + buttons, and chosen items light up
//  - the "booking slip" beside the form fills in as you type
(function () {
  var form = document.querySelector("form[data-draft]");
  if (!form || !document.getElementById("sessions")) return;

  function fire(el, type) { el.dispatchEvent(new Event(type, { bubbles: true })); }
  function esc(t) { return String(t).replace(/[&<>"']/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); }

  // ---------- One-tap choice buttons ----------
  function chips(select) {
    if (select.dataset.chipsDone) return;
    select.dataset.chipsDone = "1";
    var hide = (select.dataset.chipsHide || "").split(",");
    var row = document.createElement("div");
    row.className = "seg";
    row.setAttribute("role", "radiogroup");
    var label = select.closest(".field") && select.closest(".field").querySelector("label");
    if (label) row.setAttribute("aria-label", label.textContent.replace("*", "").trim());
    Array.prototype.forEach.call(select.options, function (o) {
      if (!o.value || hide.indexOf(o.value) !== -1) return;
      var b = document.createElement("button");
      b.type = "button"; b.dataset.value = o.value; b.setAttribute("role", "radio");
      b.textContent = o.textContent.replace(/\s*\(.*\)\s*$/, "");   // "Morning (6 AM – 1 PM)" -> "Morning"
      var hint = (o.textContent.match(/\((.*)\)/) || [])[1];
      if (hint) b.title = hint;
      b.addEventListener("click", function () { select.value = o.value; fire(select, "change"); paintChips(); });
      row.appendChild(b);
    });
    select.classList.add("chips-hidden");
    select.insertAdjacentElement("afterend", row);
    function paintChips() {
      row.querySelectorAll("button").forEach(function (b) {
        var on = b.dataset.value === select.value;
        b.classList.toggle("on", on); b.setAttribute("aria-checked", on);
      });
    }
    select.addEventListener("change", paintChips);
    paintChips();
  }

  // ---------- − / + on item counts ----------
  function stepper(input) {
    if (input.dataset.stepDone) return;
    input.dataset.stepDone = "1";
    var wrap = document.createElement("span");
    wrap.className = "stepper";
    input.parentNode.insertBefore(wrap, input);
    var minus = document.createElement("button"), plus = document.createElement("button");
    minus.type = plus.type = "button";
    minus.textContent = "−"; plus.textContent = "+";
    minus.setAttribute("aria-label", "One less"); plus.setAttribute("aria-label", "One more");
    wrap.appendChild(minus); wrap.appendChild(input); wrap.appendChild(plus);
    function step(d) {
      var v = Math.max(0, Math.min(99, (parseInt(input.value || "0", 10) || 0) + d));
      input.value = v; fire(input, "input"); fire(input, "change");
    }
    minus.addEventListener("click", function () { step(-1); });
    plus.addEventListener("click", function () { step(1); });
  }
  function lightItems() {
    form.querySelectorAll(".res-item").forEach(function (item) {
      var inp = item.querySelector("input");
      item.classList.toggle("picked", !!inp && (parseInt(inp.value || "0", 10) || 0) > 0);
    });
  }

  function enhance(root) {
    root.querySelectorAll("select[data-chips]").forEach(chips);
    root.querySelectorAll(".res-item input[type=number]").forEach(stepper);
    lightItems();
  }
  enhance(form);
  // new "Add another event date" cards
  new MutationObserver(function (list) {
    list.forEach(function (m) { m.addedNodes.forEach(function (n) { if (n.nodeType === 1) enhance(n); }); });
  }).observe(document.getElementById("sessions"), { childList: true });

  // ---------- Booking slip ----------
  var slip = document.querySelector(".bf-slip");
  function val(id) { var el = document.getElementById(id); return el ? el.value.trim() : ""; }
  function selText(id) { var el = document.getElementById(id); return el && el.selectedIndex >= 0 ? el.options[el.selectedIndex].textContent : ""; }
  function niceDate(v) {
    if (!v) return "";
    var d = new Date(v + "T00:00:00");
    return isNaN(d) ? v : d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
  }
  function render() {
    lightItems();
    var total = (document.getElementById("booking-total") || {}).textContent || "₹0";
    document.querySelectorAll("[data-slip-total]").forEach(function (el) { el.textContent = total; });
    if (!slip) return;
    var name = val("id_client_name"), phone = val("id_client_phone");
    slip.querySelector('[data-slip="customer"]').textContent = name || "Customer name";
    slip.querySelector('[data-slip="customer"]').classList.toggle("empty", !name);
    slip.querySelector('[data-slip="phone"]').textContent = phone || "Phone number";
    slip.querySelector('[data-slip="type"]').textContent = selText("id_event_type");
    var st = document.getElementById("id_status");
    var stEl = slip.querySelector('[data-slip="status"]');
    stEl.textContent = selText("id_status"); stEl.className = "slip-status " + (st ? st.value : "");
    var html = "";
    form.querySelectorAll(".session-card:not(.removed)").forEach(function (card) {
      function f(n) { return card.querySelector('[name$="-' + n + '"]'); }
      var date = f("date") ? f("date").value : "", slot = f("slot");
      var slotText = slot && slot.selectedIndex >= 0 ? slot.options[slot.selectedIndex].textContent.replace(/\s*\(.*\)\s*$/, "") : "";
      var items = [];
      card.querySelectorAll(".res-item").forEach(function (it) {
        var q = parseInt((it.querySelector("input") || {}).value || "0", 10) || 0;
        var lbl = it.querySelector("label");
        if (q > 0 && lbl) items.push(q + " " + lbl.childNodes[0].textContent.trim());
      });
      var fn = f("name") ? f("name").value.trim() : "", place = f("place") ? f("place").value.trim() : "";
      var amount = f("amount") ? parseFloat(f("amount").value || "0") || 0 : 0;
      html += "<li><div class='se-top'><b>" + esc(date ? niceDate(date) : "Pick a date") + "</b>" +
        (slotText ? "<span>" + esc(slotText) + "</span>" : "") + "</div>" +
        (fn ? "<div class='se-line'>" + esc(fn) + "</div>" : "") +
        (place ? "<div class='se-line muted'>" + esc(place.replace(/https?:\/\/\S+/, "").trim() || "Location on map") + "</div>" : "") +
        "<div class='se-line muted'>" + (items.length ? esc(items.join(", ")) : "No items yet") + "</div>" +
        (amount ? "<div class='se-amt'>₹" + amount.toLocaleString("en-IN") + "</div>" : "") + "</li>";
    });
    slip.querySelector('[data-slip="events"]').innerHTML = html;
  }
  var queued = false;
  function soon() { if (queued) return; queued = true; requestAnimationFrame(function () { queued = false; render(); }); }
  form.addEventListener("input", soon);
  form.addEventListener("change", soon);
  form.addEventListener("click", function () { setTimeout(soon, 0); });
  document.addEventListener("draft:restored", function () {
    form.querySelectorAll("select[data-chips]").forEach(function (s) { fire(s, "change"); });
    soon();
  });
  // the total is written by booking_form.js; watch it so the slip always matches
  var totalEl = document.getElementById("booking-total");
  if (totalEl) new MutationObserver(soon).observe(totalEl, { childList: true, characterData: true, subtree: true });
  render();
})();
