#!/bin/bash
# After uploading a newer version of the code: applies database changes and reloads.
#   bash ~/studioflow/deploy/update_pythonanywhere.sh
set -e
cd ~/studioflow
python3.12 manage.py backup || true          # safety copy first
DJANGO_DEBUG=0 python3.12 manage.py migrate --noinput
DJANGO_DEBUG=0 python3.12 manage.py collectstatic --noinput --clear > /dev/null
LOWER=$(echo "$USER" | tr '[:upper:]' '[:lower:]')
touch "/var/www/${LOWER}_pythonanywhere_com_wsgi.py"
echo "Updated and reloaded."
