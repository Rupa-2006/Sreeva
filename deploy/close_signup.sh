#!/bin/bash
# Sign-ups close by themselves once the first real owner account exists.
# Use this to force them closed anyway, or "open" to let other studios sign up:
#   bash ~/studioflow/deploy/close_signup.sh          (always closed)
#   bash ~/studioflow/deploy/close_signup.sh open     (always open)
#   bash ~/studioflow/deploy/close_signup.sh auto     (back to automatic)
LOWER=$(echo "$USER" | tr '[:upper:]' '[:lower:]')
WSGI="/var/www/${LOWER}_pythonanywhere_com_wsgi.py"
VALUE=0; [ "$1" = "open" ] && VALUE=1; [ "$1" = "auto" ] && VALUE=auto
sed -i "s/SREEVA_ALLOW_SIGNUP\"\] = \"[^\"]*\"/SREEVA_ALLOW_SIGNUP\"] = \"$VALUE\"/" "$WSGI"
touch "$WSGI"
case "$VALUE" in
  0) echo "Sign-ups are now closed." ;;
  1) echo "Sign-ups are now always open." ;;
  *) echo "Sign-ups are automatic: open only until the first owner account exists." ;;
esac
