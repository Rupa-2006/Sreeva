from django.contrib import admin
from django.urls import include, path

from . import pwa

urlpatterns = [
    path("admin/", admin.site.urls),
    path("manifest.webmanifest", pwa.manifest, name="manifest"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("offline/", pwa.offline, name="offline"),
    path("", include("accounts.urls")),
    path("", include("studios.urls")),
    path("", include("bookings.urls")),
]

handler403 = "accounts.views.permission_denied"
handler404 = "accounts.views.page_not_found"
