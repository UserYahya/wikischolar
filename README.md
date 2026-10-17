# WikiScholar Registration & Database Platform — Phase 1 MVP

> **New here?** Start with [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md): what the app does, how to install it anywhere (including cPanel), and the rules for changing it.
> Original spec + implementation status: [`WikiScholar Registration & Database Platform — Complete Roadmap.md`](WikiScholar%20Registration%20%26%20Database%20Platform%20%E2%80%94%20Complete%20Roadmap.md). Dated changes: [`CHANGELOG.md`](CHANGELOG.md).

Wikimedia Bangladesh's student registration system: a public Bangla registration form, the
central PostgreSQL database behind it, and an English admin dashboard for searching,
editing, messaging and auditing student records.

Built as a **modular monolith** (Django 5.1 + PostgreSQL 16), exactly as the roadmap's
Phase 1 describes: each module is a Django app that owns its own tables and migrations,
so later modules (Exam, CRM, Volunteer, Call-center, Analytics) plug in beside them.

| Module | App | Owns |
|---|---|---|
| Core | `apps/core` | `admins`, `audit_logs`, `id_sequences`, RBAC, soft-delete base, DB integrity triggers |
| Reference Data | `apps/reference` | `regions`, `districts`, `thanas`, `schools`, `school_aliases`; public lookup API; school matching & merge |
| Registration | `apps/registration` | `students`, `email_verifications`, `edit_history`; public form + OTP |
| Notification | `apps/notifications` | `email_batches`, `sms_batches`, `notification_logs`, `email_settings`, `sms_settings`; providers, delivery webhooks |
| Admin Dashboard | `apps/dashboard` | no tables; UI over the other modules' services |

## District → region mapping is data, not code

The 6-region / 64-district mapping is **not in any Python file**. It lives in
`data/reference_seed.json`, is loaded once into the database, and from then on is managed on
**Dashboard → Locations**:

* `districts.region_id` is a nullable, editable foreign key. Reassigning a district is one
  dropdown change, recorded in `audit_logs` (`reference.district_region_changed`).
* A student's region is **never stored** on the student row. It is derived through the
  district at read time, so a reassignment instantly moves every student in that district
  (dashboard filters, reports, the public form's region autofill, CSV exports).
* Regions can be added, renamed, or archived (only when empty). Districts with no region
  are highlighted and reported as "No region".
* Re-running `seed_reference` adds new places but **keeps** dashboard edits: region and district
  names are never overwritten, and district→region assignments are kept unless you pass
  `--reset-region-assignments`. A thana renamed in the dashboard is matched by name, so a manual
  re-run adds its seed name back as a new thana; the Azure stack runs it only on an empty database
  (`--if-empty`).

## Quick start (Docker)

```sh
cp .env.example .env          # set DJANGO_SECRET_KEY, DB_PASSWORD, email settings, hosts
docker compose up --build     # migrates, seeds regions/districts/thanas, starts gunicorn + worker
docker compose exec web python manage.py create_super_admin --email you@wikimedia.org.bd --name "Your Name"
```

Public form: `http://localhost:8000/` · Dashboard: `http://localhost:8000/dashboard/`

For a quick local HTTP trial, set `DJANGO_DEBUG=1` and `DJANGO_SSL_REDIRECT=0` in `.env`.

## Deploying on an Azure VM (Docker + Caddy + Cloudflare)

See [`docs/DEPLOY_AZURE.md`](docs/DEPLOY_AZURE.md): `docker-compose.prod.yml`, `deploy/Caddyfile`,
daily `pg_dump` backups to S3 (`deploy/pg_backup.sh`).

## Deploying on cPanel shared hosting

See [`docs/DEPLOY_CPANEL.md`](docs/DEPLOY_CPANEL.md): Setup Python App + PostgreSQL, `.env` from
`docs/cpanel.env.example`, and `python manage.py check_host` to confirm the host can run it.
Build the upload package with `python scripts/build_cpanel_zip.py` (→ `dist/wikischolar-cpanel.zip`,
never contains `.env`).

## Quick start (without Docker)

Requires Python 3.12 and PostgreSQL 16 (with the `pg_trgm` contrib extension available;
the DB user must be allowed to `CREATE EXTENSION`, or create it once as a superuser).

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
createdb wikischolar
export DJANGO_DEBUG=1 WS_OTP_DEBUG_ECHO=1     # dev: OTP is printed to console and echoed in the API
python manage.py migrate
python manage.py seed_reference
python manage.py create_super_admin --email you@example.org --name "You"
python manage.py runserver
```

With the default console email backend, OTP and confirmation emails print in the terminal.

## One language in the database: English

The public form and the dashboard are in English, and every free-text value (student and
guardian names, the "Other" relation, school names and aliases, class roll, SID) must be
English letters, digits and basic punctuation. Bangla digits are converted to 0-9; any other
script is refused, both in the browser and on the server (`apps.core.utils.english_text`, the
one rule every module uses). Reference data keeps its separate `name_bn` columns.

## Email & SMS sending (Brevo / Google Mail / MiM SMS)

A Super Admin sets the sending account on **Dashboard → Email & SMS settings**: Brevo (SMTP relay),
**Brevo (HTTPS API)** for hosts that block outgoing SMTP (API key `xkeysib-…`, sends over port 443),
Google Mail / Workspace (App password), any other SMTP server, or Console for development.
Every email is sent with a **Reply-to** (pre-filled `info@wikischolar.bd`, env `WS_REPLY_TO`).
Bulk messages are **named batches**: search them on Messages, filter recipients by status
(including *Not delivered*), download recipients as CSV, and filter students by message history
(received / not sent yet / not delivered). Email delivery reports come from a Brevo webhook
(`/notifications/webhook/email/?token=NOTIFY_WEBHOOK_TOKEN`).
The password / SMTP key is stored encrypted (`WS_CREDENTIALS_KEY`, or derived from
`DJANGO_SECRET_KEY`) and never shown again. Save, send a test email, then tick *Use these
settings*: from then on OTP codes, confirmations and bulk email all use it. While it is off,
the `EMAIL_*` env settings apply. Changes and tests are recorded in the audit log (without the password).

**SMS (MiM SMS)** is set on the same page: API username (your sms.mimsms.com login email),
API key (Utility → Developer; it must be activated), Sender ID (Utility → Sender ID). The key is
stored encrypted. MiM SMS only accepts calls from whitelisted IPs/domains, so add the server's
public IP and domain in Utility → Developer first. The page can send a test SMS and check the
balance. Each message is sent as a transactional SMS (`/V2/SMS`, one number per call) so every
student gets its own tracking ID.

## Guardian declaration and system emails

The form starts with a **required** guardian declaration (Youth Safety Policy): "I am the guardian
of the student named below and I am filling in this form on their behalf". It is stored per student (`filled_by`,
`guardian_declared_at`), shown on the dashboard, filterable and exported.

A Super Admin can change the wording of the **OTP email** and the **registration confirmation** on
**Dashboard → System emails** (placeholders such as `{code}`, `{student_name}`, `{wikischolar_id}`,
`{details}`; preview, test send, reset to default).

## Student IDs

Student IDs look like `WS-2027-000001`: prefix `WS_ID_PREFIX`, programme year `WS_ID_YEAR`
(default 2027; set it empty to use the calendar year), then a per-year sequence. IDs already
issued never change.

## Student batches

On **Students**, enter *Students per batch* in the filter panel to split the filtered list into
numbered batches (oldest registration first by default, so batches stay stable as new students
join). Each batch can be viewed, exported to CSV, or messaged on its own; message batches
record which student batch they were sent to.

## Management commands

| Command | Purpose |
|---|---|
| `seed_reference [--file PATH] [--reset-region-assignments]` | Load/refresh regions, districts and thanas (the government's BANBEIS list, newer upazilas, cantonments, "Other thana"). Idempotent. |
| `import_schools CSV [--status verified\|pending]` | Import a school list (`district,thana,name`; thana optional). Same checks as Dashboard → Schools → *Import CSV*, which also offers a template. |
| `import_banbeis_schools XLSX [--type TYPE] [--dry-run]` | Load the government's school list (BANBEIS .xlsx) with EIIN and government data; matches existing schools by EIIN, then by name; safe to re-run. `--type "SCHOOL & COLLEGE"` takes only that institute type. |
| `undo_school_import [ID] [--list] [--dry-run] [--yes]` | Undo one school import: its schools are removed (restorable from Schools → Removed); ones with students are kept. Run `--list`, then `ID --dry-run`. |
| `create_super_admin --email --name [--password]` | Bootstrap the first Super Admin; everyone else is created from the dashboard. |
| `check_host` | Pre-flight on a new server: Python, PostgreSQL 13+, `pg_trgm`, settings, migrations, cache. |
| `find_non_english` | List stored names, school names, rolls or SIDs that aren't English (entered before the English-only rule). |
| `send_queued` | Send queued messages of large batches. Run from **one** worker/cron (see compose `worker`). |

## Tests

```sh
DJANGO_DEBUG=1 python manage.py test tests
```

282 tests, run against real PostgreSQL (the integrity rules live in the database, so SQLite
would not exercise them). They cover: the full register flow over HTTP; WS ID sequencing;
roll-or-SID, phone, thana-in-district and consent rules; honeypot; OTP typo warning,
hashing, lockout and rate limits; school resolution (exact / abbreviation / alias / new
pending) and typeahead scoping; DB-level refusal of deletes, audit tampering, bad phone and
cross-district thanas; role permissions on every page; edit history; view/export
auditing; archive/restore; filters; region reassignment; school merge; bulk email with
opt-in filter, delivery webhook and resend; admin management and login auditing.

## Roadmap coverage

**Registration form** — 4 steps, all 17 fields (classes 6–10 only; a free-text relation when the guardian is “Other”), English labels and messages, English-only text (Bangla
digits become 0-9), BD phone `^01[3-9]\d{8}$` (normalises `+880`, spaces, dashes), roll **or**
SID, instant email typo hint ("Did you mean name@gmail.com?", also for "gmailcom" / "gmail,com"), 6-digit email OTP that gates
submission (10-minute expiry, 5 attempts, resend cooldown, rate-limited per email and IP,
bound to the browser session), Youth Safety Policy consent (timestamp + policy version
stored), guardian's photo permission for offline events (Youth Safety Policy 4.5; optional, stored with
its date, filterable, editable for withdrawal), updates opt-in, summary screen with the WikiScholar ID, confirmation email, and a confirmation
SMS with the ID and the contact address (one 160-character SMS).

**Schools** — typeahead over the whole district (the student's own thana first, each school
shown with its thana) using `pg_trgm` over names and aliases, from the 3rd letter typed (the API
returns nothing for a 1–2 character query);
free text is kept exactly as typed (`school_name_as_entered`) *and* resolved to a school row
(dual storage); unknown schools become `pending`; admins verify, rename, add aliases, and
merge duplicates (students re-pointed with edit history, misspelling becomes an alias, the
duplicate row stays as `merged`). Admins add schools on **Schools → Add school** (a typeahead
lists schools already in the thana; the same name or an alias is refused and a similar name
needs confirmation) and remove ones with no students (archived, restorable from *Removed*).
**Schools → Import CSV** bulk-loads schools: download the template (headings *District,
Thana, School name*), fill in one school per row (a downloadable district & thana list gives the
spellings), upload, check the per-row preview, then confirm. The thana may be left blank (or the
column left out): such a school belongs to its whole district (suggested and duplicate-checked
across all its thanas) until an admin sets its thana on the school page.

**Dashboard** — Super Admin / Admin / Viewer; multi-select district, region, thana, school,
class, gender, date-range, opt-in and text search; **advanced search** on Students and Schools
(conditions in ALL/ANY groups, including the schools' government data) with **shared saved
searches** and CSV export of the results; CSV export; per-student edit history;
archive/restore (no hard deletes); bulk email/SMS to the current filter with batch IDs
(`EB-2026-0001`, `SB-2026-0001`), per-recipient delivery status, and resend-failed; school
review and duplicate merge; locations; audit log (including record views and exports);
admin accounts (every admin can change their password; a Super Admin can set a new one for
others). Optional **Cloudflare Turnstile** on "Send verification code" and the sign-in
(`WS_TURNSTILE_SITE_KEY` / `WS_TURNSTILE_SECRET_KEY`).

## Deliberately deferred (decide before Phase 2)

* **Advanced query interface** — the roadmap lists it as an open question. The filter panel
  covers the listed filters; a saved-query / query-builder screen is not built.
* **Field-level encryption at rest** for phone, email and guardian name. Today: disk/volume
  encryption + TLS + least-privilege roles are assumed. Adding it later means an encrypted
  column plus a keyed hash for search/dedup.
* **Async job queue.** Batches up to `WS_INLINE_DISPATCH_MAX` (300) send within the request;
  larger ones are queued and sent by `send_queued`. Swap in Celery/RQ when volumes require.
  Run only one `send_queued` process at a time.
* **Guardian contact** — the form stores guardian name and relation only; whether a
  guardian phone/consent is needed for minors is still an open policy question.
* **Duplicate-student detection** (same name + DOB + school) — not blocked at registration;
  a review screen is a natural next step.
* **SMS delivery reports** — `MimSmsProvider.delivery_status()` wraps MiM SMS's `/V2/DlrApi`, but
  nothing polls it yet, so SMS rows stay "sent" rather than "delivered". A periodic job could poll it
  about 5 minutes after sending. For very large sends, `/V2/OneToMany` (up to 1000 numbers a call)
  would cut request count at the cost of per-student tracking IDs.
* **2FA for admins** — recommended before production.

## Going to production checklist

`DJANGO_DEBUG=0`, a strong `DJANGO_SECRET_KEY`, real `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS`,
HTTPS in front (HSTS and secure cookies turn on automatically), `REDIS_URL` set (rate limits
must be shared across workers), SMTP credentials with SPF/DKIM on the sending domain,
`NOTIFY_WEBHOOK_TOKEN`, daily PostgreSQL backups with a tested restore, and
`WS_OTP_DEBUG_ECHO=0`.

More detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/DATABASE.md`](docs/DATABASE.md) · [`docs/schema.sql`](docs/schema.sql)
