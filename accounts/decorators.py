from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

# Pages an owner may open before first-time setup is finished.
SETUP_PAGES = {"setup_studio", "setup_resources"}


def studio_required(view):
    """Logged in AND attached to a studio. Owners without a studio go to setup."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.studio is None:
            if request.is_owner:
                return redirect("setup_studio")
            raise PermissionDenied("Your account is not linked to a studio.")
        if not request.studio.setup_complete and request.resolver_match.url_name not in SETUP_PAGES:
            # First-time setup isn't finished: send the owner back to step 3.
            if request.is_owner:
                return redirect("setup_resources")
        return view(request, *args, **kwargs)

    return wrapper


def owner_required(view):
    """Only the studio owner. Staff get a 403 page (role-based access control)."""

    @studio_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.is_owner:
            raise PermissionDenied("Only the studio owner can do this.")
        return view(request, *args, **kwargs)

    return wrapper
