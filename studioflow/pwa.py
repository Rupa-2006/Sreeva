"""Lets phones install Sreeva like an app (home-screen icon, opens full screen).

The service worker must be served from the site root so it can look after every page.
"""
import json

from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_control

SW_VERSION = "sreeva-v2"


@cache_control(max_age=3600)
def manifest(request):
    data = {
        "name": "Sreeva",
        "short_name": "Sreeva",
        "description": "Bookings, team, payments and albums for your photo studio.",
        "id": "/",
        "start_url": "/dashboard/?source=app",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#f6f7fb",
        "theme_color": "#4f46e5",
        "icons": [
            {"src": static("img/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("img/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": static("img/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "New booking", "url": "/bookings/new/", "icons": [{"src": static("img/icon-192.png"), "sizes": "192x192"}]},
            {"name": "Calendar", "url": "/calendar/", "icons": [{"src": static("img/icon-192.png"), "sizes": "192x192"}]},
            {"name": "Payments", "url": "/payments/", "icons": [{"src": static("img/icon-192.png"), "sizes": "192x192"}]},
        ],
    }
    return HttpResponse(json.dumps(data), content_type="application/manifest+json")


SERVICE_WORKER = """
const CACHE = "%(version)s";
const OFFLINE = "/offline/";
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll([OFFLINE, %(icons)s])).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  // pages: always fresh from the studio; a friendly page if there is no internet
  if (req.mode === "navigate") {
    e.respondWith(fetch(req).catch(() => caches.match(OFFLINE)));
    return;
  }
  // design files and icons: always fetch the newest; use the saved copy only when offline
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req)));
  }
});
"""


def service_worker(request):
    icons = ", ".join(json.dumps(static(p)) for p in ["img/icon-192.png", "img/icon-512.png"])
    body = SERVICE_WORKER % {"version": SW_VERSION, "icons": icons}
    resp = HttpResponse(body, content_type="application/javascript")
    resp["Cache-Control"] = "no-cache"
    resp["Service-Worker-Allowed"] = "/"
    return resp


def offline(request):
    return render(request, "offline.html")
