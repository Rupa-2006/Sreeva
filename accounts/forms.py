from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from bookings.utils import normalize_phone


def _clean_username(form):
    """Store usernames in lowercase and refuse "Ravi" if "ravi" already exists."""
    username = form.cleaned_data["username"].strip().lower()
    if User.objects.filter(username__iexact=username).exists():
        raise forms.ValidationError("This username is already taken. Try another, e.g. add a number.")
    return username


def _plain_help(form, example):
    f = form.fields
    f["username"].help_text = f"Used to log in. Small letters or numbers, no spaces (e.g. {example})."
    f["password1"].help_text = "At least 8 characters, not only numbers."
    f["password2"].help_text = "Type the same password again."


class SignupForm(UserCreationForm):
    first_name = forms.CharField(label="Your name", max_length=60)
    email = forms.EmailField(
        help_text="Needed to recover your username or password if you forget them.",
    )

    class Meta:
        model = User
        fields = ["first_name", "username", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _plain_help(self, "srinivas")

    def clean_username(self):
        return _clean_username(self)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists. Use “Forgot username or password?” on the login page.")
        return email


class StaffForm(UserCreationForm):
    first_name = forms.CharField(label="Full name", max_length=60)
    phone = forms.CharField(max_length=16, required=False)
    designation = forms.CharField(
        max_length=60, required=False, help_text="Photographer, Videographer, Editor…"
    )

    class Meta:
        model = User
        fields = ["first_name", "username"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _plain_help(self, "ravi")
        self.fields["username"].widget.attrs.pop("autofocus", None)  # don't jump down the page on phones

    def clean_username(self):
        return _clean_username(self)

    def clean_phone(self):
        raw = self.cleaned_data.get("phone", "")
        if not raw:
            return ""
        phone = normalize_phone(raw)
        if not phone:
            raise forms.ValidationError("Enter a valid 10-digit mobile number.")
        return phone
