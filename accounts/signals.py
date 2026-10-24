from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .audit import log


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    studio = getattr(getattr(user, "profile", None), "studio", None)
    log(request, "Logged in", user=user, studio=studio)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        studio = getattr(getattr(user, "profile", None), "studio", None)
        log(request, "Logged out", user=user, studio=studio)
