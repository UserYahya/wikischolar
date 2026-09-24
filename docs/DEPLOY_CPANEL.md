# Deploying WikiScholar on cPanel

WikiScholar is a Django app with a PostgreSQL database. On cPanel it runs through
**Setup Python App** (Phusion Passenger). No Docker, Redis or root access is needed.

## 0. What your hosting must have (ask the host if unsure)

| Need | Where to look in cPanel | Why |
|---|---|---|
| **Setup Python App** with **Python 3.10+** (3.12 best) | Software → Setup Python App | Django 5.1 |
| **PostgreSQL 13+** (16 best), or outbound port 5432 to an external one | Databases → PostgreSQL Databases | the app is PostgreSQL-only (integrity rules are DB triggers); Django 5.1 refuses older servers |
| The **`pg_trgm`** extension | ask the host / run `check_host` (step 5) | school-name matching |
| **SSH / Terminal** access | Advanced → Terminal | to run `migrate` and other commands |
| **SSL** for your domain | Security → SSL/TLS Status (AutoSSL) | the site forces HTTPS |
| **Cron Jobs** | Advanced → Cron Jobs | sends large bulk-message batches |

**MySQL-only hosting will not work.** Many cPanel hosts still ship PostgreSQL 9.x/10: too old.
In that case keep the app on cPanel and use an external PostgreSQL (next section), or use a VPS
(the repo's `docker-compose.yml` runs everything there).

### If the host's PostgreSQL is too old: external PostgreSQL (e.g. Neon)

1. From the cPanel Terminal, check outbound port 5432 is open:
   `python3 -c "import socket; socket.create_connection(('portquiz.net', 5432), 5); print('open')"`
2. Create a PostgreSQL 16 database at neon.tech (or Supabase/Aiven) in the region nearest the
   server (e.g. Singapore for `sg*` servers).
3. Prefer the **direct** connection (turn *Connection pooling* off, or remove `-pooler` from the
   host name). A pooled host also works: when `DB_HOST` contains `pooler` the app turns off
   server-side cursors automatically, which PgBouncer's transaction mode needs for CSV exports and
   bulk sends (`check_host` says so).
4. In `.env`: `DB_HOST=<host>`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_SSLMODE=require`.
   `PGCHANNELBINDING` is not needed. Never paste the password into chats or tickets; if you did,
   reset it in the provider's console.
5. Skip step 1 below (the cPanel database) and continue from step 2.

## 1. Create the database

cPanel → **PostgreSQL Databases**:

1. Create a database, e.g. `wikischolar` (cPanel shows it as `myacct_wikischolar`).
2. Create a user with a strong password (`myacct_wsuser`).
3. **Add the user to the database** with *ALL PRIVILEGES*.

## 2. Create the Python app

cPanel → **Setup Python App → Create Application**:

| Field | Value |
|---|---|
| Python version | 3.12 (or the newest 3.10+) |
| Application root | `wikischolar` (the folder the code goes into) |
| Application URL | your domain or subdomain, e.g. `register.example.org` |
| Application startup file | `passenger_wsgi.py` |
| Application Entry point | `application` |

Click **Create**, then open the app again (pencil icon). At the top it shows
"Enter to the virtual environment…" with a command like
`source /home/myacct/virtualenv/<application root>/3.12/bin/activate && cd /home/myacct/<application root>`.
**Copy that exact command**: the folder is named after *your* application root (for example
`wikischolar.example.org`) and the Python version you picked. Until it runs without an error,
`python` and `pip` don't exist in the Terminal. Your prompt then starts with `(<app root>:3.12)`.

## 3. Upload the code

On your computer, build the upload package:

```sh
python scripts/build_cpanel_zip.py      # -> dist/wikischolar-cpanel.zip
```

It leaves out `.venv`, `.pgsql`, `.pgdata`, caches, other zips and any `.env`. Upload it into the
application root (`/home/myacct/<application root>`) with **File Manager → Upload**, then
**Extract** it there (so `manage.py` sits directly in the application root, not in a subfolder). The folder must contain `passenger_wsgi.py`, `manage.py`, `requirements.txt`,
`apps/`, `config/`, `static/`, `templates/`, `data/`.

## 4. Settings file

Copy **`docs/cpanel.env.example`** (not the root `.env.example`, which is for Docker and
points at hosts `db` and `redis` that don't exist on cPanel) to `.env` in the application root
(File Manager → Copy, then Edit) and fill in:

* `DJANGO_SECRET_KEY` and `WS_CREDENTIALS_KEY`: generate each once (commands are in the file) and
  **keep a copy**. Changing `WS_CREDENTIALS_KEY` later means re-entering the email password and
  SMS API key.
* `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS`: your real domain.
* `DB_NAME`, `DB_USER`, `DB_PASSWORD`: from step 1, with the cPanel prefix.
* Also open Setup Python App → *Environment variables*: anything set there overrides `.env`.

## 5. Install, check, set up the database

cPanel → **Terminal**, then:

Run these **in this order, one at a time**, and stop at the first error. `create_super_admin`
only works after `migrate` (before it, there is no `admins` table). It asks for the password
twice and shows nothing while you type; that password is your dashboard login.

```sh
source /home/myacct/virtualenv/<application root>/3.12/bin/activate && cd /home/myacct/<application root>
pip install -r requirements.txt
python manage.py check_host            # must end with "This host can run WikiScholar."
python manage.py migrate
python manage.py createcachetable
python manage.py seed_reference        # 6 regions, 64 districts, upazilas
python manage.py collectstatic --noinput
python manage.py create_super_admin --email you@wikimedia.org.bd --name "Your Name"
```

If `check_host` says **pg_trgm can't be created**, ask the host's support to run this once as a
PostgreSQL superuser in your database, then run `migrate` again:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

## 6. Start it

Setup Python App → your app → **Restart**. Open `https://your-domain/` (the registration form)
and `https://your-domain/dashboard/` (sign in with the Super Admin from step 5).

After **every** code upload or `.env` change: run `migrate` and `collectstatic` if needed, then
click **Restart** (or `touch tmp/restart.txt` in the app root).

## 7. Cron job for large bulk sends

Batches up to 300 recipients send immediately; bigger ones are queued. cPanel → **Cron Jobs**, *Once
Per Minute*:

```sh
/home/myacct/virtualenv/<application root>/3.12/bin/python /home/myacct/<application root>/manage.py send_queued >/dev/null 2>&1
```

## 8. Email and SMS

Dashboard → **Email & SMS settings**:

* **Email**: Brevo or Google Mail as in the dashboard hints. Many shared hosts **block outgoing
  SMTP** (ports 587/465). If the test email times out or says "Network is unreachable", choose
  **Brevo (HTTPS API)** with a Brevo API key (`xkeysib-…`; it sends over port 443), ask the host to
  allow outgoing SMTP, or use the mailbox cPanel gives you (Email Accounts → *Connect Devices* shows
  its SMTP host, port and login) with the *Other SMTP server* option.
  Every email carries the **Reply-to** from Email settings (pre-filled `info@wikischolar.bd`).
* **Delivery reports (Brevo)**: put a long random `NOTIFY_WEBHOOK_TOKEN` in `.env`
  (`python -c "import secrets; print(secrets.token_urlsafe(32))"`), Restart, then in Brevo add a
  transactional-email **webhook**: URL `https://<your-domain>/notifications/webhook/email/?token=<token>`,
  events *Delivered, Hard bounce, Invalid email, Blocked, Error*. The Messages pages then show
  delivered and bounced messages; without it they stay "Sent".
* **SMS (MiM SMS)**: whitelist the hosting **server's IP** (cPanel home → *General Information →
  Shared IP Address*) and your domain in sms.mimsms.com → Utility → Developer, or every SMS is
  rejected.

* **Wording of the OTP and confirmation emails**: Dashboard → **System emails** (Super Admin).

## 8b. Updating an existing install

1. Build a new package (`python scripts/build_cpanel_zip.py`) and upload + extract it over the
   application root. It never contains `.env`, so the server's settings stay.
2. In the Terminal (after the virtualenv command):
   ```sh
   pip install -r requirements.txt     # only needed if requirements.txt changed
   python manage.py migrate
   python manage.py collectstatic --noinput
   python manage.py check_host
   ```
3. Setup Python App → **Restart**. Read `CHANGELOG.md` for what changed and any new `.env` settings.

## 9. Backups

cPanel → **Backup** → download a *PostgreSQL database backup* regularly (or JetBackup if the host
offers it), and test restoring it once. **With an external database (Neon etc.) cPanel backups do
not include it**: use the provider's backups / point-in-time restore, or run `pg_dump` on a schedule. The database holds minors' personal data: keep backups
private.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Bad Request (400)" | the domain is missing from `DJANGO_ALLOWED_HOSTS` |
| "CSRF verification failed" on sign-in | add `https://your-domain` to `DJANGO_CSRF_TRUSTED_ORIGINS` |
| Page keeps redirecting (http/https loop) | set `DJANGO_BEHIND_PROXY=1` |
| Unstyled pages, or the **old look after an update** (e.g. a huge logo) | run `python manage.py collectstatic --noinput`, then Restart. File names carry a content hash, so browsers then load the new CSS at once (a hard refresh, Ctrl+F5, is only needed if collectstatic was skipped) |
| "Incomplete response" / 500 | `tail -50 stderr.log` in the app root shows the error; `python manage.py check_host` finds most setup problems |
| `pip install` fails building psycopg | ask the host for Python 3.12; wheels exist for it |
| Changes don't appear | click Restart in Setup Python App |
| `activate: No such file or directory`, then `python: command not found` | wrong virtualenv path: copy the exact command from Setup Python App (step 2) |
| `failed to resolve host 'db'` / `'redis'` | `.env` was made from the Docker `.env.example`; use `docs/cpanel.env.example` |
| `PostgreSQL 13 or later is required (found 9.6…)` | host PostgreSQL too old: use an external PostgreSQL (section 0) |
| `relation "admins" does not exist` | run `python manage.py migrate` first |
| Site loads but sign-in gives **500**; log shows `Error -2 connecting to redis:6379` | a leftover `REDIS_URL` (from the Docker `.env.example`) in `.env` or Setup Python App's environment variables: delete it, set `DJANGO_CACHE=db`, run `createcachetable`, Restart |
| Sign-in gives 500; log shows `relation "ws_cache" does not exist` | run `python manage.py createcachetable`, Restart |
| Forgot the dashboard password | `python manage.py changepassword you@example.org` |
| OTP works but **bulk email fails** | open the batch (Messages → batch): the error column / red message shows the provider's reason. `535 Authentication failed` = wrong SMTP login or key; 0 recipients = nobody in the group opted in (untick "Only students who opted in" for essential messages); stuck on "Queued" = keep the batch page open or set up the `send_queued` cron job |
| Emails stay "Sent", never "Delivered" | set up the Brevo webhook (section 8) and `NOTIFY_WEBHOOK_TOKEN`; Gmail/other SMTP give no delivery reports |
