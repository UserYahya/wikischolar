# Architecture

## Shape

One deployable Django process (gunicorn, or Passenger on cPanel) + PostgreSQL + a shared cache
for rate limits (Redis, or the database cache `DJANGO_CACHE=db` where there is no Redis) + one
worker loop (or cron job) for queued messages. Email leaves through SMTP or Brevo's HTTPS API;
SMS through MiM SMS; both are chosen on the dashboard (`email_settings`, `sms_settings`). No SPA: pages are server-rendered, with small vanilla-JS
files for the public form (`static/js/register.js`), the dashboard editor
(`static/js/cascade.js`) and dd/mm/yyyy date fields (`static/js/datefield.js` with the vendored
Air Datepicker). This keeps the MVP easy to host and audit; a React front end can
later consume the same JSON endpoints.

```
                ┌──────────────────────── Django (modular monolith) ────────────────────────┐
 Public form ──▶│ registration ──▶ reference (locations, schools) ──▶ core (ids, audit)    │──▶ PostgreSQL 16
 (English)      │      │                                                                     │     + pg_trgm
                │      └──▶ notifications (OTP, confirmation) ──▶ Email / SMS providers     │
 Dashboard ────▶│ dashboard (UI only) ──▶ services of the modules above                      │──▶ Redis (rate limits)
 (English)      └────────────────────────────────────────────────────────────────────────────┘
```

## Module rules

* Each module owns its tables and migrations. Other modules call its **services**
  (`apps/<module>/services.py`), not its tables. Example: a school merge lives in
  `reference.services.merge_schools`, but moving students is delegated to
  `registration.services.reassign_school`, because registration owns `students`.
* The dashboard has no models. Sidebar items go through `apps.core.registry.register_nav`
  (the dashboard registers the Phase 1 items in its `AppConfig.ready()`); a future Exam
  module can register its own item the same way without editing dashboard templates. An item's
  `group` puts it in a collapsible sidebar section (`nav_groups_for`); a new group appears by
  itself.
* Every state change goes through a service that writes `audit_logs`; student field changes
  also write `edit_history` rows grouped by a `change_set` UUID.

## Registration flow

1. The page loads districts (with their current region) from `/api/reference/districts/`.
   Picking a district shows its region — read from the DB at that moment.
2. Upazilas and the other areas (city-corporation thanas, cantonments, "Other area": `upazilas` rows
   with a `group`) load per district, grouped and in order (`reference.services.areas_of`); school typeahead queries `/api/reference/schools/?upazila=&q=`
   (trigram similarity over normalised names and aliases, scoped to the upazila). The public form
   is offered **verified schools only**; signed-in staff (`?all=1`) also see pending ones. Pending
   schools are still matched on submit (step 5), so two students typing the same new school share
   one pending row.
3. `send-otp` checks the email for likely domain typos first (the user can confirm and
   continue), then creates an `email_verifications` row holding only an HMAC of the code, and
   emails the code. The verification ID is bound to the browser session.
4. `verify-otp` checks the code (constant-time compare; locks after 5 wrong tries).
5. `submit` revalidates everything server-side, requires a verification that is verified,
   for the same email, within 60 minutes, in this session; then in one transaction:
   resolves the school, allocates the WikiScholar ID, creates the student, marks the
   verification used, and writes the audit entry. The confirmation email is sent after commit.

### School resolution order
`selected` (ID picked from typeahead, must be in the same upazila) → `exact` (normalised name)
→ `alias` → `auto` (trigram similarity ≥ `WS_SCHOOL_AUTO_RESOLVE`, default 0.8) → `created`
(new `pending` school). Normalisation lower-cases, strips punctuation and expands common
abbreviations (`govt` → `government`, `h/s` → `high school`, …). Merged schools always
redirect to their canonical row.

## IDs

`WS-YYYY-NNNNNN` from `id_sequences` (one row per scope + year, incremented with
`INSERT … ON CONFLICT DO UPDATE … RETURNING`, so concurrent registrations never collide
and numbering restarts each year). It is independent of the school-issued SID. Batch codes
use the same mechanism (`EB-`, `SB-`).

## Security

* RBAC: `apps/core/permissions.py` — Viewer (read/filter), Admin (+ edit, archive, export,
  message, merge, reference data, audit), Super Admin (+ admin accounts). Checked on every
  view with `@require_perm`; admins cannot change their own role or deactivate themselves.
* Audit: logins, failed logins, logouts, record **views**, exports, edits, archives,
  merges, region changes, batch creation and resends. `audit_logs` is append-only in the DB.
* Public endpoints: CSRF, rate limits (OTP per email/IP, submit per IP, API per IP, login per
  IP), honeypot field, strict server-side validation.
* Transport/cookies: HTTPS redirect, HSTS, secure + HttpOnly session cookie (8 h), SameSite,
  `nosniff`, same-origin referrer, dashboard pages `noindex`.
* Webhooks require a shared token (`NOTIFY_WEBHOOK_TOKEN`).
* Not yet: field-level encryption, admin 2FA (see README "Deferred").

## Messaging

A batch snapshots the filter used, the message text and the recipient list
(`notification_logs` rows, one per student). `{name}` and `{wikischolar_id}` placeholders
are filled per recipient. The compose screen requires the admin to confirm the recipient
count; if the count changed since the page loaded, sending is refused. Email batches
default to opted-in students only. Delivery webhooks update per-recipient status;
"Resend failed" creates new rows linked by `resend_of`, preserving the original attempt.

Providers are pluggable classes (`NOTIFY_EMAIL_PROVIDER`, `NOTIFY_SMS_PROVIDER`).

## Extending in Phase 2

New module = new app under `apps/`, own migrations, FK to `students` with `PROTECT`, its own
services, `register_nav(...)` in `AppConfig.ready()`, and permission codes added to
`permissions.py`.

## System emails (editable wording)

Modules register the emails they send by themselves in `AppConfig.ready()`
(`notifications.services.register_system_email`): a key, a default subject/body with
`{placeholders}`, which placeholders are required, and sample values. Registration registers
`registration.otp` and `registration.confirmation` (`apps/registration/emails.py`). Sending code
calls `render_system_email(key, values)`, which uses the Super Admin's saved wording from
`email_templates` when customised, else the default, and fills placeholders by plain replacement
(no template language, so the text can't run code). Dashboard → System emails lists every
registered email, validates placeholders, previews with the sample values and can send a test.

**HTML part.** Every email leaves as plain text plus a designed HTML version
(`EmailMultiAlternatives`; the Brevo API backend sends it as `htmlContent`).
`notifications.send_system_email(key, kind, to, values)` builds both:
`render_system_email_html` swaps each placeholder for a token, turns the text into paragraphs
(escaped, links clickable) and puts the values back, using ready-made HTML for the placeholders
named in the email's `html_values` (registration: the OTP code box, the highlighted ID, the
details table). Bulk messages and other emails get the same layout from
`DjangoMailProvider`, which builds the HTML from the text when none is given. Layout:
`apps/notifications/html_email.py` + `templates/notifications/email.html` (tables and inline
styles only, for mail apps); the logo URL comes from `WS_PUBLIC_URL`.

## Bulk messaging flow

1. **Compose** (dashboard): a filter (the same one the student list uses, incl. student batches
   and message history) selects recipients; the admin names the batch. `notifications.create_batch`
   stores the batch and one `queued` log per recipient in one transaction.
2. **Dispatch**: `notifications.dispatch_batch(batch, time_limit=…)` claims each queued log with
   `SELECT … FOR UPDATE SKIP LOCKED`, renders `{name}` / `{wikischolar_id}` by plain replacement,
   sends through the provider (email: `DjangoMailProvider` → SMTP or Brevo API with the Reply-to;
   SMS: MiM SMS) and records sent/failed with the provider's error. It returns how many are still
   queued. Up to `WS_INLINE_DISPATCH_MAX` recipients start in the web request and the batch page
   continues in `WS_INLINE_DISPATCH_SECONDS` chunks; bigger batches are sent by `send_queued`
   (cron). Because each row is claimed once, browser and cron can overlap safely.
3. **Delivery reports**: `/notifications/webhook/<channel>/?token=` updates logs to delivered /
   bounced / failed, matched on `provider_message_id` (generic JSON or Brevo events).
4. **Tracking**: the Messages list, the batch page (status incl. "not delivered", CSV) and the
   Students "Message history" filter (`notifications.student_ids_in_batch`) read the logs.

