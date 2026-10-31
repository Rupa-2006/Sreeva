"""Confirm the email address an owner signed up with.

After sign-up an email is sent with a signed link (valid 3 days). Opening it marks the
address as confirmed. Until then the owner can use Sreeva normally, but "Forgot password"
emails are not sent to that address - so signing up with someone else's email gains nothing.
"""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from .audit import client_ip, log

SALT = "sreeva-verify-email"
MAX_AGE = 3 * 24 * 60 * 60
RESEND_LIMIT = 3


def send_verification(request, user):
    token = signing.dumps({"u": user.pk, "e": user.email.lower()}, salt=SALT)
    link = request.build_absolute_uri(reverse("verify_email", args=[token]))
    body = render_to_string("accounts/emails/verify_email.txt", {"user": user, "link": link})
    send_mail("Confirm your email for Sreeva", body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=True)


def verify_email(request, token):
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
        user = User.objects.get(pk=data["u"], email__iexact=data["e"])
    except (signing.BadSignature, User.DoesNotExist, KeyError, TypeError):
        messages.error(request, "This confirmation link is invalid or has expired. Log in and send a new one.")
        return redirect("login")
    user.profile.email_verified = True
    user.profile.save(update_fields=["email_verified"])
    log(request, "Email confirmed", detail=user.email, user=user)
    messages.success(request, "Email confirmed.")
    return redirect("dashboard" if request.user.is_authenticated else "login")


@login_required
@require_POST
def resend_verification(request):
    key = f"verify-resend:{request.user.pk}:{client_ip(request)}"
    count = cache.get(key, 0)
    if count >= RESEND_LIMIT:
        messages.error(request, "Too many emails sent. Please try again in an hour.")
    elif request.user.email and not request.user.profile.email_verified:
        cache.set(key, count + 1, 60 * 60)
        send_verification(request, request.user)
        request.session["verify_sent"] = True
    return redirect(request.POST.get("next") or "dashboard")
