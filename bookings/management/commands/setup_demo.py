"""The public "Try the demo" studio on the live website.

    python manage.py setup_demo --reset     # (re)create it with fresh sample data

Run it once, then daily (PythonAnywhere → Tasks) so visitors always see a clean demo.
It only ever touches the demo studio and its users — never a real studio.

Logins:  demo / Demo@2026  (owner)   ·   demo_ravi / Demo@2026  (staff)
"""
from .seed_demo import Command as SeedCommand

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "Demo@2026"


class Command(SeedCommand):
    help = "Create or refresh the public demo studio (logins: demo / Demo@2026)."
    OWNER, OWNER_PASSWORD, STAFF_PASSWORD, STAFF_PREFIX = DEMO_USERNAME, DEMO_PASSWORD, DEMO_PASSWORD, "demo_"
    STUDIO_NAME, OWNER_EMAIL = "Demo Studio", ""
