#!/bin/bash
# After your studio account is created online, run this so nobody else can sign up:
#   bash ~/studioflow/deploy/close_signup.sh        (use "open" to allow sign-ups again)
LOWER=$(echo "$USER" | tr '[:upper:]' '[:lower:]')
WSGI="/var/www/${LOWER}_pythonanywhere_com_wsgi.py"
VALUE=0; [ "$1" = "open" ] && VALUE=1
sed -i "s/SREEVA_ALLOW_SIGNUP\"\] = \"[01]\"/SREEVA_ALLOW_SIGNUP\"] = \"$VALUE\"/" "$WSGI"
touch "$WSGI"
[ "$VALUE" = "0" ] && echo "Sign-ups are now closed." || echo "Sign-ups are open again."
