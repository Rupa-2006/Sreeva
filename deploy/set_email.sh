#!/bin/bash
# Lets "Forgot username or password?" send real emails through Gmail.
#   bash ~/studioflow/deploy/set_email.sh
# You need a Gmail "App password": Google Account -> Security -> 2-Step Verification -> App passwords.
cd ~/studioflow
LOWER=$(echo "$USER" | tr '[:upper:]' '[:lower:]')
read -r -p "Gmail address: " ADDR
read -r -s -p "16-letter app password (hidden while typing): " PASS; echo
PASS=$(echo "$PASS" | tr -d ' ')
if [ -z "$ADDR" ] || [ ${#PASS} -ne 16 ]; then
  echo "The app password must be 16 letters. Nothing was changed."; exit 1
fi
umask 077
printf '%s\n%s\n' "$ADDR" "$PASS" > .email
chmod 600 .email
echo "Sending a test email to $ADDR ..."
if DJANGO_DEBUG=0 DJANGO_ALLOWED_HOSTS="${LOWER}.pythonanywhere.com" python3.12 manage.py sendtestemail "$ADDR"; then
  touch "/var/www/${LOWER}_pythonanywhere_com_wsgi.py"
  echo "Done! Check $ADDR for a test email. 'Forgot password' now sends real emails."
else
  rm -f .email
  echo "Gmail refused the login. Check the address and app password and try again. Nothing was changed."
  exit 1
fi
