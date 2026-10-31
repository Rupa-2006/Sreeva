import os
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.contrib.auth.forms import SetPasswordForm
from django.views.decorators.http import require_POST

from .audit import client_ip, log
from .decorators import owner_required
from .forms import SignupForm, StaffForm
from .models import AuditLog, Profile

TAKEN = "That username was just taken. Please choose another one."


def _save_new_user(form):
    """Save a new user; return None if the username was taken by a parallel request
    (e.g. the button was double-clicked), instead of crashing with IntegrityError."""
    try:
        with transaction.atomic():
            return form.save()
    except IntegrityError:
        form.add_error("username", TAKEN)
        return None


def _demo_user():
    from bookings.management.commands.setup_demo import DEMO_USERNAME
    return User.objects.filter(username=DEMO_USERNAME, is_active=True, profile__studio__isnull=False).first()


def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "home.html", {"demo_ready": _demo_user() is not None})


@require_POST
def try_demo(request):
    """One tap from the welcome page: log in to the sample "Demo Studio".
    The demo studio is separate from every real studio and is refreshed daily."""
    user = _demo_user()
    if user is None:
        return redirect("home")
    # visitors may have changed things: start each day with fresh sample data
    from datetime import timedelta
    from django.utils import timezone
    if timezone.now() - user.date_joined > timedelta(hours=24):
        from django.core.management import call_command
        call_command("setup_demo", reset=True, stdout=open(os.devnull, "w"))
        user = _demo_user()
    if request.user.is_authenticated:
        logout(request)
    login(request, user, backend="accounts.backends.CaseInsensitiveBackend")
    log(request, "Demo opened", user=user)
    return redirect("dashboard")


class RateLimitedLoginView(LoginView):
    """Login page that locks a username+IP pair after too many wrong passwords."""

    template_name = "accounts/login.html"
    # Don't silently bounce to the dashboard: on a shared studio computer the
    # next person needs to see who is logged in and switch user.
    redirect_authenticated_user = False

    def _key(self):
        username = self.request.POST.get("username", "").strip().lower()
        return f"login-fail:{client_ip(self.request)}:{username}"

    def post(self, request, *args, **kwargs):
        if cache.get(self._key(), 0) >= settings.LOGIN_MAX_ATTEMPTS:
            log(request, "Login blocked (locked out)", detail=request.POST.get("username", ""))
            form = self.get_form_class()(request=request)
            minutes = settings.LOGIN_LOCKOUT_SECONDS // 60
            return self.render_to_response(
                self.get_context_data(form=form, locked_minutes=minutes), status=429
            )
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        username = self.request.POST.get("username", "").strip()
        password = self.request.POST.get("password", "")
        # Correct password but the owner disabled this login: say so clearly.
        # (Only revealed when the password is right, so it can't be used to guess usernames.)
        disabled = User.objects.filter(username__iexact=username, is_active=False).first()
        if disabled and password and disabled.check_password(password):
            log(self.request, "Login refused (disabled)", detail=disabled.username,
                user=disabled, studio=getattr(getattr(disabled, "profile", None), "studio", None))
            return self.render_to_response(self.get_context_data(form=form, disabled_login=True))
        key = self._key()
        attempts = cache.get(key, 0) + 1
        cache.set(key, attempts, settings.LOGIN_LOCKOUT_SECONDS)
        log(self.request, "Failed login", detail=username)
        remaining = settings.LOGIN_MAX_ATTEMPTS - attempts
        return self.render_to_response(
            self.get_context_data(form=form, attempts_left=max(remaining, 0))
        )

    def form_valid(self, form):
        cache.delete(self._key())
        return super().form_valid(form)


@require_POST
def logout_view(request):
    """Log out (POST only, so a link on another site can't log you out) and
    show a clear confirmation so the next person knows the device is free."""
    name = ""
    if request.user.is_authenticated:
        name = request.user.first_name or request.user.username
    logout(request)
    messages.success(request, f"{name + ' has' if name else 'You have'} been logged out. The next person can log in now.")
    return redirect("login")


@sensitive_post_parameters("password1", "password2")
def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if not settings.ALLOW_SIGNUP:
        messages.info(request, "New accounts are closed. Ask the studio owner for a staff login.")
        return redirect("login")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = _save_new_user(form)
        if user is not None:
            Profile.objects.filter(user=user).update(role=Profile.OWNER)
            login(request, user)
            from .verify import send_verification
            send_verification(request, user)
            messages.success(request, "Account created. Now tell us about your studio.")
            return redirect("setup_studio")
    return render(request, "accounts/signup.html", {"form": form})


# --- Staff management (owner only) -----------------------------------------

@sensitive_post_parameters("password1", "password2")
@owner_required
def staff_list(request):
    members = (
        Profile.objects.filter(studio=request.studio)
        .select_related("user")
        .order_by("role", "user__first_name")
    )
    form = StaffForm(request.POST or None)
    user = None
    if request.method == "POST" and form.is_valid():
        user = _save_new_user(form)
    if user is not None:
        Profile.objects.filter(user=user).update(
            studio=request.studio,
            role=Profile.STAFF,
            phone=form.cleaned_data["phone"],
            designation=form.cleaned_data["designation"],
        )
        log(request, "Added staff", detail=f"{user.first_name} ({user.username})")
        messages.success(request, f"{user.first_name} can now log in as “{user.username}”.")
        return redirect("staff_list")
    return render(
        request, "accounts/staff.html", {"members": members, "form": form, "nav": "staff", "tab": "staff"}
    )


@owner_required
@require_POST
def staff_toggle(request, user_id):
    user = get_object_or_404(User, pk=user_id, profile__studio=request.studio, profile__role=Profile.STAFF)
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    state = "enabled" if user.is_active else "disabled"
    log(request, f"Staff login {state}", detail=user.username)
    messages.success(request, f"Login {state} for {user.first_name or user.username}.")
    return redirect("staff_list")


@sensitive_post_parameters("new_password1", "new_password2")
@owner_required
@require_POST
def staff_set_password(request, user_id):
    """Staff forgot their password: the owner sets a new one for them."""
    user = get_object_or_404(User, pk=user_id, profile__studio=request.studio, profile__role=Profile.STAFF)
    form = SetPasswordForm(user, request.POST)
    if form.is_valid():
        form.save()
        log(request, "Staff password reset by owner", detail=user.username)
        messages.success(
            request,
            f"New password set for {user.first_name or user.username}. Tell them their username "
            f"is “{user.username}” and the new password — they can log in now.",
        )
    else:
        for errors in form.errors.values():
            for e in errors:
                messages.error(request, f"{user.first_name or user.username}: {e}")
    return redirect("staff_list")


@owner_required
def audit_log(request):
    logs = AuditLog.objects.filter(studio=request.studio).select_related("user")[:200]
    return render(request, "accounts/audit.html", {"logs": logs, "nav": "audit", "tab": "audit"})


def permission_denied(request, exception=None):
    return render(request, "errors/403.html", status=403)


def page_not_found(request, exception=None):
    return render(request, "errors/404.html", status=404)
