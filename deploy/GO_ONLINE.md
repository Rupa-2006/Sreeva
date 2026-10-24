# Put Sreeva online (PythonAnywhere, free)

Your address will be **https://YOURNAME.pythonanywhere.com** (YOURNAME = the username you pick).

1. **Create the account** at https://www.pythonanywhere.com → *Pricing & signup* → *Create a Beginner account* (free).
   The username becomes part of the address, so pick something like `sreeva` or `srisaiphoto`.
2. **Create the web app**: open the **Web** tab → *Add a new web app* → *Next* → **Manual configuration** → **Python 3.12** → *Next*.
3. **Upload the code**: open the **Files** tab → *Upload a file* → choose `sreeva_online.zip`.
4. **Run the setup**: open the **Consoles** tab → *Bash* and paste these two lines:

   ```bash
   unzip -o -q ~/sreeva_online.zip -d ~ && bash ~/studioflow/deploy/setup_pythonanywhere.sh
   ```
   Wait until it says **Done!**.
5. **Turn on HTTPS**: back on the **Web** tab, scroll to *Security* → switch **Force HTTPS** ON → press the green **Reload** button at the top.
6. **Create your studio**: open https://YOURNAME.pythonanywhere.com → *Create studio account* → fill in the studio details.
7. **Close sign-ups** (so strangers can't make accounts) — in the Bash console:

   ```bash
   bash ~/studioflow/deploy/close_signup.sh
   ```
8. **Every 3 months** PythonAnywhere emails you: open the **Web** tab and click **"Run until 3 months from today"**. (Free accounts must do this, or the site pauses.)

## Updating later
Upload the new `sreeva_online.zip`, then in a Bash console:
```bash
unzip -o -q ~/sreeva_online.zip -d ~ && bash ~/studioflow/deploy/update_pythonanywhere.sh
```
Your bookings and payments are kept (the zip never contains the database).

## Real emails for "Forgot password"
Create a Gmail *App password* (Google Account → Security → 2-Step Verification → App passwords), then:
```bash
bash ~/studioflow/deploy/set_email.sh
```
It asks for the Gmail address and app password (hidden), saves them in a private file and sends a test email.

## Backups
A copy of the database is saved automatically once a day in `~/studioflow/backups` (newest 30 kept).
To keep one on your computer too: **Studio settings → Backup & export → Download Excel**, or download
`~/studioflow/db.sqlite3` from the Files tab.
