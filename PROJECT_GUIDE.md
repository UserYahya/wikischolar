# WikiScholar Registration Platform: Project Guide

> **Read this first.** It explains what the app does, how it is built, how to install it
> anywhere, and the rules any change (by a person or an AI assistant) must respect.
> Deeper references: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md),
> [`docs/DATABASE.md`](docs/DATABASE.md), [`docs/DEPLOY_CPANEL.md`](docs/DEPLOY_CPANEL.md).
> The original product spec and what was built beyond it:
> [`WikiScholar Registration & Database Platform — Complete Roadmap.md`](WikiScholar%20Registration%20%26%20Database%20Platform%20%E2%80%94%20Complete%20Roadmap.md).
> What changed when: [`CHANGELOG.md`](CHANGELOG.md).
> How it was built (summary of the AI chats): [`docs/CHAT_SUMMARY.md`](docs/CHAT_SUMMARY.md).

---

## 1. What it is

**WikiScholar** is Wikimedia Bangladesh's student programme for school students in
**classes 6–10**. This app is its **registration system and central student database**:

* **Public registration form** (English, 4 steps) where a student signs up and receives a
  permanent **WikiScholar ID** such as `WS-2027-000001`.
* **Admin dashboard** where staff search, filter, edit, export and message students, manage
  schools and locations, and review an audit log.
* **Email and SMS messaging** (email OTP, confirmation email + confirmation SMS, bulk email/SMS) through
  providers configured from the dashboard: Brevo (SMTP or HTTPS API) or Google Mail for email,
  MiM SMS for SMS.

It is Phase 1 of a larger platform; later modules (Exams, CRM, Volunteers, Call-centre,
Analytics) will plug into the same app.

---

## 2. Features at a glance

### Public registration form (`/`)
| Step | Collects | Rules |
|---|---|---|
| 1. Student & guardian | **required guardian declaration** (Youth Safety Policy: the guardian fills in the form: "I am the guardian of the student named below and I am filling in this form on their behalf"), name, gender, guardian name, relation (Father / Mother / Other + typed relation). **Date of birth is not collected** (removed in October 2026, column dropped) | "Other" requires the typed relation; the declaration is stored as `filled_by = guardian` + `guardian_declared_at` |
| 2. School details | district → region (automatic) → **thana**, school (typeahead), class + **section** (labelled "(if any)": "only if the class has sections"), class roll and/or student ID (labelled "(if any)": many students have none) | the thana must be in the district; class 6–10 only; roll **or** SID required; **class roll is numbers only** (Bangla digits become 0–9, other characters are dropped as you type and refused by the server); section is English text; while typing (from the **3rd letter**; with 1–2 letters a hint asks for more), **only approved (verified) schools** are suggested, from **the whole district** (a student may attend a school in another thana), each with its thana, the student's own thana first; a school picked from the list may be in any thana of the district, but a typed name is matched only within the chosen thana (common names repeat across thanas); a school not in the list is added as *pending* for staff to approve |
| 3. Contact & email | BD mobile number, email + 6-digit OTP | phone `^01[3-9]\d{8}$` (accepts `+880`, spaces, dashes, Bangla digits); instant email typo hint ("Did you mean …@gmail.com?", also for `gmailcom`, `gmail,com`); the code is sent **by email only** and the form tells students to check Spam/Junk; **one action at a time**: "Send verification code", then "Verify code", is the solid button, and "Next step" only appears once the email is verified (until then the bar says "Verify your email to continue.", and Enter sends the code); **one email per student**: an address already used by an active student is refused on "Send verification code" ("already registered… use a different email address") and again on submit |
| 4. Consent & submit | **"How did you hear about WikiScholar?"** dropdown (Social media · Google or YouTube ad · Notice on Wikipedia · Teacher or school announcement · Banner / leaflet etc. · Wikipedia volunteers came to our school · Somewhere else), Youth Safety Policy consent (links to `WS_POLICY_URL`, default `https://wikischolar.bd/youth-policy`), optional email updates opt-in | survey answer and consent required; the answers are counted on the dashboard Overview |

* **Thana: the government's list.** Districts and thanas come from the BANBEIS institution list
  (e-survey 2024; `data/reference_seed.json`, built by `scripts/build_thana_seed.py`): the 64 districts
  in the government's spelling (Barishal, Bogura, Chattogram, Cumilla, Jashore…; three typos in the
  sheet fixed: Brahmanbaria, Cox's Bazar, Chapainawabganj) and their **560 thanas**, which include the
  metropolitan thanas of the cities. On top: the **11 upazilas created after that survey** (Eidgaon,
  Matamuhuri, Bangra…), the **cantonments** (31) and last **"Other thana (not listed)"** (one per
  district) so nobody is blocked; staff then move those students (dashboard Overview warns, *Thana
  type* filter finds them). All are rows of the `thanas` table told apart by `group` (blank = thana,
  `Cantonment`, `Other`), grouped in the dropdown (`<optgroup>`). This replaced the "Upazila / Area"
  list in October 2026 (migration `reference.0007`, from the reviewed `data/thana_mapping.csv`: each
  old row was renamed in place or retired, moving its students and schools to the thana that covers
  it). A hint under the field explains "Other thana" in English and Bangla.
* **English only.** Every free-text value must be English letters, digits and basic punctuation.
  Bangla digits are converted to 0–9 automatically; other scripts are refused, in the browser
  and on the server.
* **District and thana are searchable pickers** (`static/js/picker.js`, `<select data-picker>`).
  * On phones, a full-screen list with a search box on top; on wider screens, a panel under the
    field.
  * Search matches English or Bangla.
  * The `<select>` stays the real field: its value is sent, and choosing fires `change`.
  * The dashboard uses the same picker for district, thana and school fields.
* **Bangla beside the English.** Every label, hint, button, option and message on the public form
  has a smaller Bangla line (`.bn`, own line) or note (`.bn-inline`, buttons and chips) in natural
  Bangla; dropdown options read "English · বাংলা" (districts and thanas use their `name_bn`).
  Labels in `register.html` carry their Bangla in the template. Messages from Python (form and API
  errors) and those built in `register.js` are looked up by their exact English text in
  `apps/registration/bangla.py`, which the page embeds as `#bnMessages`. **Adding a message?** Add
  its Bangla to `bangla.MESSAGES`; `tests/test_form_update_oct2026.py` fails if a server or script
  message has none.
* **Dates are British style, dd/mm/yyyy, everywhere** (the dashboard's "Registered between"
  filter; the form no longer asks for a date). Browsers' own date pickers look
  and behave differently on every phone, so each date is a plain text box (number keypad on
  phones, slashes added while typing, Bangla digits accepted) with a calendar button that opens
  [Air Datepicker](https://github.com/t1m0n/air-datepicker) (MIT, no dependencies, copied into
  `static/vendor/air-datepicker/`, no CDN) as the same centred popup on every device. Mark an input with `data-datefield` (optional `data-min`/`data-max`
  = `today`, `yesterday` or a date; `data-view="years"`) and include `_datefield_assets.html` in the
  page's `{% block head %}`; `static/js/datefield.js` does the rest. On the server,
  `apps.core.utils.parse_date` / `BritishDateField` read dd/mm/yyyy (and still yyyy-mm-dd, so old
  links keep working). CSV exports keep ISO dates (yyyy-mm-dd) for spreadsheets.
* **No data loss on Back.** Answers are kept as a draft in the browser tab (sessionStorage);
  the browser/phone Back button moves between steps; finished steps can be clicked to reopen.
  The draft is cleared after a successful registration.
* **Anti-abuse:** honeypot field, rate limits (OTP per email/IP, registrations per IP, logins),
  OTP stored only as an HMAC, 10-minute expiry, lockout after 5 wrong codes, and optionally
  **Cloudflare Turnstile** (`apps/core/turnstile.py`): when `WS_TURNSTILE_SITE_KEY` and
  `WS_TURNSTILE_SECRET_KEY` are set, a Turnstile widget (usually invisible, at most one click) sits
  above "Send verification code" and on the dashboard sign-in, and the server checks its token with
  Cloudflare before sending a code or checking a password. A token works once, so the form resets
  the widget after each code. If Cloudflare can't be reached the check fails and the person tries
  again. Without the keys nothing is shown or checked.
* **Header:** slim white bar with the English WikiScholar logo
  (`static/img/wikischolar-logo-en.png`; the Bangla logo is kept in `docs/brand/`), "A Wikimedia
  Bangladesh programme" (with Bangla) and a **"← Back to wikischolar.bd"** pill button
  (`WS_SITE_URL`; shortened to "← wikischolar.bd" on phones); the success screen has the same link.
* **Success screen**: a check mark and "Registration complete", the WikiScholar ID in a quiet panel
  ("Keep this ID safe"), the note that a confirmation email and an SMS were sent, every detail (with "Registered on") and two
  buttons: **Print / Save as PDF** (`window.print()`; a print stylesheet in `public.css` prints only
  the logo and this card, and the page title `WikiScholar registration WS-…` becomes the PDF's file
  name; phones offer "Save as PDF" in their print dialog) and "← Back to wikischolar.bd". No PDF
  library or server work is involved.
* **Confirmation SMS**: besides the confirmation email, the student's mobile number gets one SMS
  (verification stays email-only): "WikiScholar registration successful. Your ID: WS-2027-000001.
  Questions? Email info@wikischolar.bd" (98 characters; the address is `WS_CONTACT_EMAIL`). It must
  stay one 160-character SMS in plain English letters (a Bangla or curly character turns it into a
  70-character Unicode SMS); a test checks this. Text in `registration/services.py`
  (`confirmation_sms_text`); sent through the active SMS settings (MiM SMS) after commit,
  independently of the email, and logged on the student page. A failed SMS never blocks registration.
* **Government school list (BANBEIS).** `manage.py import_banbeis_schools FILE.xlsx [--dry-run]`
  loads the government's institution list (e-survey 2024: 19,718 schools). Each school gets its
  **EIIN** (6 digits, unique) and government data: division, institute type, education level,
  management (government / non-government / …), MPO, institute for (co-education / girls / boys),
  geographical position, area status (rural / city corporation / paurashava…), post office and email.
  Thanas resolve through `data/thana_mapping.csv`. A row matches an existing school by EIIN, then
  by name in the same thana (a school without an EIIN keeps its id and students), else it is added
  as a verified "BANBEIS list" school. Removed schools are not brought back, and running it again
  changes nothing. The school page shows the government data, and *Edit government data* changes it
  (`schools.edit`, audited `school.details_updated`). The Schools list shows the EIIN, and its search
  and the typeahead (public form too) find a school by its 6-digit EIIN.
* **School names are in CAPITALS** everywhere: `School.save()` and `SchoolAlias.save()` uppercase
  them, whether a school comes from the public form, *Add school*, a rename, an import or a merge
  (migration `reference.0010` converted the existing ones). Matching ignores case. A student's
  `school_name_as_entered` stays exactly as typed.
* **Approving schools** makes them suggestible: Dashboard → Schools → a pending school → *Mark
  verified* (or bulk-load a verified list with `import_schools CSV --status verified`).
* **Adding and removing schools** (Dashboard → Schools, needs `schools.edit`): *Add school* picks
  district → thana → name; as the name is typed, schools already in that thana (verified and
  pending) are listed, and picking one opens it. On submit the same name or an alias in the
  thana (after normalising, so "Govt" = "Government") is refused, and a name as similar as
  *Review duplicates* would flag (`WS_SCHOOL_DUPLICATE`) needs "It's a different school". A school
  page's *Remove school* archives it (soft delete, reason in the audit log); it is refused while
  active students or merged schools point to it. *Removed* in the status filter lists them with
  *Restore* (refused if the same name was added since).
* **Importing schools from CSV** (Dashboard → Schools → *Import CSV*, needs `schools.edit`):
  *Download template* gives the headings `District,Thana,School name` (older templates'
  `Upazila / Area`, `Upazila` or `Area`, and a lower-case `name` column also work); fill in one school
  per row; rows without a school name are ignored. **Thana is optional**: leave it blank when it isn't
  known, or leave the column out (District and School name are required); see *Schools without a
  thana* below. *District & thana list* (all districts or one) lists
  every thana, cantonment and "Other thana" with its district and group in English and
  Bangla, spelled as the import expects. Upload (≤ 1 MB, ≤ 2000 schools, UTF-8 or Excel CSV,
  district/thana matched in English or Bangla ignoring case) and choose *Verified* or *Pending*.
  A preview shows each row as *will be added*, *similar* (added only if ticked), *already listed*,
  *repeated in the file* or *error* (unknown district, misspelt thana, not English, too long). Nothing is
  saved until *Import N schools*; the rows wait in the session and are checked again then. One
  `school.imported` audit entry records the count and the new school IDs; source is *Bulk import*.
  A wrong import is undone on the server with `manage.py undo_school_import --list`, then
  `undo_school_import ID --dry-run`, then without `--dry-run`. Its schools are removed (restorable) except ones
  students or merges point to.
* **Schools without a thana** (`schools.thana_id` blank, e.g. imported from a list with districts
  only) belong to their **whole district** until an admin sets the thana:
  * Suggestions: offered to students from every thana of the district, shown without a thana label.
  * Typed names: a name typed on the form in any thana of the district matches them, so no pending
    duplicate is created.
  * Duplicate checks: the import, *Add school* and *Review duplicates* compare them with every school
    in the district. A row without a thana repeats any same-name row of that district.
  * Merging: allowed within the district. A kept school without a thana takes the thana of the
    duplicate merged into it.
  * Dashboard: *Thana* shows "Not known", and the thana filter has a *Thana not known*
    option. The school page has *Set thana* (audited as `school.area_set`); it is refused when that
    thana already lists the name, in which case merge the two schools instead.

### Admin dashboard (`/dashboard/`)
* **Sidebar**: the WikiScholar logo, then the tools in **collapsible groups** (*Overview*;
  *Students*: All students, Archived records; *Schools & places*: Schools, Duplicate schools,
  Regions & districts; *Messaging*: Messages, System emails, Email & SMS settings;
  *Administration*: Admins, Audit log). The group holding the current page opens by itself; a
  group the admin can open only one tool of shows as a plain link. Modules choose the group with
  `register_nav(..., group="…")` (`apps/core/registry.py`).
* **Overview**: totals, daily registrations, students per region/district, **how students heard
  about WikiScholar** (survey answers), warnings (e.g. "Emails are not being delivered").
* **Students**: filters (region, district, thana, **thana type** (thana, cantonment, "Other
  thana"), school, class, gender, date range, opt-in, text search, sort), **split into batches** of N students (view / CSV / message each batch),
  CSV export (Excel-friendly), student detail with full edit history, edit, archive/restore.
* **Advanced search** (Students and Schools lists, above the results): a query builder.
  * **Conditions:** field → operator → value. Text fields take is / contains / starts with / is
    empty; lists take is any of / is none of; numbers and dates take = / < / > / between; yes/no
    fields take yes or no.
  * **Groups:** each group matches ALL or ANY of its conditions, and the groups are combined with
    ALL or ANY.
  * **Student fields:** student, guardian and contact details, place, registration date, the school
    and the school's government data (EIIN, management, MPO, …).
  * **School fields:** name and alias, status, source, number of students, date added, place,
    division, the government data, post office and email.
  * **It combines with everything else:** the other filters still apply. On Students the query is
    the `adv` filter param, so Export CSV, batches, *Message this group* and a batch's saved filter
    follow it.
  * **Export CSV:** both lists download exactly what they show, across all pages, including an
    advanced or saved search. On Schools this is `views/reference._filtered_schools`, shared by the
    list and `school_export`; it includes the government data and student counts, and is audited as
    `schools.exported`. The Students export includes the school's EIIN and government data.
  * **Safe to run:** `apps/dashboard/advanced.py` allows registered fields and operators only, and
    no SQL is built from text. Limits: 10 groups, 20 conditions, 200-character text. An invalid
    condition is left out and shown as a notice, never run. A search stops after 5 s
    (`statement_timeout`). Each search is described in plain English above the results.
* **Saved searches** (shared): *Save as new search* (name + optional note) stores the current
  conditions (`saved_searches`). Every admin who can see that list sees them in the *Saved searches*
  dropdown and on **Students → Saved searches**, and opening one (`?saved=<id>`) runs its latest
  version. Only the admin who saved it, or a Super Admin, can *Update* it with the current conditions
  or *Delete* it (archived). Audited as `search.saved`, `search.updated` and `search.deleted`. A
  condition whose field no longer exists is left out with a notice.
* **Messages**: compose bulk email/SMS to a filtered group or a batch. Every send is a **named
  batch** (name required, English) with `{name}` and `{wikischolar_id}` placeholders.
  * **Messages list**: search by batch name / code / subject, filter by channel or "only batches
    with undelivered messages"; per batch: recipients, delivered, not delivered, queued.
  * **Batch page**: recipients filtered by status, including **Not delivered** (failed or
    bounced), search by name / WS ID / address, **Download CSV** (filtered, audited),
    **Resend not delivered**, **Show these students**.
  * **Sending**: up to `WS_INLINE_DISPATCH_MAX` (300) recipients start from the browser in chunks
    of `WS_INLINE_DISPATCH_SECONDS` (20 s); the batch page keeps sending automatically until done
    ("Send the remaining N now" also works by hand). Bigger batches go to the `send_queued` cron
    job. Each message is claimed once, so browser and cron can run together without duplicates.
  * **Students → Message history** filter: students who *received* a batch, who *were not sent it
    yet* (e.g. registered later), or who *did not get it* (failed/bounced). Combine with "Message
    this group" to reach only the ones a batch missed.
* **Schools**: verify pending schools, rename (old name kept as an alias), aliases, duplicate
  finder and merge.
* **Regions & districts**: the district → region mapping is data, editable here; a student's
  region is always derived from their district, so a reassignment moves everyone instantly. A
  district's page lists its thanas with their group; *Add* takes an optional group
  (Cantonment, Other, or a custom group already in use).
* **Audit log**: every view of a student record, edit, export, message, login and setting change.
* **Admins** (Super Admin): create admins, change roles, deactivate, and **set a new password**
  for an admin who forgot theirs (signs them out everywhere; audited as `admin.password_reset`,
  the password itself is never logged).
* **Change password** (every admin, link under their name in the sidebar,
  `/dashboard/account/password/`): current password plus the new one twice, checked by the
  password rules (12+ characters, not common, not all digits, not like the name or email). Other
  sessions of that account are signed out; audited as `admin.password_changed`.
* **System emails** (Super Admin): edit the subject and text of the **OTP email** and the
  **registration confirmation** with placeholders (`{code}`, `{student_name}`, `{wikischolar_id}`,
  `{details}`, …); refuses text without required placeholders (`{code}`, `{wikischolar_id}`) or
  with unknown ones; live preview with sample data (the designed HTML email, plain text below);
  *Send test to me*; *Reset to default* (nothing deleted). Changes are audited. Any language is
  allowed in this text.
* **HTML emails**: every email (OTP, confirmation, bulk messages, test emails) is sent as a
  designed HTML email (logo, white card, footer with the website and contact address) **plus**
  the plain text for mail apps without HTML. Admins still write plain text; links and email
  addresses become clickable. System emails show some placeholders richly: `{code}` in a large
  box, `{wikischolar_id}` highlighted, `{details}` as a table (`html_values` on `SystemEmail`;
  layout in `apps/notifications/html_email.py` and `templates/notifications/email.html`). The logo
  is loaded from `WS_PUBLIC_URL`.
* **Students** also shows and filters **who filled in the form** (student / guardian), and exports it.
* **Email & SMS settings** (Super Admin): email provider (Brevo SMTP relay, Brevo HTTPS API for
  hosts that block SMTP, Google Mail/Workspace, other SMTP, console), From name/address,
  **Reply-to** (pre-filled with `info@wikischolar.bd`; every email, including OTP, confirmation and
  bulk, carries it; blank falls back to `WS_REPLY_TO`); MiM SMS credentials. Secrets stored
  encrypted. Test email, test SMS, MiM SMS balance.

### Roles
| Role | Can |
|---|---|
| **Viewer** | read and filter students, schools, locations, messages |
| **Admin** | + edit/archive/export students, edit schools & locations, merge schools, send messages, read audit log |
| **Super Admin** | + manage admins, email & SMS settings, system email wording |

---

## 3. Technology

| Layer | Choice |
|---|---|
| Language / framework | Python 3.12, **Django 5.1** |
| Database | **PostgreSQL 13+** (16 recommended) with the **`pg_trgm`** extension. PostgreSQL only: integrity rules are DB triggers and constraints |
| Front end | Server-rendered Django templates + small vanilla JS (`static/js/register.js`, `static/js/cascade.js`, `static/js/datefield.js`); one vendored library, Air Datepicker (`static/vendor/`); no build step |
| Static files | WhiteNoise with content-hashed names (`apps/core/storage.py`), so browsers load new CSS/JS right after an update; **run `collectstatic` after every upload** (if forgotten, pages still work, but may look old) |
| Cache / rate limits | Redis if `REDIS_URL` is set; else database cache (`DJANGO_CACHE=db`); else in-process memory (single process only) |
| Encryption of stored secrets | `cryptography` (Fernet) |
| App server | gunicorn (Docker/VPS) or Phusion Passenger (cPanel, via `passenger_wsgi.py`) |
| Email | Django email: SMTP (Brevo relay, Gmail, any SMTP) or Brevo's HTTPS API (`apps/notifications/backends.py`, port 443) |
| SMS | MiM SMS API v2 (`/V2/SMS`, transactional) |

Python dependencies (`requirements.txt`): Django, psycopg[binary], gunicorn, whitenoise,
cryptography, redis (optional).

---

## 4. Architecture: a modular monolith

One deployable Django project. **Each feature is its own Django app ("module") that owns its
tables and migrations.** Modules talk to each other through each other's `services.py`
functions, not by writing to another module's tables.

| Module | Folder | Owns (tables) | Responsibility |
|---|---|---|---|
| Core | `apps/core` | `admins`, `audit_logs`, `id_sequences` | admin accounts, roles & permissions (`permissions.py`), audit (`audit.py`), ID generator (`ids.py`), soft-delete base model, DB trigger helpers (`sql.py`), shared utils (`utils.py`: English-only rule, digit conversion), encryption (`crypto.py`), nav registry (`registry.py`) |
| Reference data | `apps/reference` | `regions`, `districts`, `thanas`, `schools`, `school_aliases` | locations, school matching (trigram), merge, public lookup API |
| Registration | `apps/registration` | `students`, `email_verifications`, `edit_history` | public form, OTP, registering and editing students |
| Notifications | `apps/notifications` | `email_batches`, `sms_batches`, `notification_logs`, `email_settings`, `sms_settings`, `email_templates` | providers (email/SMS), transactional + bulk sending, delivery webhooks, credentials, **system email registry** (editable wording) |
| Dashboard | `apps/dashboard` | *(none)* | staff UI only, built on the other modules' services |

Dependency direction: `dashboard → registration → reference → core`, and
`registration → notifications → core`. **Core depends on no feature module.**

### Rules that keep modules from breaking each other
1. A new feature goes in the module that owns the data, or in a **new app** under `apps/`.
2. Cross-module work goes through `services.py` (example: a school merge lives in
   `reference.services`, but moving the students is delegated to
   `registration.services.reassign_school`).
3. Dashboard menu items are registered with `apps.core.registry.register_nav(...)` (optionally with a
   `group=` name, shown as a collapsible sidebar section) in the
   module's `AppConfig.ready()`; permissions are codes in `apps/core/permissions.py`.
4. Every state change writes `audit_logs` (via `apps.core.audit.record`); student field changes
   also write `edit_history`.
5. Each app keeps its own migrations; never edit an applied migration, add a new one.
6. Shared rules (like English-only text) live in `core` so every module uses the same rule.
7. A module that sends **system emails** registers them in its `AppConfig.ready()` with
   `notifications.services.register_system_email(SystemEmail(key=..., subject=..., body=...,
   placeholders=..., required=..., sample=...))` (see `apps/registration/emails.py`) and sends with
   `render_system_email(key, values)`. They then appear on Dashboard → System emails automatically.

---

## 5. Data rules (invariants)

These are enforced in code **and** in the database; changes must keep them true.

* **Nothing is hard-deleted.** Students, schools, locations and admins are soft-deleted
  (`is_deleted`); DB triggers refuse `DELETE` on key tables. `audit_logs` and `edit_history`
  are append-only (triggers refuse `UPDATE`/`DELETE`).
* **WikiScholar ID**: `WS-<year>-<6-digit sequence>`, e.g. `WS-2027-000001`. The year is the
  programme year `WS_ID_YEAR` (default 2027; empty = calendar year). Allocated atomically from
  `id_sequences`; never changes once issued.
* **Class** is `"6"`–`"10"` (DB check constraint `student_class_6_to_10`).
* **Guardian relation** `father` / `mother` / `other`; `guardian_relation_other` must be filled
  exactly when relation is `other` (DB check).
* **Roll or SID**: at least one of `class_roll`, `student_id_sid` (DB check). New rolls are
  digits only (form check; older rows may still hold letters).
* **Survey answer** `heard_from` is one of the `HeardFrom` choices, or empty for students who
  registered before the question existed (DB check `student_heard_from_valid`).
* **Phone** matches `^01[3-9][0-9]{8}$` (DB check); stored without country code.
* **Thana belongs to the district** (composite foreign key `students_thana_in_district`). `group` is
  blank for a thana, `Cantonment`, or `Other` ("Other thana (not listed)", one per district). Names are
  unique per district.
* **English-only text**: `apps.core.utils.english_text()`; `manage.py find_non_english` lists
  older non-English values.
* **Region is never stored on a student**; it is derived from `district.region` at read time.
* **Guardian declaration** is required for every new registration (form + server). `filled_by =
  'guardian'` exactly when `guardian_declared_at` is set (DB check `student_guardian_declaration`);
  students registered before the rule keep `filled_by = 'student'`. Not editable afterwards.
* **Email is verified** by OTP before a student row can exist, and is **unique among active
  students** (checked on send-code and on submit; archiving a student frees the address).
* **Secrets** (SMTP password, SMS API key) are stored encrypted with `WS_CREDENTIALS_KEY`
  (or a key derived from `DJANGO_SECRET_KEY`) and never written to the audit log.
* **School resolution** on submit: picked ID (any school in the student's district) → exact
  normalised name → alias → trigram match ≥ 0.8 (these three within the chosen thana)
  → new *pending* school in the chosen thana. So a student's thana and their school's thana may
  differ (both in the same district); the dashboard editor only requires the same district.

---

## 6. URL map

| URL | What |
|---|---|
| `/` | public registration form |
| `/api/registration/email/check/?email=` | instant typo hint (GET, stores nothing) |
| `/api/registration/email/send-otp/`, `/verify-otp/`, `/api/registration/submit/` | form JSON API (POST, CSRF) |
| `/api/reference/districts/`, `/districts/<id>/thanas/`, `/schools/?district=&thana=&q=` (whole district, that thana first; `?thana=` alone: one thana) | lookup API |
| `/notifications/webhook/<email|sms>/?token=` | provider delivery reports (generic JSON or Brevo transactional events) |
| `/dashboard/…` | staff dashboard (login required) |
| `/dashboard/messages/?q=&channel=&problems=1` | Messages list and its filters |
| `/dashboard/messages/<code>/?status=not_delivered&q=` | batch page; `…/recipients.csv` (same filters), `…/send/` (POST, next chunk), `…/resend/` (POST) |
| `/dashboard/students/?msg_batch=<code>&msg_batch_mode=sent\|not_sent\|not_delivered` | students by message history (also `&filled_by=student\|guardian`) |
| `/dashboard/settings/system-emails/` | System emails (Super Admin) |
| `/dashboard/account/password/` | change your own password (any admin) |

---

## 7. Installation

Pick one. All need **PostgreSQL 13+ with `pg_trgm` available** (the `migrate` step creates the
extension; on PostgreSQL 13+ a database owner is allowed to).

### A. Local development: Linux / macOS
```sh
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
createdb wikischolar                      # PostgreSQL 16 running locally
export DJANGO_DEBUG=1 WS_OTP_DEBUG_ECHO=1 DJANGO_SSL_REDIRECT=0
export DB_USER=$USER DB_PASSWORD= DB_HOST=localhost
python manage.py migrate
python manage.py seed_reference
python manage.py create_super_admin --email you@example.org --name "You"
python manage.py runserver
```
Open http://127.0.0.1:8000/ and http://127.0.0.1:8000/dashboard/. In development, emails
(OTP codes) print in the terminal and the OTP is also shown on the form.

### B. Local development: Windows
1. Install Python 3.12 and PostgreSQL 16 (official installer, or the portable
   "binaries" zip from EnterpriseDB unpacked to `.pgsql\`).
2. Create a database `wikischolar` owned by user `wikischolar` / password `wikischolar`
   (the app's defaults), on port 5432.
3. In PowerShell:
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\pip install -r requirements.txt
   $env:DJANGO_DEBUG="1"; $env:WS_OTP_DEBUG_ECHO="1"; $env:DJANGO_SSL_REDIRECT="0"
   .\.venv\Scripts\python manage.py migrate
   .\.venv\Scripts\python manage.py seed_reference
   .\.venv\Scripts\python manage.py create_super_admin --email you@example.org --name "You"
   ```
4. Start with `powershell -ExecutionPolicy Bypass -File .\run-dev.ps1` (it starts a portable
   PostgreSQL in `.pgsql\`/`.pgdata\` if present, then the dev server).

### C. VPS / any Linux server with Docker (simplest production)
```sh
cp .env.example .env          # set DJANGO_SECRET_KEY, DB_PASSWORD, domain, email settings
docker compose up -d --build  # PostgreSQL 16 + Redis + app + queue worker; migrates and seeds
docker compose exec web python manage.py create_super_admin --email you@example.org --name "You"
```
Put a TLS-terminating proxy (Caddy / nginx) in front and set `DJANGO_BEHIND_PROXY=1`.

### D. cPanel shared hosting
Full steps: [`docs/DEPLOY_CPANEL.md`](docs/DEPLOY_CPANEL.md). The short version, including
the traps we already hit:

1. **Check the database first.** Many cPanel hosts only have MySQL or an old PostgreSQL (9.x);
   Django 5.1 refuses anything below 13. If so, keep the app on cPanel and use an **external
   PostgreSQL 16** (e.g. Neon, in the region nearest your server). Prefer its **direct** host
   (no `-pooler` in the name); a pooled host also works, because the app then turns off
   server-side cursors automatically. Set `DB_SSLMODE=require`.
2. **Setup Python App** → Create: Python 3.12, application root = your folder, startup file
   `passenger_wsgi.py`, entry point `application`.
3. Upload the code into that folder (no `.venv`, `.pgsql`, `.pgdata`, `.env`).
4. Create `.env` from **`docs/cpanel.env.example`**, not the root `.env.example` (that one is
   for Docker and points at hosts `db` and `redis`). Fill in secret keys, domain, database. Check
   Setup Python App → *Environment variables* has no old values (they override `.env`).
5. In Terminal, **first** run the exact "Enter to the virtual environment" command shown in
   Setup Python App (the path contains *your* folder name). Then, one at a time:
   ```sh
   pip install -r requirements.txt
   python manage.py check_host          # must end: "This host can run WikiScholar."
   python manage.py migrate             # before anything else touches the DB
   python manage.py createcachetable
   python manage.py seed_reference
   python manage.py collectstatic --noinput
   python manage.py create_super_admin --email you@example.org --name "You"   # asks for the password
   ```
6. **Restart** the app in Setup Python App. Add a once-a-minute cron job for `send_queued`.
7. Forgot the dashboard password: `python manage.py changepassword you@example.org`.

### After installing (every environment)
1. Sign in at `/dashboard/`.
2. **Email & SMS settings**: choose a provider, save its credentials → *Send test* → tick
   *Use these settings*. Until then emails are **not delivered** (a red warning says so).
   * **Brevo (SMTP relay)**: SMTP login (`…@smtp-brevo.com`) + SMTP key (`xsmtpsib-…`).
   * **Brevo (HTTPS API)**: only an API key (`xkeysib-…`). Use it when the test email fails with a
     timeout or "Network is unreachable": many shared hosts block outgoing SMTP.
   * **Google Mail**: full address + App password (needs 2-Step Verification); ~500/day (Workspace ~2,000).
   * In every case the **From address must be verified** with the provider. *Reply-to* is
     pre-filled with `info@wikischolar.bd`.
   * If a send fails, the batch page shows the provider's exact error (e.g. `535 Authentication
     failed` = wrong SMTP login or key).
   * **Delivery reports (Brevo)**: without them, emails stay "Sent" and only failures at sending time
     show as "Not delivered". Set `NOTIFY_WEBHOOK_TOKEN` (a long random string) in `.env`, restart,
     then in Brevo add a transactional **webhook** with URL
     `https://<your-domain>/notifications/webhook/email/?token=<NOTIFY_WEBHOOK_TOKEN>` and the events
     *Delivered, Hard bounce, Invalid email, Blocked, Error*. Brevo then marks each message
     delivered or bounced.
3. For MiM SMS: whitelist the server's public IP and domain in sms.mimsms.com → Utility →
   Developer, save the API username, key and Sender ID, send a test SMS, activate.
4. Create accounts for teammates under **Admins** (don't share logins).
5. Set up database backups and test a restore.

---

## 8. Configuration reference (environment variables / `.env`)

The app reads real environment variables first, then a `.env` file next to `manage.py`.

| Variable | Default | Meaning |
|---|---|---|
| `DJANGO_DEBUG` | `0` | `1` only for local development |
| `DJANGO_SECRET_KEY` | *(required in production)* | long random string |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | comma-separated domains |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | *(empty)* | e.g. `https://register.example.org` |
| `DJANGO_SSL_REDIRECT` | on when not debug | force HTTPS |
| `DJANGO_BEHIND_PROXY` | `0` | `1` behind a TLS proxy (fixes redirect loops, real client IP) |
| `DJANGO_CACHE` | *(empty)* | `db` = shared database cache (run `createcachetable`) |
| `REDIS_URL` | *(empty)* | Redis cache (preferred with several workers) |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` / `DB_SSLMODE` | `wikischolar` / `wikischolar` / `wikischolar` / `localhost` / `5432` / `prefer` | PostgreSQL |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | console backend | fallback email transport (dashboard settings override) |
| `WS_CREDENTIALS_KEY` | derived from secret key | Fernet key encrypting stored passwords/API keys; keep it safe |
| `NOTIFY_SMS_PROVIDER`, `SMS_API_URL`, `SMS_USERNAME`, `SMS_API_KEY`, `SMS_SENDER_ID` | console SMS | fallback SMS config (dashboard settings override) |
| `NOTIFY_WEBHOOK_TOKEN` | *(empty)* | shared secret for delivery-report webhooks (empty = webhooks refused) |
| `DB_DISABLE_SERVER_SIDE_CURSORS` | on when `DB_HOST` contains `pooler` | needed behind PgBouncer-style pooled connections |
| `WS_ID_PREFIX` / `WS_ID_YEAR` | `WS` / `2027` | student ID format `WS-2027-000001` |
| `WS_CONTACT_EMAIL`, `WS_POLICY_URL`, `WS_POLICY_VERSION` | `info@wikischolar.bd`, `https://wikischolar.bd/youth-policy`, `2026-01` | shown on the form / stored with consent |
| `WS_REPLY_TO` | `info@wikischolar.bd` | Reply-to of every email when Email settings has none |
| `WS_SITE_URL` | `https://wikischolar.bd` | target of the form's "Back to …" link |
| `WS_TURNSTILE_SITE_KEY` / `WS_TURNSTILE_SECRET_KEY` | *(empty: off)* | Cloudflare Turnstile on "Send verification code" and the dashboard sign-in; both needed. Cloudflare's always-pass test keys `1x00000000000000000000AA` / `1x0000000000000000000000000000000AA` work on localhost |
| `WS_PUBLIC_URL` | `https://registration.wikischolar.bd` | this app's own public address; the logo in HTML emails is loaded from here (empty = text wordmark instead) |
| `WS_OTP_TTL_MINUTES` / `WS_OTP_MAX_ATTEMPTS` / `WS_OTP_VERIFIED_WINDOW_MINUTES` | `10` / `5` / `60` | OTP rules |
| `WS_OTP_DEBUG_ECHO` | `0` | dev only: show the OTP on the form |
| `WS_SCHOOL_AUTO_RESOLVE` / `WS_SCHOOL_DUPLICATE` | `0.8` / `0.5` | trigram thresholds |
| `WS_INLINE_DISPATCH_MAX` | `300` | bulk batches up to this size are sent from the browser; bigger ones by `send_queued` |
| `WS_INLINE_DISPATCH_SECONDS` | `20` | seconds of sending per browser request (keeps requests under host timeouts) |
| `LOG_LEVEL` | `INFO` | |

Templates: `.env.example` (Docker), `docs/cpanel.env.example` (cPanel).

---

## 9. Management commands

| Command | Purpose |
|---|---|
| `check_host` | pre-flight: Python, PostgreSQL version (13+), `pg_trgm`, production settings, migrations, cache |
| `migrate` | create/update tables (run after every code update) |
| `createcachetable` | needed once when `DJANGO_CACHE=db` |
| `seed_reference [--reset-region-assignments]` | load 6 regions, 64 districts and 666 thanas (the government's list, newer upazilas, cantonments, "Other thana"; idempotent; keeps dashboard edits). On an existing database, migration `reference.0007` applies the list by itself |
| `import_schools CSV [--status verified\|pending]` | bulk-load schools (`district,thana,name`, English; the thana may be blank or the column left out); same checks as the dashboard import (`apps/reference/importer.py`), similar names are added |
| `import_banbeis_schools XLSX [--type TYPE] [--dry-run]` | load the government's school list (BANBEIS .xlsx): EIIN, name, thana and government data; matches by EIIN, then by name in the thana; safe to re-run (`apps/reference/banbeis.py`). `--type "SCHOOL & COLLEGE"` imports only that INSTITUTE_TYPE_NAME (used for the School and College sheet) |
| `undo_school_import [ID] [--list] [--dry-run] [--yes]` | undo one wrong school import: removes (archives) the schools its audit entry lists, keeping ones with students or merges (`importer.undo`) |
| `create_super_admin --email --name` | first Super Admin (prompts for password) |
| `changepassword EMAIL` | reset an admin's password |
| `send_queued` | send queued bulk messages (cron/worker, run one at a time) |
| `find_non_english` | list stored text that isn't English |
| `collectstatic --noinput` | gather CSS/JS for production |

---

## 9a. Source code and git

The code lives in a **private GitHub repository** (`main` branch). Ask the owner for access, then:

```sh
git clone https://github.com/UserYahya/wikischolar.git && cd wikischolar
```

Never commit secrets or local data. `.gitignore` already excludes `.env` (all real settings and
passwords), `.venv`, the portable PostgreSQL (`.pgsql/`, `.pgdata/`), `dist/`, `staticfiles/`, zips
and logs; only the templates `.env.example` and `docs/cpanel.env.example` are tracked. Tests use
made-up accounts only. `.gitattributes` keeps LF line endings (the servers are Linux). Commit with
a clear message, add a `CHANGELOG.md` entry and run the tests.

**Never push directly to `main`.** The Azure VM runs `main`: deploys are manual (a `git pull` and
rebuild on the server, docs/DEPLOY_AZURE.md section F), and each one puts everything merged into
`main` live. Work on a branch and open a pull request; the owner merges it:

```sh
git checkout -b my-change
git commit -m "Describe the change"
git push -u origin my-change
gh pr create            # or open the pull request on github.com
```

## 9b. Packaging a release for upload

```sh
python scripts/build_cpanel_zip.py      # -> dist/wikischolar-cpanel.zip
```
The zip holds code, templates, static files, seed data and docs, and **never** a `.env`,
`.venv`, portable PostgreSQL, caches or other `.zip` files, so extracting it on the server doesn't
overwrite the server's settings. After uploading an update: `pip install -r requirements.txt` (if
requirements changed), `migrate`, `collectstatic --noinput`, then Restart.

---

## 10. Tests

```sh
DJANGO_DEBUG=1 python manage.py test tests
```
275 tests in `tests/`, run against **real PostgreSQL** (the integrity rules live in the
database). They cover the full registration flow, OTP, typo hints, English-only rules, school
resolution, DB constraints and triggers, permissions on every page, edits and history,
archive/restore, filters, batches, CSV export, bulk email/SMS, email & SMS settings (with a
simulated MiM SMS gateway and Brevo API), region reassignment and school merge. `tests/test_messaging.py`
covers the header/logo/back link, approved-only school suggestions, reply-to on every email, named
batches, chunked sending, the send_queued job, braces in messages, pooled connections, the Brevo
webhook, not-delivered filters, recipients CSV and the Message history filter. `tests/test_system_emails.py` covers the guardian declaration (form, DB
check, dashboard, export) and editable system emails (permissions, validation, use in real emails,
reset, test send). `tests/test_form_update_oct2026.py` covers the October 2026 form update: Bangla on
the form (and that every message has a translation), section, numbers-only roll, the survey, no
date of birth, HTML emails, grouped navigation and the favicon. `tests/test_thanas.py` covers
"Thana" (grouped API order, registering with a thana, dashboard grouping, the Thana type filter,
adding a grouped thana, the import), checks that `data/reference_seed.json` has the government's 64
districts and 571 thanas, the cantonments and an "Other thana" in every district, cleaning the sheet's
thana names, the `reference.0007` swap (rename in place, retire and move, restore archived names)
and what keeps working from before the rename (`?upazila=` links, old CSV headings, `{upazila}`).
`tests/test_security_accounts.py` covers Turnstile (off without keys; on: widget shown, missing,
bad or unverifiable tokens refused, a good token sends the code; dashboard sign-in) and password
changes (own password; Super Admin setting another admin's; permissions; audit without passwords).
`tests/test_school_district.py` covers district-wide school suggestions (own thana first, thana
shown, approved only), picks from another thana, typed names matched only in the chosen thana, and
the dashboard editor keeping a school from another thana. `tests/test_school_government_data.py`
covers the BANBEIS import (create, match by name keeping students, update by EIIN with the old name
as an alias, re-run, dry run, skipped rows, value clean-up), EIIN rules (database and form), EIIN in
the typeahead and list search, editing government data, and the capitals migration.
`tests/test_advanced_search.py` covers every operator type, ALL/ANY within and across groups,
invalid conditions and limits, the plain-English description, the Students list, export and
message composer following the search, the Schools list by government data and student count, and
saved searches (save, load, update, delete, shared visibility, owner / Super Admin rights, stale
fields). External calls (SMTP,
MiM SMS) are mocked; no real messages are sent.

---

## 11. Project layout

```
manage.py, passenger_wsgi.py      entry points (CLI, cPanel)
scripts/build_cpanel_zip.py       builds the upload package (dist/ is git-ignored)
PROJECT_GUIDE.md, CHANGELOG.md    this guide, dated changes
WikiScholar … Roadmap.md          original spec + status + what was added later
config/settings.py, urls.py       settings (all from env / .env), root URLs
apps/core/                        admins, roles, audit, IDs, shared utils, crypto, nav registry
apps/reference/                   regions, districts, thanas, schools (+ lookup API)
apps/registration/                students, OTP, public form (templates/registration/), emails.py (system email defaults),
                                  bangla.py (Bangla for every form label/message)
apps/notifications/               email/SMS providers, batches, logs, settings, html_email.py + templates/notifications/email.html
apps/dashboard/                   staff UI: views/, templates/dashboard/, filters.py, forms.py,
                                  advanced.py (advanced search), models.py (saved searches)
static/css, static/js             public.css, dashboard.css, datefield.css, register.js, cascade.js, datefield.js
static/vendor/air-datepicker/     date picker library (MIT), copied unchanged from npm
templates/public_base.html        public page shell
templates/_favicons.html          site icon links (public pages and dashboard)
static/img/                       logos (English, Bangla) and site icons; full-size originals in docs/brand/
templates/_datefield_assets.html  CSS/JS for dd/mm/yyyy date fields (include in {% block head %})
data/reference_seed.json          regions/districts/thanas seed (sources and rules in its _comment)
data/thana_mapping.csv            old "Upazila / Area" row → thana (reviewed; used by migration reference.0007)
scripts/build_thana_seed.py       builds both from the BANBEIS list
tests/                            test suite (base.py has fixtures and helpers)
docs/                             architecture, database, cPanel deployment, env template
```

---

## 12. Known gaps and ideas for next steps

* **Email delivery reports need the Brevo webhook** (see section 7); Gmail/other SMTP give no delivery
  reports, so their emails stay "Sent" unless rejected.
* **SMS delivery reports** are not polled yet: SMS show "sent", not "delivered". A periodic job
  calling `MimSmsProvider.delivery_status()` (MiM `/V2/DlrApi`, ~5 min after sending) would fix it.
* **Duplicate-student detection** (same name + guardian + school, now that date of birth is not
  collected) and a review screen.
* **Paurashavas (municipalities)** could become their own thana group the same way (a `group` value
  plus seed rows), with no code change; they are inside thanas today, so nobody is left out.
* **Schools from the BANBEIS list**: the same sheet lists 19,718 schools with their EIIN; loading
  them (with an EIIN field to prevent duplicates) is the next step.
* **Two-factor login** for admins.
* **Saved queries / query builder** beyond the filter panel.
* **Field-level encryption** of phone, email and guardian name at rest.
* **Background job queue** (Celery/RQ) instead of the cron-driven `send_queued` for large volumes.
* **Guardian phone / consent for minors**: policy decision still open.
* Phase 2 modules: Exams, CRM, Volunteers, Call-centre, Analytics (each as a new app).

---

## 13. Working on this project with an AI assistant

Paste this section (or the whole file) at the start of a conversation, then describe the change.

### Context prompt
```text
You are working on WikiScholar, a Django 5.1 + PostgreSQL 16 modular monolith for
Wikimedia Bangladesh's student registration (classes 6-10). Read PROJECT_GUIDE.md first.

Hard rules:
- Keep it a modular monolith: each feature is a Django app in apps/ that owns its tables
  and migrations; modules call each other through services.py, never another module's
  tables; core depends on no feature module. Adding a module must not break existing ones.
- Register dashboard menu items via apps.core.registry.register_nav and permissions in
  apps/core/permissions.py. Every state change writes audit_logs via apps.core.audit.record.
- Never hard-delete; keep audit_logs/edit_history append-only; add new migrations, never
  edit applied ones; keep DB constraints and code validation in sync.
- All stored free text is English (apps.core.utils.english_text). UI text is English.
- Secrets are stored encrypted (apps.core.crypto) and never logged or audited.
- Match the existing code style (small functions, comments only where the reason isn't
  obvious, server-rendered templates + vanilla JS, no new frameworks without a reason).
- Add or update tests in tests/ and run: DJANGO_DEBUG=1 python manage.py test tests
  (real PostgreSQL). Mock external services (SMTP, SMS).
- After every change, update the docs it affects (see "Keeping the docs current" in
  PROJECT_GUIDE.md) and add a CHANGELOG.md entry.
```

### Checklist for any change
- [ ] Right module (or a new app) and no reach into another module's tables
- [ ] Migration added if models changed; `makemigrations --check` is clean
- [ ] Validation in the form **and** a DB constraint for hard rules
- [ ] Audit entry for state changes; no secrets in logs
- [ ] Permission code checked on new views; nav registered through the registry
- [ ] English-only for new text fields; English UI text
- [ ] Tests added; full suite passes
- [ ] Docs updated (table below) and a `CHANGELOG.md` entry added

### Example prompts
* "Add a Duplicate students page to the dashboard that lists students with the same name,
  guardian name and school, with a merge action that keeps the older WikiScholar ID. Follow
  PROJECT_GUIDE.md."
* "Add a periodic command that polls MiM SMS delivery reports for SMS sent in the last 24 hours
  and marks notification_logs as delivered or failed."
* "Create a new `exams` module: exam sessions, student enrolment by WikiScholar ID, results.
  Its own app, tables and migrations; dashboard nav via the registry; tests included."
* "Add two-factor authentication (TOTP) for Super Admins."

---

## 14. Keeping the docs current

**Rule: every improvement updates the documents it affects, in the same change.** A newcomer
should be able to read the docs, not the chat history, and start work.

| If you change… | Update |
|---|---|
| anything | `CHANGELOG.md` (dated entry: Added / Changed / Fixed) |
| a feature or user-visible behaviour | this guide (sections 2, 5, 12), the roadmap's status table and Section 10 |
| models, tables, constraints | `docs/DATABASE.md` (diagram, tables, integrity) |
| module boundaries or flows | `docs/ARCHITECTURE.md`, section 4 here |
| settings / env variables | section 8 here, `.env.example`, `docs/cpanel.env.example` |
| install or deployment steps | section 7 here, `docs/DEPLOY_CPANEL.md`, `README.md` |
| commands | section 9 here, `README.md` |
| tests | the count and coverage in section 10 |
