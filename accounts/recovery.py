"""Forgot username / password.

Flow (owner):
  1. "Forgot username or password?" on the login page -> enter the email used at signup.
  2. An email is sent with the USERNAME and a one-time reset link (valid 3 days,
     stops working once used or if the password changes).
  3. The link opens a page to choose a new password.

Security choices:
  * The page always says "if an account exists, we've sent an email" - it never
    reveals whether an email is registered (prevents user enumeration).
  * Max 5 requests per IP per hour (prevents email flooding / abuse).
  * Tokens are Django's signed, single-use, time-limited password-reset tokens.
  * Every request and every successful reset is written to the activity log.

Staff don't need email: the owner resets a staff password from the Staff page.
Last resort on the computer that runs the app:  python manage.py changepassword <username>
"""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordResetForm
from django.core.cache import cache
from django.urls import reverse_lazy

from .audit import client_ip, log

RESET_LIMIT = 5
RESET_WINDOW = 60 * 60


class ForgotForm(PasswordResetForm):
    def get_users(self, email):
        # only confirmed addresses get a recovery email (see accounts/verify.py)
        return (u for u in super().get_users(email)
                if getattr(getattr(u, "profile", None), "email_verified", False))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].label = "Email used when you signed up"
        self.fields["email"].widget.attrs.update(placeholder="you@example.com", autofocus=True)


class ForgotView(auth_views.PasswordResetView):
    form_class = ForgotForm
    template_name = "accounts/forgot.html"
    email_template_name = "accounts/emails/reset_email.txt"
    subject_template_name = "accounts/emails/reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")

    def post(self, request, *args, **kwargs):
        key = f"pw-reset:{client_ip(request)}"
        count = cache.get(key, 0)
        if count >= RESET_LIMIT:
            log(request, "Password reset blocked (too many requests)")
            form = self.get_form()
            form.is_valid()
            form.add_error(None, "Too many requests from this device. Please try again in an hour.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        cache.set(key, count + 1, RESET_WINDOW)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        log(self.request, "Password reset requested", detail=form.cleaned_data["email"])
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["console_email"] = settings.EMAIL_BACKEND.endswith("console.EmailBackend")
        ctx["on_laptop"] = settings.DEBUG
        return ctx


class ForgotSentView(auth_views.PasswordResetDoneView):
    template_name = "accounts/forgot_sent.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["console_email"] = settings.EMAIL_BACKEND.endswith("console.EmailBackend")
        ctx["on_laptop"] = settings.DEBUG
        return ctx


class ResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/reset_confirm.html"
    success_url = reverse_lazy("login")

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user
        studio = getattr(getattr(user, "profile", None), "studio", None)
        log(self.request, "Password reset via email link", user=user, studio=studio)
        messages.success(
            self.request,
            f"Password changed. Log in with your username “{user.username}” and the new password.",
        )
        return response
