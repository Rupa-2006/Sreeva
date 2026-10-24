// Booking form: add/remove event dates, live availability, existing-client lookup.
(function () {
  var root = document.getElementById("sessions");
  if (!root) return;
  var total = document.getElementById("id_sessions-TOTAL_FORMS");
  var template = document.getElementById("session-template").innerHTML;
  var availUrl = root.dataset.availabilityUrl;
  var bookingId = root.dataset.bookingId || "";

  function cards() {
    return Array.prototype.slice.call(root.querySelectorAll(".session-card:not(.removed)"));
  }

  function renumber() {
    cards().forEach(function (card, i) {
      var n = card.querySelector(".s-num");
      if (n) n.textContent = "Event " + (i + 1);
    });
    var only = cards().length === 1;
    cards().forEach(function (card) {
      var rm = card.querySelector("[data-remove]");
      if (rm) rm.style.visibility = only ? "hidden" : "visible";
    });
  }

  function field(card, name) {
    return card.querySelector('[name$="-' + name + '"]');
  }

  function toggleTimes(card) {
    var slot = field(card, "slot");
    card.querySelectorAll(".time-fields").forEach(function (el) {
      el.classList.toggle("show", slot && slot.value === "custom");
    });
  }

  function paint(card, data) {
    var byId = {};
    (data.resources || []).forEach(function (r) { byId[r.id] = r; });
    card.querySelectorAll(".res-item").forEach(function (item) {
      var r = byId[item.dataset.resource];
      var badge = item.querySelector(".avail");
      var input = item.querySelector("input");
      if (!r || !badge) return;
      badge.textContent = r.free + " of " + r.total + " free";
      badge.className = "avail " + (r.free === 0 ? "none" : r.free < r.total ? "low" : "ok");
      var want = parseInt(input.value || "0", 10);
      item.classList.toggle("over", want > r.free);
      item.title = r.used ? r.used + " already booked at this time" : "All available";
    });
    var note = card.querySelector(".clash-note");
    if (note) {
      note.textContent = data.clashes && data.clashes.length
        ? "Other shoots at this time: " + data.clashes.join(" · ")
        : "";
    }
    var status = card.querySelector(".avail-status");
    if (status) status.textContent = "Free on this date";
  }

  function check(card) {
    var date = field(card, "date"), slot = field(card, "slot");
    var status = card.querySelector(".avail-status");
    if (!date || !date.value) {
      if (status) status.textContent = "Pick a date to see what's free";
      // no date yet: show how many the studio has, so the space is never blank
      var counts = {};
      try { counts = JSON.parse(document.getElementById("resource-rates").textContent || "{}"); } catch (e) {}
      card.querySelectorAll(".res-item").forEach(function (item) {
        var b = item.querySelector(".avail"), r = counts[item.dataset.resource];
        if (!b) return;
        b.className = "avail total";
        b.textContent = r && r.count != null ? r.count + " in studio" : "";
      });
      return;
    }
    var params = new URLSearchParams({ date: date.value, slot: slot.value, booking: bookingId });
    if (slot.value === "custom") {
      var s = field(card, "start_time"), e = field(card, "end_time");
      if (!s.value || !e.value) return;
      params.set("start", s.value); params.set("end", e.value);
    }
    if (status) status.textContent = "Checking…";
    fetch(availUrl + "?" + params.toString(), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) { if (status) status.textContent = data.error; return; }
        card._avail = data;
        paint(card, data);
      })
      .catch(function () { if (status) status.textContent = "Couldn't check availability"; });
  }

  function init(card) {
    toggleTimes(card);
    card.addEventListener("change", function (e) {
      var n = e.target.name || "";
      if (/-(slot)$/.test(n)) toggleTimes(card);
      if (/-(date|slot|start_time|end_time)$/.test(n)) check(card);
    });
    card.addEventListener("input", function (e) {
      if (e.target.closest(".res-item") && card._avail) paint(card, card._avail);
    });
    var rm = card.querySelector("[data-remove]");
    if (rm) rm.addEventListener("click", function () {
      var del = field(card, "DELETE");
      if (del) del.checked = true;
      card.classList.add("removed");
      renumber();
    });
    check(card);
  }

  // ---------------------------------------------------------------------
  // Pricing
  //
  // 1. The owner enters what the customer needs (photographers, drone…).
  // 2. The best-value package is picked automatically:
  //      cost(package) = package price + extras it doesn't cover × their rates
  //      cost(no package) = every item × its rate
  //    and the cheapest wins. The owner can still choose a package by hand.
  // 3. Extra charges (delivery, travel, extra album…) and discounts are added on top.
  // 4. The owner can type any final price; it's then marked "Custom price"
  //    with a one-click way back to the calculated price.
  // ---------------------------------------------------------------------
  var packages = {}, rates = {};
  try { packages = JSON.parse((document.getElementById("package-data") || {}).textContent || "{}"); } catch (e) {}
  try { rates = JSON.parse((document.getElementById("resource-rates") || {}).textContent || "{}"); } catch (e) {}
  var anyRate = Object.keys(rates).some(function (k) { return rates[k].rate > 0; });
  var hasPackages = Object.keys(packages).length > 0;
  var eventType = document.getElementById("id_event_type");
  function inr(n) { return "₹" + Math.round(n).toLocaleString("en-IN"); }
  function escapeHtml(t) { return String(t).replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  // Only touch the page when the text really changes, so a button the user is
  // about to click is never swapped out under the mouse.
  function setHtml(el, html) { if (el && el._html !== html) { el.innerHTML = html; el._html = html; } }

  // --- Extra charges, kept as JSON in a hidden box the server checks --------
  function chargesInput(card) { return card.querySelector("[data-charges-input]"); }
  function readCharges(card) {
    var inp = chargesInput(card);
    try { var v = JSON.parse((inp && inp.value) || "[]"); return Array.isArray(v) ? v : []; } catch (e) { return []; }
  }
  function writeCharges(card) {
    var out = [];
    card.querySelectorAll(".charge-row").forEach(function (r) {
      var label = r.querySelector(".cl").value.trim();
      var amt = Math.abs(parseFloat(r.querySelector(".ca").value || "0") || 0);
      if (!amt) return;
      out.push({ label: label || (r.dataset.neg ? "Discount" : "Extra charge"), amount: r.dataset.neg ? -amt : amt });
    });
    var inp = chargesInput(card);
    if (inp) inp.value = JSON.stringify(out);
  }
  function chargeRow(card, label, amount, negative) {
    var row = document.createElement("div");
    row.className = "charge-row";
    if (negative) row.dataset.neg = "1";
    row.innerHTML = '<input class="cl" type="text" maxlength="60" placeholder="What for? e.g. Delivery">' +
      '<input class="ca" type="number" min="0" step="1" placeholder="' + (negative ? "Discount ₹" : "Amount ₹") + '">' +
      '<button type="button" class="x" title="Remove" aria-label="Remove this charge">×</button>';
    row.querySelector(".cl").value = label || "";
    if (amount) row.querySelector(".ca").value = Math.abs(amount);
    card.querySelector(".charge-rows").appendChild(row);
    return row;
  }
  function renderCharges(card) {
    var box = card.querySelector(".charge-rows");
    if (!box) return;
    box.innerHTML = "";
    readCharges(card).forEach(function (c) { chargeRow(card, c.label, c.amount, parseFloat(c.amount) < 0); });
  }

  // --- Price of the team -------------------------------------------------------
  // The package box only exists when the studio has packages.
  function pkgVal(card) { var sel = field(card, "package"); return sel ? sel.value : ""; }

  function needs(card) {
    var n = {};
    card.querySelectorAll(".res-item input").forEach(function (inp) { n[inp.dataset.resource] = parseInt(inp.value || "0", 10) || 0; });
    return n;
  }
  // deduct = true only when the owner chose the package by hand and then removed items
  function teamCost(card, pk, deduct) {
    var total = pk ? parseFloat(pk.price) || 0 : 0;
    var parts = pk ? ["<b>" + escapeHtml(pk.name) + "</b> " + inr(total)] : [];
    var n = needs(card);
    Object.keys(n).forEach(function (rid) {
      var r = rates[rid];
      if (!r || !r.rate) return;
      var diff = n[rid] - (pk ? (pk.items[rid] || 0) : 0);
      if (diff < 0 && !deduct) return;
      if (!diff) return;
      total += diff * r.rate;
      var label = Math.abs(diff) + " " + escapeHtml(r.name) + " × " + inr(r.rate);
      parts.push((diff > 0 ? (parts.length ? "+ " : "") + (pk ? "extra " : "") : "− ") + label);
    });
    return { total: Math.max(total, 0), parts: parts };
  }

  // Packages include more than people (albums, editing…), so they're compared
  // with each other, not with per-item prices. Among the packages for this event
  // type, pick the lowest total = package price + extras it doesn't cover.
  // Only when no package fits is the price built from per-item rates.
  function bestPackage(card) {
    var n = needs(card);
    var wanted = Object.keys(n).some(function (k) { return n[k] > 0; });
    if (!wanted) return null;
    var type = eventType ? eventType.value : "";
    var best = null;
    Object.keys(packages).forEach(function (id) {
      var pk = packages[id];
      if (pk.event_type && type && pk.event_type !== type) return;
      // a package must include at least one thing the customer asked for
      var covers = Object.keys(n).some(function (rid) { return n[rid] > 0 && (pk.items[rid] || 0) > 0; });
      if (!covers) return;
      var c = teamCost(card, pk, false).total;
      if (!best || c < best.cost) best = { id: id, cost: c };
    });
    if (best) return best;
    return anyRate ? { id: "", cost: teamCost(card, null, false).total } : null;
  }

  function autoPick(card) {
    var sel = field(card, "package"), note = card.querySelector(".pick-note");
    if (!sel || card.dataset.pkgMode !== "auto") return;
    var best = bestPackage(card);
    if (!best) { sel.value = ""; setHtml(note, ""); return; }
    sel.value = best.id;
    var fold = sel.closest("details");
    if (fold && best.id) fold.open = true;  // show which package was picked
    setHtml(note, best.id
      ? "✨ Auto-picked <b>" + escapeHtml(packages[best.id].name) + "</b>"
      : "✨ No package for this event type — priced per item");
  }

  function calc(card) {
    var sel = field(card, "package");
    var pk = sel && packages[sel.value];
    var r = teamCost(card, pk, card.dataset.pkgMode === "manual");
    readCharges(card).forEach(function (c) {
      var a = parseFloat(c.amount) || 0;
      if (!a) return;
      r.total += a;
      r.parts.push((a < 0 ? "− " : (r.parts.length ? "+ " : "")) + escapeHtml(c.label) + " " + inr(Math.abs(a)));
    });
    r.total = Math.max(r.total, 0);
    return r;
  }

  // Each item box: "₹2,000 each" and, when chosen, "2 × ₹2,000 = ₹4,000"
  function paintItemPrices(card) {
    card.querySelectorAll(".res-item").forEach(function (item) {
      var inp = item.querySelector("input"), r = rates[item.dataset.resource];
      var out = item.querySelector(".unit-price");
      if (!out) return;
      var qty = parseInt(inp.value || "0", 10) || 0;
      item.classList.toggle("picked", qty > 0);
      if (!r || !r.rate) { setHtml(out, qty ? '<span class="custom">No cost set</span>' : ""); return; }
      setHtml(out, inr(r.rate) + " each");   // the sum is shown once, under "Price for this event"
    });
  }

  function showCalc(card) {
    paintItemPrices(card);
    var box = card.querySelector(".price-calc");
    if (!box) return;
    var c = calc(card), price = field(card, "amount");
    var current = parseFloat(price && price.value ? price.value : "0") || 0;
    if (!anyRate && !pkgVal(card) && !c.parts.length) {
      setHtml(box, 'Costs are not set yet. Add the <b>cost for one</b> of each item in ' +
        '<a href="/setup/resources/" target="_blank">Studio settings → Resources &amp; equipment</a> and the cost of everything you choose will add up here.');
      return;
    }
    if (!c.parts.length && card.dataset.auto !== "0") { setHtml(box, ""); return; }  // nothing chosen yet: say nothing
    var line = c.parts.length ? c.parts.join(" ") + " = <b>" + inr(c.total) + "</b>" : inr(0);
    if (card.dataset.auto === "0" && Math.round(current) !== Math.round(c.total)) {
      setHtml(box, '<span class="custom">Custom price.</span> Calculated: ' + line +
        ' · <button type="button" data-use-calc>Use ' + inr(c.total) + "</button>");
    } else {
      setHtml(box, "Calculated: " + line);
    }
  }

  var internal = false;
  function recalc(card) {
    autoPick(card);
    if (card.dataset.auto !== "0") {
      var price = field(card, "amount"), c = calc(card);
      if (price && (c.parts.length || pkgVal(card))) {
        price.value = Math.round(c.total);
        internal = true;  // our own update: don't treat it as a typed "custom" price
        price.dispatchEvent(new Event("input", { bubbles: true }));
        internal = false;
      }
    }
    showCalc(card);
  }

  // New events start in "auto-pick" mode. Saved events keep the package they have,
  // and their saved price is never changed just by opening the page.
  function initPricing(card) {
    if (!card.dataset.pkgMode) {
      var isNew = !(field(card, "id") && field(card, "id").value);
      var sel = field(card, "package");
      card.dataset.pkgMode = (isNew && sel && !sel.value) ? "auto" : "manual";
    }
    renderCharges(card);
    var price = field(card, "amount");
    var v = parseFloat(price && price.value ? price.value : "0") || 0;
    card.dataset.auto = (!v || Math.round(v) === Math.round(calc(card).total)) ? "1" : "0";
    var note = card.querySelector(".pick-note");
    if (card.dataset.pkgMode === "manual" && hasPackages)
      setHtml(note, '<button type="button" data-auto-pick>✨ Auto-pick best package</button>');
    showCalc(card);
  }

  // The owner picked a package (or "no package") by hand
  function applyPackage(card) {
    var sel = field(card, "package");
    var pk = sel && packages[sel.value];
    card.dataset.pkgMode = "manual";
    if (pk) {
      card.querySelectorAll(".res-item input").forEach(function (inp) { inp.value = pk.items[inp.dataset.resource] || 0; });
      if (card._avail) paint(card, card._avail);
    }
    setHtml(card.querySelector(".pick-note"),
      (pk ? "✓ Team filled from <b>" + escapeHtml(pk.name) + "</b>. " : "") +
      '<button type="button" data-auto-pick>✨ Auto-pick best package</button>');
    card.dataset.auto = "1";
    recalc(card);
  }

  // React to the user's changes, but not to our own updates or to values
  // being restored from a saved draft (those must keep their saved price).
  function skip(e) {
    var f = e.target.form;
    return internal || (f && f.dataset.restoring === "1");
  }
  root.addEventListener("change", function (e) {
    if (skip(e)) return;
    var card = e.target.closest(".session-card");
    if (!card) return;
    if (/-package$/.test(e.target.name || "")) applyPackage(card);
    else if (e.target.closest(".res-item")) recalc(card);
  });
  root.addEventListener("input", function (e) {
    if (skip(e)) return;
    var card = e.target.closest(".session-card");
    if (!card) return;
    if (e.target.closest(".charge-row")) { writeCharges(card); recalc(card); }
    else if (e.target.closest(".res-item")) recalc(card);
    else if (/-amount$/.test(e.target.name || "")) { card.dataset.auto = "0"; showCalc(card); }
  });
  root.addEventListener("click", function (e) {
    var card = e.target.closest(".session-card");
    if (!card) return;
    var t = e.target;
    if (t.closest("[data-use-calc]")) { card.dataset.auto = "1"; recalc(card); }
    else if (t.closest("[data-auto-pick]")) { card.dataset.pkgMode = "auto"; card.dataset.auto = "1"; recalc(card); }
    else if (t.closest("[data-add-charge]")) {
      var b = t.closest("[data-add-charge]");
      var row = chargeRow(card, b.dataset.addCharge, "", b.hasAttribute("data-negative"));
      (b.dataset.addCharge ? row.querySelector(".ca") : row.querySelector(".cl")).focus();
    }
    else if (t.closest(".charge-row .x")) { t.closest(".charge-row").remove(); writeCharges(card); recalc(card); }
  });
  if (eventType) eventType.addEventListener("change", function () { cards().forEach(recalc); });

  document.getElementById("add-session").addEventListener("click", function () {
    var idx = parseInt(total.value, 10);
    var wrap = document.createElement("div");
    wrap.innerHTML = template.replace(/__prefix__/g, idx).trim();
    var card = wrap.firstElementChild;
    // Convenience: copy the previous event (same day, place, slot, package, price and team);
    // only the event name is left empty.
    var prev = cards().pop();
    if (prev) {
      ["date", "slot", "start_time", "end_time", "place", "package", "amount", "extra_charges"].forEach(function (n) {
        var from = field(prev, n), to = field(card, n);
        if (from && to) to.value = from.value;
      });
      var prevRes = prev.querySelectorAll(".res-item input");
      card.querySelectorAll(".res-item input").forEach(function (inp, i) {
        if (prevRes[i]) inp.value = prevRes[i].value;
      });
    }
    root.appendChild(card);
    total.value = idx + 1;
    init(card);
    if (prev) card.dataset.pkgMode = prev.dataset.pkgMode || "auto";
    initPricing(card);
    if (prev) card.dataset.auto = prev.dataset.auto || "1";
    renumber();
    updateTotal();
    field(card, "name").focus();
  });

  // Live total of all event prices
  var totalEl = document.getElementById("booking-total");
  function updateTotal() {
    if (!totalEl) return;
    var sum = 0;
    cards().forEach(function (c) {
      var p = c.querySelector('[name$="-amount"]');
      sum += parseFloat(p && p.value ? p.value : "0") || 0;
    });
    totalEl.textContent = "₹" + sum.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  }
  root.addEventListener("input", function (e) { if (/-amount$/.test(e.target.name || "")) updateTotal(); });
  root.addEventListener("click", function (e) { if (e.target.closest("[data-remove]")) setTimeout(updateTotal, 0); });

  cards().forEach(init);
  cards().forEach(initPricing);
  document.addEventListener("draft:restored", function () { cards().forEach(initPricing); updateTotal(); });
  renumber();
  updateTotal();

  // Existing client lookup by phone
  var phone = document.getElementById("id_client_phone");
  var hint = document.getElementById("client-hint");
  if (phone && root.dataset.clientUrl) {
    phone.addEventListener("change", function () {
      if (phone.value.replace(/\D/g, "").length < 10) { hint.textContent = ""; return; }
      fetch(root.dataset.clientUrl + "?phone=" + encodeURIComponent(phone.value), { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (c) {
          if (!c.found) { hint.textContent = "New customer"; hint.style.color = "var(--muted)"; return; }
          hint.style.color = "";
          hint.textContent = "Returning customer · " + c.bookings + " earlier booking" + (c.bookings === 1 ? "" : "s");
          var setIfEmpty = function (id, v) { var el = document.getElementById(id); if (el && !el.value && v) el.value = v; };
          setIfEmpty("id_client_name", c.name);
          setIfEmpty("id_client_alt_phone", c.alt_phone);
          setIfEmpty("id_client_address", c.address);
        });
    });
  }
})();
