from .models import Profile


class StudioMiddleware:
    """Attaches the logged-in user's studio and role to every request.

    Every query in the app filters by ``request.studio`` so one studio can never
    see another studio's data (multi-tenant isolation).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.studio = None
        request.is_owner = False
        request.profile = None
        user = request.user
        if user.is_authenticated:
            profile, _ = Profile.objects.select_related("studio").get_or_create(user=user)
            request.profile = profile
            request.studio = profile.studio
            request.is_owner = profile.is_owner
        return self.get_response(request)
