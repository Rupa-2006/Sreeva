from .models import AuditLog


def client_ip(request):
    # REMOTE_ADDR only: X-Forwarded-For can be forged by the client, so we don't
    # trust it unless a known reverse proxy is configured in front of the app.
    return request.META.get("REMOTE_ADDR") or None


def log(request, action, detail="", studio=None, user=None):
    if user is None and request.user.is_authenticated:
        user = request.user
    if studio is None:
        studio = getattr(request, "studio", None)
    AuditLog.objects.create(
        studio=studio, user=user, action=action, detail=str(detail)[:255], ip=client_ip(request)
    )
