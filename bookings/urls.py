from django.urls import path

from . import data_views, views

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("bookings/", views.booking_list, name="booking_list"),
    path("bookings/new/", views.booking_edit, name="booking_new"),
    path("bookings/quick/", views.quick_booking, name="quick_booking"),
    path("bookings/<int:pk>/", views.booking_detail, name="booking_detail"),
    path("bookings/<int:pk>/edit/", views.booking_edit, name="booking_edit"),
    path("bookings/<int:pk>/status/", views.booking_status, name="booking_status"),
    path("bookings/<int:pk>/delete/", views.booking_delete, name="booking_delete"),
    path("bookings/<int:pk>/payments/add/", views.payment_add, name="payment_add"),
    path("sessions/<int:pk>/assign/", views.session_assign, name="session_assign"),
    path("payments/", views.payments_overview, name="payments"),
    path("payments/<int:pk>/receipt/", views.payment_receipt, name="payment_receipt"),
    path("payments/<int:pk>/edit/", views.payment_edit, name="payment_edit"),
    path("payments/<int:pk>/delete/", views.payment_delete, name="payment_delete"),
    path("calendar/", views.calendar_view, name="calendar"),
    path("clients/", views.client_list, name="client_list"),
    path("clients/<int:pk>/", views.client_detail, name="client_detail"),
    path("api/availability/", views.api_availability, name="api_availability"),
    path("api/client/", views.api_client_lookup, name="api_client_lookup"),
    path("notifications/", views.notification_list, name="notifications"),
    path("notifications/<int:pk>/done/", views.notification_done, name="notification_done"),
    path("api/notifications/", views.api_notifications, name="api_notifications"),
    path("backup/", data_views.backup_page, name="backup"),
    path("backup/now/", data_views.backup_now, name="backup_now"),
    path("backup/excel/", data_views.export_excel, name="export_excel"),
]
