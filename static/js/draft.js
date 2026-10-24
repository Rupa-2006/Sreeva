// Auto-save drafts for forms marked <form data-draft>.
//
// While you type, the form is copied into this browser's localStorage.
// Leave the page and come back: the half-filled form is restored with a banner.
// The draft is deleted after a successful save, on "Discard draft", on logout,
// or after 7 days. Drafts are kept per user, so another member logging in on the
// same computer never sees them. Passwords and security tokens are never stored.
(function () {
  var PREFIX = "sf-draft:";
  var MAX_AGE = 7 * 24 * 60 * 60 * 1000;
  var user = document.body.dataset.user || "";

  function store() { try { return window.localStorage; } catch (e) { return null; } }
  var ls = store();
  if (!ls) return;

  function get(key) { try { return JSON.parse(ls.getItem(key)); } catch (e) { return null; } }
  function put(key, val) { try { ls.setItem(key, JSON.stringify(val)); } catch (e) { /* storage full or blocked */ } }
  function drop(key) { try { ls.removeItem(key); } catch (e) {} }
  function allKeys() {
    var out = [];
    try { for (var i = 0; i < ls.length; i++) { var k = ls.key(i); if (k && k.indexOf(PREFIX) === 0) out.push(k); } } catch (e) {}
    return out;
  }

  // Housekeeping: expire old drafts.
  allKeys().forEach(function (k) {
    var d = get(k);
    if (!d || !d.t || Date.now() - d.t > MAX_AGE) drop(k);
  });

  // Logout wipes every draft in this browser (shared studio computer).
  document.addEventListener("submit", function (e) {
    var a = e.target.getAttribute("action") || "";
    if (/\/logout\/?$/.test(a)) allKeys().forEach(drop);
  }, true);

  if (!user) return;

  // After a submit we land on a new page. If that page shows the same form with
  // errors, keep the draft; otherwise the save worked, so delete the draft.
  var submittedKey = null;
  try { submittedKey = sessionStorage.getItem("sf-draft-submitted"); sessionStorage.removeItem("sf-draft-submitted"); } catch (e) {}

  var forms = Array.prototype.slice.call(document.querySelectorAll("form[data-draft]"));
  var keysHere = {};
  forms.forEach(function (form) { keysHere[keyFor(form)] = form; });

  if (submittedKey) {
    var f = keysHere[submittedKey];
    var failed = f && f.dataset.bound === "1";
    if (!failed) drop(submittedKey);
  }

  function keyFor(form) {
    return PREFIX + user + ":" + location.pathname + "#" + (form.dataset.draft || "main");
  }

  function skip(el) {
    if (!el.name || el.disabled) return true;
    if (el.name === "csrfmiddlewaretoken" || el.name === "next") return true;
    var t = (el.type || "").toLowerCase();
    return t === "password" || t === "file" || t === "submit" || t === "button";
  }

  function snapshot(form) {
    var data = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (skip(el)) return;
      var t = (el.type || "").toLowerCase();
      if (t === "hidden" && !/TOTAL_FORMS$/.test(el.name) && !el.dataset.chargesInput) return;
      if (t === "checkbox") data[el.name] = el.checked;
      else if (t === "radio") { if (el.checked) data[el.name] = el.value; }
      else data[el.name] = el.value;
    });
    return data;
  }

  function differsFromPage(form, data) {
    var now = snapshot(form);
    return Object.keys(data).some(function (k) { return k in now ? String(now[k]) !== String(data[k]) : data[k] !== "" && data[k] !== false; });
  }

  function growRows(form, data) {
    var addSel = form.dataset.draftAdd, totalSel = form.dataset.draftTotal;
    if (!addSel || !totalSel) return;
    var total = form.querySelector(totalSel) || document.querySelector(totalSel);
    var add = document.querySelector(addSel);
    if (!total || !add || !(total.name in data)) return;
    var want = parseInt(data[total.name], 10), guard = 0;
    while (parseInt(total.value, 10) < want && guard++ < 50) add.click();
  }

  function fire(el, type) { el.dispatchEvent(new Event(type, { bubbles: true })); }

  function restore(form, data) {
    form.dataset.restoring = "1";  // other scripts can tell restored values from real typing
    growRows(form, data);
    Array.prototype.forEach.call(form.elements, function (el) {
      if (skip(el) || !(el.name in data)) return;
      var t = (el.type || "").toLowerCase();
      if (t === "hidden") {
        if (el.dataset.chargesInput) el.value = data[el.name];  // extra charges live in a hidden box
        return;
      }
      var v = data[el.name], changed = false;
      if (t === "checkbox") { if (el.checked !== !!v) { el.checked = !!v; changed = true; } }
      else if (t === "radio") { var c = el.value === v; if (el.checked !== c) { el.checked = c; changed = c; } }
      else if (el.value !== String(v)) { el.value = v; changed = true; }
      if (changed) { fire(el, "input"); fire(el, "change"); }
      // Rows marked for removal stay hidden.
      if (t === "checkbox" && /-DELETE$/.test(el.name) && el.checked) {
        var row = el.closest("tr, .session-card");
        if (row) row.classList.add("removed");
      }
    });
    delete form.dataset.restoring;
  }

  function banner(form, key, when) {
    var div = document.createElement("div");
    div.className = "draft-banner";
    var time = new Date(when).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
    div.innerHTML = '<span>↺ We restored the details you hadn\'t saved yet (' + time + '). Check them and click Save.</span>';
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn sm";
    btn.textContent = "Discard draft";
    btn.addEventListener("click", function () {
      drop(key);
      form.dataset.draftOff = "1";
      location.reload();
    });
    div.appendChild(btn);
    form.insertBefore(div, form.firstChild);
  }

  var pill;
  function showSaved() {
    if (!pill) {
      pill = document.createElement("div");
      pill.className = "draft-pill";
      pill.setAttribute("role", "status");
      document.body.appendChild(pill);
    }
    pill.textContent = "✓ Draft saved";
    pill.classList.add("show");
    clearTimeout(pill._t);
    pill._t = setTimeout(function () { pill.classList.remove("show"); }, 1400);
  }

  forms.forEach(function (form) {
    var key = keyFor(form);
    var saved = get(key);
    var baseline = JSON.stringify(snapshot(form));

    // Restore, unless the server just re-showed this form with your input (errors).
    if (saved && saved.d && form.dataset.bound !== "1" && differsFromPage(form, saved.d)) {
      restore(form, saved.d);
      banner(form, key, saved.t);
      form.dispatchEvent(new CustomEvent("draft:restored", { bubbles: true }));
      baseline = null; // the restored state is itself unsaved work
    }

    var timer;
    function save() {
      if (form.dataset.draftOff) return;
      var data = snapshot(form);
      var json = JSON.stringify(data);
      if (baseline !== null && json === baseline) { drop(key); return; } // nothing changed
      put(key, { t: Date.now(), d: data });
    }
    function queue() { clearTimeout(timer); timer = setTimeout(save, 500); }
    form.addEventListener("input", queue);
    form.addEventListener("change", queue);
    form.addEventListener("click", function (e) { if (e.target.closest("[data-remove], [data-remove-row]")) queue(); });
    var add = form.dataset.draftAdd && document.querySelector(form.dataset.draftAdd);
    if (add) add.addEventListener("click", queue);

    form.addEventListener("submit", function () {
      clearTimeout(timer);
      if (!form.dataset.draftOff) put(key, { t: Date.now(), d: snapshot(form) });
      try { sessionStorage.setItem("sf-draft-submitted", key); } catch (e) {}
    });
  });
})();
