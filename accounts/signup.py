"""Decides whether the "Create an account" sign-up page is open."""
from django.conf import settings
from django.contrib.auth.models import User


def real_accounts_exist():
    """True once anyone other than the demo studio's accounts has an account."""
    from bookings.management.commands.setup_demo import DEMO_USERNAME
    return (
        User.objects.exclude(username=DEMO_USERNAME)
        .exclude(username__startswith=DEMO_USERNAME + "_")
        .exists()
    )


def signup_open():
    """ALLOW_SIGNUP True/False forces it open/closed; None (the default) means
    open only for the very first owner of a new installation."""
    mode = getattr(settings, "ALLOW_SIGNUP", None)
    if mode is not None:
        return bool(mode)
    return not real_accounts_exist()
