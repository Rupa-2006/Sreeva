def studio_context(request):
    studio = getattr(request, "studio", None)
    notif_count = 0
    if studio and studio.setup_complete and request.user.is_authenticated:
        from bookings import notifications
        notifications.refresh(request.user, studio, getattr(request, "is_owner", False))
        notif_count = notifications.unread_count(request.user, studio)
        if getattr(request, "is_owner", False):
            _daily_backup()
    from django.conf import settings
    return {
        "allow_signup": getattr(settings, "ALLOW_SIGNUP", True),
        "notif_count": notif_count,
        "studio": studio,
        "is_owner": getattr(request, "is_owner", False),
        # During first-time setup the pages use the step-by-step layout (no side menu).
        "onboarding": bool(studio and not studio.setup_complete),
    }


def _daily_backup():
    """Once a day, save a copy of the database (checked at most once an hour)."""
    from django.core.cache import cache
    if cache.get("daily-backup-checked"):
        return
    cache.set("daily-backup-checked", 1, 60 * 60)
    try:
        from bookings.backup import backup_today_if_needed
        backup_today_if_needed()
    except Exception:  # a failed backup must never break the website
        import logging
        logging.getLogger(__name__).exception("Daily backup failed")
