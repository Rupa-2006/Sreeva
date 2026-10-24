"""Last-resort recovery for whoever runs the server on their own computer.

    python manage.py show_logins                 # list every username, its studio and role
    python manage.py changepassword <username>   # (built into Django) set a new password

Passwords are stored as one-way hashes, so nobody - not even this command - can
read an old password. It can only be replaced with a new one.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "List all usernames with their studio and role (for recovering a forgotten username)."

    def handle(self, *args, **options):
        users = User.objects.select_related("profile__studio").order_by("profile__studio__name", "username")
        if not users:
            self.stdout.write("No accounts yet.")
            return
        self.stdout.write(f"{'USERNAME':<18}{'NAME':<18}{'ROLE':<9}{'ACTIVE':<8}{'EMAIL':<30}STUDIO")
        for u in users:
            p = getattr(u, "profile", None)
            role = "admin" if u.is_superuser else (p.get_role_display() if p else "-")
            self.stdout.write(
                f"{u.username:<18}{(u.first_name or '-')[:17]:<18}{role:<9}{'yes' if u.is_active else 'no':<8}"
                f"{(u.email or '-')[:29]:<30}{p.studio.name if p and p.studio else '-'}"
            )
        self.stdout.write(self.style.SUCCESS(
            "\nForgot a password? Run:  python manage.py changepassword <username>"
        ))
