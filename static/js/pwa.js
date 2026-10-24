// Install Sreeva like an app: registers the service worker and shows a small
// "Install" bar when the phone/computer allows it (Chrome, Edge, Android).
(function () {
  var me = document.currentScript;
  if ("serviceWorker" in navigator && me && me.dataset.sw) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register(me.dataset.sw, { scope: "/" }).catch(function () {});
    });
  }
  var bar = document.querySelector("[data-install]");
  if (!bar) return;
  var standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  if (standalone) return;
  var KEY = "sreeva-install-later";
  function snoozed() {
    try { return Date.now() < (+localStorage.getItem(KEY) || 0); } catch (e) { return false; }
  }
  var prompt = null;
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    prompt = e;
    if (!snoozed()) bar.hidden = false;
  });
  bar.querySelector("[data-install-go]").addEventListener("click", function () {
    if (!prompt) return;
    prompt.prompt();
    prompt.userChoice.finally(function () { prompt = null; bar.hidden = true; });
  });
  bar.querySelector("[data-install-close]").addEventListener("click", function () {
    bar.hidden = true;
    try { localStorage.setItem(KEY, String(Date.now() + 14 * 864e5)); } catch (e) {}
  });
  window.addEventListener("appinstalled", function () { bar.hidden = true; });
})();
