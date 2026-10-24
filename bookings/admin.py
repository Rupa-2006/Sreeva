from django.contrib import admin

from .models import Booking, Client, Payment, Session, SessionResource


class SessionInline(admin.StackedInline):
    model = Session
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "display_title", "studio", "status", "work_status", "total_amount", "created_at")
    list_filter = ("studio", "status", "work_status", "event_type")
    search_fields = ("title", "client__name", "client__phone")
    inlines = [SessionInline, PaymentInline]


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "studio")
    search_fields = ("name", "phone")


admin.site.register(SessionResource)
admin.site.register(Payment)
