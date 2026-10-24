"""Automatic backups of the whole database (a copy of db.sqlite3).

- A copy is made every time Sreeva starts (START_SREEVA.bat) and once a day while
  it is running. The newest 30 copies are kept in the "backups" folder.
- The copy uses SQLite's own backup feature, so it is safe while the website runs.
- To restore: close Sreeva, copy a backup file over db.sqlite3, start again.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

KEEP = 30


def backup_dir():
    return Path(settings.BACKUP_DIR)


def list_backups():
    d = backup_dir()
    if not d.exists():
        return []
    files = sorted(d.glob("sreeva-*.sqlite3"), key=lambda p: p.name, reverse=True)
    out = []
    for p in files:
        st = p.stat()
        out.append({"name": p.name, "size": st.st_size,
                     "when": timezone.make_aware(datetime.fromtimestamp(st.st_mtime))})
    return out


def make_backup(label=""):
    """Copy the live database into the backups folder. Returns the new file's path (or None)."""
    if connection.vendor != "sqlite":
        return None
    d = backup_dir()
    d.mkdir(parents=True, exist_ok=True)
    stamp = timezone.localtime().strftime("%Y-%m-%d_%H%M%S")
    target = d / f"sreeva-{stamp}{('-' + label) if label else ''}.sqlite3"
    connection.ensure_connection()
    dest = sqlite3.connect(str(target))
    try:
        connection.connection.backup(dest)
    finally:
        dest.close()
    for old in sorted(d.glob("sreeva-*.sqlite3"), key=lambda p: p.name)[:-KEEP]:
        old.unlink(missing_ok=True)
    return target


def backup_today_if_needed():
    """Make today's copy if there isn't one yet."""
    if not getattr(settings, "AUTO_BACKUP", True):
        return None
    today = timezone.localdate().strftime("%Y-%m-%d")
    d = backup_dir()
    if d.exists() and any(d.glob(f"sreeva-{today}_*.sqlite3")):
        return None
    return make_backup()
