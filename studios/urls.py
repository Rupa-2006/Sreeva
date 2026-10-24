from django.urls import path

from . import views

urlpatterns = [
    path("setup/studio/", views.setup_studio, name="setup_studio"),
    path("setup/resources/", views.setup_resources, name="setup_resources"),
    path("setup/packages/", views.package_list, name="package_list"),
    path("setup/packages/new/", views.package_edit, name="package_new"),
    path("setup/packages/to-item-prices/", views.package_convert, name="package_convert"),
    path("setup/packages/<int:pk>/", views.package_edit, name="package_edit"),
    path("setup/packages/<int:pk>/delete/", views.package_delete, name="package_delete"),
]
