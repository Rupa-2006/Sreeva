// Notifications: keeps the bell count fresh and shows a pop-up on this computer
// for new reminders (only if the user turned pop-ups on). No external service.
(function () {
  var me = document.currentScript;
  var api = me.dataset.api, seenKey = "sreeva-notif-seen-" + me.dataset.user;
  var supported = "Notification" in window;

  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }

  function setCount(n) {
    document.querySelectorAll("[data-notif-count]").forEach(function (el) {
      el.textContent = n > 99 ? "99+" : n;
      el.hidden = !n;
    });
    var bell = document.querySelector(".bell");
    if (bell) bell.classList.toggle("has", !!n);
    document.title = document.title.replace(/^\(\d+\+?\) /, "");
    if (n) document.title = "(" + n + ") " + document.title;
  }

  function popups(items) {
    var seen = parseInt(store(seenKey) || "0", 10);
    var fresh = items.filter(function (i) { return i.id > seen; });
    if (!fresh.length) return;
    store(seenKey, String(Math.max.apply(null, items.map(function (i) { return i.id; }))));
    if (!supported || Notification.permission !== "granted") return;
    fresh.slice(0, 3).reverse().forEach(function (i) {
      var pop = new Notification(i.title, { body: i.body, tag: "sreeva-" + i.id });
      pop.onclick = function () { window.focus(); window.location = i.url; pop.close(); };
    });
  }

  function poll() {
    if (document.hidden && !(supported && Notification.permission === "granted")) return;
    fetch(api, { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) { setCount(d.count); popups(d.items); } })
      .catch(function () {});
  }
  poll();
  setInterval(poll, 60000);

  // --- Notifications page ---
  var box = document.getElementById("alert-setup");
  if (box) {
    var btn = document.getElementById("alert-on"), text = document.getElementById("alert-text");
    var show = function () {
      if (!supported) { box.hidden = false; btn.hidden = true; text.textContent = "This browser can't show pop-ups. Use Chrome or Edge."; return; }
      if (Notification.permission === "granted") { box.hidden = true; return; }
      box.hidden = false;
      if (Notification.permission === "denied") {
        btn.hidden = true;
        text.textContent = "Pop-ups are blocked for this website. Click the lock icon next to the address bar → Notifications → Allow.";
      }
    };
    show();
    btn.addEventListener("click", function () {
      Notification.requestPermission().then(function (p) {
        show();
        if (p === "granted") new Notification("Pop-ups are on ✓", { body: "Sreeva will tell you about shoots, payments and deliveries." });
      });
    });
  }

  // WhatsApp reminder sent → mark that notification done.
  document.addEventListener("click", function (e) {
    var a = e.target.closest("[data-done-on-click]");
    if (!a) return;
    var card = a.closest(".notif"), form = card && card.querySelector(".done-form");
    if (!form) return;
    fetch(form.action, { method: "POST", credentials: "same-origin", body: new FormData(form),
                         headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) return;
        card.classList.add("sent");
        var tag = document.createElement("span");
        tag.className = "badge confirmed"; tag.textContent = "Sent ✓ — moved to Done";
        card.querySelector(".notif-top").appendChild(tag);
        form.remove();
      }).catch(function () {});
  });
})();
