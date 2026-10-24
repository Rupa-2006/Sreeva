"""
Sreeva settings.

Secrets and production switches come from environment variables, so the same
code runs safely on a laptop (DEBUG on) and on a server (DEBUG off, HTTPS on).
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Core -------------------------------------------------------------------
def _secret_key():
    """From the environment, else from a private `.secret_key` file made on the server."""
    if os.environ.get("DJANGO_SECRET_KEY"):
        return os.environ["DJANGO_SECRET_KEY"]
    key_file = BASE_DIR / ".secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    return "dev-only-insecure-key-change-me-before-deploying-3f9a1c7e5b"


SECRET_KEY = _secret_key()
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "studios",
    "bookings",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves the design files online (removed below if not installed)
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "accounts.middleware.StudioMiddleware",
]

try:  # WhiteNoise is only needed on the server; the laptop works without it
    import whitenoise  # noqa: F401
except ImportError:
    MIDDLEWARE.remove("whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "studioflow.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.studio_context",
            ],
        },
    },
]

WSGI_APPLICATION = "studioflow.wsgi.application"

# SQLite for development. For production switch to PostgreSQL (see README).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# New studios can sign up ("Create an account"). Set SREEVA_ALLOW_SIGNUP=0 online
# once your own studio is created, so strangers can't make accounts.
ALLOW_SIGNUP = os.environ.get("SREEVA_ALLOW_SIGNUP", "1") == "1"

# --- Login --------------------------------------------------------------------
AUTHENTICATION_BACKENDS = ["accounts.backends.CaseInsensitiveBackend"]

# --- Passwords --------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Locale -----------------------------------------------------------------
LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# --- Static files -----------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# --- Backups ----------------------------------------------------------------
# A copy of the database is saved here on every start and once a day (newest 30 kept).
# Point it at a Google Drive / OneDrive folder to keep copies off this computer too:
#   set SREEVA_BACKUP_DIR=C:\Users\<you>\Google Drive\Sreeva backups
BACKUP_DIR = Path(os.environ.get("SREEVA_BACKUP_DIR", BASE_DIR / "backups"))
AUTO_BACKUP = "test" not in sys.argv  # never during automatic tests

# --- Email (used for "Forgot username or password?") -------------------------
# By default emails are PRINTED in the Command Prompt window running the server,
# so recovery works on your own computer without any email account.
# To send real emails through Gmail, set these before `runserver` (see README):
#   set DJANGO_EMAIL_HOST_USER=yourstudio@gmail.com
#   set DJANGO_EMAIL_HOST_PASSWORD=<16-letter Gmail app password>
EMAIL_HOST_USER = os.environ.get("DJANGO_EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("DJANGO_EMAIL_HOST_PASSWORD", "")
# Online: `bash deploy/set_email.sh` saves the Gmail address + app password in a private
# `.email` file (line 1 address, line 2 app password) instead of in the code.
if not (EMAIL_HOST_USER and EMAIL_HOST_PASSWORD) and (BASE_DIR / ".email").exists():
    _lines = (BASE_DIR / ".email").read_text().split("\n")
    if len(_lines) >= 2:
        EMAIL_HOST_USER, EMAIL_HOST_PASSWORD = _lines[0].strip(), _lines[1].replace(" ", "").strip()
if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ.get("DJANGO_EMAIL_HOST", "smtp.gmail.com")
    EMAIL_PORT = int(os.environ.get("DJANGO_EMAIL_PORT", "587"))
    EMAIL_USE_TLS = True
    DEFAULT_FROM_EMAIL = f"Sreeva <{EMAIL_HOST_USER}>"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    DEFAULT_FROM_EMAIL = "Sreeva <no-reply@sreeva.local>"
PASSWORD_RESET_TIMEOUT = 3 * 24 * 60 * 60  # reset links expire after 3 days

# --- Security ---------------------------------------------------------------
# Brute-force protection for the login page (see accounts/views.py).
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60

SESSION_COOKIE_HTTPONLY = True          # JavaScript can't read the session cookie
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 12 * 60 * 60       # log out after 12 hours
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"                # can't be embedded in other sites (clickjacking)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SSL_REDIRECT", "1") == "1"
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    CSRF_TRUSTED_ORIGINS = [
        o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
    ]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"django.security": {"handlers": ["console"], "level": "WARNING"}},
}
