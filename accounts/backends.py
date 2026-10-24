from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User


class CaseInsensitiveBackend(ModelBackend):
    """Log in with the username in any case: "Ravi", "ravi" and "RAVI" all work.

    Staff often type capitals on phones; an exact-case match would wrongly say
    "wrong username or password".
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        username = username.strip()
        try:
            user = User.objects.get(username__iexact=username)
        except User.DoesNotExist:
            User().set_password(password)  # same timing as a real check (no username guessing by speed)
            return None
        except User.MultipleObjectsReturned:
            user = User.objects.filter(username=username).first()
            if user is None:
                return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
