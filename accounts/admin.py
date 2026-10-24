from django.contrib import admin

from .models import AuditLog, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "studio", "role", "designation", "phone")
    list_filter = ("role", "studio")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "studio", "user", "action", "detail", "ip")
    list_filter = ("studio", "action")
    readonly_fields = [f.name for f in AuditLog._meta.fields]
