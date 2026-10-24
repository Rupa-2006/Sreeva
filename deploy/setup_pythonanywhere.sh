#!/bin/bash
# Sreeva — one-time setup on PythonAnywhere (free account).
# Run in a PythonAnywhere "Bash console":   bash ~/studioflow/deploy/setup_pythonanywhere.sh
# Safe to run again later (after uploading a new version) — it never deletes your data.
set -e
PY=python3.12
APP=~/studioflow
LOWER=$(echo "$USER" | tr '[:upper:]' '[:lower:]')   # web addresses are lowercase (MyName -> myname)
SITE="${LOWER}.pythonanywhere.com"
WSGI="/var/www/${LOWER}_pythonanywhere_com_wsgi.py"
cd "$APP"

echo "1/5  Installing Django ..."
$PY -m pip install --user --quiet -r requirements-server.txt

echo "2/5  Creating the private secret key (only the first time) ..."
if [ ! -f .secret_key ]; then
  $PY -c "import secrets; print(secrets.token_urlsafe(64))" > .secret_key
  chmod 600 .secret_key
fi

export DJANGO_DEBUG=0 DJANGO_ALLOWED_HOSTS="$SITE"
echo "3/5  Preparing the database ..."
$PY manage.py migrate --noinput
echo "4/5  Preparing the design files ..."
$PY manage.py collectstatic --noinput --clear > /dev/null

echo "5/5  Connecting the website ..."
if [ ! -f "$WSGI" ]; then
  echo
  echo "!! Web app not found. Open the 'Web' tab, click 'Add a new web app',"
  echo "   choose 'Manual configuration' and 'Python 3.12', then run this again."
  exit 1
fi
SIGNUP=1
if grep -q 'SREEVA_ALLOW_SIGNUP"] = "0"' "$WSGI" 2>/dev/null; then SIGNUP=0; fi
cat > "$WSGI" <<PYEOF
# Sreeva — written by deploy/setup_pythonanywhere.sh
import os, sys
path = "/home/${USER}/studioflow"
if path not in sys.path:
    sys.path.insert(0, path)
os.environ["DJANGO_SETTINGS_MODULE"] = "studioflow.settings"
os.environ["DJANGO_DEBUG"] = "0"
os.environ["DJANGO_ALLOWED_HOSTS"] = "${SITE}"
os.environ["DJANGO_CSRF_TRUSTED_ORIGINS"] = "https://${SITE}"
os.environ["DJANGO_SSL_REDIRECT"] = "0"   # use "Force HTTPS" on the Web tab instead
os.environ["SREEVA_ALLOW_SIGNUP"] = "${SIGNUP}"
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
PYEOF
touch "$WSGI"   # reloads the website

echo
echo "Done!  Open https://${SITE}"
echo "Last step on the Web tab: turn ON 'Force HTTPS', then press the green Reload button."
