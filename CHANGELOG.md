# Changelog

What changed, newest first. Every improvement adds an entry here and updates the documents it
affects (see "Keeping the docs current" in [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md)).

## 2026-10-12

### Added
- **`manage.py undo_school_import`** takes back a wrong school import. `--list` shows the 20 most
  recent imports (audit id, date, who, how many schools, verified/pending, and whether it was already
  undone). `undo_school_import ID --dry-run` lists what would be removed, and without `--dry-run` it asks you
  to type REMOVE (`--yes` skips the question). The import's schools are removed in the same way as a school
  page's *Remove school* (archived, so they can be restored from Schools → Removed). They leave the list,
  suggestions and duplicate checks, so the corrected file imports cleanly. Schools that students are
  linked to, or that other schools were merged into, are kept and listed with the reason. One
  `school.import_undone` audit entry records it. 3 new tests (142 in total).

## 2026-10-03

### Changed
- **Dates are British style (dd/mm/yyyy) and look the same on every browser and phone.** The
  registration form's date of birth, the dashboard's student editor and the "Registered between"
  filter no longer use the browser's own date picker (which differs per phone and shows US order
  on some). Each is now a text box (number keypad on phones, slashes added while typing, Bangla
  digits accepted) with a calendar button that opens Air Datepicker 3.6.0 (MIT, vendored in
  `static/vendor/air-datepicker/`). The birth-date calendar starts on a year grid.
- The server reads dd/mm/yyyy (`apps.core.utils.parse_date`, `BritishDateField`) and still accepts
  yyyy-mm-dd, so old dashboard links keep working. A wrong date gets "Enter the date as dd/mm/yyyy,
  for example 14/03/2012."
- The registration summary and confirmation email show the date of birth as dd/mm/yyyy
  (`{date_of_birth}` placeholder). CSV exports keep yyyy-mm-dd.
- Registration step 2: the label is now **"Student ID (SID) (if any)"** and the hint below says "Fill in at
  least one. If the school hasn't given the student an ID, the class roll is enough.", so students
  without an SID aren't held up looking for one.
- Registration step 3: **one clear next action**. "Send verification code" and then "Verify code" are the solid
  green buttons; "Next step" is hidden until the email is verified (the bar says "Verify your email to
  continue.") and then gets focus. Enter in the phone or email box sends the code instead of showing an
  error. Changing a verified email hides "Next step" again.
- Registration step 3: after "Send verification code" a **countdown** under the code box shows
  "Code expires in 9:59" (from `WS_OTP_TTL_MINUTES`), turning red in the last minute. At zero, "Verify
  code" is disabled, the message "This code has expired. Send a new one." appears and "Send a new code"
  is enabled at once. Verifying, or changing the email, removes the countdown.
- Dashboard **Schools: add and remove schools.** *Add school* (header button, also offered when a
  list is empty) replaces the small form that only appeared after picking a district. Choose district
  and upazila, then type the name: schools already listed in that upazila appear as you type (like
  the registration form, but including pending ones), and picking one opens it. The server refuses
  the same name or an alias in the upazila, and asks for confirmation when a name is as similar as
  the duplicate review would flag. Each school page has **Remove school** (with a reason), allowed
  only when no active students or merged schools point to it; removed schools are listed under
  *Removed* and can be restored. Removed schools no longer catch registrations through their
  aliases. 10 new tests (131 in total).
- Dashboard **Schools → Import CSV**: download the **template** (headings *District, Upazila, School
  name*), fill in one school per row, and upload it. A separate **district & upazila list** (all
  districts or one, English and Bangla) gives the spellings the import recognises. A
  **preview** shows what happens to each row (will be added / similar to a listed school, added only
  if ticked / already listed / repeated in the file / error with the reason) and nothing is saved
  until you confirm. Schools can be added as verified or pending. `manage.py import_schools` now
  uses the same checks (it also catches aliases and reports each bad row). 8 new tests (139 in total).
- Dashboard **Students**: a **"Hide filters"** button next to Export CSV folds the filter panel away so
  the list uses the full width. While hidden it reads "Show filters (2 on)", counting the filters that
  narrow the list (not sort or batching). The choice is remembered in that browser. 1 new test (122 in total).

## 2026-09-25

### Added
- `docs/CHAT_SUMMARY.md`: summary of the development chats (requests, decisions, deployment lessons), without secrets.

## 2026-09-24 (fifth update)

### Added
- **Email already registered** warning: "Send verification code" refuses an address that an active student already
  uses ("This email address is already registered for another student. Please use a different email address.",
  HTTP 409, no code sent). Re-checked on submit (two tabs); archived students free their address. Checked after
  the rate limit, so the form can't be used to probe many addresses quickly. 3 new tests (118 in total).

### Upgrade notes
- No migrations. Upload, `collectstatic --noinput`, Restart.

## 2026-09-24 (fourth update)

### Changed
- **Guardian declaration is required** (Youth Safety Policy): the checkbox is mandatory in the browser and on the
  server; the "leave unticked if you are the student" text is gone; the section explains the policy and the
  guardian-name field reads "Guardian's name (your name)". Existing registrations keep `filled_by = student`.
- **New header design**: slim white bar, logo 44 px high (36 px on phones), "A Wikimedia Bangladesh programme"
  and a pill-shaped "← Back to wikischolar.bd" button, all on one centre line; the logo has fixed width/height
  attributes so it stays small even before the CSS loads.
- Static files get **content-hashed names** (`apps/core/storage.py`, WhiteNoise manifest storage): browsers load
  new CSS/JS immediately after an update. If `collectstatic` is forgotten, the page falls back to the plain file
  name instead of an error.

### Fixed
- System emails page: the subject box (and other form rows) stretched to the height of the preview column.
- The logo appeared huge on the live site because browsers kept the old cached stylesheet (see above).

### Added
- The code is in a **private GitHub repository** (see PROJECT_GUIDE "Source code and git"); `.gitignore` extended
  (zips, logs, `.claude/`, `.env.bak`) and `.gitattributes` added (LF line endings).

### Upgrade notes
- No migrations. Run `collectstatic --noinput` (required from now on after every upload), then Restart.

## 2026-09-24 (third update)

### Added
- **Guardian declaration** at the start of the form (first optional; required since the fourth update): "I am the guardian (parent) of the student
  named below, and I am filling in this form on their behalf." Stored as `students.filled_by` (`student` /
  `guardian`) and `guardian_declared_at` (DB check keeps them consistent); shown in the success summary,
  the confirmation email and the student page; Students filter "Form filled in by"; exported in the CSV.
- **System emails** page (Super Admin, Dashboard → System emails): edit the subject and text of the OTP email and
  the registration confirmation with placeholders; required/unknown placeholders are checked; preview with sample
  data; "Send test to me"; "Reset to default" (no delete); all changes audited (`email_templates` table).
- System email registry (`notifications.services.register_system_email`), so future modules can make their own
  emails editable the same way; registration's defaults live in `apps/registration/emails.py`.
- `tests/test_system_emails.py` (13 tests; 115 in total).

### Changed
- OTP and confirmation emails are built from the registry instead of `templates/registration/email/*.txt`
  (removed). Default wording unchanged, plus a "Form filled in by" line in the confirmation.

### Not changed (checked)
- The **Brevo HTTPS API** email option that fixed sending on the live server is intact; the provider saved on
  the server is not touched by uploads.

### Upgrade notes
- New migrations `registration.0005_guardian_declaration` and `notifications.0008_email_templates`: run
  `migrate`. New CSS/JS: run `collectstatic --noinput`. No new packages, no new `.env` settings.

## 2026-09-24 (second update)

### Added
- **Logo** in the public header and on the dashboard sign-in (`static/img/wikischolar-logo.png`, also the favicon).
- **"Back to wikischolar.bd"** link in the header and on the success screen (`WS_SITE_URL`).
- Email step: the code is sent **by email only**; students are told to check **Spam/Junk**.
- **Named message batches** (name required, English); Messages list search by name/code/subject, channel
  filter, "only batches with undelivered messages", per-status counts.
- Batch page: recipient filter incl. **Not delivered** (failed or bounced), recipient search, **recipients CSV**
  (audited), "Show these students", "Send the remaining N now" with automatic continuation.
- Students → **Message history** filter: received / not sent yet / not delivered, for any batch.
- **Brevo delivery webhook** support (`/notifications/webhook/email/?token=`): delivered / bounced per message;
  the Brevo API's own `messageId` is stored so webhooks can match.
- Settings `WS_REPLY_TO`, `WS_SITE_URL`, `WS_INLINE_DISPATCH_SECONDS`, `DB_DISABLE_SERVER_SIDE_CURSORS`.
- `tests/test_messaging.py` (30 tests; 102 in total).

### Changed
- **Reply-to on every email** (OTP, confirmation, bulk, test): Email settings' Reply-to, pre-filled with
  `info@wikischolar.bd`; blank falls back to `WS_REPLY_TO`.
- Public school typeahead suggests **approved (verified) schools only**; the dashboard editor still lists pending.
- Bulk sending is chunked (`WS_INLINE_DISPATCH_SECONDS`) and claims each message with `SKIP LOCKED`, so the
  browser, the button and `send_queued` never send twice; `dispatch_batch` returns how many are still queued.
- Compose explains when there are 0 recipients (nobody opted in) and keeps typed text when switching channel.

### Fixed
- **Bulk email failing while OTP worked** (reported from the cPanel install; the server's exact error wasn't
  captured, so every cause found in the bulk path was fixed): bulk sending held a server-side cursor open,
  which pooled database connections (Neon `-pooler`) reject, so server-side cursors are now off automatically
  for pooled hosts and sending no longer depends on them; message text containing `{` or `}` crashed
  rendering; a request timeout mid-send left the batch stuck on "Sending"; provider errors
  (e.g. `535 Authentication failed`) are now shown with a hint.

### Upgrade notes
- New migration `notifications.0007_batch_name`: run `migrate`. New static files (logo, CSS, JS): run
  `collectstatic --noinput`. No new Python packages.
- Optional `.env` additions: `WS_REPLY_TO`, `WS_SITE_URL`, `WS_CONTACT_EMAIL=info@wikischolar.bd`, and
  `NOTIFY_WEBHOOK_TOKEN` for the Brevo webhook.

## 2026-09-24

### Added
- **Brevo HTTPS API** email provider (`apps/notifications/backends.py`): sends over port 443 for hosts
  that block outgoing SMTP; uses a Brevo API key (`xkeysib-…`), no username. Rejects an SMTP key by mistake.
- **Reply-to address** in Email settings: used by every email (SMTP and Brevo API).
- `manage.py check_host` also checks that migrations are applied, the cache works and the cache table exists.
- 500 errors are logged with tracebacks to stderr (`stderr.log` on cPanel), even with debug off.
- `scripts/build_cpanel_zip.py`: builds `dist/wikischolar-cpanel.zip` without local or secret files.
- `PROJECT_GUIDE.md` (handover + AI prompting guide) and this changelog.

### Changed
- `check_host` requires **PostgreSQL 13+** (what Django 5.1 actually needs) and points to the
  external-PostgreSQL route when the host's is too old.
- `docs/cpanel.env.example`: console email until the dashboard is configured, external database
  (Neon) block, explicit "no Redis".
- `.env.example` is marked **Docker only**.
- `docs/DEPLOY_CPANEL.md`: external PostgreSQL section, exact virtualenv command, order of commands,
  troubleshooting for every error met during the first cPanel install.
- Roadmap: implementation status, update notes, and "Built after the original spec".

## 2026-09-23

### Added
- **MiM SMS** provider (API v2, transactional `/V2/SMS`), SMS credentials on the dashboard, test SMS,
  balance check; delivery-report call wrapped (`delivery_status`) but not polled yet.
- **Email & SMS settings** page (Super Admin): Brevo SMTP, Google Mail, other SMTP, console; secrets
  encrypted with `WS_CREDENTIALS_KEY`; test email; warnings when mail isn't really delivered.
- **Student batches** on the Students page: split the filtered list into batches of N; per-batch view,
  CSV and message.
- Guardian relation **"Other"** requires a typed relation (`guardian_relation_other`).
- **Instant email typo hint** (`/api/registration/email/check/`), including missing or wrong dots.
- **Draft + history** on the public form: Back (form or browser) and reload never lose answers.
- `find_non_english` command; `check_host` command; `passenger_wsgi.py`; `.env` loading; database cache
  option (`DJANGO_CACHE=db`); `docs/DEPLOY_CPANEL.md`.

### Changed
- Public form, messages and emails in **English**; all stored free text must be English.
- Classes limited to **6–10** (form + DB constraint, `NOT VALID` so older rows are kept).
- Student IDs use the programme year: `WS-2027-000001` (`WS_ID_YEAR`).

### Fixed
- "Oldest first" ordering broke ties the wrong way (affected batch membership).

## Phase 1 MVP (before 2026-09-23)
Registration form with email OTP, reference data (regions, districts, upazilas, schools with trigram
matching and merge), admin dashboard (filters, edit history, archive/restore, CSV export, audit log,
admins), bulk email/SMS with batches and delivery status, Docker setup. Built from
[`WikiScholar Registration & Database Platform — Complete Roadmap.md`](WikiScholar%20Registration%20%26%20Database%20Platform%20%E2%80%94%20Complete%20Roadmap.md).
