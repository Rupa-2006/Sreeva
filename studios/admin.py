from django.contrib import admin

from .models import ResourceType, Studio


class ResourceInline(admin.TabularInline):
    model = ResourceType
    extra = 0


@admin.register(Studio)
class StudioAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "phone", "city", "created_at")
    inlines = [ResourceInline]
