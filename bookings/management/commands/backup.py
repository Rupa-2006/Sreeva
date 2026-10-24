from django.core.management.base import BaseCommand
from django.db import connection

from bookings.backup import make_backup


class Command(BaseCommand):
    help = "Save a copy of the database in the backups folder (keeps the newest 30)."

    def handle(self, *args, **options):
        if connection.vendor == "sqlite":
            from django.conf import settings
            from pathlib import Path
            if not Path(settings.DATABASES["default"]["NAME"]).exists():
                self.stdout.write("  No data yet, nothing to back up.")
                return
        path = make_backup()
        if path:
            self.stdout.write(f"  Backup saved: {path}")
